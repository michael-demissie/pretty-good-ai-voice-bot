import os
import sys
import json
import time
import asyncio
import argparse
import threading
import websockets
from twilio.rest import Client
from utils import load_env
from personas import PERSONAS
from bot import handle_call
from download_recording import download_recording

load_env()

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER")
TARGET_NUMBER = os.getenv("TARGET_NUMBER")

PORT = 5050
twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

# Shared state for the call currently in progress
current = {"persona": None, "done": None}


def get_ngrok_url():
    """Query the local ngrok API for the active public https tunnel URL."""
    import urllib.request
    try:
        with urllib.request.urlopen("http://127.0.0.1:4040/api/tunnels") as resp:
            data = json.loads(resp.read())
        for tunnel in data["tunnels"]:
            if tunnel["public_url"].startswith("https"):
                return tunnel["public_url"]
    except Exception as e:
        print(f"Could not reach ngrok API: {e}")
    return None


async def ws_handler(websocket):
    """Twilio Media Streams connects here. Hand off to the bot pipeline."""
    try:
        await handle_call(websocket, current["persona"])
    finally:
        # Signal the runner that this call's conversation has finished.
        if current["done"] and not current["done"].done():
            current["done"].get_loop().call_soon_threadsafe(current["done"].set_result, True)


async def run_server():
    async with websockets.serve(ws_handler, "0.0.0.0", PORT):
        print(f"WebSocket server listening on port {PORT}")
        await asyncio.Future()


def place_call(public_url):
    ws_url = public_url.replace("https", "wss") + "/"
    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Connect>
        <Stream url="{ws_url}" />
    </Connect>
</Response>"""
    call = twilio_client.calls.create(
        to=TARGET_NUMBER,
        from_=TWILIO_PHONE_NUMBER,
        twiml=twiml,
        record=True,
    )
    print(f"📞 Call initiated. SID: {call.sid}")
    return call.sid


async def run_one(persona, public_url, loop):
    """Place the call, wait for it to actually finish, then download the mp3."""
    current["persona"] = persona
    current["done"] = loop.create_future()

    print(f"\n{'='*50}")
    print(f"Persona #{persona['id']}: {persona['name']} ({persona['voice_name']})")
    print(f"Scenario: {persona['scenario']}")
    print(f"{'='*50}")

    call_sid = place_call(public_url)

    # Wait for the conversation to end (event-driven), with a safety ceiling.
    try:
        await asyncio.wait_for(current["done"], timeout=240)
    except asyncio.TimeoutError:
        print("⏱️  Call hit the safety timeout.")

    # Twilio needs a moment to finalize the recording after hangup.
    await asyncio.sleep(3)
    out_name = f"call_{persona['id']:02d}_{persona['scenario']}"
    await loop.run_in_executor(None, download_recording, call_sid, out_name)


def main():
    parser = argparse.ArgumentParser(description="Pretty Good AI voice-bot caller")
    parser.add_argument("--persona", type=int, help="Run a single persona by id (1-15)")
    parser.add_argument("--all", action="store_true", help="Run all personas in sequence")
    args = parser.parse_args()

    public_url = get_ngrok_url()
    if not public_url:
        print("❌ No ngrok tunnel found. Start it first with:  ngrok http 5050")
        sys.exit(1)
    print(f"🌐 Public URL: {public_url}")

    loop = asyncio.new_event_loop()

    def start_loop():
        asyncio.set_event_loop(loop)
        loop.run_until_complete(run_server())

    threading.Thread(target=start_loop, daemon=True).start()
    time.sleep(2)

    if args.all:
        selected = PERSONAS
    elif args.persona:
        selected = [p for p in PERSONAS if p["id"] == args.persona]
        if not selected:
            print(f"No persona with id {args.persona}")
            sys.exit(1)
    else:
        selected = [PERSONAS[0]]
        print("No flag given — running persona #1. Use --persona N or --all.")

    for persona in selected:
        asyncio.run_coroutine_threadsafe(
            run_one(persona, public_url, loop), loop
        ).result()
        if persona is not selected[-1]:
            print("Pausing 8s before next call...")
            time.sleep(8)

    print("\n✅ All selected calls complete.")


if __name__ == "__main__":
    main()
