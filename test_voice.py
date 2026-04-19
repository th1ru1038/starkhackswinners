import os
import subprocess
import tempfile
import requests
from dotenv import load_dotenv

load_dotenv()

VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")
API_KEY  = os.getenv("ELEVENLABS_API_KEY", "")
TEXT     = "Warning. Grip instability detected. Servo tightened automatically."

assert API_KEY, "ELEVENLABS_API_KEY not found in .env"

url     = f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}"
headers = {"xi-api-key": API_KEY, "Content-Type": "application/json"}
body    = {
    "text": TEXT,
    "model_id": "eleven_flash_v2_5",
    "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
}

print(f"Sending to ElevenLabs (voice={VOICE_ID})...")
resp = requests.post(url, json=body, headers=headers, timeout=15)
print(f"Status: {resp.status_code}, bytes: {len(resp.content)}")

if resp.status_code != 200:
    print(f"Error: {resp.text[:300]}")
    raise SystemExit(1)

with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
    f.write(resp.content)
    tmp_path = f.name

print(f"Playing: {tmp_path}")
subprocess.run(["afplay", tmp_path])
print("Done.")
