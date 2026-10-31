"""Timed atmosphere tracks: on the clock, once all the way through, then back to the loop."""
import collections, copy, datetime, pathlib, sys, tempfile, threading, time, types
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import numpy as np, engine

R = engine.RATE
tmp = pathlib.Path(tempfile.mkdtemp())
(tmp / "loop.wav").touch()
(tmp / "theme.wav").touch()
engine.AMBIENCE_DIR = tmp
RAW = {"loop.wav": np.full((20 * R, 2), 0.1, np.float32), "theme.wav": np.ones((6 * R, 2), np.float32)}
engine.decode_stereo = lambda path: RAW[path.name].copy()

clock = [1000.0]
engine.time = types.SimpleNamespace(time=lambda: clock[0], sleep=time.sleep)

cfg = copy.deepcopy(engine.DEFAULT_CONFIG)
cfg["ambience"].update(on=True, track="loop.wav", active_hours_only=False,
                       schedule=[{"track": "theme.wav", "every": 60, "volume": 0.6}])
cfg = engine.sanitize(cfg)
E = engine.Engine.__new__(engine.Engine)
E.config, E.log = cfg, collections.deque(maxlen=50)
E.ambience, E.radio = engine.Ambience(), types.SimpleNamespace(playing=False)
E.feature = E.feature_vol = None
E.fired = {}
a = E.ambience
print(f"schedule after sanitize: {cfg['ambience']['schedule']}")

def run(seconds):
    """Advance the fake clock, pulling audio the way the mixer does. Returns (track, position) heard."""
    heard = []
    for _ in range(int(seconds * R / engine.BLOCK)):
        a.want = E.ambience_wanted()
        while a.loading:
            time.sleep(0.001)
        if a.read(engine.BLOCK, 1) is not None:
            heard.append((a.track, (a.pos - engine.BLOCK) % len(a.buf)))
        clock[0] += engine.BLOCK / R
    return heard

run(8)
assert a.track == "loop.wav" and a.gain == 1.0
print("regular loop playing")

# --- fires on the hour, once per slot ---
E._check_schedule(datetime.datetime(2026, 10, 31, 18, 59, 40))
assert E.feature is None
E._check_schedule(datetime.datetime(2026, 10, 31, 19, 0, 1))
assert E.feature and E.feature["track"] == "theme.wav"
E._check_schedule(datetime.datetime(2026, 10, 31, 19, 0, 30))
assert sum("timed" in l["text"] for l in E.log) == 1
print("6:59:40 nothing, 7:00:01 fires, 7:00:30 doesn't fire again")

# --- plays from the top, unblended, and hands back before it repeats ---
heard = run(14)
starts = [p for t, p in heard if t == "theme.wav"]
assert starts[0] == 0, f"started {starts[0] / R:.2f}s in, not at the top"
assert all(b > x for x, b in zip(starts, starts[1:])), "theme wrapped round to its start"
played = (starts[-1] + engine.BLOCK) / R
assert 6 - engine.AMBIENCE_FADE - 1 < played <= 6, f"played to {played:.2f}s of a 6s track"
assert a.track == "loop.wav" and E.feature is None
print(f"theme: from 0.00s to {played:.2f}s of 6.00s, no repeat, then back to the loop")

# --- its own volume holds through its fade-out, then lets go ---
E._check_schedule(datetime.datetime(2026, 10, 31, 19, 1))
assert E.feature_vol is None and a.once is None
print("timed volume released once the loop is back")

# --- already the loop? it still starts from the top ---
cfg["ambience"]["track"] = "theme.wav"
run(6)
E.play_feature("theme.wav", 0.6)
heard = run(4)
starts = [p for t, p in heard if t == "theme.wav"]
assert 0 in starts and starts[-1] > starts[starts.index(0)], "didn't restart from the top"
cfg["ambience"]["track"] = "loop.wav"
E.feature = None
run(8)
print("same track as the loop: reloaded and started from the top")

# --- active hours and the radio hold it back ---
cfg["ambience"]["active_hours_only"] = True
E.active_hours = lambda c=None: False
E._check_schedule(datetime.datetime(2026, 10, 31, 9, 0))
assert E.feature is None
cfg["ambience"]["active_hours_only"] = False
E.radio.playing, cfg["radio"]["override"] = True, True
E._check_schedule(datetime.datetime(2026, 10, 31, 10, 0))
assert E.feature is None
E.radio.playing = False
print("outside active hours or with the radio on: skipped")

# --- the next one due ---
assert E.next_feature(datetime.datetime(2026, 10, 31, 18, 47, 12)) == datetime.datetime(2026, 10, 31, 19, 0)
cfg["ambience"]["schedule"].append({"track": "theme.wav", "every": 15, "volume": 0.3, "on": True})
assert E.next_feature(datetime.datetime(2026, 10, 31, 18, 47)) == datetime.datetime(2026, 10, 31, 19, 0)
assert E.next_feature(datetime.datetime(2026, 10, 31, 18, 31)) == datetime.datetime(2026, 10, 31, 18, 45)
print("next due: 6:47 -> 7:00, and 6:31 -> 6:45 with a 15-minute one added")
