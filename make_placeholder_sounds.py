#!/usr/bin/env python3
"""Synthesize a few creepy placeholder sounds into ./sounds so the rig works out of the box.

These are fine for testing (and the growls/heartbeat are honestly pretty unsettling
at low volume in the dark), but real recordings of dogs, wolves, etc. will sound
better. See README.md for where to get free ones.
"""
import wave
from pathlib import Path

import numpy as np

RATE = 44100
OUT = Path(__file__).parent / "sounds"
rng = np.random.default_rng(13)


def lowpass(x, width):
    return np.convolve(x, np.ones(width) / width, mode="same")


def envelope(n, attack, release):
    env = np.ones(n)
    a, r = int(attack * RATE), int(release * RATE)
    env[:a] = np.linspace(0, 1, a)
    env[-r:] = np.linspace(1, 0, r)
    return env


def t_for(seconds):
    return np.arange(int(seconds * RATE)) / RATE


def growl(seconds=2.8, pitch=65.0):
    t = t_for(seconds)
    jitter = np.cumsum(rng.normal(0, 0.4, len(t))) / RATE * 40
    phase = 2 * np.pi * np.cumsum(pitch * (1 + 0.08 * np.sin(2 * np.pi * 0.7 * t)) + jitter) / RATE
    buzz = (phase / (2 * np.pi)) % 1.0 * 2 - 1            # sawtooth = throat buzz
    rasp = lowpass(rng.normal(0, 1, len(t)), 25)          # breathy rasp
    flutter = 0.55 + 0.45 * np.sin(2 * np.pi * 28 * t)     # rattling, gravelly texture
    sig = lowpass(0.7 * buzz + 0.6 * rasp, 12) * flutter
    return sig * envelope(len(t), 0.6, 0.8)


def heartbeat(beats=6, bpm=58):
    out = []
    for _ in range(beats):
        t = t_for(60 / bpm)
        thump = np.zeros(len(t))
        for offset, amp in ((0.0, 1.0), (0.28, 0.7)):        # lub-dub
            s = int(offset * RATE)
            tt = t[: len(t) - s]
            thump[s:] += amp * np.sin(2 * np.pi * 50 * tt) * np.exp(-tt * 18)
        out.append(thump)
    sig = np.concatenate(out)
    return sig * envelope(len(sig), 0.3, 0.5)


def breath(seconds=3.5):
    t = t_for(seconds)
    noise = lowpass(rng.normal(0, 1, len(t)), 6) - lowpass(rng.normal(0, 1, len(t)), 60)
    inhale_exhale = np.clip(np.sin(2 * np.pi * t / seconds * 2), 0, None) ** 1.5
    return noise * inhale_exhale


def moan(seconds=4.0):
    t = t_for(seconds)
    f = 180 + 70 * np.sin(np.pi * t / seconds) + 6 * np.sin(2 * np.pi * 5 * t)
    phase = 2 * np.pi * np.cumsum(f) / RATE
    sig = np.sin(phase) + 0.3 * np.sin(2 * phase) + 0.05 * rng.normal(0, 1, len(t))
    return lowpass(sig, 4) * envelope(len(t), 1.2, 1.5)


def save(name, sig):
    sig = sig / np.max(np.abs(sig)) * 0.9
    pcm = (sig * 32767).astype(np.int16)
    OUT.mkdir(exist_ok=True)
    with wave.open(str(OUT / f"{name}.wav"), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm.tobytes())
    print(f"  wrote sounds/{name}.wav ({len(sig) / RATE:.1f}s)")


if __name__ == "__main__":
    save("growl_beast", growl())
    save("growl_deep", growl(seconds=3.5, pitch=45))
    save("heartbeat", heartbeat())
    save("breathing", breath())
    save("ghost_moan", moan())
