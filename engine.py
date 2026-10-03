"""Audio engine for Spooky Halloween Sounds.

One always-running mixer streams 8-channel (7.1) audio to the Pi's HDMI port.
Spooky sounds and internet radio are mixed into it, so the Denon stays locked
on MULTI CH IN and never clips the start of a scare.
"""
import collections
import copy
import datetime
import json
import random
import shutil
import subprocess
import threading
import time
import urllib.parse
import urllib.request
import wave
from pathlib import Path

import numpy as np

import denon

ROOT = Path(__file__).resolve().parent
SOUNDS_DIR = ROOT / "sounds"
CONFIG_PATH = ROOT / "config.json"
RATE = 48000
CHANNELS = 8
BLOCK = 1024
EXTS = {".wav", ".mp3", ".ogg", ".flac", ".m4a"}

# Denon AVR-1912 speaker terminals and the HDMI channel each one usually gets
# (ALSA 7.1 order). Use the Beep button on the dashboard to confirm.
TERMINALS = [
    ("Front L", 0), ("Front R", 1), ("Center", 4), ("Surround L", 6),
    ("Surround R", 7), ("Surr. Back L", 2), ("Surr. Back R", 3),
]
YARD_NAMES = ["Bushes", "Big Tree", "Porch", "Mailbox", "Driveway", "Side Gate", "Garage"]

DEFAULT_CONFIG = {
    "audio_device": "hdmi:CARD=vc4hdmi0,DEV=0",
    "master_volume": 0.5,
    "mode": "motion",                 # off | motion | auto | both
    "auto_min": 45, "auto_max": 180,  # seconds between automatic scares
    "cooldown_min": 10, "cooldown_max": 25,  # silence after a motion scare
    "answer_chance": 0.45,
    "creep_chance": 0.15,
    "active_hours_enabled": True,
    "active_start": "17:00",
    "active_end": "23:00",
    "pir_pin": 17,
    "placements": [
        {"id": f"p{i + 1}", "name": name, "terminal": term, "channel": ch,
         "enabled": i < 2, "volume": 1.0, "muted_sounds": []}
        for i, (name, (term, ch)) in enumerate(zip(YARD_NAMES, TERMINALS))
    ],
    "radio": {"volume": 0.5, "placements": ["p1", "p2"], "override": True, "autoplay": False,
              "last_url": "", "last_name": ""},
    "denon": {"host": denon.DEFAULT_HOST, "auto_power": False, "input": "DVD", "mode": "DIRECT",
              "volume_db": -35.0, "max_db": -15.0},
}


# ---- Config ----------------------------------------------------------------

def _num(v, lo, hi, default):
    try:
        return min(hi, max(lo, float(v)))
    except (TypeError, ValueError):
        return default


def sanitize(cfg):
    d = DEFAULT_CONFIG
    cfg["master_volume"] = _num(cfg.get("master_volume"), 0, 1, d["master_volume"])
    if cfg.get("mode") not in ("off", "motion", "auto", "both"):
        cfg["mode"] = d["mode"]
    for lo, hi in (("auto_min", "auto_max"), ("cooldown_min", "cooldown_max")):
        a, b = _num(cfg.get(lo), 1, 86400, d[lo]), _num(cfg.get(hi), 1, 86400, d[hi])
        cfg[lo], cfg[hi] = min(a, b), max(a, b)
    for k in ("answer_chance", "creep_chance"):
        cfg[k] = _num(cfg.get(k), 0, 1, d[k])
    cfg["active_hours_enabled"] = bool(cfg.get("active_hours_enabled"))
    by_id = {p.get("id"): p for p in cfg.get("placements", [])}
    placements = []
    for default in d["placements"]:
        p = {**default, **by_id.get(default["id"], {})}
        p["channel"] = int(_num(p["channel"], 0, CHANNELS - 1, default["channel"]))
        p["volume"] = _num(p["volume"], 0, 1, 1.0)
        p["enabled"] = bool(p["enabled"])
        p["name"] = str(p["name"])[:30] or default["name"]
        p["muted_sounds"] = list(p.get("muted_sounds") or [])
        placements.append(p)
    cfg["placements"] = placements
    cfg["radio"] = {**d["radio"], **cfg.get("radio", {})}
    cfg["radio"]["volume"] = _num(cfg["radio"]["volume"], 0, 1, 0.5)
    cfg["denon"] = {**d["denon"], **cfg.get("denon", {})}
    dn = cfg["denon"]
    dn["max_db"] = _num(dn["max_db"], -80, 18, d["denon"]["max_db"])
    dn["volume_db"] = _num(dn["volume_db"], -80, dn["max_db"], d["denon"]["volume_db"])
    dn["auto_power"] = bool(dn["auto_power"])
    dn["host"] = str(dn["host"]).strip() or denon.DEFAULT_HOST
    return cfg


def load_config():
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        try:
            saved = json.loads(CONFIG_PATH.read_text())
            cfg.update({k: v for k, v in saved.items() if k in cfg})
        except (OSError, ValueError):
            pass
    return sanitize(cfg)


def save_config(cfg):
    tmp = CONFIG_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, indent=2))
    tmp.replace(CONFIG_PATH)


# ---- Decoding ----------------------------------------------------------------

def read_wav(path):
    with wave.open(str(path)) as w:
        if w.getsampwidth() != 2:
            raise ValueError("only 16-bit WAV supported without ffmpeg")
        rate, nch = w.getframerate(), w.getnchannels()
        data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32)
    mono = data.reshape(-1, nch).mean(axis=1)
    if rate != RATE:
        n = int(len(mono) * RATE / rate)
        mono = np.interp(np.linspace(0, len(mono) - 1, n), np.arange(len(mono)), mono)
    return mono.astype(np.float32)


def decode(path):
    """Any audio file -> mono float32 samples at RATE."""
    if shutil.which("ffmpeg"):
        out = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(path), "-f", "s16le", "-ac", "1", "-ar", str(RATE), "-"],
            capture_output=True, check=True).stdout
        return np.frombuffer(out, dtype=np.int16).astype(np.float32)
    if path.suffix.lower() == ".wav":
        return read_wav(path)
    raise ValueError("install ffmpeg to play non-WAV files")


def render(mono, gains):
    """Place a mono sound into the 8-channel stream. gains: {channel: scalar or per-sample array}."""
    buf = np.zeros((len(mono), CHANNELS), dtype=np.float32)
    for ch, g in gains.items():
        buf[:, ch] += mono * g
    return buf


def creep_gains(n_samples, spots):
    """Equal-power crossfade along a list of placements, e.g. Bushes -> Big Tree -> Porch."""
    pos = np.linspace(0, len(spots) - 1, n_samples)
    gains = {}
    for i, p in enumerate(spots):
        d = np.abs(pos - i)
        g = np.where(d < 1, np.cos(d * np.pi / 2), 0.0) * p["volume"]
        gains[p["channel"]] = gains.get(p["channel"], 0) + g
    return gains


def beep_sound():
    t = np.arange(int(0.15 * RATE)) / RATE
    one = np.concatenate([np.sin(2 * np.pi * 660 * t) * 16000, np.zeros(int(0.15 * RATE))])
    return np.tile(one, 3).astype(np.float32)


# ---- Output & radio ------------------------------------------------------------

class Output:
    """Streams raw 8-channel PCM into aplay. With no aplay (e.g. testing on a laptop) it just keeps time."""

    def __init__(self, device):
        self.device = device
        self.proc = None
        self.error = None
        self.retry_at = 0

    def set_device(self, device):
        if device != self.device:
            self.device = device
            self.close()

    def close(self):
        if self.proc:
            self.proc.kill()
            self.proc = None

    def write(self, data):
        if not shutil.which("aplay"):
            now = time.monotonic()
            self.clock = max(getattr(self, "clock", now), now - 0.1) + BLOCK / RATE
            time.sleep(max(0, self.clock - now))
            return
        if self.proc is None or self.proc.poll() is not None:
            if self.proc is not None:
                self.error = f"Audio device '{self.device}' stopped. Is the HDMI cable in and the Denon on?"
                self.proc = None
                self.retry_at = time.time() + 3
            if time.time() < self.retry_at:
                time.sleep(BLOCK / RATE)
                return
            self.proc = subprocess.Popen(
                ["aplay", "-q", "-D", self.device, "-t", "raw", "-f", "S16_LE",
                 "-c", str(CHANNELS), "-r", str(RATE), "--buffer-time=250000"],
                stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
            self.opened_at = time.time()
        try:
            self.proc.stdin.write(data)
            if time.time() - self.opened_at > 2:
                self.error = None
        except (BrokenPipeError, OSError):
            self.proc.kill()


class Radio:
    """Decodes an internet radio stream with ffmpeg into a small stereo buffer the mixer pulls from."""

    def __init__(self):
        self.lock = threading.Lock()
        self.proc = None
        self.chunks = collections.deque()
        self.frames = 0
        self.gen = 0
        self.name = None
        self.url = None
        self.error = None
        self.started = 0

    @property
    def playing(self):
        return self.proc is not None

    def start(self, url, name):
        self.stop()
        if not shutil.which("ffmpeg"):
            self.error = "ffmpeg is not installed"
            return
        proc = subprocess.Popen(
            ["ffmpeg", "-v", "error", "-reconnect", "1", "-reconnect_streamed", "1",
             "-reconnect_delay_max", "5", "-i", url, "-vn",
             "-f", "s16le", "-ac", "2", "-ar", str(RATE), "-"],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        with self.lock:
            self.gen += 1
            self.proc, self.name, self.url, self.error = proc, name, url, None
            self.started = time.time()
            gen = self.gen
        threading.Thread(target=self._reader, args=(proc, gen), daemon=True).start()

    def _reader(self, proc, gen):
        leftover = b""
        while gen == self.gen:
            if self.frames > RATE * 3:  # keep ~3 s buffered, no more
                time.sleep(0.05)
                continue
            data = proc.stdout.read(16384)
            if not data:
                break
            data = leftover + data
            cut = len(data) // 4 * 4
            leftover = data[cut:]
            arr = np.frombuffer(data[:cut], dtype=np.int16).reshape(-1, 2).astype(np.float32)
            with self.lock:
                if gen != self.gen:
                    break
                self.chunks.append(arr)
                self.frames += len(arr)
        with self.lock:
            if gen == self.gen and self.proc is proc:
                self.error = "The station stopped streaming (or the link doesn't work). Try another one."
                self.proc = None
                self.chunks.clear()
                self.frames = 0

    def read(self, n):
        with self.lock:
            if self.proc is None:
                return None
            out = np.zeros((n, 2), dtype=np.float32)
            filled = 0
            while filled < n and self.chunks:
                c = self.chunks[0]
                take = min(n - filled, len(c))
                out[filled:filled + take] = c[:take]
                if take == len(c):
                    self.chunks.popleft()
                else:
                    self.chunks[0] = c[take:]
                filled += take
            self.frames -= filled
            return out

    def stop(self):
        with self.lock:
            proc, self.proc = self.proc, None
            self.gen += 1
            self.chunks.clear()
            self.frames = 0
            self.name = self.url = None
        if proc:
            proc.kill()

    def status(self):
        return {"playing": self.playing, "name": self.name, "url": self.url, "error": self.error,
                "buffering": self.playing and self.frames == 0 and time.time() - self.started < 15}


def search_stations(term):
    """Search the free, open radio-browser.info directory by tag, then by name."""
    params = {"hidebroken": "true", "order": "clickcount", "reverse": "true", "limit": "30"}
    results, last_error = [], None
    for host in ("de1", "nl1", "at1", "fi1"):
        try:
            for field in ("tag", "name"):
                q = urllib.parse.urlencode({**params, field: term})
                req = urllib.request.Request(
                    f"https://{host}.api.radio-browser.info/json/stations/search?{q}",
                    headers={"User-Agent": "SpookyHalloweenSounds/1.0"})
                with urllib.request.urlopen(req, timeout=8) as r:
                    results += json.load(r)
                if len(results) >= 10:
                    break
            break
        except Exception as e:  # try the next mirror
            last_error = e
    if not results and last_error:
        raise RuntimeError(f"Radio directory unreachable: {last_error}")
    seen, out = set(), []
    for s in results:
        url = s.get("url_resolved") or s.get("url")
        if url and url not in seen:
            seen.add(url)
            out.append({"name": s.get("name", "").strip() or url, "url": url,
                        "tags": s.get("tags", "")[:80], "country": s.get("countrycode", ""),
                        "codec": s.get("codec", ""), "bitrate": s.get("bitrate", 0)})
    return out[:30]


# ---- Engine ----------------------------------------------------------------------

class Engine:
    def __init__(self):
        self.lock = threading.RLock()
        self.config = load_config()
        self.log = collections.deque(maxlen=60)
        self.sounds = {}       # filename -> mono samples
        self._mtimes = {}
        self.refresh_sounds()
        self.voices = []
        self.radio = Radio()
        self.out = Output(self.config["audio_device"])
        self.scaring = threading.Lock()
        self.stop_gen = 0
        self.last_spot = None
        self.cooldown_until = 0
        self.next_auto = time.time() + 10
        self.last_motion = None
        self.now_playing = None
        self.sensor_status = "starting"
        threading.Thread(target=self._mix_loop, daemon=True).start()
        threading.Thread(target=self._schedule_loop, daemon=True).start()
        self.denon = denon.Denon()
        threading.Thread(target=self._denon_loop, daemon=True).start()
        self._start_sensor()
        self.add_log("Spooky engine started")
        if self.config["radio"].get("autoplay") and self.config["radio"].get("last_url"):
            self.play_radio(self.config["radio"]["last_url"], self.config["radio"]["last_name"])

    # -- helpers
    def add_log(self, text):
        self.log.appendleft({"t": datetime.datetime.now().strftime("%H:%M:%S"), "text": text})

    def refresh_sounds(self):
        SOUNDS_DIR.mkdir(exist_ok=True)
        found = {}
        for p in sorted(SOUNDS_DIR.iterdir()):
            if p.suffix.lower() not in EXTS:
                continue
            mtime = p.stat().st_mtime
            if p.name in self.sounds and self._mtimes.get(p.name) == mtime:
                found[p.name] = self.sounds[p.name]
                continue
            try:
                found[p.name] = decode(p)
                self._mtimes[p.name] = mtime
            except Exception as e:
                self.add_log(f"Couldn't load {p.name}: {e}")
        with self.lock:
            self.sounds = found

    def allowed(self, placement):
        return [s for s in self.sounds if s not in placement["muted_sounds"]]

    def placement(self, pid):
        return next((p for p in self.config["placements"] if p["id"] == pid), None)

    def active_hours(self, cfg=None):
        cfg = cfg or self.config
        if not cfg["active_hours_enabled"]:
            return True
        now = datetime.datetime.now().strftime("%H:%M")
        s, e = cfg["active_start"], cfg["active_end"]
        return s <= now < e if s <= e else (now >= s or now < e)

    def blocked_reason(self):
        cfg = self.config
        if self.scaring.locked():
            return "playing"
        if self.radio.playing and cfg["radio"]["override"]:
            return "radio is on"
        if not self.active_hours(cfg):
            return f"outside active hours ({cfg['active_start']}–{cfg['active_end']})"
        if not any(p["enabled"] and self.allowed(p) for p in cfg["placements"]):
            return "no speakers turned on"
        return None

    # -- mixer
    def _mix_loop(self):
        while True:
            out = np.zeros((BLOCK, CHANNELS), dtype=np.float32)
            with self.lock:
                for v in self.voices:
                    chunk = v["buf"][v["pos"]:v["pos"] + BLOCK]
                    out[:len(chunk)] += chunk
                    v["pos"] += BLOCK
                for v in self.voices:
                    if v["pos"] >= len(v["buf"]):
                        v["done"].set()
                self.voices = [v for v in self.voices if v["pos"] < len(v["buf"])]
                cfg = self.config
            stereo = self.radio.read(BLOCK)
            if stereo is not None:
                spots = [p for p in cfg["placements"] if p["id"] in cfg["radio"]["placements"]]
                vol = cfg["radio"]["volume"]
                for i, p in enumerate(spots):
                    src = stereo.mean(axis=1) if len(spots) == 1 else stereo[:, i % 2]
                    out[:, p["channel"]] += src * vol * p["volume"]
            out *= cfg["master_volume"]
            self.out.write(np.clip(out, -32768, 32767).astype(np.int16).tobytes())

    def _add_voice(self, buf):
        v = {"buf": buf, "pos": 0, "done": threading.Event()}
        with self.lock:
            self.voices.append(v)
        return v

    def stop_sounds(self):
        with self.lock:
            self.stop_gen += 1
            for v in self.voices:
                v["done"].set()
            self.voices = []
            self.now_playing = None

    def _play(self, sound, spots, creep=False):
        mono = self.sounds[sound]
        if creep:
            gains = creep_gains(len(mono), spots)
        else:
            gains = {}
            for p in spots:
                gains[p["channel"]] = gains.get(p["channel"], 0) + p["volume"]
        v = self._add_voice(render(mono, gains))
        self.now_playing = {"sound": sound, "spots": [p["id"] for p in spots], "voice": v}
        names = " → ".join(p["name"] for p in spots) if creep else spots[0]["name"]
        self.add_log(f"{Path(sound).stem} {'creeping ' if creep else 'from the '}{names}")
        return v

    # -- scares
    def trigger(self, reason):
        if not self.scaring.acquire(blocking=False):
            return False
        threading.Thread(target=self._scare_thread, args=(reason,), daemon=True).start()
        return True

    def _scare_thread(self, reason):
        try:
            self._scare(reason)
        except Exception as e:
            self.add_log(f"Error during scare: {e}")
        finally:
            cfg = self.config
            self.now_playing = None
            self.cooldown_until = time.time() + random.uniform(cfg["cooldown_min"], cfg["cooldown_max"])
            self.next_auto = time.time() + random.uniform(cfg["auto_min"], cfg["auto_max"])
            self.scaring.release()

    def _scare(self, reason):
        cfg = copy.deepcopy(self.config)
        gen = self.stop_gen
        spots = [p for p in cfg["placements"] if p["enabled"] and self.allowed(p)]
        if not spots:
            self.add_log("Nothing to play: turn on a speaker and give it some sounds")
            return
        self.add_log(f"Scare! ({reason})")

        def wait(v):
            v["done"].wait()
            return gen == self.stop_gen

        if len(spots) > 1 and random.random() < cfg["creep_chance"]:
            i = random.randrange(len(spots))
            step = 1 if i == 0 else -1 if i == len(spots) - 1 else random.choice([-1, 1])
            path = [spots[j] for j in (i + step * k for k in range(random.randint(2, 3))) if 0 <= j < len(spots)]
            wait(self._play(random.choice(self.allowed(path[0])), path, creep=True))
            self.last_spot = path[-1]["id"]
            return

        spot = random.choice([p for p in spots if p["id"] != self.last_spot] or spots)
        sound = random.choice(self.allowed(spot))
        if not wait(self._play(sound, [spot])):
            return
        self.last_spot = spot["id"]

        if len(spots) > 1 and random.random() < cfg["answer_chance"]:
            time.sleep(random.uniform(0.8, 3.0))
            if gen != self.stop_gen:
                return
            other = random.choice([p for p in spots if p["id"] != spot["id"]])
            opts = [s for s in self.allowed(other) if s != sound] or self.allowed(other)
            wait(self._play(random.choice(opts), [other]))
            self.last_spot = other["id"]

    def play_now(self, sound=None, placement_id=None):
        """Dashboard soundboard: stop whatever is playing and play right away."""
        self.stop_sounds()
        cfg = self.config
        if placement_id:
            spot = self.placement(placement_id)
        else:
            choices = [p for p in cfg["placements"] if p["enabled"] and (sound in self.allowed(p) if sound else self.allowed(p))]
            spot = random.choice(choices) if choices else None
        if spot is None:
            return "No speaker available for that sound"
        pool = [sound] if sound else self.allowed(spot) or list(self.sounds)
        if not pool or pool[0] not in self.sounds:
            return "No sounds loaded"
        self._play(random.choice(pool), [spot])
        return None

    def beep(self, channel):
        self.stop_sounds()
        self._add_voice(render(beep_sound() / max(self.config["master_volume"], 0.05) * 0.5, {int(channel): 1.0}))
        self.add_log(f"Beep on HDMI channel {channel}")

    # -- scheduling & motion
    def _schedule_loop(self):
        while True:
            time.sleep(0.5)
            if self.config["mode"] in ("auto", "both") and time.time() >= self.next_auto \
                    and self.blocked_reason() is None:
                self.trigger("timer")

    def _start_sensor(self):
        pin = self.config["pir_pin"]
        try:
            from gpiozero import MotionSensor
            self.pir = MotionSensor(pin)
            self.pir.when_motion = self.on_motion
            self.sensor_status = f"ready on GPIO{pin}"
        except Exception as e:
            self.sensor_status = f"not available ({type(e).__name__})"

    def on_motion(self, simulated=False):
        self.last_motion = time.time()
        if self.config["mode"] not in ("motion", "both"):
            self.add_log("Motion detected (motion mode is off)")
            return
        reason = self.blocked_reason()
        if reason is None and time.time() < self.cooldown_until:
            reason = "cooling down"
        if reason:
            self.add_log(f"Motion detected, but {reason}")
            return
        self.trigger("simulated motion" if simulated else "motion")

    # -- Denon receiver
    def _denon_loop(self):
        """Check the receiver now and then, find it if needed, and power it on/off with active hours."""
        was_active = None
        last_search = 0
        while True:
            dn = self.config["denon"]
            if not dn["host"] and time.time() - last_search > 60:
                last_search = time.time()
                host = denon.find_denon()
                if host:
                    self.update_config({"denon": {"host": host}})
                    self.add_log(f"Found the Denon at {host}")
            if self.config["denon"]["host"]:
                self.denon.refresh(self.config["denon"]["host"])
            active = self.active_hours()
            if dn["auto_power"] and self.config["active_hours_enabled"] and was_active is not None \
                    and active != was_active:
                self.denon_action("ready" if active else "standby", auto=True)
            was_active = active
            time.sleep(15)

    def denon_action(self, action, value=None, auto=False):
        """Run a dashboard command on the receiver. Returns an error message or None."""
        dn = self.config["denon"]
        host = dn["host"]
        st = self.denon.status
        try:
            if action == "find":
                host = denon.find_denon()
                if not host:
                    return "No Denon found on the Ethernet cable. Is it plugged in and turned on at the wall?"
                self.update_config({"denon": {"host": host}})
                self.add_log(f"Found the Denon at {host}")
            elif action == "ready":
                self.denon.get_ready(host, dn["input"], dn["mode"], dn["volume_db"], dn["max_db"])
                self.add_log(f"Denon: {'auto ' if auto else ''}on, input {dn['input']}, {dn['volume_db']:g} dB")
            elif action == "on":
                self.denon.send(host, ["PWON", "ZMON"])
            elif action == "standby":
                self.denon.send(host, ["PWSTANDBY"])
                self.add_log(f"Denon: {'auto ' if auto else ''}standby")
            elif action == "mute":
                self.denon.send(host, ["MUOFF" if st.get("muted") else "MUON"])
            elif action == "volume":
                db = min(float(value), dn["max_db"])
                self.denon.send(host, [denon.db_to_mv(db)])
            elif action == "nudge":
                cur = st.get("volume_db", dn["volume_db"])
                self.denon.send(host, [denon.db_to_mv(min(cur + float(value), dn["max_db"]))])
            elif action == "input":
                self.denon.send(host, [f"SI{value}"])
            elif action == "mode":
                self.denon.send(host, [f"MS{value}"])
            else:
                return f"Unknown command {action}"
        except Exception as e:
            return f"Denon didn't respond: {e}"
        finally:
            if self.config["denon"]["host"]:
                self.denon.refresh(self.config["denon"]["host"])
        return None

    # -- radio
    def play_radio(self, url, name):
        self.radio.start(url, name)
        self.update_config({"radio": {"last_url": url, "last_name": name}})
        if self.config["radio"]["override"]:
            self.stop_sounds()
        self.add_log(f"Radio: {name}")

    def stop_radio(self):
        if self.radio.playing:
            self.add_log("Radio off")
        self.radio.stop()

    # -- config & state
    def update_config(self, patch):
        with self.lock:
            cfg = copy.deepcopy(self.config)
            for k, v in patch.items():
                if k in ("radio", "denon") and isinstance(v, dict):
                    cfg[k].update(v)
                elif k in DEFAULT_CONFIG:
                    cfg[k] = v
            cfg = sanitize(cfg)
            timing_changed = any(cfg[k] != self.config[k] for k in ("mode", "auto_min", "auto_max"))
            self.config = cfg
            save_config(cfg)
        self.out.set_device(cfg["audio_device"])
        if timing_changed:
            self.next_auto = time.time() + random.uniform(min(10, cfg["auto_min"]), cfg["auto_min"])
        return cfg

    def state(self):
        cfg = self.config
        now = time.time()
        cur = self.now_playing
        np_ = {"sound": cur["sound"], "spots": cur["spots"]} if cur and not cur["voice"]["done"].is_set() else None
        return {
            "config": cfg,
            "sounds": [{"name": n, "label": Path(n).stem, "seconds": round(len(m) / RATE, 1)}
                       for n, m in self.sounds.items()],
            "status": {
                "now_playing": np_,
                "blocked": self.blocked_reason(),
                "active_hours": self.active_hours(cfg),
                "next_auto_in": max(0, round(self.next_auto - now)) if cfg["mode"] in ("auto", "both") else None,
                "cooldown_in": max(0, round(self.cooldown_until - now)),
                "last_motion_ago": round(now - self.last_motion) if self.last_motion else None,
                "sensor": self.sensor_status,
                "audio_error": self.out.error,
                "radio": self.radio.status(),
                "denon": self.denon.status,
                "time": datetime.datetime.now().strftime("%-I:%M %p"),
            },
            "log": list(self.log)[:30],
        }
