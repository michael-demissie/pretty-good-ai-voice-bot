import os
import sys
import time
import subprocess
from twilio.rest import Client
from dotenv import load_dotenv

load_dotenv()

client = Client(os.getenv("TWILIO_ACCOUNT_SID"), os.getenv("TWILIO_AUTH_TOKEN"))


def download_recording(call_sid, out_name=None, out_dir="recordings"):
    """Fetch the Twilio recording for a call SID and save it as mp3."""
    os.makedirs(out_dir, exist_ok=True)

    # Twilio may take a few seconds to finalize the recording after a call ends.
    recordings = []
    for _ in range(10):
        recordings = client.recordings.list(call_sid=call_sid)
        if recordings:
            break
        print("Waiting for Twilio to finalize the recording...")
        time.sleep(3)

    if not recordings:
        print(f"No recording found for call {call_sid}")
        return None

    rec = recordings[0]
    base = out_name or f"call_{call_sid}"
    mp3_path = os.path.join(out_dir, f"{base}.mp3")

    # Twilio exposes the recording media as .mp3 via the REST media URL.
    media_url = (
        f"https://api.twilio.com/2010-04-01/Accounts/"
        f"{os.getenv('TWILIO_ACCOUNT_SID')}/Recordings/{rec.sid}.mp3"
    )

    subprocess.run([
        "curl", "-s", "-o", mp3_path,
        "-u", f"{os.getenv('TWILIO_ACCOUNT_SID')}:{os.getenv('TWILIO_AUTH_TOKEN')}",
        media_url
    ], check=True)

    print(f"Saved recording: {mp3_path}  ({rec.duration}s)")
    return mp3_path


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python download_recording.py <CALL_SID> [output_name]")
        sys.exit(1)
    call_sid = sys.argv[1]
    out_name = sys.argv[2] if len(sys.argv) > 2 else None
    download_recording(call_sid, out_name)
