"""Light the bulbs of your light chains one at a time, to see where they really are.

The dashboard needs to know which slice of the yard each chain covers, and whether its
first bulb is at the west or the east end. Guessing at that gets the yard out of step:
a sound plays in one place and the wrong bulb lights. This walks the whole run, one
solid white bulb at a time, so you can stand outside and write down what you see.

    sudo systemctl stop spooky          # or leave it running, this pauses light sync
    python3 walk_bulbs.py

Press Enter to step to the next bulb, type a number to jump to it, or q to finish.
Light sync is paused while it runs and switched back on at the end.

Non-interactive (handy over ssh): run it with --file, and it takes the bulb number from
/tmp/spooky_walk instead, re-reading it continuously:

    python3 walk_bulbs.py --file &
    echo 3 > /tmp/spooky_walk
    echo done > /tmp/spooky_walk
"""
import json
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import govee

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / "config.json"
STATE = Path("/tmp/spooky_walk")
DASHBOARD = "http://127.0.0.1"
WHITE, OFF = (255, 255, 255), (0, 0, 0)
FRAME_SECONDS = 0.15      # a chain drops out of segment mode without a steady stream


def chains():
    """Every chain that's switched on, west to east, with the bulb numbers it holds."""
    cfg = json.loads(CONFIG.read_text())
    devices = [d for d in cfg.get("lights", {}).get("devices", []) if d.get("chain") and d.get("on", True)]
    devices.sort(key=lambda d: d.get("span_start", 0))
    out, first = [], 1
    for d in devices:
        n = int(d.get("segments", 4))
        out.append({"ip": d["ip"], "name": d.get("name", d["ip"]), "segments": n,
                    "reverse": bool(d.get("reverse")), "first": first, "last": first + n - 1})
        first += n
    return out


def sync(on):
    """Switch the dashboard's light sync on or off, so the engine stops repainting."""
    body = json.dumps({"lights": {"enabled": on}}).encode()
    req = urllib.request.Request(f"{DASHBOARD}/api/config", data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=5).read()
        return True
    except (urllib.error.URLError, OSError):
        return False      # not running, which is fine: nothing to pause


def frames(runs, bulb):
    """One frame per chain: the chosen bulb white, every other bulb dark."""
    out = {}
    for c in runs:
        seg = [OFF] * c["segments"]
        if c["first"] <= bulb <= c["last"]:
            i = bulb - c["first"]
            seg[c["segments"] - 1 - i if c["reverse"] else i] = WHITE
        out[c["ip"]] = seg
    return out


def main():
    runs = chains()
    if not runs:
        sys.exit("No chains switched on. Turn on 'Chain across the yard' for a light first.")
    total = runs[-1]["last"]

    print("Bulbs, west to east:")
    for c in runs:
        where = "first bulb at its east end" if c["reverse"] else "first bulb at its west end"
        print(f"  {c['first']}-{c['last']}  {c['name']} ({c['ip']}, {where})")
    print()

    paused = sync(False)
    print("light sync paused" if paused else "dashboard not answering, carrying on")

    g = govee.Govee()
    for c in runs:
        g.power(c["ip"], True)
        g.brightness(c["ip"], 100)
        g.segments_mode(c["ip"], True)
    time.sleep(1.5)

    use_file = "--file" in sys.argv
    if use_file:
        STATE.write_text("1")
    bulb, stop, shown = 1, threading.Event(), None

    def stream():
        while not stop.is_set():
            for ip, seg in frames(runs, bulb).items():
                g.segments(ip, seg)
            time.sleep(FRAME_SECONDS)

    streamer = threading.Thread(target=stream, daemon=True)
    streamer.start()
    try:
        while True:
            if use_file:
                want = STATE.read_text().strip() if STATE.exists() else "1"
                if want in ("done", "q"):
                    break
                if want.isdigit():
                    bulb = max(1, min(total, int(want)))
                if bulb != shown:
                    print(f"{time.strftime('%H:%M:%S')}  bulb {bulb} of {total}", flush=True)
                    shown = bulb
                time.sleep(0.2)
                continue
            answer = input(f"bulb {bulb} of {total} lit - Enter for next, a number to jump, q to finish: ").strip()
            if answer in ("q", "quit", "done"):
                break
            if answer.isdigit():
                bulb = max(1, min(total, int(answer)))
            elif bulb >= total:
                print("that was the last one")
            else:
                bulb += 1
    except (EOFError, KeyboardInterrupt):
        print()
    finally:
        stop.set()
        streamer.join(timeout=2)
        if paused:
            sync(True)
            print("light sync switched back on")


if __name__ == "__main__":
    main()
