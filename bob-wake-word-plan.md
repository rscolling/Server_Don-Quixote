# BOB — Wake-Word Listener Build Plan
### *"Hey BOB" · Windows 11 laptop · Porcupine · ElevenLabs*

---

## What We're Building

Right now, talking to BOB requires navigating to a browser tab and clicking the ElevenLabs widget. This plan adds an always-on background listener on the Windows 11 laptop — when Rob says "Hey BOB," the listener detects it locally, opens the ElevenLabs agent connection automatically, and BOB is ready to talk within a second.

No cloud dependency for detection. No microphone audio leaves the laptop during the listening phase. The wake word runs fully on-device via Porcupine.

---

## How It Works

```
Laptop microphone (always on, low CPU)
       ↓
Porcupine engine (on-device, detects "Hey BOB")
       ↓  triggered
Python listener script
       ↓  opens
ElevenLabs agent session in browser
       ↓  voice flows through
BOB (Claude + ElevenLabs TTS → speaker)
```

The listener uses ~1–3% CPU while idle. When the wake word fires, it opens a browser tab to the ElevenLabs widget URL and optionally plays an audio chime so Rob knows BOB is active.

---

## Prerequisites

- Windows 11 laptop ✓
- Python 3.9+ installed on Windows ✓
- Microphone connected or built into laptop ✓
- ElevenLabs agent configured with BOB's personality and webhook tools ✓
- Picovoice account (free tier covers this use case) — **needs to be created**

---

## Phase 1 — Picovoice Account & Custom Wake Word

**Step 1 — Create a free Picovoice account**

Open a browser on the Windows laptop and go to:

```
https://console.picovoice.ai
```

Sign up for a free account. No credit card required for personal use.

After signing in, on the dashboard you will see your **AccessKey** — a long string starting with something like `pv_`. Copy it. You need it in Step 5.

---

**Step 2 — Train the "Hey BOB" wake word**

In the Picovoice Console:

1. Click **Wake Word** in the left sidebar
2. Click **+ Train a Wake Word**
3. Enter the phrase: `Hey BOB`
4. Select platform: **Windows**
5. Select language: **English**
6. Click **Train** — takes about 30 seconds

When training is complete, click **Download** on the model. You will receive a file named something like:

```
Hey-BOB_en_windows_v3_0_0.ppn
```

Save this file to:

```
C:\Users\colli\hey-bob\Hey-BOB_en_windows_v3_0_0.ppn
```

> **Why a custom wake word?** Using "Hey BOB" is cleaner than using a built-in word like "Jarvis" — it matches the character, it's natural to say, and it won't false-trigger on random conversation.

---

## Phase 2 — Install Dependencies on Windows

**Step 3 — Open PowerShell as Administrator**

```powershell
# [WINDOWS] Right-click PowerShell → Run as Administrator
```

---

**Step 4 — Create the listener directory and virtual environment**

```powershell
# [WINDOWS — PowerShell]
mkdir C:\Users\colli\hey-bob
cd C:\Users\colli\hey-bob

# Create isolated Python environment
python -m venv venv
.\venv\Scripts\Activate.ps1
```

You should see `(venv)` appear in the prompt. All installs from here go into this environment.

---

**Step 5 — Install Porcupine and audio dependencies**

```powershell
# [WINDOWS — PowerShell, venv active]
pip install pvporcupine pvrecorder
```

`pvporcupine` — the wake word engine.
`pvrecorder` — Picovoice's cross-platform audio recorder. More reliable on Windows than PyAudio.

Verify install:

```powershell
python -c "import pvporcupine; print('Porcupine OK:', pvporcupine.__version__)"
python -c "import pvrecorder; print('PvRecorder OK')"
```

Both should print without errors.

---

**Step 6 — Add your AccessKey and wake word path to a config file**

```powershell
# [WINDOWS — PowerShell]
New-Item -Path C:\Users\colli\hey-bob\.env -ItemType File
notepad C:\Users\colli\hey-bob\.env
```

Paste and save:

```env
PICOVOICE_ACCESS_KEY=your_access_key_here
WAKE_WORD_PATH=C:\Users\colli\hey-bob\Hey-BOB_en_windows_v3_0_0.ppn
ELEVENLABS_WIDGET_URL=https://elevenlabs.io/convai/widget/YOUR_AGENT_ID
```

> `ELEVENLABS_WIDGET_URL` — get this from your ElevenLabs agent settings page. It is the direct URL to the conversational AI widget for BOB's agent.

---

## Phase 3 — The Listener Script

**Step 7 — Create the listener script**

```powershell
notepad C:\Users\colli\hey-bob\hey_bob_listener.py
```

Paste the following exactly:

```python
# hey_bob_listener.py
# Always-on wake word listener for BOB
# Runs on Windows 11 laptop — lightweight, ~1-3% CPU while idle

import os
import sys
import time
import struct
import threading
import subprocess
import webbrowser
from pathlib import Path

# Load .env manually (no dotenv dependency needed)
env_path = Path(__file__).parent / ".env"
env_vars = {}
if env_path.exists():
    for line in env_path.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            key, _, val = line.partition("=")
            env_vars[key.strip()] = val.strip()

ACCESS_KEY          = env_vars.get("PICOVOICE_ACCESS_KEY", "")
WAKE_WORD_PATH      = env_vars.get("WAKE_WORD_PATH", "")
ELEVENLABS_URL      = env_vars.get("ELEVENLABS_WIDGET_URL", "")

# ── Sensitivity ───────────────────────────────────────────────────────────────
# 0.0 = very strict (fewer false triggers, may miss some detections)
# 1.0 = very sensitive (catches everything, more false triggers)
# 0.5 is a good starting point — tune after testing
SENSITIVITY = 0.5

# ── Cooldown — prevent double-triggers ───────────────────────────────────────
# After wake word fires, ignore detections for this many seconds
COOLDOWN_SECONDS = 3.0

# ── Chime — optional audio feedback when BOB wakes ───────────────────────────
# Set to True to play a short beep when wake word is detected
PLAY_CHIME = True

import pvporcupine
from pvrecorder import PvRecorder


def play_chime():
    """Play a short Windows system sound to confirm wake word detected."""
    try:
        import winsound
        winsound.MessageBeep(winsound.MB_OK)
    except Exception:
        pass   # Fail silently — chime is non-critical


def open_bob_session():
    """
    Open the ElevenLabs BOB agent in the default browser.
    The agent widget auto-starts the microphone and connects to BOB.
    """
    if ELEVENLABS_URL:
        webbrowser.open(ELEVENLABS_URL)
    else:
        print("[hey-bob] ERROR: ELEVENLABS_WIDGET_URL not set in .env")


def list_microphones():
    """Print available microphones — useful for setup and troubleshooting."""
    devices = PvRecorder.get_available_devices()
    print("Available microphones:")
    for i, device in enumerate(devices):
        print(f"  [{i}] {device}")
    return devices


def run_listener(device_index: int = -1):
    """
    Main listener loop. Runs until interrupted.
    device_index = -1 uses the system default microphone.
    """
    if not ACCESS_KEY:
        print("[hey-bob] ERROR: PICOVOICE_ACCESS_KEY not set in .env")
        sys.exit(1)

    if not WAKE_WORD_PATH or not Path(WAKE_WORD_PATH).exists():
        print(f"[hey-bob] ERROR: Wake word file not found at: {WAKE_WORD_PATH}")
        print("Download the .ppn file from https://console.picovoice.ai")
        sys.exit(1)

    # Initialise Porcupine
    porcupine = pvporcupine.create(
        access_key=ACCESS_KEY,
        keyword_paths=[WAKE_WORD_PATH],
        sensitivities=[SENSITIVITY],
    )

    # Initialise microphone recorder
    recorder = PvRecorder(
        frame_length=porcupine.frame_length,
        device_index=device_index,
    )

    last_detection_time = 0.0

    print(f"[hey-bob] Listening for 'Hey BOB'... (sensitivity={SENSITIVITY})")
    print(f"[hey-bob] Microphone: {recorder.selected_device}")
    print(f"[hey-bob] Press Ctrl+C to stop.\n")

    recorder.start()

    try:
        while True:
            pcm_frame = recorder.read()
            keyword_index = porcupine.process(pcm_frame)

            if keyword_index >= 0:
                now = time.time()

                # Cooldown check — don't double-fire
                if now - last_detection_time < COOLDOWN_SECONDS:
                    continue

                last_detection_time = now
                print(f"[hey-bob] Wake word detected at {time.strftime('%H:%M:%S')}")

                # Play chime in a thread so it doesn't block the listener
                if PLAY_CHIME:
                    threading.Thread(target=play_chime, daemon=True).start()

                # Open BOB session
                threading.Thread(target=open_bob_session, daemon=True).start()

    except KeyboardInterrupt:
        print("\n[hey-bob] Stopping listener.")
    finally:
        recorder.stop()
        recorder.delete()
        porcupine.delete()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Hey BOB wake word listener")
    parser.add_argument(
        "--list-devices", action="store_true",
        help="List available microphones and exit"
    )
    parser.add_argument(
        "--device", type=int, default=-1,
        help="Microphone device index (-1 = system default)"
    )
    parser.add_argument(
        "--sensitivity", type=float, default=SENSITIVITY,
        help="Detection sensitivity 0.0–1.0 (default: 0.5)"
    )
    args = parser.parse_args()

    if args.list_devices:
        list_microphones()
        sys.exit(0)

    SENSITIVITY = args.sensitivity
    run_listener(device_index=args.device)
```

Save and close Notepad.

---

**Step 8 — Test the listener**

```powershell
# [WINDOWS — PowerShell, venv active, in C:\Users\colli\hey-bob\]

# First: list available microphones
python hey_bob_listener.py --list-devices
```

Note which microphone index is the one you want to use. Then run the listener:

```powershell
python hey_bob_listener.py
```

You should see:
```
[hey-bob] Listening for 'Hey BOB'... (sensitivity=0.5)
[hey-bob] Microphone: Microphone Array (Realtek...)
[hey-bob] Press Ctrl+C to stop.
```

Say **"Hey BOB"** clearly. You should see:
```
[hey-bob] Wake word detected at 14:32:07
```

And a browser tab should open to the ElevenLabs widget.

If detection is too sensitive (false triggers): lower sensitivity to `0.3`.
If it's missing your voice: raise to `0.7`.

```powershell
python hey_bob_listener.py --sensitivity 0.3
```

Confirm with Rob when working correctly before proceeding to Step 9.

---

## Phase 4 — Run as a Windows Background Service

The listener needs to run automatically on startup — silently, in the background, without Rob having to launch it manually.

**Step 9 — Create a startup wrapper script**

```powershell
notepad C:\Users\colli\hey-bob\start_hey_bob.bat
```

Paste:

```bat
@echo off
cd /d C:\Users\colli\hey-bob
call venv\Scripts\activate.bat
start /min python hey_bob_listener.py --device -1
```

Save and close.

---

**Step 10 — Add to Windows startup**

```powershell
# [WINDOWS — PowerShell]
# Open the Startup folder
$startup = [System.Environment]::GetFolderPath("Startup")
Write-Host "Startup folder: $startup"

# Create a shortcut to the batch file in the Startup folder
$shell    = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut("$startup\HeyBOB.lnk")
$shortcut.TargetPath       = "C:\Users\colli\hey-bob\start_hey_bob.bat"
$shortcut.WorkingDirectory = "C:\Users\colli\hey-bob"
$shortcut.WindowStyle      = 7   # 7 = minimized
$shortcut.Description      = "Hey BOB wake word listener"
$shortcut.Save()

Write-Host "Shortcut created in Startup folder."
```

Verify the shortcut was created:

```powershell
ls "$([System.Environment]::GetFolderPath('Startup'))"
# Should list: HeyBOB.lnk
```

---

**Step 11 — Test startup behavior**

Restart the laptop. After login, wait 30 seconds and then say "Hey BOB." The browser tab should open automatically without Rob launching anything.

Confirm working before proceeding.

---

## Phase 5 — Health Monitoring

**Step 12 — Add a process health check to the server monitor**

The listener runs on the laptop — the server can't watch it directly. Add a heartbeat: the listener pings the server's orchestrator API every 5 minutes so BOB knows it's alive.

Update `hey_bob_listener.py` — add this to the imports section and the run loop:

```python
# Add to imports
import urllib.request
import json

# Add this function
def send_heartbeat():
    """Ping the server so BOB knows the wake word listener is alive."""
    try:
        data = json.dumps({
            "service": "hey_bob_listener",
            "status":  "alive",
            "time":    time.time(),
        }).encode()
        req = urllib.request.Request(
            "http://192.168.1.228:8100/health/laptop-listener",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass   # Fail silently — heartbeat is non-critical

# Add to run_listener() loop — after recorder.start():
HEARTBEAT_INTERVAL = 300   # 5 minutes
last_heartbeat = 0.0

# Inside the while True loop, add:
if time.time() - last_heartbeat > HEARTBEAT_INTERVAL:
    threading.Thread(target=send_heartbeat, daemon=True).start()
    last_heartbeat = time.time()
```

---

**Step 13 — Add the heartbeat endpoint to the orchestrator**

```python
# orchestrator/api.py

_laptop_listener_heartbeat = {"last_seen": None, "status": "unknown"}

@app.post("/health/laptop-listener")
async def laptop_listener_heartbeat(request: Request):
    body = await request.json()
    _laptop_listener_heartbeat["last_seen"] = body.get("time")
    _laptop_listener_heartbeat["status"]    = body.get("status", "alive")
    return {"received": True}

@app.get("/health/laptop-listener")
async def get_laptop_listener_status():
    last = _laptop_listener_heartbeat["last_seen"]
    if not last:
        return {"status": "never_seen", "message": "Listener has not connected yet."}
    age_minutes = (time.time() - last) / 60
    if age_minutes > 10:
        return {
            "status":      "stale",
            "age_minutes": round(age_minutes, 1),
            "message":     "Listener heartbeat is stale — may have stopped.",
        }
    return {
        "status":      "alive",
        "age_minutes": round(age_minutes, 1),
    }
```

---

**Step 14 — Add listener status to BOB's daily report**

In `daily_report.py`, add to the system health section:

```python
import aiohttp

async def get_listener_status() -> str:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "http://localhost:8100/health/laptop-listener",
                timeout=aiohttp.ClientTimeout(total=3),
            ) as resp:
                data = await resp.json()
                if data["status"] == "alive":
                    return f"Wake word listener: alive ({data['age_minutes']:.0f}m ago)."
                elif data["status"] == "stale":
                    return (
                        f"Wake word listener: STALE — last heartbeat "
                        f"{data['age_minutes']:.0f} minutes ago. "
                        f"Check if the laptop is on and the listener is running."
                    )
                return "Wake word listener: not yet seen."
    except Exception:
        return "Wake word listener: status unavailable."

# Add to compose_daily_report() system health section:
listener_status = await get_listener_status()
lines.append(f"  {listener_status}")
```

---

## Summary — What's Done After These Steps

| Capability | Status |
|---|---|
| "Hey BOB" detected locally on Windows laptop | ✓ |
| No microphone audio sent to cloud during idle listening | ✓ |
| ElevenLabs agent opens automatically on wake | ✓ |
| Audio chime confirms wake word detected | ✓ |
| Cooldown prevents double-triggers | ✓ |
| Sensitivity tunable via command-line flag | ✓ |
| Listener auto-starts on Windows login | ✓ |
| Runs minimized — no window cluttering the taskbar | ✓ |
| Heartbeat pings server every 5 minutes | ✓ |
| BOB reports listener health in daily briefing | ✓ |
| Specific microphone selectable via device index | ✓ |

---

### Tuning guide — if detection isn't right

**Too many false triggers (random words activating BOB):**
- Lower sensitivity: `--sensitivity 0.3`
- Check if background TV/radio is causing triggers
- Try a directional microphone pointed at Rob's usual position

**Missing detections (saying "Hey BOB" but nothing happens):**
- Raise sensitivity: `--sensitivity 0.7`
- Run `--list-devices` and try a different microphone index
- Speak more clearly and at normal volume — Porcupine is trained on natural speech

**Browser tab opens but ElevenLabs doesn't connect:**
- Check `ELEVENLABS_WIDGET_URL` in `.env` is the correct direct widget URL
- Make sure the ElevenLabs agent is published and active in the console

---

### What Rob experiences

Before this build: opens browser → navigates to tab → clicks widget → waits.

After this build: says "Hey BOB" → hears chime → BOB's voice responds within 1–2 seconds.

---

*BOB Wake-Word Listener Build Plan v1.0 — 2026-03-18*
*Next build: Push Notifications to Rob's Phone*
