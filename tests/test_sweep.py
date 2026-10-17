"""A sweep should hand off from the west string to the east one: bulbs 1 -> 8 in order."""
import copy, pathlib, sys, threading, types
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import numpy as np
import engine

cfg = copy.deepcopy(engine.DEFAULT_CONFIG)
for i, p in enumerate(cfg["placements"]):
    p["enabled"], p["x"], p["y"] = True, 10 + i * 13.0, 50
cfg["lights"]["enabled"] = True
cfg["lights"]["devices"] = [
    {"ip": "w", "name": "west", "chain": True, "segments": 4, "span_start": 0, "span_end": 50},
    {"ip": "e", "name": "east", "chain": True, "segments": 4, "span_start": 50, "span_end": 100},
]
cfg = engine.sanitize(cfg)

sent = {}
class FakeGovee:
    def power(self, *a): pass
    def brightness(self, *a): pass
    def color(self, *a): pass
    def segments_mode(self, *a): pass
    def segments(self, ip, colors): sent[ip] = colors
class FakeEng:
    config = cfg
    ambience = types.SimpleNamespace(status=lambda: {"playing": False})
    def add_log(self, m): print("LOG", m)

L = engine.Lights.__new__(engine.Lights)
L.eng, L.govee = FakeEng(), FakeGovee()
L.event, L.tests, L.last, L.chains, L.dark_t, L._sched = None, {}, {}, {}, None, (0, None)

mono = np.ones(engine.RATE * 4, dtype=np.float32)
spots = [p["id"] for p in cfg["placements"]]
env = engine.envelope(mono)
pos_map = L._chain_positions()
print("a 4-second sweep west to east — the brightest bulb at each step:")
hottest = []
for step in range(21):
    ev = {"color": (255, 0, 0), "env": env, "spots": spots, "sweep": True, "len": len(mono),
          "voice": {"pos": int(step / 20 * (len(mono) - 1)), "done": threading.Event()}}
    for dev in cfg["lights"]["devices"]:
        for _ in range(6):
            L._chain_tick(dev, ev, pos_map, (255, 90, 0), 50, False, 1000.0 + step)
    reds = [int(c[0]) for c in sent["w"]] + [int(c[0]) for c in sent["e"]]
    bulb = int(np.argmax(reds)) + 1
    hottest.append(bulb)
    print(f"  {step/20*4:4.1f}s  bulb {bulb}  " + "".join("#" if r > 190 else ("+" if r > 170 else ".") for r in reds))
assert hottest[0] <= 2 and hottest[-1] >= 7, hottest
# one bulb of wobble is the flame flicker at the hand-off, where bulbs 4 and 5 are both lit
assert all(b >= a - 1 for a, b in zip(hottest, hottest[1:])), f"the sweep jumped back: {hottest}"
assert max(hottest[:7]) <= 4 and min(hottest[-7:]) >= 5, hottest
print("\nOK: the sweep runs west to east across both strings, handing off at bulbs 4-5")
