#!/usr/bin/env python3
"""Spooky Halloween Sounds: web dashboard + audio engine.

Open http://spooky.local (or the Pi's IP address) from any phone or laptop on your Wi-Fi.
Set SPOOKY_PORT to use a port other than 80.
"""
import os

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
    return ok()


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
    for f in request.files.getlist("files"):
        name = secure_filename(f.filename or "")
        if name and os.path.splitext(name)[1].lower() in engine.EXTS:
            f.save(engine.SOUNDS_DIR / name)
            saved.append(name)
    eng.refresh_sounds()
    eng.add_log(f"Added {', '.join(saved)}" if saved else "Upload had no audio files")
    return ok(saved=saved)


@app.delete("/api/sounds/<name>")
def delete_sound(name):
    path = engine.SOUNDS_DIR / secure_filename(name)
    if path.exists() and path.suffix.lower() in engine.EXTS:
        path.unlink()
        eng.refresh_sounds()
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


@app.post("/api/radio/stop")
def radio_stop():
    eng.stop_radio()
    return ok()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("SPOOKY_PORT", 80)), threaded=True)
