#!/usr/bin/env python3
"""Spooky Halloween Sounds: web dashboard + audio engine.

Open http://spooky.local (or the Pi's IP address) from any phone or laptop on your Wi-Fi.
Set SPOOKY_PORT to use a port other than 80.
"""
import json
import os
import urllib.parse
import urllib.request

from flask import Flask, jsonify, request, send_from_directory
from werkzeug.utils import secure_filename

import engine

eng = engine.Engine()
app = Flask(__name__, static_folder="static")
app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024


def ok(**extra):
    return jsonify({"ok": True, **extra})


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/remote")
def remote():
    return send_from_directory(app.static_folder, "remote.html")


@app.get("/manifest.webmanifest")
def manifest():
    return send_from_directory(app.static_folder, "manifest.webmanifest", mimetype="application/manifest+json")


@app.get("/sw.js")
def service_worker():
    resp = send_from_directory(app.static_folder, "sw.js", mimetype="text/javascript")
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@app.get("/sounds/<path:name>")
def sound_file(name):
    """The raw audio file, so the dashboard can preview it on your own computer or phone."""
    return send_from_directory(engine.SOUNDS_DIR, name, conditional=True)


@app.get("/api/state")
def state():
    s = eng.state()
    s["terminals"] = engine.TERMINALS
    s["denon_inputs"] = engine.denon.INPUTS
    s["denon_modes"] = engine.denon.SOUND_MODES
    return jsonify(s)


@app.post("/api/config")
def config():
    return jsonify(eng.update_config(request.get_json(force=True) or {}))


@app.post("/api/scare")
def scare():
    started = eng.trigger("dashboard")
    return ok(started=started)


@app.post("/api/play")
def play():
    body = request.get_json(force=True) or {}
    err = eng.play_now(body.get("sound"), body.get("placement"))
    return jsonify({"ok": err is None, "error": err})


@app.post("/api/stop")
def stop():
    eng.stop_sounds()
    if (request.get_json(silent=True) or {}).get("radio"):
        eng.stop_radio()
        eng.update_config({"ambience": {"on": False}})
    return ok()


@app.post("/api/sweep")
def sweep():
    body = request.get_json(force=True) or {}
    err = eng.sweep(body.get("direction", "ltr"), body.get("sound"), body.get("seconds"))
    return jsonify({"ok": err is None, "error": err})


@app.post("/api/beep")
def beep():
    eng.beep(int((request.get_json(force=True) or {}).get("channel", 0)))
    return ok()


@app.post("/api/motion")
def motion():
    eng.on_motion(simulated=True)
    return ok()


@app.post("/api/sounds")
def upload():
    saved = []
    folder = engine.AMBIENCE_DIR if request.args.get("kind") == "ambience" else engine.SOUNDS_DIR
    folder.mkdir(parents=True, exist_ok=True)
    for f in request.files.getlist("files"):
        name = secure_filename(f.filename or "")
        if name and os.path.splitext(name)[1].lower() in engine.EXTS:
            engine.write_safely(folder / name, f.read())
            saved.append(name)
    eng.refresh_sounds()
    eng.add_log(f"Added {', '.join(saved)}" if saved else "Upload had no audio files")
    return ok(saved=saved)


@app.delete("/api/sounds/<name>")
def delete_sound(name):
    folder = engine.AMBIENCE_DIR if request.args.get("kind") == "ambience" else engine.SOUNDS_DIR
    path = folder / secure_filename(name)
    if path.exists() and path.suffix.lower() in engine.EXTS:
        path.unlink()
        eng.refresh_sounds()
        if eng.config["ambience"]["track"] == name:
            eng.update_config({"ambience": {"on": False}})
        eng.add_log(f"Removed {name}")
    return ok()


@app.get("/api/radio/search")
def radio_search():
    try:
        return jsonify({"ok": True, "stations": engine.search_stations(request.args.get("q", "halloween"))})
    except RuntimeError as e:
        return jsonify({"ok": False, "error": str(e), "stations": []})


@app.post("/api/radio/play")
def radio_play():
    body = request.get_json(force=True) or {}
    url = (body.get("url") or "").strip()
    if not url.startswith(("http://", "https://")):
        return jsonify({"ok": False, "error": "That doesn't look like a stream link (http://…)"})
    eng.play_radio(url, body.get("name") or url)
    return ok()


@app.post("/api/denon")
def denon_cmd():
    body = request.get_json(force=True) or {}
    err = eng.denon_action(body.get("action", ""), body.get("value"))
    return jsonify({"ok": err is None, "error": err, "denon": eng.denon.status})


@app.post("/api/lights/find")
def lights_find():
    try:
        found = eng.find_lights()
    except OSError as e:
        return jsonify({"ok": False, "error": f"Couldn't search the network: {e}"})
    return jsonify({"ok": True, "found": len(found), "lights": eng.config["lights"]})


@app.get("/api/geocode")
def geocode():
    """Look up a town so the lights know when sunset is (free Open-Meteo place search, no key)."""
    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify({"ok": False, "error": "Type a town or ZIP code"})
    try:
        url = "https://geocoding-api.open-meteo.com/v1/search?" + urllib.parse.urlencode(
            {"name": q, "count": 5, "language": "en", "format": "json"})
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "SpookyHalloweenSounds/1.0"}), timeout=8) as r:
            data = json.load(r)
    except Exception as e:
        return jsonify({"ok": False, "error": f"Couldn't look that up: {e}"})
    places = [{"name": ", ".join(x for x in (p.get("name"), p.get("admin1"), p.get("country_code")) if x),
               "lat": p["latitude"], "lon": p["longitude"]} for p in data.get("results", [])]
    return jsonify({"ok": True, "places": places})


@app.post("/api/ring/test")
def ring_test():
    kind = (request.get_json(force=True) or {}).get("kind", "motion")
    eng.on_ring("ding" if kind == "ding" else "motion", "the dashboard", test=True)
    return ok()


@app.post("/api/lights/test")
def lights_test():
    eng.lights.test((request.get_json(force=True) or {}).get("ip", ""))
    return ok()


@app.post("/api/radio/stop")
def radio_stop():
    eng.stop_radio()
    return ok()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("SPOOKY_PORT", 80)), threaded=True)
