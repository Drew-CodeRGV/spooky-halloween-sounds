"""Two shows, one yard: Christmas starts as a copy of Halloween, then each keeps its own settings."""
import collections, copy, json, pathlib, re, sys, tempfile, threading, types
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import engine

tmp = pathlib.Path(tempfile.mkdtemp())
for name, show in engine.SHOWS.items():
    show["config"] = tmp / show["config"].name
    show["sounds"] = tmp / show["sounds"].name
engine.SHOW_PATH = tmp / "show.json"
assert engine.live_show() == "halloween"
print("no show.json: Halloween is on")

# Halloween as it's set up in the yard
hal = copy.deepcopy(engine.DEFAULT_CONFIG)
hal["mode"] = "both"
hal["placements"][1].update(name="Across the street", enabled=True, ambush=True, muted_sounds=["growl_deep.wav"])
hal["disabled_sounds"], hal["sound_colors"] = ["heartbeat.wav"], {"wolf_howl.mp3": "#ff0000"}
hal["sweep_sounds"] = ["ghost_wail.mp3"]
hal["ambience"].update(on=True, track="graveyard.mp3",
                       schedule=[{"track": "Nightmare_On_Elm_Street_-_Main_Theme.mp3", "every": 60}])
hal["radio"].update(last_url="https://example.com/hrc", last_name="Halloween Radio", autoplay=True)
hal["ring"]["motion_sound"] = "evil_whisper.mp3"
hal["lights"]["devices"] = [{"ip": "192.168.5.40", "chain": True, "segments": 4}]
hal = engine.sanitize(hal)
engine.use_show("halloween")
engine.save_config(hal)
saved_hal = json.loads(engine.SHOWS["halloween"]["config"].read_text())

E = engine.Engine.__new__(engine.Engine)
E.lock, E.voices, E.log, E.stop_gen, E.now_playing = threading.RLock(), [], collections.deque(maxlen=50), 0, None
E.radio = types.SimpleNamespace(playing=False, stop=lambda: None)
E.out = types.SimpleNamespace(set_device=lambda d: None)
E.show, E.config, E.sounds, E._mtimes = "halloween", engine.load_config(), {}, {}

# --- first switch to Christmas: a copy of the yard, none of Halloween's sounds ---
assert E.switch_show("christmas") is None
x = E.config
assert json.loads(engine.SHOW_PATH.read_text()) == {"live": "christmas"} and engine.live_show() == "christmas"
assert engine.SOUNDS_DIR == tmp / "sounds-christmas" and engine.CONFIG_PATH.name == "config-christmas.json"
assert x["mode"] == "both" and x["placements"][1]["name"] == "Across the street" and x["placements"][1]["ambush"]
assert [p["x"] for p in x["placements"]] == [p["x"] for p in hal["placements"]]
assert x["lights"]["devices"] == hal["lights"]["devices"]
assert all(not p["muted_sounds"] for p in x["placements"])
assert not x["disabled_sounds"] and not x["sound_colors"] and not x["sweep_sounds"]
assert x["ambience"]["track"] == "crackling_fireplace.mp3" and x["ambience"]["schedule"] == []
assert x["radio"]["last_url"] == "" and not x["radio"]["autoplay"] and x["ring"]["motion_sound"] == ""
assert x["lights"]["idle_color"] == "#ff2a36"
assert json.loads(engine.SHOWS["halloween"]["config"].read_text()) == saved_hal
print("Christmas: same spots, modes and lights as Halloween; no Halloween sounds, loop or stations")
print("Halloween's settings file untouched")

# --- the show's own settings stay its own; the hardware is shared ---
E.update_config({"mode": "auto", "ambience": {"volume": 0.2}})
E.update_config({"denon": {"max_db": -20.0}, "lights": {"lat": 26.2, "lon": -98.2}})
h = json.loads(engine.SHOWS["halloween"]["config"].read_text())
assert h["mode"] == "both" and h["ambience"]["volume"] == saved_hal["ambience"]["volume"]
assert h["denon"]["max_db"] == -20.0 and (h["lights"]["lat"], h["lights"]["lon"]) == (26.2, -98.2)
print("Christmas mode and atmosphere volume stay in Christmas; receiver limit and location reach Halloween")

# --- back to Halloween: everything as it was, plus the hardware change ---
assert E.switch_show("halloween") is None
c = E.config
assert c["mode"] == "both" and c["disabled_sounds"] == ["heartbeat.wav"]
assert c["ambience"]["schedule"][0]["track"].startswith("Nightmare") and c["radio"]["last_url"]
assert c["placements"][1]["muted_sounds"] == ["growl_deep.wav"] and c["denon"]["max_db"] == -20.0
assert engine.SOUNDS_DIR == tmp / "sounds" and engine.live_show() == "halloween"
print("back to Halloween: its sounds, timed theme and station are all still there")

# --- and Christmas again: picks up where it left off, not a fresh copy ---
E.switch_show("christmas")
assert E.config["mode"] == "auto" and E.config["ambience"]["volume"] == 0.2
assert E.switch_show("easter") and E.show == "christmas"
print("Christmas again: kept its own changes; an unknown show is refused")

# --- the Christmas pages are the Halloween pages with new words: every control the script needs is there ---
static = pathlib.Path(__file__).resolve().parent.parent / "static"
ids = lambda f: set(re.findall(r'id="([^"]+)"', (static / f).read_text()))
for a, b in (("index.html", "christmas.html"), ("remote.html", "remote-christmas.html")):
    assert ids(a) == ids(b), (a, ids(a) ^ ids(b))
    assert 'data-show="christmas"' in (static / b).read_text()
print(f"christmas.html has all {len(ids('index.html'))} controls of index.html; the remotes match too")
