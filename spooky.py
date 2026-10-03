#!/usr/bin/env python3
"""Spooky Halloween Sounds.

When the motion sensor trips, play a random creepy sound from ONE yard speaker
at a time. Sometimes a different speaker "answers", and sometimes a sound
creeps from speaker to speaker along the yard.

Audio goes out the Pi 4's HDMI as 7.1 (8-channel) PCM to the Denon receiver,
so every speaker terminal on the receiver can be a separate hiding spot.

  python3 spooky.py --identify   play beeps on each channel to find which terminal is which
  python3 spooky.py --test       no motion sensor; press Enter to trigger
  python3 spooky.py              the real thing
"""
import argparse
import datetime
import io
import random
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path

import numpy as np

# ---- Settings you'll probably want to tweak -------------------------------
SOUNDS_DIR = Path(__file__).parent / "sounds"
AUDIO_DEVICE = "hdmi:CARD=vc4hdmi0,DEV=0"   # Pi 4 HDMI port next to USB-C power. See `aplay -L`.
OUTPUT_CHANNELS = 8                          # 7.1 over HDMI
RATE = 48000
PIR_PIN = 17                 # BCM GPIO pin the motion sensor's OUT is wired to
VOLUME = 0.35                # 0.0-1.0. Keep it low: creepier when it's faint
COOLDOWN = (10, 25)          # seconds of silence after a scare (random in range)
ANSWER_CHANCE = 0.45         # chance a different speaker "answers" the first one
CREEP_CHANCE = 0.15          # chance a sound moves from speaker to speaker
ACTIVE_HOURS = (17, 23)      # only scare between 5pm and 11pm; set to None for always

# Your hiding spots, IN ORDER along the sidewalk (so "creeping" moves naturally).
# "channel" is the HDMI channel number. Run --identify to find out which
# receiver terminal each number comes out of, then add more spots here.
SPEAKERS = [
    {"name": "bushes", "channel": 0},
    {"name": "tree", "channel": 1},
]
# ---------------------------------------------------------------------------

EXTS = {".wav", ".ogg", ".mp3", ".flac", ".m4a"}


def read_wav(path):
    with wave.open(str(path)) as w:
        if w.getsampwidth() != 2:
            raise ValueError("only 16-bit WAV supported without ffmpeg")
        rate, nch = w.getframerate(), w.getnchannels()
        data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32)
    mono = data.reshape(-1, nch).mean(axis=1)
    if rate != RATE:
        n = int(len(mono) * RATE / rate)
        mono = np.interp(np.linspace(0, len(mono) - 1, n), np.arange(len(mono)), mono)
    return mono


def decode(path):
    """Any audio file -> mono float samples at RATE."""
    try:
        out = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(path), "-f", "s16le", "-ac", "1", "-ar", str(RATE), "-"],
            capture_output=True, check=True).stdout
        return np.frombuffer(out, dtype=np.int16).astype(np.float32)
    except FileNotFoundError:
        if path.suffix.lower() == ".wav":
            return read_wav(path)
        raise SystemExit(f"{path.name}: install ffmpeg (sudo apt install ffmpeg) to play non-WAV files")


def render(mono, gains):
    """Place a mono sound into the multichannel stream. gains: {channel: scalar or per-sample array}."""
    buf = np.zeros((len(mono), OUTPUT_CHANNELS), dtype=np.float32)
    for ch, g in gains.items():
        buf[:, ch] += mono * g * VOLUME
    return np.clip(buf, -32768, 32767).astype(np.int16)


def play(pcm):
    """Play a multichannel buffer and block until it finishes (so sounds never overlap)."""
    bio = io.BytesIO()
    with wave.open(bio, "wb") as w:
        w.setnchannels(OUTPUT_CHANNELS)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm.tobytes())
    if sys.platform == "darwin":  # testing on a Mac
        with tempfile.NamedTemporaryFile(suffix=".wav") as f:
            f.write(bio.getvalue())
            f.flush()
            subprocess.run(["afplay", f.name])
    else:
        subprocess.run(["aplay", "-q", "-D", AUDIO_DEVICE, "-"], input=bio.getvalue())


def creep_gains(n_samples, path):
    """Equal-power crossfade along a list of channels, e.g. bushes -> tree -> porch."""
    pos = np.linspace(0, len(path) - 1, n_samples)
    gains = {}
    for i, ch in enumerate(path):
        d = np.abs(pos - i)
        gains[ch] = np.where(d < 1, np.cos(d * np.pi / 2), 0.0)
    return gains


def load_bank():
    files = sorted(p for p in SOUNDS_DIR.rglob("*") if p.suffix.lower() in EXTS)
    if not files:
        raise SystemExit(f"No sounds found in {SOUNDS_DIR}. Run make_placeholder_sounds.py or add audio files.")
    bank = [{"name": p.stem, "mono": decode(p)} for p in files]
    print(f"Loaded {len(bank)} sounds: {', '.join(s['name'] for s in bank)}")
    return bank


def scare(bank, state):
    first = random.choice(bank)
    n = len(SPEAKERS)

    if n > 1 and random.random() < CREEP_CHANCE:
        start = random.randrange(n)
        step = random.choice([-1, 1]) if 0 < start < n - 1 else (1 if start == 0 else -1)
        idx = [start + step * k for k in range(random.randint(2, 3))]
        path = [SPEAKERS[i] for i in idx if 0 <= i < n]
        print(f"  ~ {first['name']} creeping {' -> '.join(s['name'] for s in path)}")
        play(render(first["mono"], creep_gains(len(first["mono"]), [s["channel"] for s in path])))
        state["last"] = path[-1]["name"]
        return

    # Don't use the same spot twice in a row, so it keeps people guessing.
    spot = random.choice([s for s in SPEAKERS if s["name"] != state.get("last")] or SPEAKERS)
    print(f"  ~ {first['name']} from the {spot['name']}")
    play(render(first["mono"], {spot["channel"]: 1.0}))
    state["last"] = spot["name"]

    if n > 1 and len(bank) > 1 and random.random() < ANSWER_CHANCE:
        time.sleep(random.uniform(0.8, 3.0))
        other = random.choice([s for s in SPEAKERS if s is not spot])
        reply = random.choice([s for s in bank if s is not first])
        print(f"  ~ {reply['name']} answers from the {other['name']}")
        play(render(reply["mono"], {other["channel"]: 1.0}))
        state["last"] = other["name"]


def identify():
    """Beep N+1 times on channel N, one channel at a time."""
    t = np.arange(int(0.15 * RATE)) / RATE
    beep = np.concatenate([np.sin(2 * np.pi * 660 * t) * 20000, np.zeros(int(0.2 * RATE))])
    for ch in range(OUTPUT_CHANNELS):
        print(f"channel {ch}: {ch + 1} beep(s)")
        play(render(np.tile(beep, ch + 1) / VOLUME, {ch: 1.0}))
        time.sleep(1.5)


def is_active_hours():
    if ACTIVE_HOURS is None:
        return True
    start, end = ACTIVE_HOURS
    return start <= datetime.datetime.now().hour < end


def main():
    parser = argparse.ArgumentParser(description="Spooky Halloween Sounds")
    parser.add_argument("--test", action="store_true", help="no motion sensor; press Enter to trigger")
    parser.add_argument("--identify", action="store_true", help="beep on each channel to map speaker terminals")
    args = parser.parse_args()

    if args.identify:
        identify()
        return

    bank = load_bank()
    state = {}

    if args.test:
        print("Test mode: press Enter to trigger, Ctrl+C to quit.")
        while True:
            input()
            scare(bank, state)

    from gpiozero import MotionSensor
    pir = MotionSensor(PIR_PIN)
    print(f"Watching for motion on GPIO{PIR_PIN}...")
    while True:
        pir.wait_for_motion()
        if not is_active_hours():
            time.sleep(60)
            continue
        print(f"{datetime.datetime.now():%H:%M:%S} motion!")
        scare(bank, state)
        time.sleep(random.uniform(*COOLDOWN))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
