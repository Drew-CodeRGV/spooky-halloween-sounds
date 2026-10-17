"""The re-arm packet blinks the string, so it must be rare while frames keep flowing."""
import copy, pathlib, sys, threading, types
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import numpy as np, engine

cfg = copy.deepcopy(engine.DEFAULT_CONFIG)
for i, p in enumerate(cfg["placements"]):
    p["enabled"], p["x"], p["y"] = True, 10 + i * 13.0, 50
cfg["lights"]["enabled"] = True
cfg["lights"]["devices"] = [{"ip": "w", "chain": True, "segments": 4, "span_start": 0, "span_end": 50}]
cfg = engine.sanitize(cfg)
dev = cfg["lights"]["devices"][0]

rearms = []
class FakeGovee:
    def power(self, *a): pass
    def brightness(self, *a): pass
    def color(self, *a): pass
    def segments(self, *a): pass
    def segments_mode(self, ip, on):
        if on: rearms.append(round(NOW[0], 1))
class FakeEng:
    config = cfg
    ambience = types.SimpleNamespace(status=lambda: {"playing": False})
    def add_log(self, m): pass

L = engine.Lights.__new__(engine.Lights)
L.eng, L.govee = FakeEng(), FakeGovee()
L.event, L.tests, L.last, L.chains, L.dark_t, L._sched = None, {}, {}, {}, None, (0, None)
NOW = [1000.0]
pos = L._chain_positions()

def tick(ev=None):
    L._chain_tick(dev, ev, pos, (255, 90, 0), 50, False, NOW[0])

# --- an hour of quiet, ticking at the engine's real rate ---
for _ in range(int(3600 * engine.LIGHT_HZ)):
    tick(); NOW[0] += 1 / engine.LIGHT_HZ
print(f"one quiet hour: {len(rearms)} re-arms at t+{[round(r-1000) for r in rearms]}s")
assert len(rearms) <= 7, f"too many blinks: {len(rearms)}"
assert rearms[0] == 1000.0, "should arm on the very first tick"
gaps = [b - a for a, b in zip(rearms, rearms[1:])]
assert all(g >= engine.MODE_REARM * 2 - 1 for g in gaps), f"quiet re-arms too close: {gaps}"

# --- the old code re-armed every 20s: 180 blinks an hour ---
print(f"the old every-20s rule would have been {3600 // 20} blinks in that hour")

# --- a lapse in the frame stream re-arms straight away (light came back after a power cut) ---
rearms.clear()
NOW[0] += 45                      # no frames went out for 45s
tick()
assert rearms, "a stale stream must re-arm"
print(f"after a 45s gap in the stream: re-armed immediately ({len(rearms)})")

# --- while a sound plays, re-arming is allowed sooner, since the flare hides it ---
rearms.clear()
mono = np.ones(engine.RATE, dtype=np.float32)
ev = {"color": (255, 0, 0), "env": engine.envelope(mono), "spots": ["p1"], "sweep": False,
      "len": len(mono), "voice": {"pos": 0, "done": threading.Event()}}
start = NOW[0]
while NOW[0] - start < engine.MODE_REARM * 1.5:
    tick(ev); NOW[0] += 1 / engine.LIGHT_HZ
assert rearms, "should re-arm within MODE_REARM while playing"
assert rearms[0] - start >= engine.MODE_REARM - 1, "but not before MODE_REARM"
print(f"while a sound plays: re-armed {round(rearms[0]-start)}s in (MODE_REARM={engine.MODE_REARM}s)")
print("\nOK: no blinking during normal running, recovery still works")
