"""The flicker sliders: depth is how far bulbs dip, speed is how often they change."""
import copy, pathlib, sys, types
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import numpy as np, engine

cfg = copy.deepcopy(engine.DEFAULT_CONFIG)
cfg["lights"]["devices"] = [{"ip": "w", "chain": True, "segments": 4}]
cfg = engine.sanitize(cfg)
li = cfg["lights"]
print(f"defaults: flicker={li['flicker']} rate={li['flicker_rate']}/s depth={li['flicker_depth']}")

class FakeEng:
    config = cfg
    ambience = types.SimpleNamespace(status=lambda: {"playing": False})
    def add_log(self, m): pass

L = engine.Lights.__new__(engine.Lights)
L.eng, L.flick = FakeEng(), {}

# --- depth 0 means no flicker at all ---
li["flicker_depth"] = 0.0
assert np.all(L._flicker("w", 4, 100.0) == 1.0)
print("depth 0: every bulb steady")

# --- levels stay inside the band the depth sets ---
for depth in (0.2, 0.4, 0.9):
    li["flicker_depth"] = depth
    L.flick.clear()
    seen = []
    for i in range(400):
        seen.append(L._flicker("w", 4, 100.0 + i).copy())   # 1s apart: a new pick each time
    a = np.concatenate(seen)
    lo, hi = 1 - depth, 1 + depth * 0.25
    assert a.min() >= lo - 1e-9 and a.max() <= hi + 1e-9, (depth, a.min(), a.max())
    print(f"depth {depth}: levels spanned {a.min():.2f}-{a.max():.2f} (band {lo:.2f}-{hi:.2f})")

# --- the rate decides how often a bulb picks a new level ---
li["flicker_depth"] = 0.5
for rate in (1.0, 3.0, 5.0, 15.0):
    li["flicker_rate"] = rate
    L.flick.clear()
    at, prev, t = [], None, 0.0
    for _ in range(int(20 * engine.LIGHT_HZ)):     # twenty seconds at the engine's tick rate
        cur = L._flicker("w", 1, t).copy()
        if prev is not None and cur[0] != prev[0]:
            at.append(t)
        prev, t = cur, t + 1 / engine.LIGHT_HZ
    gaps = np.diff(at)
    got = 1 / gaps.mean()
    print(f"rate {rate:>5}/s: {len(at)} changes in 20s, average {got:.2f}/s")
    assert abs(got - rate) < max(0.2, rate * 0.08), f"asked {rate}/s, got {got:.2f}/s"

# --- it no longer waits for an atmosphere to be playing ---
import inspect
src = inspect.getsource(engine.Lights._tick)
assert "ambience" not in src, "flicker should not depend on an atmosphere any more"
print("flicker runs whenever it is switched on, not only under an atmosphere")
print("\nOK: flicker speed and depth both do what the sliders say")
