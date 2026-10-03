#!/usr/bin/env python3
"""Synthesize original spooky sounds, so they're free to use and share.

  sounds/*.mp3            one-shot scares (roar, howl, cackle, creaking door…)
  sounds/ambience/*.mp3   seamless background loops (graveyard, sewer, asylum…)

Everything is generated from noise and oscillators with numpy. The background
loops are built "circularly" (FFT filtering, wrap-around events and reverb), so
the end flows straight into the start with no seam.

Usage: python3 make_spooky_sounds.py [--only NAME] [--wav]
Needs ffmpeg for MP3 output (otherwise writes WAV).
"""
import argparse
import shutil
import subprocess
import wave
from pathlib import Path

import numpy as np

RATE = 48000
ROOT = Path(__file__).parent
FX_DIR = ROOT / "sounds"
AMB_DIR = ROOT / "sounds" / "ambience"
rng = np.random.default_rng(1031)


# ---- DSP toolkit -------------------------------------------------------------------

def secs(s):
    return int(s * RATE)


def tt(s):
    return np.arange(secs(s)) / RATE


def noise(n):
    return rng.standard_normal(n)


def band(x, lo=0.0, hi=None, order=2):
    """Zero-phase FFT band-pass (circular, so loops stay seamless)."""
    n = len(x)
    f = np.fft.rfftfreq(n, 1 / RATE)
    g = np.ones_like(f)
    if lo:
        g /= 1 + (lo / np.maximum(f, 1e-3)) ** (2 * order)
    if hi:
        g /= 1 + (f / hi) ** (2 * order)
    return np.fft.irfft(np.fft.rfft(x) * g, n)


def formant(x, peaks, floor=0.02):
    """Shape a buzzy source into a vowel. peaks: [(freq, bandwidth, gain)]."""
    n = len(x)
    f = np.fft.rfftfreq(n, 1 / RATE)
    g = np.full_like(f, floor)
    for fc, bw, gain in peaks:
        g += gain / (1 + ((f - fc) / (bw / 2)) ** 2)
    return np.fft.irfft(np.fft.rfft(x) * g, n)


VOWELS = {
    "ah": [(750, 120, 1.0), (1200, 140, 0.6), (2600, 200, 0.25)],
    "oo": [(320, 90, 1.0), (800, 120, 0.45), (2300, 200, 0.12)],
    "uh": [(550, 110, 1.0), (1000, 130, 0.5), (2400, 200, 0.2)],
    "aw": [(600, 110, 1.0), (900, 120, 0.7), (2500, 200, 0.18)],
    "ee": [(300, 80, 1.0), (2300, 180, 0.5), (3000, 220, 0.3)],
}


def vowel_morph(src, a, b):
    """Glide from vowel a to vowel b over the length of src."""
    k = np.linspace(0, 1, len(src))
    return formant(src, VOWELS[a]) * (1 - k) + formant(src, VOWELS[b]) * k


def saw(freq):
    """Sawtooth with a per-sample frequency array."""
    phase = np.cumsum(freq) / RATE
    return 2 * (phase % 1.0) - 1


def slow(n, rate, lo=0.0, hi=1.0):
    """Smooth random modulation (circular), scaled to lo..hi."""
    m = band(noise(n), 0, rate, order=3)
    m = (m - m.min()) / (np.ptp(m) + 1e-9)
    return lo + (hi - lo) * m


def env(n, attack, release, curve=1.0):
    e = np.ones(n)
    a, r = min(secs(attack), n), min(secs(release), n)
    if a:
        e[:a] = np.linspace(0, 1, a) ** curve
    if r:
        e[-r:] *= np.linspace(1, 0, r) ** curve
    return e


def decay(n, time):
    return np.exp(-np.arange(n) / RATE * 6.9 / time)


def reverb(x, seconds=2.0, mix=0.3, bright=5000, circular=False):
    """Convolution reverb with a decaying-noise impulse response. Mono in -> stereo out."""
    n_ir = secs(seconds)
    outs = []
    for _ in range(2):  # different IR per side = wide stereo
        ir = band(noise(n_ir), 80, bright) * decay(n_ir, seconds)
        ir /= np.sqrt(np.sum(ir ** 2)) + 1e-9
        size = len(x) if circular else len(x) + n_ir
        wet = np.fft.irfft(np.fft.rfft(x, size) * np.fft.rfft(ir, size), size)
        outs.append(wet[:size])
    dry = np.pad(x, (0, len(outs[0]) - len(x)))
    return np.stack([dry * (1 - mix) + outs[0] * mix * 1.6, dry * (1 - mix) + outs[1] * mix * 1.6], axis=1)


def place(buf, ev, pos, gain=1.0, pan=0.0):
    """Add a mono or stereo event into a looping stereo buffer at pos (wraps around the end)."""
    if ev.ndim == 1:
        th = (pan + 1) * np.pi / 4
        ev = np.stack([ev * np.cos(th), ev * np.sin(th)], axis=1)
    idx = (pos + np.arange(len(ev))) % len(buf)
    np.add.at(buf, idx, ev * gain)


def stereo_bed(n, maker):
    return np.stack([maker(n), maker(n)], axis=1)


def norm(x, rms=0.12, peak=0.95):
    x = x - np.mean(x, axis=0)
    x = x * (rms / (np.sqrt(np.mean(x ** 2)) + 1e-9))
    p = np.max(np.abs(x))
    return x * (peak / p) if p > peak else x


# ---- Building blocks -------------------------------------------------------------------

def bell(dur=7.0, base=196.0):
    t = tt(dur)
    partials = [(0.5, 1.0, 1.0), (1.0, 0.8, 0.8), (1.19, 0.5, 0.6), (1.5, 0.45, 0.5),
                (2.0, 0.35, 0.4), (2.52, 0.25, 0.3), (2.66, 0.2, 0.25), (3.0, 0.15, 0.2)]
    x = sum(a * np.sin(2 * np.pi * base * r * t + rng.uniform(0, 6)) * decay(len(t), dur * d)
            for r, a, d in partials)
    return x * env(len(t), 0.003, 0.3)


def owl_hoots():
    out = []
    for length, f in ((0.32, 390), (0.18, 370), (0.45, 350)):
        t = tt(length)
        x = np.sin(2 * np.pi * np.cumsum(np.linspace(f * 1.03, f * 0.95, len(t))) / RATE)
        x += 0.15 * np.sin(2 * 2 * np.pi * f * t)
        out += [x * env(len(t), 0.06, 0.15), np.zeros(secs(0.12))]
    return np.concatenate(out)


def cricket(dur, freq=4600):
    t = tt(dur)
    tone = np.sin(2 * np.pi * freq * t)
    pulses = (np.sin(2 * np.pi * 32 * t) > 0.2).astype(float)
    chirp_gate = (np.sin(2 * np.pi * 1.4 * t) > 0.55).astype(float)
    return band(tone * pulses * chirp_gate, 3000, 7000) * 0.5


def drip():
    n = secs(0.09)
    f = np.linspace(rng.uniform(900, 1500), rng.uniform(2200, 3600), n)
    return np.sin(2 * np.pi * np.cumsum(f) / RATE) * decay(n, 0.06) * env(n, 0.001, 0.01)


def clank(bright=4000):
    n = secs(1.2)
    t = np.arange(n) / RATE
    x = sum(np.sin(2 * np.pi * f * t) * decay(n, d) for f, d in
            ((rng.uniform(180, 260), 0.9), (rng.uniform(530, 700), 0.5), (rng.uniform(1300, 1900), 0.3)))
    x += band(noise(n), 200, bright) * decay(n, 0.08) * 2
    return x


def footstep(hard=False):
    n = secs(0.22)
    x = band(noise(n), 60, 900 if hard else 3500) * decay(n, 0.12)
    x += np.sin(2 * np.pi * 70 * np.arange(n) / RATE) * decay(n, 0.08) * (1.5 if hard else 0.6)
    return x


def growl_voice(dur, pitch_from, pitch_to, vowels=("ah", "oo"), rasp=0.6, grit=30):
    n = secs(dur)
    t = np.arange(n) / RATE
    pitch = np.linspace(pitch_from, pitch_to, n) * (1 + 0.04 * np.sin(2 * np.pi * 0.9 * t))
    pitch *= 1 + 0.03 * band(noise(n), 0, 12) / 0.02
    src = saw(pitch) + rasp * band(noise(n), 200, 4000)
    src *= 0.6 + 0.4 * np.sin(2 * np.pi * grit * t) ** 2   # gravelly flutter
    return vowel_morph(src, *vowels)


def howl(dur=4.0, peak=620):
    n = secs(dur)
    t = np.arange(n) / RATE
    shape = np.interp(t / dur, [0, 0.15, 0.55, 0.85, 1], [0.55, 0.85, 1.0, 0.9, 0.6])
    f = peak * shape * (1 + 0.012 * np.sin(2 * np.pi * 5.5 * t))
    src = np.sin(2 * np.pi * np.cumsum(f) / RATE) + 0.3 * saw(f) + 0.05 * noise(n)
    return formant(src, VOWELS["oo"], floor=0.15) * env(n, 0.4, 1.2)


def crow_caw():
    n = secs(0.34)
    t = np.arange(n) / RATE
    f = np.interp(t, [0, 0.05, 0.34], [520, 640, 470])
    src = saw(f) + 0.5 * band(noise(n), 800, 4000)
    x = np.tanh(3 * formant(src, [(1500, 300, 1.0), (2600, 400, 0.6), (900, 200, 0.4)]))
    return x * env(n, 0.01, 0.12)


def creak(dur=2.4, rate=(14, 55, 24)):
    n = secs(dur)
    r = np.interp(np.linspace(0, 1, n), [0, 0.4, 1], list(rate))
    r *= 1 + 0.25 * band(noise(n), 0, 6) / 0.02
    phase = np.cumsum(np.clip(r, 3, None)) / RATE
    clicks = np.diff(np.floor(phase), prepend=0) * (0.6 + 0.4 * rng.random(n))
    body = np.zeros(n)
    k = np.arange(secs(0.03)) / RATE
    for f, g in ((340, 1.0), (820, 0.6), (1650, 0.35), (2900, 0.2)):
        body += np.convolve(clicks, g * np.sin(2 * np.pi * f * k) * np.exp(-k * 120), mode="same")
    return body * env(n, 0.05, 0.25)


def thunder(dur=8.0, crack=True):
    n = secs(dur)
    rumble = band(noise(n), 25, 180) * decay(n, dur * 0.8) * slow(n, 3, 0.3, 1.0)
    rumble *= env(n, 0.25 if not crack else 0.02, 1.5)
    if crack:
        c = band(noise(secs(0.6)), 300, 5000) * decay(secs(0.6), 0.35)
        rumble[: len(c)] += c * 0.8
    return np.tanh(rumble / (np.std(rumble) * 2.5))


def zap(dur):
    n = secs(dur)
    t = np.arange(n) / RATE
    crackle = (rng.random(n) < 0.02) * rng.standard_normal(n) * 6
    buzz = np.sign(np.sin(2 * np.pi * 120 * t)) * 0.4
    x = band(crackle + band(noise(n), 1500, 9000), 400, 10000) * (0.5 + 0.5 * np.abs(buzz))
    return x * env(n, 0.005, 0.1) * (rng.random(n) > 0.003)


def bubbles(dur, density=12.0, lo=250, hi=900):
    n = secs(dur)
    out = np.zeros(n)
    for _ in range(int(dur * density)):
        m = secs(rng.uniform(0.02, 0.07))
        f0 = rng.uniform(lo, hi)
        f = np.linspace(f0, f0 * rng.uniform(1.4, 2.2), m)
        b = np.sin(2 * np.pi * np.cumsum(f) / RATE) * np.sin(np.linspace(0, np.pi, m))
        p = rng.integers(0, n)
        idx = (p + np.arange(m)) % n
        out[idx] += b * rng.uniform(0.3, 1.0)
    return out


def fire_crackle(n):
    pops = (rng.random(n) < 0.0016) * rng.standard_normal(n) * 8
    pops = band(pops, 700, 7000)
    roar = band(noise(n), 60, 600) * slow(n, 1.5, 0.4, 1.0) * 0.5
    return pops + roar


# ---- One-shot scares ---------------------------------------------------------------------

def fx_monster_roar():
    x = growl_voice(3.2, 95, 58, ("ah", "aw"), rasp=0.9, grit=26)
    x = np.tanh(2.5 * x / np.std(x)) * env(len(x), 0.35, 0.9)
    return reverb(x, 1.2, 0.2).mean(axis=1)


def fx_zombie_groan():
    x = growl_voice(3.6, 105, 78, ("uh", "aw"), rasp=0.5, grit=9)
    x *= env(len(x), 0.6, 1.2) * (0.7 + 0.3 * slow(len(x), 3))
    return reverb(x, 1.0, 0.15).mean(axis=1)


def fx_wolf_howl():
    return reverb(howl(4.2), 2.5, 0.35).mean(axis=1)


def fx_ghost_wail():
    n = secs(4.5)
    t = np.arange(n) / RATE
    f = np.interp(t, [0, 1.2, 2.6, 4.5], [380, 760, 520, 300]) * (1 + 0.03 * np.sin(2 * np.pi * 6.3 * t))
    src = np.sin(2 * np.pi * np.cumsum(f) / RATE) + 0.25 * saw(f) + 0.3 * band(noise(n), 1500, 6000)
    x = vowel_morph(src, "oo", "ah") * env(n, 0.8, 1.5)
    return reverb(x, 3.0, 0.45).mean(axis=1)


def fx_evil_whisper():
    n = secs(3.4)
    src = band(noise(n), 300, 9000)
    syll = np.zeros(n)
    pos = secs(0.1)
    while pos < n - secs(0.3):
        m = secs(rng.uniform(0.12, 0.3))
        syll[pos:pos + m] += np.sin(np.linspace(0, np.pi, m)) ** 1.5
        pos += m + secs(rng.uniform(0.03, 0.18))
    a = formant(src, VOWELS["ee"], floor=0.3)
    b = formant(src, VOWELS["ah"], floor=0.3)
    mix = slow(n, 4)
    x = (a * mix + b * (1 - mix)) * syll
    hiss = band(noise(n), 4000, 10000) * (syll > 0.6) * 0.5
    return reverb(x + hiss, 1.6, 0.35).mean(axis=1)


def fx_witch_cackle():
    parts = []
    gap = 0.05
    for i in range(11):
        d = 0.1 + i * 0.006
        n = secs(d)
        f = np.linspace(720 - i * 22, 640 - i * 22, n)
        src = saw(f) + 0.6 * band(noise(n), 1000, 6000)
        h = formant(src, VOWELS["ah"]) * np.sin(np.linspace(0, np.pi, n)) ** 0.7
        parts += [h, np.zeros(secs(gap))]
        gap += 0.012
    n = secs(0.9)
    tail_f = np.linspace(900, 520, n)
    tail = formant(saw(tail_f) + 0.4 * noise(n), VOWELS["ee"]) * env(n, 0.05, 0.6)
    x = np.concatenate(parts + [tail])
    return reverb(x, 1.4, 0.3).mean(axis=1)


def fx_door_creak():
    return reverb(creak(2.8), 0.8, 0.2).mean(axis=1)


def fx_chains_rattle():
    n = secs(2.6)
    out = np.zeros(n)
    t0 = 0
    while t0 < n - secs(0.2):
        m = secs(0.2)
        k = np.arange(m) / RATE
        link = sum(np.sin(2 * np.pi * f * k) * np.exp(-k * d)
                   for f, d in ((rng.uniform(1800, 2400), 30), (rng.uniform(3100, 3700), 45),
                                (rng.uniform(5000, 6200), 60)))
        out[t0:t0 + m] += link[: n - t0] * rng.uniform(0.3, 1)
        t0 += secs(rng.exponential(0.035)) + secs(0.008)
    drag = band(noise(n), 1500, 6000) * slow(n, 6, 0.1, 0.6)
    return reverb((out + drag) * env(n, 0.05, 0.6), 1.0, 0.2).mean(axis=1)


def fx_bell_toll():
    gap = secs(2.4)
    one = bell(7.0)
    n = gap * 2 + len(one)
    x = np.zeros(n)
    for i in range(3):
        x[i * gap:i * gap + len(one)] += one
    return reverb(band(x, 60, 3500), 3.0, 0.35).mean(axis=1)[: secs(9.5)] * env(secs(9.5), 0.001, 1.5)


def fx_thunder_crack():
    return reverb(thunder(7.0), 2.0, 0.25).mean(axis=1)


def fx_knock_knock():
    parts = []
    for gap in (0.24, 0.24, 0.9, 0.0):
        n = secs(0.25)
        k = np.arange(n) / RATE
        knock = (np.sin(2 * np.pi * 120 * k) * np.exp(-k * 35) + 0.6 * np.sin(2 * np.pi * 310 * k) * np.exp(-k * 55)
                 + 0.3 * band(noise(n), 300, 3000) * np.exp(-k * 120))
        parts += [knock, np.zeros(secs(gap))]
    return reverb(np.concatenate(parts), 1.2, 0.25).mean(axis=1)


def fx_crow_caws():
    parts = []
    for gap in (0.18, 0.22, 0.0):
        parts += [crow_caw(), np.zeros(secs(gap))]
    return reverb(np.concatenate(parts), 1.6, 0.3).mean(axis=1)


EFFECTS = {
    "monster_roar": fx_monster_roar, "zombie_groan": fx_zombie_groan, "wolf_howl": fx_wolf_howl,
    "ghost_wail": fx_ghost_wail, "evil_whisper": fx_evil_whisper, "witch_cackle": fx_witch_cackle,
    "door_creak": fx_door_creak, "chains_rattle": fx_chains_rattle, "bell_toll": fx_bell_toll,
    "thunder_crack": fx_thunder_crack, "knock_knock": fx_knock_knock, "crow_caws": fx_crow_caws,
}


# ---- Background loops ----------------------------------------------------------------------

LOOP = 60.0


def wind_bed(n, lo=80, hi=900, gust_rate=0.08):
    return band(noise(n), lo, hi) * slow(n, gust_rate, 0.25, 1.0)


def amb_graveyard():
    n = secs(LOOP)
    bed = stereo_bed(n, lambda m: wind_bed(m) + 0.35 * band(noise(m), 500, 1400) * slow(m, 0.05) ** 3)
    events = np.zeros((n, 2))
    for p, pan in ((secs(4), -0.6), (secs(27), 0.5)):
        place(events, cricket(9.0, rng.uniform(4300, 4900)), p, 0.08, pan)
    for p in (secs(11), secs(43)):
        place(events, band(owl_hoots(), 200, 1200), p, 0.35, rng.uniform(-0.7, 0.7))
    toll = band(bell(6.0, 174.6), 60, 1800)
    for i in range(3):
        place(events, toll, secs(32) + i * secs(2.6), 0.12, -0.2)
    for p in (secs(19), secs(52)):
        place(events, np.concatenate([crow_caw(), np.zeros(secs(0.2)), crow_caw()]), p, 0.06, 0.8)
    wet = reverb(events.mean(axis=1), 2.5, 0.5, bright=3000, circular=True)
    return norm(bed * 0.6 + wet, rms=0.09)


def amb_sewer():
    n = secs(LOOP)
    flow = stereo_bed(n, lambda m: band(noise(m), 180, 2200) * (0.6 + 0.4 * band(noise(m), 2, 9, order=1) / 0.02))
    rumble = stereo_bed(n, lambda m: band(noise(m), 20, 90))
    drips = np.zeros(n)
    pos = 0
    while pos < n:
        d = drip() * rng.uniform(0.3, 1.0)
        idx = (pos + np.arange(len(d))) % n
        drips[idx] += d
        pos += secs(rng.exponential(0.7)) + secs(0.1)
    for p in (secs(15), secs(41)):
        clk = clank(2500)
        drips[(p + np.arange(len(clk))) % n] += clk * 0.25
    for p in (secs(8), secs(33), secs(50)):  # rat squeaks
        m = secs(0.12)
        f = np.linspace(3800, 5200, m) * (1 + 0.05 * np.sin(np.linspace(0, 40, m)))
        sq = np.sin(2 * np.pi * np.cumsum(f) / RATE) * np.sin(np.linspace(0, np.pi, m))
        for k in range(3):
            drips[(p + k * secs(0.18) + np.arange(m)) % n] += sq * 0.08
    wet = reverb(drips, 3.0, 0.55, bright=4500, circular=True)
    return norm(flow * 0.5 + rumble * 0.6 + wet * 0.9, rms=0.09)


def amb_asylum():
    n = secs(LOOP)
    t = np.arange(n) / RATE
    hum = sum(a * np.sin(2 * np.pi * f * t) for f, a in ((120, 1.0), (240, 0.5), (360, 0.3), (480, 0.15)))
    flicker = 1 - 0.9 * (band(noise(n), 0, 3) > 0.012)   # occasional dropouts
    hum = hum * flicker + band((rng.random(n) < 0.0005) * noise(n) * 5, 1000, 8000) * (flicker < 0.5)
    room = stereo_bed(n, lambda m: band(noise(m), 60, 400) * 0.6)
    events = np.zeros(n)
    for p in (secs(6), secs(29), secs(47)):  # distant moans
        mo = growl_voice(rng.uniform(2.5, 3.5), rng.uniform(170, 210), rng.uniform(140, 170), ("oo", "ah"), 0.3, 5)
        events[(p + np.arange(len(mo))) % n] += band(mo, 100, 1500) * env(len(mo), 0.8, 1.0) * 0.35
    for p in (secs(18), secs(39)):
        clk = clank(1800)
        events[(p + np.arange(len(clk))) % n] += clk * 0.18
    for i in range(6):  # slow footsteps down the hall
        s = footstep(hard=True)
        events[(secs(52) + i * secs(0.85) + np.arange(len(s))) % n] += s * (0.07 + 0.025 * i)
    notes = [659, 622, 587, 554, 523, 494, 523, 466]   # out-of-tune music box, far away
    for i, f in enumerate(notes):
        m = secs(1.2)
        k = np.arange(m) / RATE
        note = (np.sin(2 * np.pi * f * 2 * k) + 0.3 * np.sin(2 * np.pi * f * 6.1 * k)) * np.exp(-k * 4)
        events[(secs(22) + i * secs(0.6) + np.arange(m)) % n] += note * 0.05
    wet = reverb(events, 3.5, 0.6, bright=3500, circular=True)
    return norm(np.stack([hum, hum], axis=1) * 0.015 + room * 0.25 + wet, rms=0.08)


def amb_thunderstorm():
    n = secs(LOOP)
    rain = stereo_bed(n, lambda m: band(noise(m), 500, 9000) * slow(m, 0.1, 0.7, 1.0))
    roof = stereo_bed(n, lambda m: band(noise(m), 90, 900) * 0.7)
    drops = stereo_bed(n, lambda m: band((rng.random(m) < 0.004) * noise(m) * 4, 1500, 8000))
    wind = stereo_bed(n, lambda m: wind_bed(m, 100, 700, 0.06) * 0.8)
    events = np.zeros((n, 2))
    for p, crack, pan in ((secs(9), False, -0.4), (secs(31), True, 0.3), (secs(48), False, 0.7)):
        place(events, thunder(rng.uniform(7, 10), crack), p, 0.9 if crack else 0.6, pan)
    return norm(rain * 0.35 + roof * 0.4 + drops * 0.25 + wind * 0.35 + events, rms=0.1)


def amb_haunted_forest():
    n = secs(LOOP)
    gust = slow(n, 0.07, 0.15, 1.0)
    rustle = stereo_bed(n, lambda m: band(noise(m), 1200, 7000)) * gust[:, None] ** 2
    wind = stereo_bed(n, lambda m: band(noise(m), 90, 700)) * gust[:, None]
    events = np.zeros((n, 2))
    for p, pan in ((secs(13), -0.7), (secs(44), 0.6)):
        place(events, band(howl(rng.uniform(3.5, 4.5), rng.uniform(520, 640)), 150, 2500), p, 0.18, pan)
    for p in (secs(5), secs(25), secs(37), secs(55)):
        place(events, creak(rng.uniform(1.5, 2.6), (8, rng.uniform(25, 45), 12)), p, 0.25, rng.uniform(-0.8, 0.8))
    for p in rng.integers(0, n, 7):  # twigs snapping
        m = secs(0.05)
        place(events, band(noise(m), 800, 6000) * decay(m, 0.02), int(p), 0.5, rng.uniform(-1, 1))
    place(events, band(owl_hoots(), 200, 1200), secs(30), 0.2, 0.2)
    wet = reverb(events.mean(axis=1), 2.2, 0.45, bright=4000, circular=True)
    return norm(rustle * 0.25 + wind * 0.5 + wet, rms=0.09)


def amb_mad_lab():
    n = secs(LOOP)
    t = np.arange(n) / RATE
    throb = 0.75 + 0.25 * np.sin(2 * np.pi * t / 4)   # 4 s pulse fits the 60 s loop exactly
    hum = sum(a * np.sin(2 * np.pi * f * t) for f, a in ((50, 1.0), (100, 0.6), (150, 0.4), (250, 0.2))) * throb
    bub = band(bubbles(LOOP, 14), 150, 3000)
    geiger = band((rng.random(n) < 0.00012) * noise(n) * 12, 2000, 9000)
    events = np.zeros(n)
    for p in (secs(7), secs(21), secs(38), secs(53)):
        z = zap(rng.uniform(0.4, 1.4))
        events[(p + np.arange(len(z))) % n] += z * 0.5
    for p in (secs(15), secs(46)):  # steam hiss
        m = secs(2.0)
        events[(p + np.arange(m)) % n] += band(noise(m), 2500, 10000) * env(m, 0.05, 1.2) * 0.25
    wet = reverb(events + bub * 0.5 + geiger * 0.4, 1.4, 0.35, circular=True)
    return norm(np.stack([hum, hum], axis=1) * 0.04 + wet, rms=0.08)


def amb_witch_cauldron():
    n = secs(LOOP)
    big_bub = band(bubbles(LOOP, 7, 80, 300), 60, 1500)
    small_bub = band(bubbles(LOOP, 10, 300, 700), 200, 3000)
    fire = stereo_bed(n, fire_crackle)
    wind = stereo_bed(n, lambda m: wind_bed(m, 100, 600, 0.05) * 0.4)
    events = np.zeros(n)
    cackle = fx_witch_cackle()
    events[(secs(40) + np.arange(len(cackle))) % n] += band(cackle, 200, 3000) * 0.12
    wet = reverb(big_bub * 0.6 + small_bub * 0.3 + events, 1.2, 0.3, circular=True)
    return norm(wet + fire * 0.2 + wind, rms=0.09)


AMBIENCE = {
    "graveyard": amb_graveyard, "sewer": amb_sewer, "abandoned_asylum": amb_asylum,
    "thunderstorm": amb_thunderstorm, "haunted_forest": amb_haunted_forest,
    "mad_scientist_lab": amb_mad_lab, "witch_cauldron": amb_witch_cauldron,
}


# ---- Output ----------------------------------------------------------------------------------

def save(path, x, as_wav):
    x = np.atleast_2d(x.T).T if x.ndim == 1 else x
    pcm = (np.clip(x, -1, 1) * 32767).astype(np.int16)
    path.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = shutil.which("ffmpeg")
    if as_wav or not ffmpeg:
        path = path.with_suffix(".wav")
        with wave.open(str(path), "wb") as w:
            w.setnchannels(pcm.shape[1])
            w.setsampwidth(2)
            w.setframerate(RATE)
            w.writeframes(pcm.tobytes())
    else:
        bitrate = "128k" if pcm.shape[1] == 2 else "96k"
        subprocess.run([ffmpeg, "-v", "error", "-y", "-f", "s16le", "-ar", str(RATE), "-ac", str(pcm.shape[1]),
                        "-i", "-", "-codec:a", "libmp3lame", "-b:a", bitrate, str(path)],
                       input=pcm.tobytes(), check=True)
    print(f"  wrote {path.relative_to(ROOT)} ({len(x) / RATE:.1f}s)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="make just this one sound")
    ap.add_argument("--wav", action="store_true", help="write WAV instead of MP3")
    args = ap.parse_args()
    for name, fn in EFFECTS.items():
        if not args.only or args.only == name:
            save(FX_DIR / f"{name}.mp3", norm(fn(), rms=0.14), args.wav)
    for name, fn in AMBIENCE.items():
        if not args.only or args.only == name:
            save(AMB_DIR / f"{name}.mp3", fn(), args.wav)
