import os
import json
from datetime import datetime


def get_timestamp():
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def save_transcript(persona_id, persona_name, scenario, transcript, recordings_dir="transcripts"):
    os.makedirs(recordings_dir, exist_ok=True)
    timestamp = get_timestamp()
    filename = f"{recordings_dir}/call_{persona_id:02d}_{scenario}_{timestamp}.txt"
    
    with open(filename, "w") as f:
        f.write(f"Call Transcript\n")
        f.write(f"===============\n")
        f.write(f"Persona ID: {persona_id}\n")
        f.write(f"Persona Name: {persona_name}\n")
        f.write(f"Scenario: {scenario}\n")
        f.write(f"Timestamp: {timestamp}\n")
        f.write(f"===============\n\n")
        for entry in transcript:
            speaker = entry.get("speaker", "unknown").upper()
            text = entry.get("text", "")
            f.write(f"[{speaker}]: {text}\n\n")
    
    print(f"Transcript saved: {filename}")
    return filename


def save_recording_metadata(persona_id, scenario, recording_url, transcript_file, recordings_dir="recordings"):
    os.makedirs(recordings_dir, exist_ok=True)
    timestamp = get_timestamp()
    filename = f"{recordings_dir}/call_{persona_id:02d}_{scenario}_{timestamp}.json"
    
    metadata = {
        "persona_id": persona_id,
        "scenario": scenario,
        "timestamp": timestamp,
        "recording_url": recording_url,
        "transcript_file": transcript_file
    }
    
    with open(filename, "w") as f:
        json.dump(metadata, f, indent=2)
    
    print(f"Recording metadata saved: {filename}")
    return filename


def load_env():
    from dotenv import load_dotenv
    load_dotenv()
    
    required_keys = [
        "TWILIO_ACCOUNT_SID",
        "TWILIO_AUTH_TOKEN", 
        "TWILIO_PHONE_NUMBER",
        "TARGET_NUMBER",
        "GROQ_API_KEY",
        "DEEPGRAM_API_KEY",
        "ELEVENLABS_API_KEY"
    ]
    
    missing = [key for key in required_keys if not os.getenv(key)]
    if missing:
        raise ValueError(f"Missing required environment variables: {missing}")
    
    print("✅ All environment variables loaded successfully")
