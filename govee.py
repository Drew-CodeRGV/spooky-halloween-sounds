"""Control Govee lights over the local network (Govee "LAN Control").

Turn on LAN Control for each light in the Govee Home app (device → Settings → LAN Control).
The protocol is small JSON messages over UDP:
  - discovery: send "scan" to multicast 239.255.255.250:4001, lights answer on port 4002
  - commands:  send to the light's IP on port 4003 (turn, brightness, colorwc, devStatus)
No cloud, no account, and fast enough to flicker along with a sound.
"""
import json
import socket
import time

SCAN_GROUP = ("239.255.255.250", 4001)
REPLY_PORT = 4002
CMD_PORT = 4003


def discover(timeout=3.0):
    """Ask every Govee light on the network to say hello. Returns [{ip, id, sku}]."""
    found = {}
    rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    rx.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if hasattr(socket, "SO_REUSEPORT"):
        try:
            rx.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except OSError:
            pass
    rx.bind(("", REPLY_PORT))
    rx.settimeout(0.3)
    tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    tx.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
    scan = json.dumps({"msg": {"cmd": "scan", "data": {"account_topic": "reserve"}}}).encode()
    try:
        end = time.time() + timeout
        next_scan = 0
        while time.time() < end:
            if time.time() >= next_scan:  # ask a few times; UDP can drop
                tx.sendto(scan, SCAN_GROUP)
                next_scan = time.time() + 1.0
            try:
                data, addr = rx.recvfrom(4096)
            except socket.timeout:
                continue
            try:
                d = json.loads(data)["msg"]["data"]
            except (ValueError, KeyError, TypeError):
                continue
            ip = d.get("ip") or addr[0]
            found[ip] = {"ip": ip, "id": d.get("device", ""), "sku": d.get("sku", "Govee")}
    finally:
        rx.close()
        tx.close()
    return sorted(found.values(), key=lambda x: x["ip"])


class Govee:
    """Fire-and-forget commands to lights by IP."""

    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)

    def _send(self, ip, cmd, data):
        msg = json.dumps({"msg": {"cmd": cmd, "data": data}}).encode()
        try:
            self.sock.sendto(msg, (ip, CMD_PORT))
        except OSError:
            pass  # light unplugged or off the network; the next update will try again

    def power(self, ip, on):
        self._send(ip, "turn", {"value": 1 if on else 0})

    def brightness(self, ip, pct):
        self._send(ip, "brightness", {"value": max(1, min(100, int(round(pct))))})

    def color(self, ip, rgb):
        r, g, b = (max(0, min(255, int(c))) for c in rgb)
        self._send(ip, "colorwc", {"color": {"r": r, "g": g, "b": b}, "colorTemInKelvin": 0})


def hex_to_rgb(h, default=(80, 0, 140)):
    try:
        h = h.lstrip("#")
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    except (ValueError, AttributeError):
        return default


# What color a sound flashes, picked from its name.
SOUND_COLORS = [
    (("thunder", "lightning", "storm"), (255, 255, 255)),
    (("witch", "cackle", "cauldron", "zombie", "slime"), (60, 255, 40)),
    (("ghost", "wail", "moan", "whisper", "dead", "spirit"), (90, 160, 255)),
    (("monster", "growl", "roar", "beast", "howl", "wolf", "blood", "scream"), (255, 0, 0)),
    (("bell", "church", "chain"), (255, 180, 60)),
]
DEFAULT_FLASH = (255, 90, 0)


def color_for(sound_name):
    n = sound_name.lower()
    for words, rgb in SOUND_COLORS:
        if any(w in n for w in words):
            return rgb
    return DEFAULT_FLASH
