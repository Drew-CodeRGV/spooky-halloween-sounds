"""Audio engine for Spooky Halloween Sounds.

One always-running mixer streams 8-channel (7.1) audio to the Pi's HDMI port.
Spooky sounds and internet radio are mixed into it, so the Denon stays locked
on MULTI CH IN and never clips the start of a scare.
"""
import collections
import copy
import datetime
import json
import os
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
import govee

ROOT = Path(__file__).resolve().parent
SOUNDS_DIR = ROOT / "sounds"
AMBIENCE_DIR = SOUNDS_DIR / "ambience"
AMBIENCE_FADE = 2.5   # seconds to fade a background loop in/out
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
# Where each speaker starts on the dashboard's yard map (percent across, percent down).
# Drag them on the map; left-to-right on the map is the order sweeps and creeps travel.
MAP_SPOTS = [(9, 58), (25, 38), (50, 52), (75, 38), (91, 58), (22, 78), (78, 78)]

DEFAULT_CONFIG = {
    "audio_device": "hdmi:CARD=vc4hdmi0,DEV=0",
    "master_volume": 0.5,
    "mode": "motion",                 # off | motion | auto | both
    "auto_min": 45, "auto_max": 180,  # seconds between automatic scares
    "cooldown_min": 10, "cooldown_max": 25,  # silence after a motion scare
    "answer_chance": 0.45,
    "creep_chance": 0.15,
    "sweep_seconds": 8,               # how long a full-yard sweep takes
    "sweep_sound": "",                # "" = random
    "sweep_sounds": [],               # sounds that always sweep across the yard when they play
    "active_hours_enabled": True,
    "active_start": "17:00",
    "active_end": "23:00",
    "pir_pin": 17,
    "disabled_sounds": [],            # sounds switched off everywhere (still playable by hand)
    "placements": [
        {"id": f"p{i + 1}", "name": name, "terminal": term, "channel": ch,
         "enabled": i < 2, "volume": 1.0, "muted_sounds": [], "x": MAP_SPOTS[i][0], "y": MAP_SPOTS[i][1]}
        for i, (name, (term, ch)) in enumerate(zip(YARD_NAMES, TERMINALS))
    ],
    "radio": {"volume": 0.5, "placements": ["p1", "p2"], "override": True, "autoplay": False,
              "last_url": "", "last_name": ""},
    "ambience": {"on": False, "track": "graveyard.mp3", "volume": 0.4,
                 "placements": [f"p{i + 1}" for i in range(7)], "active_hours_only": True},
    "lights": {"enabled": False, "devices": [], "idle_color": "#ff5a00", "idle_brightness": 35,
               "flash_brightness": 100, "flicker": True},
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
    cfg["sweep_seconds"] = _num(cfg.get("sweep_seconds"), 2, 60, d["sweep_seconds"])
    cfg["sweep_sound"] = str(cfg.get("sweep_sound") or "")
    cfg["sweep_sounds"] = [str(x) for x in (cfg.get("sweep_sounds") or [])]
    for k in ("answer_chance", "creep_chance"):
        cfg[k] = _num(cfg.get(k), 0, 1, d[k])
    cfg["active_hours_enabled"] = bool(cfg.get("active_hours_enabled"))
    cfg["disabled_sounds"] = [str(x) for x in (cfg.get("disabled_sounds") or [])]
    by_id = {p.get("id"): p for p in cfg.get("placements", [])}
    placements = []
    for default in d["placements"]:
        p = {**default, **by_id.get(default["id"], {})}
        p["channel"] = int(_num(p["channel"], 0, CHANNELS - 1, default["channel"]))
        p["volume"] = _num(p["volume"], 0, 1, 1.0)
        p["enabled"] = bool(p["enabled"])
        p["name"] = str(p["name"])[:30] or default["name"]
        p["muted_sounds"] = list(p.get("muted_sounds") or [])
        p["x"] = _num(p.get("x"), 3, 97, default["x"])
        p["y"] = _num(p.get("y"), 5, 92, default["y"])
        placements.append(p)
    cfg["placements"] = placements
    cfg["radio"] = {**d["radio"], **cfg.get("radio", {})}
    cfg["radio"]["volume"] = _num(cfg["radio"]["volume"], 0, 1, 0.5)
    cfg["ambience"] = {**d["ambience"], **cfg.get("ambience", {})}
    am = cfg["ambience"]
    am["volume"] = _num(am["volume"], 0, 1, d["ambience"]["volume"])
    am["on"] = bool(am["on"])
    am["active_hours_only"] = bool(am["active_hours_only"])
    cfg["lights"] = {**d["lights"], **cfg.get("lights", {})}
    li = cfg["lights"]
    li["enabled"] = bool(li["enabled"])
    li["flicker"] = bool(li["flicker"])
    li["idle_brightness"] = _num(li["idle_brightness"], 0, 100, 15)
    li["flash_brightness"] = _num(li["flash_brightness"], 1, 100, 100)
    li["devices"] = [{"ip": str(x.get("ip", "")), "id": str(x.get("id", "")), "sku": str(x.get("sku", "")),
                      "name": str(x.get("name") or x.get("sku") or "Light")[:30],
                      "placement": str(x.get("placement") or "all"), "on": bool(x.get("on", True)),
                      # a chain of bulbs strung across the yard, first bulb at the west end
                      "chain": bool(x.get("chain", False)),
                      "segments": int(_num(x.get("segments"), 2, 100, 15)),
                      "reverse": bool(x.get("reverse", False))}
                     for x in li.get("devices") or [] if isinstance(x, dict) and x.get("ip")]
    cfg["denon"] = {**d["denon"], **cfg.get("denon", {})}
    dn = cfg["denon"]
    dn["max_db"] = _num(dn["max_db"], -80, 18, d["denon"]["max_db"])
    dn["volume_db"] = _num(dn["volume_db"], -80, dn["max_db"], d["denon"]["volume_db"])
    dn["auto_power"] = False   # "Get ready" automation removed from the dashboard
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


def write_safely(path, data):
    """Write to a temp file, flush it to the SD card, then swap it in.

    If the power dies mid-write, the old file is still there instead of an empty one.
    """
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)  # make the rename itself stick
    finally:
        os.close(fd)


def save_config(cfg):
    write_safely(CONFIG_PATH, json.dumps(cfg, indent=2).encode())


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


def decode_stereo(path):
    """Any audio file -> (n, 2) float32 samples at RATE."""
    if shutil.which("ffmpeg"):
        out = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(path), "-f", "s16le", "-ac", "2", "-ar", str(RATE), "-"],
            capture_output=True, check=True).stdout
        return np.frombuffer(out, dtype=np.int16).reshape(-1, 2).astype(np.float32)
    mono = decode(path)
    return np.stack([mono, mono], axis=1)


def make_loop(x, fade=1.5):
    """Blend the end of a recording into its start so it repeats without a click or gap."""
    n = int(fade * RATE)
    if len(x) < n * 4:
        return x
    k = np.linspace(0, np.pi / 2, n, dtype=np.float32)[:, None]
    body = x[:-n].copy()
    body[:n] = x[:n] * np.sin(k) + x[-n:] * np.cos(k)
    return body


def render(mono, gains):
    """Place a mono sound into the 8-channel stream. gains: {channel: scalar or per-sample array}."""
    buf = np.zeros((len(mono), CHANNELS), dtype=np.float32)
    for ch, g in gains.items():
        buf[:, ch] += mono * g
    return buf


def yard_order(placements):
    """Left to right as arranged on the dashboard's yard map."""
    return sorted(placements, key=lambda p: (p["x"], p["y"]))


def creep_gains(n_samples, spots):
    """Equal-power crossfade along a list of placements, e.g. Bushes -> Big Tree -> Porch."""
    pos = np.linspace(0, len(spots) - 1, n_samples)
    gains = {}
    for i, p in enumerate(spots):
        d = np.abs(pos - i)
        g = np.where(d < 1, np.cos(d * np.pi / 2), 0.0) * p["volume"]
        gains[p["channel"]] = gains.get(p["channel"], 0) + g
    return gains


def stretch(mono, n, fade=0.4):
    """Repeat a sound with short crossfades until it's n samples long, then fade the end."""
    if len(mono) >= n:
        out = mono[:n].copy()
    else:
        f = min(int(fade * RATE), len(mono) // 3)
        ramp = np.linspace(0, 1, f, dtype=np.float32)
        out = mono.copy()
        while len(out) < n:
            out[-f:] = out[-f:] * (1 - ramp) + mono[:f] * ramp
            out = np.concatenate([out, mono[f:]])
        out = out[:n]
    tail = min(int(0.6 * RATE), n // 4)
    out[-tail:] *= np.linspace(1, 0, tail, dtype=np.float32)
    return out


def beep_sound():
    t = np.arange(int(0.15 * RATE)) / RATE
    one = np.concatenate([np.sin(2 * np.pi * 660 * t) * 16000, np.zeros(int(0.15 * RATE))])
    return np.tile(one, 3).astype(np.float32)


# ---- Output & radio ------------------------------------------------------------

def hdmi_link_state(device):
    """Describe the HDMI connection behind an ALSA device, e.g. 'connected DENON-AVAMP'.

    The Denon only picks up the Pi's audio if the stream starts after the HDMI link is
    up, so the engine restarts the stream whenever this changes to connected.
    """
    port = "1" if "vc4hdmi1" in device else "0"
    status = ""
    for f in Path("/sys/class/drm").glob(f"card*-HDMI-A-{int(port) + 1}/status"):
        status = f.read_text().strip()
    name = ""
    for f in Path(f"/proc/asound/vc4hdmi{port}").glob("eld#*"):
        for line in f.read_text().splitlines():
            if line.startswith("monitor_name"):
                name = line.split(None, 1)[1].strip() if len(line.split(None, 1)) > 1 else ""
    return f"{status} {name}".strip()


class Output:
    """Streams raw 8-channel PCM into aplay. With no aplay (e.g. testing on a laptop) it just keeps time.

    Only the mixer thread touches the aplay process; other threads just ask for a new
    device, and the mixer switches over on its next write.
    """

    def __init__(self, device):
        self.device = device
        self.proc = None
        self.proc_device = None
        self.error = None
        self.retry_at = 0
        self.opened_at = 0

    def set_device(self, device):
        self.device = device

    def restart(self):
        """Ask the mixer to reopen the audio device (it does so on its next write)."""
        self.restart_requested = True

    def _kill(self):
        proc, self.proc = self.proc, None
        if proc:
            try:
                proc.kill()
                proc.wait(timeout=2)  # reap it so it doesn't linger as a zombie
            except (OSError, subprocess.TimeoutExpired):
                pass

    def write(self, data):
        if not shutil.which("aplay"):
            now = time.monotonic()
            self.clock = max(getattr(self, "clock", now), now - 0.1) + BLOCK / RATE
            time.sleep(max(0, self.clock - now))
            return
        if self.proc is not None and (self.proc_device != self.device or getattr(self, "restart_requested", False)):
            self._kill()  # device changed, or HDMI just (re)connected
            self.retry_at = 0
        self.restart_requested = False
        if self.proc is None or self.proc.poll() is not None:
            if self.proc is not None:
                self.error = f"Audio device '{self.device}' stopped. Is the HDMI cable in and the Denon on?"
                self._kill()
                self.retry_at = time.time() + 3
            if time.time() < self.retry_at:
                time.sleep(BLOCK / RATE)
                return
            self.proc_device = self.device
            self.proc = subprocess.Popen(
                ["aplay", "-q", "-D", self.device, "-t", "raw", "-f", "S16_LE",
                 "-c", str(CHANNELS), "-r", str(RATE), "--buffer-time=250000"],
                stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
            self.opened_at = time.time()
        try:
            self.proc.stdin.write(data)
            if time.time() - self.opened_at > 2:
                self.error = None
        except (BrokenPipeError, OSError, AttributeError):
            self._kill()
            self.retry_at = time.time() + 1


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


class Ambience:
    """A background loop that fades in/out and plays on several speakers at once.

    Each speaker reads the loop from a different starting point, so the same
    owl or drip doesn't come out of every speaker at the same moment.
    """

    def __init__(self):
        self.lock = threading.Lock()
        self.want = None          # filename we should be playing, or None for silence
        self.track = None         # filename currently loaded
        self.buf = None
        self.pos = 0
        self.gain = 0.0
        self.loading = None
        self.ready = (None, None)  # (filename, buffer) loaded in the background
        self.error = None

    def _load(self, name):
        try:
            buf = make_loop(decode_stereo(AMBIENCE_DIR / name))
            with self.lock:
                self.ready = (name, buf)
                self.error = None
        except Exception as e:
            self.error = f"Couldn't load {name}: {e}"
        finally:
            self.loading = None

    def read(self, n, k):
        """Return k blocks of (n, 2) audio, one per speaker, or None when silent."""
        with self.lock:
            want = self.want
            if want and want != self.track and self.ready[0] != want and self.loading != want:
                self.loading = want
                threading.Thread(target=self._load, args=(want,), daemon=True).start()
            step = n / (RATE * AMBIENCE_FADE)
            g0 = self.gain
            if want == self.track and self.buf is not None:
                self.gain = min(1.0, g0 + step)
            else:
                self.gain = max(0.0, g0 - step)
                if self.gain == 0.0:  # faded out: switch to the next loop (or stay quiet)
                    if want and self.ready[0] == want:
                        self.track, self.buf = self.ready
                        self.ready, self.pos = (None, None), 0
                    elif not want:
                        self.track, self.buf = None, None
            buf, pos, g1 = self.buf, self.pos, self.gain
            if buf is None or (g0 == 0 and g1 == 0) or k == 0:
                return None
            self.pos = (pos + n) % len(buf)
        ramp = np.linspace(g0, g1, n, dtype=np.float32)[:, None]
        length = len(buf)
        return [buf[(pos + j * length // k + np.arange(n)) % length] * ramp for j in range(k)]

    def status(self):
        return {"playing": self.track if self.buf is not None and self.gain > 0 else None,
                "want": self.want, "loading": bool(self.loading), "error": self.error}


LIGHT_HZ = 15  # light updates per second


def envelope(mono, hz=LIGHT_HZ):
    """Loudness of a sound, 0..1, sampled hz times a second (drives the light flicker)."""
    step = RATE // hz
    n = len(mono) // step
    if n == 0:
        return np.array([1.0])
    e = np.sqrt((mono[:n * step].reshape(n, step) ** 2).mean(axis=1))
    return np.clip(e / (e.max() or 1), 0, 1)


class Lights:
    """Keeps Govee lights in step with the sounds.

    Between scares every light sits at a dim "idle" color. When a sound plays, lights
    assigned to that yard spot (or to "all") take on the sound's color and follow its
    loudness. During a sweep each light brightens as the sound passes its spot.
    """

    def __init__(self, engine):
        self.eng = engine
        self.govee = govee.Govee()
        self.event = None
        self.tests = {}       # ip -> time a test flash ends
        self.last = {}        # ip -> {"rgb", "bri", "on", "t"}
        self.chains = {}      # ip -> {"cur": current segment colors, "sent", "t", "mode_t"}
        threading.Thread(target=self._loop, daemon=True).start()

    def show(self, sound, mono, spot_ids, voice, sweep=False):
        self.event = {"color": govee.color_for(sound), "env": envelope(mono), "spots": spot_ids,
                      "voice": voice, "sweep": sweep and len(spot_ids) > 1, "len": max(1, len(mono))}

    def test(self, ip):
        self.tests[ip] = time.time() + 2.5

    def forget(self):
        self.last.clear()  # resend everything on the next tick (after settings change)
        self.chains.clear()

    def _loop(self):
        while True:
            time.sleep(1 / LIGHT_HZ)
            try:
                self._tick()
            except Exception as e:
                self.eng.add_log(f"Lights hiccup: {e}")
                time.sleep(2)

    def _weight(self, dev, ev):
        """How strongly this light should react to the current sound, 0..1."""
        spots = ev["spots"]
        if dev["placement"] == "all":
            return 1.0
        if dev["placement"] not in spots:
            return 0.0
        if not ev["sweep"]:
            return 1.0
        pos = ev["voice"]["pos"] / ev["len"] * (len(spots) - 1)
        d = abs(pos - spots.index(dev["placement"]))
        return float(np.cos(min(1.0, d) * np.pi / 2))

    def _tick(self):
        cfg = self.eng.config["lights"]
        if not cfg["enabled"] or not cfg["devices"]:
            return
        ev = self.event
        if ev and ev["voice"]["done"].is_set():
            self.event = ev = None
        idle_rgb = govee.hex_to_rgb(cfg["idle_color"])
        idle_b = cfg["idle_brightness"]
        flicker = cfg["flicker"] and self.eng.ambience.status()["playing"]
        now = time.time()
        positions = self._chain_positions()
        for dev in cfg["devices"]:
            ip = dev["ip"]
            if not dev["on"]:
                continue
            if dev["chain"]:
                self._chain_tick(dev, ev, positions, idle_rgb, idle_b, flicker, now)
                continue
            if self.chains.pop(ip, None) is not None:   # chain mode just switched off: back to whole-light control
                self.govee.segments_mode(ip, False)
                self.last.pop(ip, None)
            if self.tests.get(ip, 0) > now:  # test flash: alternate orange and white
                on_beat = int(now * 4) % 2 == 0
                self._set(ip, (255, 90, 0) if on_beat else (255, 255, 255), 100)
                continue
            w = self._weight(dev, ev) if ev else 0.0
            if w > 0.05:
                env = ev["env"]
                level = env[min(len(env) - 1, int(ev["voice"]["pos"] / (RATE / LIGHT_HZ)))]
                bri = max(idle_b, 5) + (cfg["flash_brightness"] - max(idle_b, 5)) * level * w
                self._set(ip, ev["color"], bri)
            else:
                b = idle_b * (random.uniform(0.55, 1.15) if flicker and idle_b else 1)
                self._set(ip, idle_rgb, b)

    def _chain_positions(self):
        """Where each turned-on speaker sits along the chain: 0 = west end, 1 = east end (from the yard map)."""
        spots = [p for p in self.eng.config["placements"] if p["enabled"]]
        if not spots:
            return {}
        lo, hi = min(p["x"] for p in spots), max(p["x"] for p in spots)
        return {p["id"]: (p["x"] - lo) / (hi - lo) if hi > lo else 0.5 for p in spots}

    def _event_center(self, ev, positions):
        """Where along the chain the current sound is (0..1), following sweeps as they travel."""
        spots = [s for s in ev["spots"] if s in positions]
        if not spots:
            return None
        if not ev["sweep"] or len(spots) == 1:
            return positions[spots[0]]
        pos = ev["voice"]["pos"] / ev["len"] * (len(spots) - 1)
        i = min(int(pos), len(spots) - 2)
        f = pos - i
        return positions[spots[i]] * (1 - f) + positions[spots[i + 1]] * f

    def _chain_tick(self, dev, ev, positions, idle_rgb, idle_b, flicker, now):
        ip, n = dev["ip"], dev["segments"]
        st = self.chains.get(ip)
        if st is None or len(st["cur"]) != n:
            self.govee.power(ip, True)
            self.govee.brightness(ip, 100)   # brightness is in the colors themselves
            st = self.chains[ip] = {"cur": None, "sent": None, "t": 0, "mode_t": 0}
        if now - st["mode_t"] > 20:          # keep segment mode switched on
            self.govee.segments_mode(ip, True)
            st["mode_t"] = now

        idle = np.array(idle_rgb, dtype=float) * (idle_b / 100)
        target = np.tile(idle, (n, 1))
        if flicker and idle_b:
            target *= np.random.uniform(0.6, 1.1, (n, 1))
        if self.tests.get(ip, 0) > now:      # test flash: a spot running end to end
            pos = (now * 0.8) % 1.0
            ev_center, color, level = pos, np.array((255, 90, 0), float), 1.0
        elif ev:
            ev_center = self._event_center(ev, positions)
            color = np.array(ev["color"], dtype=float) * (self.eng.config["lights"]["flash_brightness"] / 100)
            env = ev["env"]
            level = 0.45 + 0.55 * env[min(len(env) - 1, int(ev["voice"]["pos"] / (RATE / LIGHT_HZ)))]
        else:
            ev_center = None
        if ev_center is not None:
            seg_pos = (1 - ev_center if dev["reverse"] else ev_center) * (n - 1)
            d = np.abs(np.arange(n) - seg_pos)
            w = (np.exp(-(d / 0.9) ** 2) * level)[:, None]   # only the bulbs right next to the sound
            target = target * (1 - w) + color * w

        # Ease toward the target so bulbs fade in and out instead of snapping
        cur = target if st["cur"] is None else st["cur"] + (target - st["cur"]) * 0.45
        st["cur"] = cur
        frame = np.clip(np.round(cur), 0, 255).astype(int)
        if st["sent"] is None or np.abs(frame - st["sent"]).max() >= 2 or now - st["t"] > 5:
            self.govee.segments(ip, [tuple(c) for c in frame])
            st["sent"], st["t"] = frame, now

    def _set(self, ip, rgb, bri):
        """Send only what changed (plus a refresh every 30 s in case someone used the Govee app)."""
        now = time.time()
        last = self.last.get(ip)
        stale = last is None or now - last["t"] > 30
        bri = int(round(bri))
        want_on = bri > 0
        if stale or last["on"] != want_on:
            self.govee.power(ip, want_on)
        if want_on:
            if stale or last["rgb"] != rgb:
                self.govee.color(ip, rgb)
            if stale or abs(last["bri"] - bri) >= 3:
                self.govee.brightness(ip, bri)
        self.last[ip] = {"rgb": rgb, "bri": bri, "on": want_on, "t": now if stale else last["t"]}


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
        self.ambience = Ambience()
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
        self.lights = Lights(self)
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

    def allowed(self, placement, include_off=False):
        """Sounds this speaker may play. Sounds switched off entirely are left out unless include_off."""
        off = () if include_off else self.config["disabled_sounds"]
        return [s for s in self.sounds if s not in placement["muted_sounds"] and s not in off]

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
            try:
                self._mix_block()
            except Exception as e:  # never let one bad block kill the audio for good
                self.add_log(f"Audio hiccup: {type(e).__name__}: {e}")
                time.sleep(0.2)

    def _mix_block(self):
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
        am = cfg["ambience"]
        amb_spots = [p for p in cfg["placements"] if p["enabled"] and p["id"] in am["placements"]]
        blocks = self.ambience.read(BLOCK, len(amb_spots))
        if blocks:
            for i, (p, blk) in enumerate(zip(amb_spots, blocks)):
                src = blk.mean(axis=1) if len(amb_spots) == 1 else blk[:, i % 2]
                out[:, p["channel"]] += src * am["volume"] * p["volume"]
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
        self.now_playing = {"sound": sound, "spots": [p["id"] for p in spots], "voice": v,
                            "sweep": creep, "samples": len(mono)}
        self.lights.show(sound, mono, [p["id"] for p in spots], v, sweep=creep)
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
        spots = yard_order([p for p in cfg["placements"] if p["enabled"] and self.allowed(p)])
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
        if sound in cfg["sweep_sounds"] and len(spots) > 1:
            err, v = self._sweep("random", sound, stop=False)
            if v:
                wait(v)
                self.last_spot = self.now_playing["spots"][-1] if self.now_playing else None
                return
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
        cfg = self.config
        if sound and not placement_id and sound in cfg["sweep_sounds"]:
            err = self.sweep("random", sound)
            if err is None or "two speakers" not in err:
                return err  # else: only one speaker is on, so just play it there
        self.stop_sounds()
        if placement_id:
            spot = self.placement(placement_id)
        else:
            choices = [p for p in cfg["placements"] if p["enabled"] and (sound in self.allowed(p, include_off=True) if sound else self.allowed(p))]
            spot = random.choice(choices) if choices else None
        if spot is None:
            return "No speaker available for that sound"
        pool = [sound] if sound else self.allowed(spot) or list(self.sounds)
        if not pool or pool[0] not in self.sounds:
            return "No sounds loaded"
        self._play(random.choice(pool), [spot])
        return None

    def sweep(self, direction="ltr", sound=None, seconds=None):
        """Send one sound across every speaker that's on, end to end. Returns an error or None."""
        err, _ = self._sweep(direction, sound, seconds)
        return err

    def _sweep(self, direction="ltr", sound=None, seconds=None, stop=True):
        """Start a sweep. Returns (error, voice)."""
        cfg = self.config
        spots = yard_order([p for p in cfg["placements"] if p["enabled"]])
        if len(spots) < 2:
            return "Turn on at least two speakers to sweep across.", None
        if direction == "random":
            direction = random.choice(["ltr", "rtl"])
        if direction == "rtl":
            spots = spots[::-1]
        sound = sound or cfg["sweep_sound"]
        if sound and sound not in self.sounds:
            sound = ""
        pool = [sound] if sound else [s for s in self.sounds if s not in cfg["disabled_sounds"]] or list(self.sounds)
        if not pool:
            return "No sounds loaded", None
        sound = random.choice(pool)
        # Last at least the chosen sweep time, but never cut the sound itself short
        n = max(int(float(seconds or cfg["sweep_seconds"]) * RATE), len(self.sounds[sound]))
        mono = stretch(self.sounds[sound], n)
        if stop:
            self.stop_sounds()
        gains = creep_gains(len(mono), spots)
        v = self._add_voice(render(mono, gains))
        self.now_playing = {"sound": sound, "spots": [p["id"] for p in spots], "voice": v,
                            "sweep": True, "samples": len(mono)}
        self.lights.show(sound, mono, [p["id"] for p in spots], v, sweep=True)
        self.add_log(f"{Path(sound).stem} sweeping {spots[0]['name']} → {spots[-1]['name']}")
        return None, v

    def beep(self, channel):
        self.stop_sounds()
        self._add_voice(render(beep_sound() / max(self.config["master_volume"], 0.05) * 0.5, {int(channel): 1.0}))
        self.add_log(f"Beep on HDMI channel {channel}")

    # -- scheduling & motion
    def _schedule_loop(self):
        while True:
            time.sleep(0.5)
            self.ambience.want = self.ambience_wanted()
            self._watch_hdmi()
            if self.config["mode"] in ("auto", "both") and time.time() >= self.next_auto \
                    and self.blocked_reason() is None:
                self.trigger("timer")

    def _watch_hdmi(self):
        try:
            link = hdmi_link_state(self.config["audio_device"])
        except OSError:
            return
        prev = getattr(self, "hdmi_link", None)
        self.hdmi_link = link
        if prev is not None and link != prev:
            if link.startswith("connected") and link != "connected":
                self.add_log(f"HDMI connected ({link.split(' ', 1)[1]}); restarting audio")
                threading.Timer(2.0, self.out.restart).start()
            elif not link.startswith("connected"):
                self.add_log("HDMI disconnected. Check the cable to the Denon.")

    def ambience_wanted(self):
        cfg = self.config
        am = cfg["ambience"]
        if not am["on"] or not (AMBIENCE_DIR / am["track"]).is_file():
            return None
        if am["active_hours_only"] and not self.active_hours(cfg):
            return None
        if self.radio.playing and cfg["radio"]["override"]:
            return None
        return am["track"]

    def ambience_tracks(self):
        if not AMBIENCE_DIR.is_dir():
            return []
        return [{"name": p.name, "label": p.stem.replace("_", " ").title()}
                for p in sorted(AMBIENCE_DIR.iterdir()) if p.suffix.lower() in EXTS]

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
                threading.Timer(6.0, self.out.restart).start()  # let it wake, then resend audio
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

    # -- Govee lights
    def find_lights(self):
        """Look for Govee lights on the network and add any new ones (keeps names and spots)."""
        found = govee.discover()
        devices = list(self.config["lights"]["devices"])
        known = {d["id"]: d for d in devices if d["id"]}
        added = 0
        for f in found:
            if f["id"] in known:
                known[f["id"]]["ip"] = f["ip"]   # it may have a new address
            else:
                devices.append({"ip": f["ip"], "id": f["id"], "sku": f["sku"],
                                "name": f"{f['sku']} …{f['id'][-5:].replace(':', '')}" if f["id"] else f["sku"],
                                "placement": "all", "on": True})
                added += 1
        self.update_config({"lights": {"devices": devices}})
        self.lights.forget()
        self.add_log(f"Found {len(found)} Govee light(s), {added} new")
        return found

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
                if k in ("radio", "denon", "ambience", "lights") and isinstance(v, dict):
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
        np_ = None
        if cur and not cur["voice"]["done"].is_set():
            np_ = {"sound": cur["sound"], "spots": cur["spots"]}
            if cur.get("sweep"):  # how far along the yard it is, 0..1, so the map can follow it
                np_["progress"] = round(min(1.0, cur["voice"]["pos"] / max(1, cur["samples"])), 3)
        return {
            "config": cfg,
            "ambience": self.ambience_tracks(),
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
                "ambience": self.ambience.status(),
                "time": datetime.datetime.now().strftime("%-I:%M %p"),
            },
            "log": list(self.log)[:30],
        }
