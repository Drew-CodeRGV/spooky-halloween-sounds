"""Jump-scare spots: silent through ordinary scares, then strike while a house sound is playing."""
import collections, copy, pathlib, sys, threading, time, types
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import numpy as np, engine

cfg = copy.deepcopy(engine.DEFAULT_CONFIG)
for p in cfg["placements"]:
    p["enabled"] = p["id"] in ("p1", "p5", "p7", "p2")
cfg["placements"][1]["ambush"] = True          # p2, "across the street"
cfg = engine.sanitize(cfg)
cfg["answer_chance"] = cfg["creep_chance"] = 0.0
HIDDEN = cfg["placements"][1]["channel"]
print(f"hidden spot on channel {HIDDEN}; house spots p1, p5, p7")

# A stand-in mixer: a voice plays for its real length, then reports done.
E = engine.Engine.__new__(engine.Engine)
E.config, E.lock, E.voices, E.log = cfg, threading.Lock(), [], collections.deque(maxlen=50)
E.stop_gen, E.last_spot, E.last_ambush, E.now_playing = 0, None, 0, None
E.show = "halloween"
E.lights = types.SimpleNamespace(show=lambda *a, **k: None)
quiet_start = np.concatenate([np.zeros(int(0.3 * engine.RATE)), np.ones(int(0.1 * engine.RATE))])
E.sounds = {"growl.wav": np.ones(int(0.4 * engine.RATE)), "roar.wav": quiet_start * 9000}
played = []   # (time started, channels it's on, voice)

def add_voice(buf):
    v = {"buf": buf, "pos": 0, "done": threading.Event()}
    played.append((time.time(), set(np.flatnonzero(np.abs(buf).sum(axis=0))), v))
    threading.Timer(len(buf) / engine.RATE, v["done"].set).start()
    return v
E._add_voice = add_voice

def jumps():
    return [x for x in played if x[1] == {HIDDEN}]

# --- the hidden spot never plays an ordinary scare ---
cfg["ambush_chance"] = 0.0
for _ in range(20):
    E._scare("test")
assert not any(HIDDEN in ch for _, ch, _ in played), "hidden spot played an ordinary scare"
assert not E._sweep("ltr", "growl.wav")[1] is None
assert HIDDEN not in played[-1][1], "sweep crossed the hidden spot"
print("20 scares and a sweep: hidden spot stayed silent")

# --- with the chance at 100%, it strikes during the house sound, and only there ---
cfg["ambush_chance"] = 1.0
played.clear()
E._scare("test")
house, jump = [x for x in played if x[1] != {HIDDEN}], jumps()
assert len(jump) == 1 and len(house) == 1, (house, jump)
lag = jump[0][0] - house[0][0]
assert 0.4 * 0.4 - 0.05 <= lag <= 0.4 * 0.75 + 0.05, f"struck {lag:.2f}s in"
assert any("Jump scare!" in l["text"] for l in E.log)
print(f"chance 100%: struck from the hidden spot {lag:.2f}s into a 0.40s house sound")

# --- the jump scare starts on the hit, not on its quiet lead-in ---
lead = len(quiet_start) - len(engine.onset(quiet_start))
assert abs(lead - int(0.29 * engine.RATE)) <= 2, lead
print(f"onset: trimmed {lead / engine.RATE:.2f}s of silence from the front")

# --- never twice inside the gap ---
played.clear()
E._scare("test")
assert not jumps(), "struck again inside the gap"
E.last_ambush -= engine.AMBUSH_GAP
E._scare("test")
assert len(jumps()) == 1
print(f"gap: none within {engine.AMBUSH_GAP}s of the last, one after")

# --- Stop cancels a jump scare that hasn't sprung yet ---
played.clear()
E.last_ambush = 0
t = threading.Thread(target=E._scare, args=("test",))
t.start()
time.sleep(0.05)
E.stop_gen += 1
for _, _, v in played:
    v["done"].set()
t.join(2)
assert not jumps(), "struck after Stop"
print("stop: pending jump scare called off")

# --- with only a hidden spot on, nothing counts as playable ---
for p in cfg["placements"]:
    p["enabled"] = p["id"] == "p2"
assert not any(engine.at_house(p) for p in cfg["placements"])
print("hidden spot alone: no house speakers, so no scares")
