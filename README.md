# Pretty Good AI — Voice Bot Patient Simulator

An automated voice bot that calls Pretty Good AI's test line (`+1-805-439-8008`) and role-plays realistic patients to stress-test the AI scheduling agent. Each call is driven by a distinct patient persona, recorded, transcribed, and automatically analyzed for bugs.

The bot holds a live, two-way phone conversation: it listens to the agent, decides what a real patient would say next, speaks back in a matching voice, and steers toward each scenario's test goal — then saves the transcript, the audio recording, and an automated bug analysis.

---

## How it works (architecture)

The bot chains four services into a real-time loop over a phone call:

1. **Twilio** places the outbound call and streams the call audio both ways over a WebSocket (Media Streams), in mulaw 8 kHz telephony format.
2. **Deepgram** (`nova-2`, streaming) transcribes the agent's speech in real time and signals when the agent has finished a turn.
3. **Groq** (`llama-3.3-70b-versatile`) is the patient "brain": given the conversation so far and the persona's instructions, it produces the next thing the patient says and decides when the call should end.
4. **ElevenLabs** (`eleven_turbo_v2_5`, mulaw 8 kHz output) converts the reply to a natural voice, which is streamed back to Twilio.

A local **FastAPI/WebSocket server** (exposed to Twilio via **ngrok**) bridges Twilio's audio stream and the pipeline. After each call, the transcript is saved, the Twilio recording is downloaded as MP3, and an LLM pass produces a per-call bug analysis.

```
Twilio (call) ─▶ Deepgram (STT) ─▶ Groq (patient brain) ─▶ ElevenLabs (TTS) ─▶ Twilio
                                                                │
                                              transcript + recording + auto bug analysis
```

**Key design choices:** turn-taking is driven by Deepgram's end-of-utterance signal (not a fixed timer) so the bot waits for the agent to finish before replying; the brain decides on its own when to wrap up naturally rather than following hardcoded steps; and each persona is a small data object (name, voice, scenario, instructions) so adding a new test case requires no code changes.

---

## Setup

**Requirements:** Python 3.11, an [ngrok](https://ngrok.com) account, and API keys for Twilio, Groq, Deepgram, and ElevenLabs.

**1. Clone and install dependencies**
```bash
git clone <your-repo-url>
cd "Pretty Good AI Application"
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

**2. Configure environment variables**

Copy the example file and fill in your real keys:
```bash
cp .env.example .env
```

Then edit `.env`:

| Variable | What it is |
|----------|------------|
| `TWILIO_ACCOUNT_SID` | Twilio account SID |
| `TWILIO_AUTH_TOKEN` | Twilio auth token |
| `TWILIO_PHONE_NUMBER` | Your Twilio number (E.164, e.g. `+17856997662`) |
| `TARGET_NUMBER` | The test line: `+18054398008` |
| `GROQ_API_KEY` | Groq API key (the patient brain LLM) |
| `DEEPGRAM_API_KEY` | Deepgram API key (speech-to-text) |
| `ELEVENLABS_API_KEY` | ElevenLabs API key (text-to-speech) |

**3. Start the ngrok tunnel** (in a separate terminal)
```bash
ngrok http 5050
```
Leave it running. The bot reads the public URL automatically from ngrok's local API.

---

## Run

With the venv active and ngrok running, run a single persona:

```bash
python main.py --persona 1
```

Or run all personas in sequence:

```bash
python main.py --all
```

Each call automatically saves:
- a transcript → `transcripts/`
- an MP3 recording → `recordings/`
- an automated bug analysis → `Call scenario analysis by bot/`

---

## Project structure

```
main.py                          # Entry point: places calls, runs the WS server, downloads recordings
bot.py                           # Core call pipeline: STT → brain → TTS, turn-taking, saving
personas.py                      # The patient personas (name, voice, scenario, instructions)
analyzer.py                      # Post-call LLM bug analysis
download_recording.py            # Fetches the Twilio recording as MP3
utils.py                         # Env loading + transcript saving helpers
transcripts/                     # Saved call transcripts (both sides)
recordings/                      # Saved MP3 recordings
Call scenario analysis by bot/   # Per-call automated bug analyses
Bug Report/BUG_REPORT.md         # Human-reviewed bug report (the main deliverable)
.env.example                     # Required environment variables (no secrets)
```

---

## Notes

- All test calls go to a single number (`+1-805-439-8008`) from a single Twilio number, per the challenge requirements.
- Secrets live only in `.env`, which is git-ignored. Never commit `.env`.
- macOS note: port 5050 is used (not 5000) because macOS AirPlay Receiver occupies 5000.
