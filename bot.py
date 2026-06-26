import os
import re
import json
import time
import base64
import asyncio

import websockets
from groq import Groq
from deepgram import DeepgramClient, LiveTranscriptionEvents, LiveOptions
from elevenlabs.client import ElevenLabs
from elevenlabs import VoiceSettings
from utils import save_transcript
from analyzer import analyze_call

from dotenv import load_dotenv
load_dotenv()

groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
deepgram_client = DeepgramClient(os.getenv("DEEPGRAM_API_KEY"))
elevenlabs_client = ElevenLabs(api_key=os.getenv("ELEVENLABS_API_KEY"))

LLM_MODEL = "llama-3.3-70b-versatile"
TTS_MODEL = "eleven_turbo_v2_5"

SILENCE_NUDGE_SECONDS = 8     # genuine dead-air before a gentle prompt
MAX_NUDGES = 2                # prompts before bowing out
HARD_BACKSTOP_SECONDS = 240   # last-resort ceiling (4 min)


def generate_response(conversation_history, persona_instructions, agent_text, elapsed_seconds):
    """Patient's next line + whether to end. Returns {"say","end","reason"}."""
    minutes = elapsed_seconds / 60.0
    system = f"""You are role-playing as a real patient on a phone call with a medical office's AI scheduling agent. Behave exactly like a real human caller.

{persona_instructions}

HOW TO TALK:
- Speak naturally — short phrases, contractions, the way people really talk on the phone.
- LISTEN to what the agent just said and respond to THAT. Don't repeat yourself.
- Give one complete thought; never trail off mid-sentence.
- One or two natural sentences, max.
- Only the words you'd say aloud. No narration, no stage directions.
- Talk like a real person: occasionally use natural fillers like "hmm", "uh", "oh", "yeah" — but ONLY when it fits naturally. Never force them, never start every line with one.
- If you realize you spoke over the agent, briefly apologize and yield, e.g. "oh sorry, go ahead".

ENDING THE CALL:
- Call length so far: about {minutes:.1f} minutes.
- Don't rush. Stay until your reason for calling is actually resolved.
- Once your goal IS met (or the agent has done all it can), wrap up promptly and naturally — thank them, say goodbye.
- Aim to finish under ~3 minutes once the goal is handled.

Stay silent ONLY for automated notices that clearly need no reply — a "this call may be recorded" message, hold music, or system filler. In that one case set respond to false.
For ANYTHING the agent asks you — even a question you already answered — you MUST respond (respond: true). If they re-ask, just answer again naturally, maybe noting you already said it ("I just said, it's..."). 
Never stay silent on a real question.

Return ONLY this JSON, nothing else:
{{"say": "<your spoken line>", "end": <true|false>, "reason": "<short reason>"}}"""

    messages = [{"role": "system", "content": system}]
    messages.extend(conversation_history)
    messages.append({"role": "user", "content": f'The agent just said: "{agent_text}"\n\nRespond with the JSON:'})

    raw = ""
    for _ in range(2):  # retry once if the model returns empty content
        resp = groq_client.chat.completions.create(
            model=LLM_MODEL,
            messages=messages,
            max_tokens=400,
            temperature=0.7,
        )
        raw = (resp.choices[0].message.content or "").strip()
        if raw:
            break
    return _parse(raw)


def _parse(raw):
    """Parse the model's JSON, recovering from truncation or stray text.

    On a genuine question we never want silence, so a failed parse falls back
    to a brief recovery line rather than going quiet."""
    if not raw:
        return {"respond": True, "say": "Sorry, could you repeat that?",
                "end": False, "reason": "empty"}

    # 1. Clean parse on a full {...} block.
    try:
        obj = json.loads(raw[raw.index("{"): raw.rindex("}") + 1])
        say = str(obj.get("say", "")).strip()
        if say:
            return {"respond": bool(obj.get("respond", True)), "say": say,
                    "end": bool(obj.get("end", False)),
                    "reason": str(obj.get("reason", "")).strip()}
        # respond explicitly false with empty say = intentional silence (notices)
        if obj.get("respond") is False:
            return {"respond": False, "say": "", "end": False, "reason": "intentional-silence"}
    except Exception:
        pass

    # 2. Recover the "say" value even if JSON is truncated before the close.
    m = re.search(r'"say"\s*:\s*"(.*?)(?:"|$)', raw, re.DOTALL)
    if m and m.group(1).strip():
        say = m.group(1).strip().rstrip('\\').strip()
        end = '"end": true' in raw.lower() or '"end":true' in raw.lower()
        return {"respond": True, "say": say, "end": end, "reason": "recovered"}

    # 3. Salvage plain text before any brace.
    cleaned = raw.split("{")[0].strip()
    if len(cleaned) > 3 and "{" not in cleaned:
        return {"respond": True, "say": cleaned, "end": False, "reason": "salvaged"}

    # 4. Last resort: a brief recovery line, never silence on a real turn.
    return {"respond": True, "say": "Sorry, could you say that again?",
            "end": False, "reason": "fallback-recovery"}


def text_to_speech_mulaw(text, voice_id):
    audio = elevenlabs_client.text_to_speech.convert(
        voice_id=voice_id, text=text, model_id=TTS_MODEL, output_format="ulaw_8000",
        voice_settings=VoiceSettings(stability=0.4, similarity_boost=0.75,
                                     style=0.4, use_speaker_boost=True),
    )
    return b"".join(audio)


async def send_audio_to_twilio(websocket, stream_sid, mulaw_bytes):
    frame = 160
    for i in range(0, len(mulaw_bytes), frame):
        await websocket.send(json.dumps({
            "event": "media", "streamSid": stream_sid,
            "media": {"payload": base64.b64encode(mulaw_bytes[i:i + frame]).decode("utf-8")},
        }))
        await asyncio.sleep(0.018)


async def handle_call(websocket, persona):
    print(f"\n🎙️ Call: {persona['name']} ({persona['scenario']}) [{persona['voice_name']}]")

    conversation_history = []
    transcript = []
    stream_sid = None
    loop = asyncio.get_event_loop()
    saved = {"done": False}
    started_at = time.monotonic()

    agent_turns = asyncio.Queue()
    # agent_speaking: agent is mid-utterance (from Deepgram VAD)
    # last_voice_at: timestamp of the most recent agent speech, for silence math
    state = {"buffer": "", "agent_speaking": False, "last_voice_at": time.monotonic()}

    dg = deepgram_client.listen.live.v("1")

    def on_speech_started(_s, *a, **k):
        state["agent_speaking"] = True
        state["last_voice_at"] = time.monotonic()

    def on_transcript(_s, result, **kwargs):
        sentence = result.channel.alternatives[0].transcript
        if sentence:
            state["last_voice_at"] = time.monotonic()
            if result.is_final:
                state["buffer"] += " " + sentence
                print(f"   ...heard: {sentence}")

    def on_utterance_end(_s, *a, **k):
        # Agent has truly finished a turn.
        state["agent_speaking"] = False
        text = state["buffer"].strip()
        if text:
            state["buffer"] = ""
            asyncio.run_coroutine_threadsafe(agent_turns.put(text), loop)

    dg.on(LiveTranscriptionEvents.SpeechStarted, on_speech_started)
    dg.on(LiveTranscriptionEvents.Transcript, on_transcript)
    dg.on(LiveTranscriptionEvents.UtteranceEnd, on_utterance_end)
    dg.start(LiveOptions(
        model="nova-2", language="en-US", encoding="mulaw", sample_rate=8000,
        channels=1, smart_format=True, interim_results=True,
        utterance_end_ms=1000, vad_events=True, endpointing=300,
    ))

    def persist():
        if not saved["done"]:
            save_transcript(persona["id"], persona["name"], persona["scenario"], transcript)
            saved["done"] = True
            try:
                analyze_call(persona, transcript)
            except Exception as e:
                print(f"Analysis skipped: {e}")

    async def speak(text):
        # Wait for the agent to finish, then say the full line without interruption.
        while state["agent_speaking"]:
            await asyncio.sleep(0.1)
        mulaw = await loop.run_in_executor(None, text_to_speech_mulaw, text, persona["voice_id"])
        await send_audio_to_twilio(websocket, stream_sid, mulaw)
        await asyncio.sleep(0.25)

    async def responder():
        nudges = 0
        while True:
            try:
                agent_text = await asyncio.wait_for(agent_turns.get(), timeout=1.0)
            except asyncio.TimeoutError:
                # Only count as dead air if the agent isn't speaking AND it's been
                # quiet for a real stretch since the last voice we heard.
                quiet_for = time.monotonic() - state["last_voice_at"]
                if not state["agent_speaking"] and quiet_for >= SILENCE_NUDGE_SECONDS:
                    nudges += 1
                    if nudges > MAX_NUDGES:
                        closing = "I think we got disconnected. I'll try calling back later. Thanks, goodbye."
                        print(f"[PATIENT]: {closing}")
                        transcript.append({"speaker": "patient", "text": closing})
                        await speak(closing)
                        persist()
                        return
                    nudge = "Sorry, are you still there?"
                    print(f"[PATIENT]: {nudge}")
                    transcript.append({"speaker": "patient", "text": nudge})
                    await speak(nudge)
                    state["last_voice_at"] = time.monotonic()
                continue

            nudges = 0
            print(f"[AGENT]: {agent_text}")
            transcript.append({"speaker": "agent", "text": agent_text})
            conversation_history.append({"role": "assistant", "content": agent_text})

            elapsed = time.monotonic() - started_at
            result = await loop.run_in_executor(
                None, generate_response,
                conversation_history, persona["instructions"], agent_text, elapsed
            )
            # Skip only the automated recorded-line notice; always reply otherwise.
            if "may be recorded" in agent_text.lower() and len(transcript) <= 1:
                continue
            if not result["say"].strip():
                result["say"] = "Sorry, could you say that again?"

            say, end_call = result["say"], result["end"]
            print(f"[PATIENT]: {say}" + (f"   (ending: {result['reason']})" if end_call else ""))
            transcript.append({"speaker": "patient", "text": say})
            conversation_history.append({"role": "user", "content": say})

            if stream_sid:
                await speak(say)
            if end_call:
                await asyncio.sleep(1.0)
                persist()
                return

    responder_task = None
    try:
        async for message in websocket:
            data = json.loads(message)
            event = data.get("event")

            if event == "start":
                stream_sid = data["start"]["streamSid"]
                print(f"Stream started: {stream_sid}")
                responder_task = asyncio.create_task(responder())
                # Like a real caller, listen first — let the agent's recorded notice
                # and greeting play, then respond via the responder loop.

            elif event == "media":
                dg.send(base64.b64decode(data["media"]["payload"]))

            elif event == "stop":
                print("Stream stopped")
                break

            if time.monotonic() - started_at > HARD_BACKSTOP_SECONDS:
                print("⏱️  Hard backstop reached.")
                break
            if responder_task and responder_task.done():
                break

    except websockets.exceptions.ConnectionClosed:
        print("WebSocket closed")
    finally:
        if responder_task and not responder_task.done():
            responder_task.cancel()
        dg.finish()
        persist()
        print(f"✅ Call complete: {persona['name']}")

    return transcript
