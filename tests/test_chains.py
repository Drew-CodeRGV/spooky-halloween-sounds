"""Check two Govee chains: old string west (bulbs 1-4), new string east (5-8)."""
import copy, pathlib, sys, threading, types
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import numpy as np
import engine

# --- a yard with 7 speakers spread west to east, and two 4-segment chains ---
cfg = copy.deepcopy(engine.DEFAULT_CONFIG)
for i, p in enumerate(cfg["placements"]):
    p["enabled"] = True
    p["x"] = 10 + i * 13.0          # 10,23,36,49,62,75,88
    p["y"] = 50
cfg["lights"]["enabled"] = True
cfg["lights"]["devices"] = [
    {"ip": "10.0.0.11", "name": "Old string (west)", "chain": True, "segments": 4,
     "span_start": 0, "span_end": 50},
    {"ip": "10.0.0.12", "name": "New string (east)", "chain": True, "segments": 4,
     "span_start": 50, "span_end": 100},
]
cfg = engine.sanitize(cfg)
west, east = cfg["lights"]["devices"]
print("spans after sanitize:", [(d["name"], d["span_start"], d["span_end"]) for d in cfg["lights"]["devices"]])

sent = {}
class FakeGovee:
    def power(self, ip, on): pass
    def brightness(self, ip, pct): pass
    def color(self, ip, rgb): pass
    def segments_mode(self, ip, on): pass
    def segments(self, ip, colors): sent[ip] = colors

class FakeEng:
    config = cfg
    ambience = types.SimpleNamespace(status=lambda: {"playing": False})
    def add_log(self, m): print("LOG", m)

lights = engine.Lights.__new__(engine.Lights)   # no background thread for the test
lights.eng, lights.govee = FakeEng(), FakeGovee()
lights.event, lights.tests, lights.last, lights.chains = None, {}, {}, {}
lights.dark_t, lights._sched = None, (0, None)

mono = np.ones(engine.RATE, dtype=np.float32)   # a steady one-second sound
def play_at(spot_id):
    ev = {"color": (255, 0, 0), "env": engine.envelope(mono), "spots": [spot_id],
          "voice": {"pos": engine.RATE // 2, "done": threading.Event()}, "sweep": False,
          "len": len(mono)}
    pos = lights._chain_positions()
    for dev in cfg["lights"]["devices"]:
        lights.chains.pop(dev["ip"], None)
        for _ in range(12):                      # let the ease-toward-target settle
            lights._chain_tick(dev, ev, pos, (255, 90, 0), 50, False, 1000.0)
    return {d["name"]: [int(c[0]) for c in sent[d["ip"]]] for d in cfg["lights"]["devices"]}

print("\nred channel per bulb (idle red is ~128, a lit bulb is ~255)")
print(f"{'sound at':<34}{'west string 1-2-3-4':<26}east string 5-6-7-8")
for i, p in enumerate(cfg["placements"]):
    r = play_at(p["id"])
    print(f"{p['name']+' (x='+str(p['x'])+'%)':<34}{str(r['Old string (west)']):<26}{r['New string (east)']}")

# --- each string answers only the half of the yard it covers ---
IDLE = 170   # idle plus ripple; a bulb lit by a scare is well above this
r_west = play_at(cfg["placements"][0]["id"])      # x=10, inside the west string's 0-50%
r_east = play_at(cfg["placements"][6]["id"])      # x=88, inside the east string's 50-100%
assert max(r_west["New string (east)"]) < IDLE, r_west     # east string stays at idle
assert max(r_east["Old string (west)"]) < IDLE, r_east     # west string stays at idle
# x=10 is 20% along a string covering 0-50%, so the hot spot sits between bulbs 1 and 2
assert np.argmax(r_west["Old string (west)"]) in (0, 1), r_west
# x=88 is 76% along a string covering 50-100%, so between bulbs 7 and 8
assert np.argmax(r_east["New string (east)"]) in (2, 3), r_east
print("\nOK: each string answers only the half of the yard it covers")

# --- a scare at the far west end sits on bulb 1 ---
cfg["placements"][0]["x"] = 0.0
r = play_at(cfg["placements"][0]["id"])
assert np.argmax(r["Old string (west)"]) == 0, r
cfg["placements"][0]["x"] = 10.0
print("OK: a scare at the west fence peaks on bulb 1")

# --- reverse flips one string ---
east["reverse"] = True
r = play_at(cfg["placements"][6]["id"])
assert np.argmax(r["New string (east)"]) in (0, 1), r
print("OK: 'first bulb is on the east end' flips that string")
east["reverse"] = False

# --- a chain left at the default span still covers the whole yard ---
cfg["lights"]["devices"] = [{"ip": "10.0.0.11", "name": "One string", "chain": True, "segments": 8}]
engine.sanitize(cfg)
one = cfg["lights"]["devices"][0]
print("default span:", one["span_start"], one["span_end"])
r = play_at(cfg["placements"][0]["id"])
lit = [int(c[0]) for c in sent["10.0.0.11"]]
print("one string, scare at the west speaker:", lit)
assert np.argmax(lit) in (0, 1)      # x=10 is 10% along a string that runs fence to fence
r = play_at(cfg["placements"][6]["id"])
lit = [int(c[0]) for c in sent["10.0.0.11"]]
print("one string, scare at the east speaker:", lit)
assert np.argmax(lit) in (6, 7)
print("OK: a single chain still spans the whole yard")
