#!/usr/bin/env python3
"""Draw the jack-o'-lantern app icons in static/icons/ (only numpy needed)."""
import struct
import zlib
from pathlib import Path

import numpy as np

OUT = Path(__file__).parent / "static" / "icons"

PURPLE_IN, PURPLE_OUT = np.array([107, 47, 163]), np.array([42, 8, 69])
ORANGE, RIDGE = np.array([255, 122, 26]), np.array([214, 86, 8])
STEM, GLOW = np.array([74, 122, 42]), np.array([255, 214, 70])


def write_png(path, img):
    h, w, _ = img.shape
    raw = b"".join(b"\x00" + img[y].tobytes() for y in range(h))

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def in_tri(x, y, a, b, c):
    def side(p, q):
        return (x - q[0]) * (p[1] - q[1]) - (p[0] - q[0]) * (y - q[1])
    d1, d2, d3 = side(a, b), side(b, c), side(c, a)
    neg = (d1 < 0) | (d2 < 0) | (d3 < 0)
    pos = (d1 > 0) | (d2 > 0) | (d3 > 0)
    return ~(neg & pos)


def ellipse(x, y, cx, cy, rx, ry):
    return ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2


def draw(size, scale):
    ss = size * 2  # supersample for smooth edges
    v, u = np.mgrid[0:ss, 0:ss] / ss * 2 - 1           # -1..1
    x, y = u / scale, v / scale - 0.06                  # pumpkin space

    r = np.clip(np.hypot(u, v + 0.3) / 1.6, 0, 1)[..., None]
    img = PURPLE_IN * (1 - r) + PURPLE_OUT * r

    center = ellipse(x, y, 0, 0.12, 0.52, 0.58)
    left = ellipse(x, y, -0.3, 0.15, 0.5, 0.5)
    right = ellipse(x, y, 0.3, 0.15, 0.5, 0.5)
    body = (center < 1) | (left < 1) | (right < 1)
    ridge = body & (np.abs(np.sqrt(center) - 1) < 0.03) & (np.abs(y - 0.12) > 0.36)
    stem = (np.abs(x + (y + 0.5) * 0.25) < 0.08) & (y > -0.66) & (y < -0.38)

    eye_l = in_tri(x, y, (-0.42, 0.06), (-0.12, 0.06), (-0.27, -0.16))
    eye_r = in_tri(x, y, (0.12, 0.06), (0.42, 0.06), (0.27, -0.16))
    nose = in_tri(x, y, (-0.07, 0.2), (0.07, 0.2), (0, 0.1))
    mouth = (ellipse(x, y, 0, 0.26, 0.42, 0.28) < 1) & (y > 0.3)
    teeth = ((np.abs(x + 0.17) < 0.07) | (np.abs(x - 0.17) < 0.07)) & (y < 0.39)
    tooth_bottom = (np.abs(x) < 0.08) & (y > 0.47)
    face = eye_l | eye_r | nose | (mouth & ~teeth & ~tooth_bottom)

    img[stem] = STEM
    img[body] = ORANGE
    img[ridge] = RIDGE
    img[body & face] = GLOW
    return img.reshape(size, 2, size, 2, 3).mean(axis=(1, 3)).round().astype(np.uint8)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for name, size, scale in [("icon-192.png", 192, 0.82), ("icon-512.png", 512, 0.82),
                              ("maskable-512.png", 512, 0.66), ("apple-touch-icon.png", 180, 0.8)]:
        write_png(OUT / name, draw(size, scale))
        print(f"  wrote static/icons/{name}")
