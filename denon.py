"""Control a Denon AVR (built for the AVR-1912) over its network control port.

The Denon listens on TCP port 23 for plain-text commands ending in a carriage
return: PWON, PWSTANDBY, MV45, MUON, SIDVD, MSDIRECT, and queries like PW?.

It accepts one connection at a time and refuses a new one for a moment after the
last closes, so we open a single session and keep it. It also announces every
change on that session without being asked, which keeps the dashboard live.
"""
import concurrent.futures
import re
import socket
import subprocess
import threading
import time
from pathlib import Path

PORT = 23
LEASES = [Path("/var/lib/NetworkManager/dnsmasq-eth0.leases"), Path("/var/lib/misc/dnsmasq.leases")]
# Networks on the Pi's Ethernet cable: the "shared" DHCP network, plus the fixed
# network Drew's AVR-1912 is set to (10.10.10.4).
SUBNETS = ["10.10.10.", "10.42.0."]
DEFAULT_HOST = "10.10.10.4"   # Drew's AVR-1912 (fixed address, DHCP off)

INPUTS = ["DVD", "BD", "TV", "SAT/CBL", "GAME", "GAME2", "V.AUX", "DOCK", "CD", "NET/USB", "TUNER"]  # AVR-1912's list
SOUND_MODES = {"DIRECT": "Direct", "PURE DIRECT": "Pure Direct", "STEREO": "Stereo",
               "MCH STEREO": "All speakers (Multi Ch Stereo)", "AUTO": "Auto"}


def db_to_mv(db):
    """-30.0 dB -> 'MV50', -34.5 dB -> 'MV455'. 0 dB on the Denon's display is 80."""
    v = max(0.0, min(98.0, round((float(db) + 80) * 2) / 2))
    return f"MV{int(v):02d}5" if v % 1 else f"MV{int(v):02d}"


def mv_to_db(raw):
    """'50' -> -30.0, '455' -> -34.5"""
    v = int(raw[:2]) + (0.5 if len(raw) == 3 else 0)
    return v - 80


def _addr(host):
    """'10.42.0.23' or '10.42.0.23:2323' -> (host, port)"""
    h, _, p = host.partition(":")
    return h, int(p or PORT)


def _port_open(host, timeout=0.4):
    try:
        with socket.create_connection(_addr(host), timeout=timeout):
            return True
    except OSError:
        return False


def find_denon():
    """Look for the receiver on the Pi's Ethernet link: DHCP leases first, then a quick scan."""
    candidates = []
    candidates.append(DEFAULT_HOST)
    for f in LEASES:
        try:
            for line in f.read_text().splitlines():
                parts = line.split()
                if len(parts) >= 4:
                    ip, name = parts[2], parts[3].lower()
                    candidates.insert(0 if ("denon" in name or "avr" in name) else len(candidates), ip)
        except OSError:
            pass
    try:  # devices seen on the cable; readable without root, unlike the lease file
        out = subprocess.run(["ip", "neigh", "show", "dev", "eth0"], capture_output=True, text=True, timeout=3).stdout
        candidates += [line.split()[0] for line in out.splitlines() if line.startswith(tuple(SUBNETS))]
    except (OSError, subprocess.SubprocessError):
        pass
    for ip in dict.fromkeys(candidates):
        if _port_open(ip):
            return ip
    with concurrent.futures.ThreadPoolExecutor(max_workers=64) as pool:
        hosts = [f"{net}{i}" for net in SUBNETS for i in range(2, 255) if f"{net}{i}" not in ("10.10.10.1",)]
        for ip, ok in zip(hosts, pool.map(_port_open, hosts)):
            if ok:
                return ip
    return None


def pi_has_route(host):
    """Does the Pi have its own address on the same network as host (e.g. 10.10.10.1 for 10.10.10.4)?"""
    prefix = _addr(host)[0].rsplit(".", 1)[0] + "."
    try:
        out = subprocess.run(["ip", "-4", "-o", "addr"], capture_output=True, text=True, timeout=3).stdout
    except (OSError, subprocess.SubprocessError):
        return True  # can't tell (e.g. testing on a Mac)
    return f"inet {prefix}" in out


def diagnose(host, err):
    """Turn a connection error into what to actually do about it."""
    ip = _addr(host)[0]
    net = ip.rsplit(".", 1)[0]
    if not pi_has_route(host):
        return (f"The Pi has no {net}.x address on the Ethernet cable, so it can't reach {ip}. "
                f"On the Pi run: sudo nmcli con modify denon-link ipv4.addresses \"10.42.0.1/24,{net}.1/24\" "
                f"&& sudo nmcli con up denon-link")
    if isinstance(err, ConnectionRefusedError):
        return (f"The Denon at {ip} is on the network but refused the connection. Another app may be "
                f"connected to it (it allows one at a time), or turn on Network Standby / Network Control.")
    if isinstance(err, (socket.timeout, TimeoutError)):
        return f"No answer from {ip}. Is the Denon plugged in and the Ethernet cable connected?"
    return f"Can't reach the Denon at {ip} ({err})"


QUERIES = ["PW?", "MV?", "MU?", "SI?", "MS?"]
GAP = 0.15          # the receiver drops commands sent back to back
RECONNECT_MAX = 30.0


class Denon:
    """One telnet session, held open for as long as the program runs.

    Opening a connection per command looked fine in testing and fell apart in the
    yard: the receiver refuses a new connection for a moment after the last one
    closes, so a command and the status read that followed it would knock each
    other out, and dragging the volume slider lost most of its messages.
    """

    def __init__(self):
        self.lock = threading.Lock()     # one writer at a time on the socket
        self.status = {"connected": False, "error": "Not set up yet"}
        self.checked = 0
        self.sock = None
        self.host = None
        self.want = None                 # the address we should be talking to
        threading.Thread(target=self._run, daemon=True).start()

    # -- the session ---------------------------------------------------------
    def _drop(self):
        with self.lock:
            if self.sock:
                try:
                    self.sock.close()
                except OSError:
                    pass
            self.sock = None

    def _run(self):
        """Keep the session up, and turn everything the receiver says into status."""
        buf, wait = "", 1.0
        while True:
            host = self.want
            if not host:
                time.sleep(0.5)
                continue
            if self.sock is None or self.host != host:
                self._drop()
                try:
                    sock = socket.create_connection(_addr(host), timeout=4)
                except Exception as e:
                    self.status = {"connected": False, "error": diagnose(host, e)}
                    time.sleep(wait)
                    wait = min(RECONNECT_MAX, wait * 2)
                    continue
                sock.settimeout(1.0)
                with self.lock:
                    self.sock, self.host = sock, host
                buf, wait = "", 1.0
                self.status = {"connected": True, "error": None, "host": host}
                self.ask(QUERIES)        # fill in where the receiver currently stands
            try:
                chunk = self.sock.recv(4096)
                if not chunk:
                    raise ConnectionResetError("the Denon closed the connection")
            except socket.timeout:
                continue
            except OSError as e:
                self.status = {"connected": False, "error": diagnose(host, e)}
                self._drop()
                time.sleep(1.0)
                continue
            buf += chunk.decode("ascii", "replace")
            *lines, buf = buf.split("\r")
            for line in lines:
                self._absorb(line.strip())

    def _absorb(self, line):
        """One line from the receiver, solicited or not."""
        st = dict(self.status)
        if line in ("PWON", "PWSTANDBY"):
            st["power"] = "on" if line == "PWON" else "standby"
        elif m := re.fullmatch(r"MV(\d{2,3})", line):
            st["volume_db"] = mv_to_db(m.group(1))
        elif line in ("MUON", "MUOFF"):
            st["muted"] = line == "MUON"
        elif line.startswith("SI"):
            st["input"] = line[2:]
        elif line.startswith("MS"):
            st["mode"] = line[2:]
        else:
            return                       # MVMAX, Z2ON, SVSOURCE and friends
        st["connected"], st["error"], st["host"] = True, None, self.host
        self.status = st
        self.checked = time.time()

    # -- talking to it -------------------------------------------------------
    def ask(self, commands):
        """Write commands on the open session. Answers arrive in the reader."""
        with self.lock:
            sock = self.sock
            if sock is None:
                raise ConnectionError(self.status.get("error") or "not connected to the Denon")
            for cmd in commands:
                sock.sendall(cmd.encode("ascii") + b"\r")
                time.sleep(1.5 if cmd == "PWON" else GAP)   # it needs a moment after power-on

    def send(self, host, commands, settle=0.3):
        """Send commands, waiting briefly for the receiver to report back."""
        if not host:
            raise RuntimeError("No Denon address set. Press Find Denon.")
        self.want = host
        deadline = time.time() + 6
        while self.sock is None and time.time() < deadline:
            time.sleep(0.05)             # a reconnect may be in flight
        self.ask(commands)
        time.sleep(settle)               # give the reader a moment to pick up the answer
        return []

    def refresh(self, host):
        """Ask where the receiver stands. Mostly a keepalive now: it reports changes itself."""
        self.want = host
        try:
            self.send(host, QUERIES)
        except Exception as e:
            if self.status.get("connected"):
                self.status = {"connected": False, "error": diagnose(host, e)}
        return self.status

    def get_ready(self, host, input_name, mode, volume_db, max_db):
        """Power on and set the input, sound mode, and volume for the haunt."""
        self.send(host, ["PWON", "ZMON", f"SI{input_name}", f"MS{mode}",
                         db_to_mv(min(volume_db, max_db)), "MUOFF"])
        return self.status
