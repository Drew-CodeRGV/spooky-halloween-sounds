"""The yard as measured by walking the bulbs: two 4-bulb strings over 10-50 and 50-78,
speakers at 21.6 / 49.7 / 77.6%. Bulb 1 sits west of the first speaker, bulb 4 on the
porch, and the eastmost speaker falls between bulbs 7 and 8."""
import copy, pathlib, sys, threading, types
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import numpy as np, engine

cfg = copy.deepcopy(engine.DEFAULT_CONFIG)
XS = {"p1": 21.6, "p7": 49.7, "p5": 77.6}
for p in cfg["placements"]:
    p["enabled"] = p["id"] in XS
    if p["enabled"]:
        p["x"], p["y"] = XS[p["id"]], 50.0
cfg["lights"]["enabled"] = True
cfg["lights"]["devices"] = [
    {"ip": "w", "name": "West string", "chain": True, "segments": 4, "span_start": 10, "span_end": 50},
    {"ip": "e", "name": "East string", "chain": True, "segments": 4, "span_start": 50, "span_end": 78},
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
    def add_log(self, m): pass

L = engine.Lights.__new__(engine.Lights)
L.eng, L.govee = FakeEng(), FakeGovee()
L.event, L.tests, L.last, L.chains, L.dark_t, L._sched = None, {}, {}, {}, None, (0, None)
pos = L._chain_positions()
for pid in ("p1", "p7", "p5"):
    print(f"  speaker {pid} at x={XS[pid]}%  ->  placed at {pos[pid]*100:.1f}%")

def bulbs():
    """Bulb 1-8 brightness: the west string, then the east. Both run west to east."""
    return [int(c[0]) for c in sent["w"]] + [int(c[0]) for c in sent["e"]]

def paint(ev, settle=12):
    for dev in cfg["lights"]["devices"]:
        L.chains.pop(dev["ip"], None)
        for _ in range(settle):
            L._chain_tick(dev, ev, pos, (255, 90, 0), 70, False, 1000.0)
    return bulbs()

mono = np.ones(engine.RATE, dtype=np.float32)
env = engine.envelope(mono)
def one(spot):
    return {"color": (255, 0, 0), "env": env, "spots": [spot], "sweep": False, "len": len(mono),
            "voice": {"pos": engine.RATE // 2, "done": threading.Event()}}

print("\nsingle sounds (bulbs 1-8, idle ~190, lit 255):")
for pid, name in (("p1", "West Mid Bushes"), ("p7", "Front porch"), ("p5", "East Bushes")):
    b = paint(one(pid))
    print(f"  {name:<16} {''.join('#' if v > 235 else ('+' if v > 205 else '.') for v in b)}  {b}")

west_b, porch_b, east_b = (paint(one(p)) for p in ("p1", "p7", "p5"))
# the measured yard: speaker 1 sits between bulbs 1 and 2, the porch is on bulb 4,
# and the eastmost speaker is between bulbs 7 and 8
assert np.argmax(west_b) in (0, 1), f"speaker 1 belongs at bulb 1-2: {west_b}"
# the porch is at 49.7%, right where the two strings meet, so bulbs 4 and 5 share it
assert np.argmax(porch_b) in (3, 4), f"the porch belongs on bulbs 4-5: {porch_b}"
assert min(porch_b[3], porch_b[4]) > max(porch_b[:3] + porch_b[5:]) + 20, porch_b
assert np.argmax(east_b) in (6, 7), f"the eastmost speaker belongs at bulb 7-8: {east_b}"
print("  OK: every sound lights the bulb actually beside it")

print("\nfull sweep west -> east:")
long = np.ones(engine.RATE * 4, dtype=np.float32)
spots = ["p1", "p7", "p5"]
hottest = []
for step in range(17):
    ev = {"color": (255, 0, 0), "env": engine.envelope(long), "spots": spots, "sweep": True,
          "len": len(long), "voice": {"pos": int(step / 16 * (len(long) - 1)), "done": threading.Event()}}
    b = paint(ev, settle=6)
    hottest.append(int(np.argmax(b)) + 1)
    print(f"  {step/16*4:4.1f}s bulb {hottest[-1]}  " + "".join("#" if v > 235 else ("+" if v > 205 else ".") for v in b))
assert hottest[0] <= 2, f"a sweep should start at the west end: {hottest}"
assert hottest[-1] >= 7, f"and finish at the east end: {hottest}"
assert all(b >= a - 1 for a, b in zip(hottest, hottest[1:])), f"it jumped back: {hottest}"
assert len(set(hottest)) >= 6, f"it should visit most of the run: {hottest}"
print("\nOK: sounds track the length of the run, on the right bulbs")
