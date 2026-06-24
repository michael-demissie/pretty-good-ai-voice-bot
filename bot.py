import os
import json
import asyncio
import websockets
import base64
from groq import Groq
from deepgram import DeepgramClient, LiveTranscriptionEvents, LiveOptions
from elevenlabs.client import ElevenLabs
from elevenlabs import VoiceSettings
from utils import save_transcript, get_timestamp

from dotenv import load_dotenv
load_dotenv()

# Initialize clients
groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
deepgram_client = DeepgramClient(os.getenv("DEEPGRAM_API_KEY"))
elevenlabs_client = ElevenLabs(api_key=os.getenv("ELEVENLABS_API_KEY"))


def generate_response(conversation_history, persona_instructions, user_input):
    """Use Groq to generate the next patient response."""
    messages = [
        {
            "role": "system",
            "content": f"""You are a patient calling a medical office AI agent.
{persona_instructions}

IMPORTANT RULES:
- Keep responses SHORT and natural (1-3 sentences max)
- Sound like a real person on the phone, not a script
- React naturally to what the agent says
- Stay in character throughout
- If the agent says something incorrect or handles something poorly, react as a real patient would
- When the conversation reaches a natural conclusion, say goodbye and end politely
- Do not narrate your actions, just speak as the character"""
        }
    ]
    
    messages.extend(conversation_history)
    messages.append({"role": "user", "content": f"Agent said: {user_input}\n\nRespond as your character:"})
    
    response = groq_client.chat.completions.create(
        model="llama3-8b-8192",
        messages=messages,
        max_tokens=150,
        temperature=0.8
    )
    
    return response.choices[0].message.content.strip()


def text_to_speech(text, voice_id):
    """Convert text to speech using ElevenLabs and return audio bytes."""
    audio = elevenlabs_client.text_to_speech.convert(
        voice_id=voice_id,
        text=text,
        model_id="eleven_turbo_v2",
        voice_settings=VoiceSettings(
            stability=0.5,
            similarity_boost=0.8,
            style=0.2,
            use_speaker_boost=True
        )
    )
    
    audio_bytes = b"".join(audio)
    return base64.b64encode(audio_bytes).decode("utf-8")


async def handle_call(websocket, persona):
    """Handle a single call session via Twilio Media Streams WebSocket."""
    print(f"\n🎙️ Call started for persona: {persona['name']} ({persona['scenario']})")
    
    conversation_history = []
    transcript = []
    stream_sid = None
    agent_speech_buffer = ""
    
    # Setup Deepgram live transcription
    deepgram_connection = deepgram_client.listen.live.v("1")
    
    agent_transcript_buffer = []
    
    def on_transcript(self, result, **kwargs):
        nonlocal agent_speech_buffer
        sentence = result.channel.alternatives[0].transcript
        if sentence and result.is_final:
            agent_speech_buffer += " " + sentence
            print(f"[AGENT]: {sentence}")
    
    deepgram_connection.on(LiveTranscriptionEvents.Transcript, on_transcript)
    
    options = LiveOptions(
        model="nova-2",
        language="en-US",
        smart_format=True,
        interim_results=True,
        endpointing=500
    )
    
    deepgram_connection.start(options)
    
    # Send initial greeting as the patient
    initial_message = "Hello?"
    print(f"[PATIENT]: {initial_message}")
    transcript.append({"speaker": "patient", "text": initial_message})
    
    try:
        async for message in websocket:
            data = json.loads(message)
            event = data.get("event")
            
            if event == "start":
                stream_sid = data["start"]["streamSid"]
                print(f"Stream started: {stream_sid}")
                
                # Send initial patient greeting
                audio_b64 = text_to_speech(initial_message, persona["voice_id"])
                await websocket.send(json.dumps({
                    "event": "media",
                    "streamSid": stream_sid,
                    "media": {"payload": audio_b64}
                }))
                
            elif event == "media":
                # Send audio to Deepgram for transcription
                audio_payload = base64.b64decode(data["media"]["payload"])
                deepgram_connection.send(audio_payload)
                
            elif event == "stop":
                print("Stream stopped")
                break
                
            # Check if agent has finished speaking and we have a response to generate
            if agent_speech_buffer.strip() and len(agent_speech_buffer.strip()) > 10:
                agent_text = agent_speech_buffer.strip()
                agent_speech_buffer = ""
                
                transcript.append({"speaker": "agent", "text": agent_text})
                conversation_history.append({"role": "assistant", "content": agent_text})
                
                # Generate patient response
                patient_response = generate_response(
                    conversation_history,
                    persona["instructions"],
                    agent_text
                )
                
                print(f"[PATIENT]: {patient_response}")
                transcript.append({"speaker": "patient", "text": patient_response})
                conversation_history.append({"role": "user", "content": patient_response})
                
                # Convert to speech and send back
                if stream_sid:
                    audio_b64 = text_to_speech(patient_response, persona["voice_id"])
                    await websocket.send(json.dumps({
                        "event": "media",
                        "streamSid": stream_sid,
                        "media": {"payload": audio_b64}
                    }))
                
                # Check if conversation should end
                end_phrases = ["goodbye", "bye", "have a great day", "thank you for calling", "is there anything else"]
                if any(phrase in patient_response.lower() for phrase in end_phrases):
                    await asyncio.sleep(2)
                    break
                    
    except websockets.exceptions.ConnectionClosed:
        print("WebSocket connection closed")
    finally:
        deepgram_connection.finish()
        save_transcript(
            persona["id"],
            persona["name"],
            persona["scenario"],
            transcript
        )
        print(f"✅ Call completed for {persona['name']}")
    
    return transcript
