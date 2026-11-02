#!/usr/bin/env python3
"""Synthesize original Christmas sounds for the Lentz Holiday Spectacular, free to use and share.

  sounds-christmas/*.mp3            one-shots (sleigh bells, music-box carols, chimes, hooves…)
  sounds-christmas/ambience/*.mp3   seamless background loops (fireplace, snowy night, workshop)

Built with the same toolkit as make_spooky_sounds.py. The carols are traditional tunes in the
public domain; every note is synthesized here.

Usage: python3 make_christmas_sounds.py [--only NAME] [--wav]
Needs ffmpeg for MP3 output (otherwise writes WAV).
"""
import argparse

import numpy as np

from make_spooky_sounds import (LOOP, RATE, ROOT, band, bell, decay, env, fire_crackle, noise, norm, place,
                                reverb, rng, save, secs, slow, stereo_bed, tt, wind_bed)

FX_DIR = ROOT / "sounds-christmas"
AMB_DIR = FX_DIR / "ambience"


# ---- Building blocks -------------------------------------------------------------------

def soft(x, drive=2.5):
    """Round off the peaks, so a few sharp clicks don't set the level for the whole sound."""
    return np.tanh(drive * x / (np.max(np.abs(x)) + 1e-9))


def midi(n):
    return 440.0 * 2 ** ((n - 69) / 12)


def tine(freq, dur=1.6):
    """One music-box note: a plucked steel tine, bright at first and ringing away."""
    t = tt(dur)
    x = sum(a * np.sin(2 * np.pi * freq * r * t) * decay(len(t), dur * d)
            for r, a, d in ((1.0, 1.0, 0.9), (2.0, 0.35, 0.5), (3.0, 0.12, 0.3), (5.4, 0.18, 0.08)))
    return x * env(len(t), 0.002, 0.05)


def tune(notes, bpm=132, dur=1.6, swing=0.0):
    """Lay tines out on a beat grid. notes: [(midi or None for a rest, beats)]."""
    beat = 60 / bpm
    total = sum(b for _, b in notes) * beat + dur
    out = np.zeros(secs(total))
    pos = 0.0
    for i, (n, b) in enumerate(notes):
        if n is not None:
            one = tine(midi(n), dur) * rng.uniform(0.85, 1.0)
            at = secs(pos + (swing * beat if i % 2 else 0))
            out[at:at + len(one)] += one[:len(out) - at]
        pos += b * beat
    return out


def jingle(dur=0.35):
    """A cluster of small bells shaken once: bright, inharmonic, quick to fade."""
    n = secs(dur)
    t = np.arange(n) / RATE
    x = np.zeros(n)
    for _ in range(7):
        f = rng.uniform(2800, 6500)
        start = rng.integers(0, secs(0.03))
        ring = sum(a * np.sin(2 * np.pi * f * r * t[:n - start] + rng.uniform(0, 6))
                   for r, a in ((1.0, 1.0), (2.76, 0.5), (5.4, 0.25)))
        x[start:] += ring * decay(n - start, rng.uniform(0.12, 0.3))
    x += band(noise(n), 4000, 12000) * decay(n, 0.04) * 0.6   # the rattle of the clapper
    return x * env(n, 0.001, 0.05)


def sleigh_shake(dur, rate=4.2, swell=True):
    """Bells shaken in time, the way they ride on a trotting harness."""
    out = np.zeros(secs(dur) + secs(0.4))
    step = 1 / rate
    k = 0
    while k * step < dur:
        g = np.sin(np.pi * k * step / dur) if swell else 1.0
        g *= 1.0 if k % 2 == 0 else 0.6                       # strong-weak, like hoofbeats
        one = jingle() * (0.3 + 0.7 * g)
        at = secs(k * step + rng.uniform(-0.01, 0.01))
        out[max(at, 0):max(at, 0) + len(one)] += one
        k += 1
    return out


def hoof(hard=1.0):
    n = secs(0.12)
    x = band(noise(n), 250, 2600) * decay(n, 0.035) * hard
    x += np.sin(2 * np.pi * rng.uniform(140, 190) * np.arange(n) / RATE) * decay(n, 0.05) * 0.8 * hard
    return x


def tap(bright=3500):
    """A small hammer on wood: the elves at work."""
    n = secs(0.18)
    x = band(noise(n), 400, bright) * decay(n, 0.03)
    x += np.sin(2 * np.pi * rng.uniform(600, 900) * np.arange(n) / RATE) * decay(n, 0.04) * 0.5
    return x


def tick(n_secs, rate=2.0, freq=3200):
    """A clock ticking: alternating tick and tock."""
    out = np.zeros(secs(n_secs))
    for k in range(int(n_secs * rate)):
        m = secs(0.02)
        click = band(noise(m), freq * (1.0 if k % 2 else 0.8), freq * 2.2) * decay(m, 0.006)
        at = secs((k + 0.5) / rate)            # off the loop point, so the seam stays smooth
        out[at:at + m] += click[:len(out) - at]
    return out


# Traditional melodies (public domain), as (midi note, beats)
E5, F5, G5, A5, B5, C5, D5, C6, B4, FS5 = 76, 77, 79, 81, 83, 72, 74, 84, 71, 78
JINGLE_BELLS = [(E5, 1), (E5, 1), (E5, 2), (E5, 1), (E5, 1), (E5, 2), (E5, 1), (G5, 1), (C5, 1.5), (D5, .5),
                (E5, 4), (F5, 1), (F5, 1), (F5, 1.5), (F5, .5), (F5, 1), (E5, 1), (E5, 1), (E5, .5), (E5, .5),
                (E5, 1), (D5, 1), (D5, 1), (E5, 1), (D5, 2), (G5, 2)]
DECK_THE_HALLS = [(G5, 1.5), (F5, .5), (E5, 1), (D5, 1), (C5, 1), (D5, 1), (E5, 1), (C5, 1),
                  (D5, .5), (E5, .5), (F5, .5), (D5, .5), (E5, 1.5), (D5, .5), (C5, 1), (B4, 1), (C5, 2)]
WE_WISH_YOU = [(D5, 1), (G5, 1), (G5, .5), (A5, .5), (G5, .5), (FS5, .5), (E5, 1), (E5, 1),
               (E5, 1), (A5, 1), (A5, .5), (B5, .5), (A5, .5), (G5, .5), (FS5, 1), (D5, 1),
               (D5, 1), (B5, 1), (B5, .5), (C6, .5), (B5, .5), (A5, .5), (G5, 1), (E5, 1),
               (D5, .5), (D5, .5), (E5, 1), (A5, 1), (FS5, 1), (G5, 2)]


# ---- One-shots -----------------------------------------------------------------------------

def fx_sleigh_bells():
    return soft(reverb(band(sleigh_shake(5.0), 1500, 14000), 1.2, 0.25).mean(axis=1))


def fx_music_box_jingle_bells():
    return reverb(tune(JINGLE_BELLS, 150), 1.5, 0.3, bright=7000).mean(axis=1)


def fx_music_box_deck_the_halls():
    return reverb(tune(DECK_THE_HALLS, 120), 1.5, 0.3, bright=7000).mean(axis=1)


def fx_music_box_we_wish_you():
    return reverb(tune(WE_WISH_YOU, 140), 1.5, 0.3, bright=7000).mean(axis=1)


def fx_church_bells_peal():
    """Eight bells rung down the scale, twice round: a Christmas morning peal."""
    gap = secs(0.42)
    scale = [523.3, 493.9, 440.0, 392.0, 349.2, 329.6, 293.7, 261.6]
    one_len = secs(5.0)
    x = np.zeros(gap * 16 + one_len)
    for i in range(16):
        b = bell(5.0, scale[i % 8] / 2) * (0.8 if i % 8 else 1.0)
        x[i * gap:i * gap + one_len] += b[:one_len]
    return reverb(band(x, 80, 5000), 3.5, 0.4).mean(axis=1)[: secs(11)] * env(secs(11), 0.001, 2.0)


def fx_sparkle_chime():
    """A quick run up a pentatonic scale, then a shimmer: something magical just happened."""
    notes = [(n, 0.25) for n in (72, 74, 76, 79, 81, 84, 86, 88, 91, 93, 96)] + [(None, 0.5), (96, 1)]
    run = tune(notes, 220, dur=2.2)
    shimmer = band(noise(len(run)), 6000, 14000) * slow(len(run), 3, 0, 1) ** 2 * 0.08 * decay(len(run), 2.0)
    return soft(reverb(run + shimmer, 2.5, 0.45, bright=9000).mean(axis=1), 1.8)


def fx_reindeer_on_the_roof():
    """Hooves clattering across the roof, bells on the harness, then they're off."""
    dur = 4.5
    out = np.zeros(secs(dur + 0.5))
    t = 0.0
    while t < dur:
        for off, g in ((0.0, 1.0), (0.09, 0.7), (0.2, 0.85)):     # da-da-dum, a canter
            one = hoof(g * (0.5 + 0.5 * np.sin(np.pi * t / dur)))
            at = secs(t + off)
            out[at:at + len(one)] += one[:len(out) - at]
        t += 0.42
    bells = sleigh_shake(dur, rate=2.4)[: len(out)] * 0.35
    out[: len(bells)] += bells
    return soft(reverb(band(out, 120, 9000), 0.8, 0.2).mean(axis=1))


EFFECTS = {
    "sleigh_bells": fx_sleigh_bells, "music_box_jingle_bells": fx_music_box_jingle_bells,
    "music_box_deck_the_halls": fx_music_box_deck_the_halls, "music_box_we_wish_you": fx_music_box_we_wish_you,
    "church_bells_peal": fx_church_bells_peal, "sparkle_chime": fx_sparkle_chime,
    "reindeer_on_the_roof": fx_reindeer_on_the_roof,
}


# ---- Background loops ----------------------------------------------------------------------

def amb_crackling_fireplace():
    n = secs(LOOP)
    bed = stereo_bed(n, lambda m: soft(fire_crackle(m), 4.0))
    events = np.zeros((n, 2))
    for p in (secs(13), secs(38), secs(51)):                          # a log settling
        thump = band(noise(secs(0.5)), 40, 400) * decay(secs(0.5), 0.15) * 2
        place(events, thump, p, 0.4, rng.uniform(-0.3, 0.3))
    wet = reverb(events.mean(axis=1) + bed.mean(axis=1) * 0.3, 0.6, 0.3, bright=4000, circular=True)
    return norm(bed * 0.7 + wet, rms=0.09)


def amb_snowy_night():
    n = secs(LOOP)
    bed = stereo_bed(n, lambda m: wind_bed(m, 60, 600, 0.05) * 0.8 + band(noise(m), 2000, 6000) * 0.04)
    events = np.zeros((n, 2))
    # A sleigh passing in the distance, left to right
    pass_len = secs(14)
    bells = band(sleigh_shake(14, rate=3.6), 2000, 9000)[:pass_len]
    pan = np.linspace(-0.9, 0.9, pass_len)
    th = (pan + 1) * np.pi / 4
    place(events, np.stack([bells * np.cos(th), bells * np.sin(th)], axis=1), secs(8), 0.25)
    toll = band(bell(6.0, 196.0), 60, 2000)
    for i in range(3):                                                 # a church far off
        place(events, toll, secs(36) + i * secs(2.8), 0.08, 0.4)
    wet = reverb(events.mean(axis=1), 3.0, 0.55, bright=5000, circular=True)
    return norm(bed * 0.6 + wet + events * 0.3, rms=0.08)


def amb_santas_workshop():
    n = secs(LOOP)
    bed = stereo_bed(n, lambda m: band(noise(m), 100, 1200) * slow(m, 0.2, 0.3, 0.6) * 0.15)
    events = np.zeros((n, 2))
    clock = tick(LOOP, 2.0)
    place(events, np.stack([clock * 0.4, clock * 0.25], axis=1), 0, 0.5)
    t = 0.7                                                           # not on the loop point
    while t < LOOP - 2:                                               # elves hammering, here and there
        burst = rng.integers(2, 6)
        pan = rng.uniform(-0.8, 0.8)
        for k in range(burst):
            place(events, tap(), secs(t + k * 0.22), rng.uniform(0.25, 0.45), pan)
        t += rng.uniform(2.5, 6.0)
    box = tune(JINGLE_BELLS, 150)
    place(events, box, secs(20), 0.18, -0.4)                         # someone testing a music box
    for p in (secs(5), secs(47)):
        place(events, jingle(0.5), p, 0.25, rng.uniform(-0.6, 0.6))
    wet = reverb(events.mean(axis=1), 1.4, 0.35, bright=6000, circular=True)
    return norm(soft(bed + wet + events * 0.5, 2.0), rms=0.09)


AMBIENCE = {
    "crackling_fireplace": amb_crackling_fireplace, "snowy_night": amb_snowy_night,
    "santas_workshop": amb_santas_workshop,
}


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
