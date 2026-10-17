"""A stand-in AVR-1912: one connection at a time, refuses the rest, announces changes."""
import pathlib, socket, sys, threading, time
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import denon

class FakeAVR:
    def __init__(self):
        self.lsock = socket.socket(); self.lsock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.lsock.bind(("127.0.0.1", 0)); self.lsock.listen(1)
        self.port = self.lsock.getsockname()[1]
        self.got, self.conns, self.refused = [], 0, 0
        self.client = None
        self.volume = "73"
        self.kill = threading.Event()
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        while not self.kill.is_set():
            try:
                c, _ = self.lsock.accept()
            except OSError:
                return
            self.conns += 1
            self.client = c
            # while a client is on, the real unit refuses everyone else: stop listening
            self.lsock.close()
            c.settimeout(0.2)
            buf = ""
            while not self.kill.is_set():
                try:
                    data = c.recv(4096)
                    if not data: break
                except socket.timeout:
                    continue
                except OSError:
                    break
                buf += data.decode()
                *lines, buf = buf.split("\r")
                for cmd in (l.strip() for l in lines if l.strip()):
                    self.got.append(cmd)
                    self._reply(c, cmd)
            try: c.close()
            except OSError: pass
            self.client = None
            time.sleep(0.05)
            if self.kill.is_set(): return
            self.lsock = socket.socket(); self.lsock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.lsock.bind(("127.0.0.1", self.port)); self.lsock.listen(1)

    def _reply(self, c, cmd):
        out = None
        if cmd == "PW?": out = "PWON"
        elif cmd == "MV?": out = f"MV{self.volume}\rMVMAX 98"
        elif cmd == "MU?": out = "MUOFF"
        elif cmd == "SI?": out = "SIDVD"
        elif cmd == "MS?": out = "MSDIRECT"
        elif cmd.startswith("MV") and cmd[2:].isdigit():
            if cmd[2:] != self.volume:          # only a real change is announced
                self.volume = cmd[2:]; out = f"MV{self.volume}\rMVMAX 98"
        if out:
            try: c.sendall(out.encode() + b"\r")
            except OSError: pass

    def announce(self, line):
        if self.client:
            self.client.sendall(line.encode() + b"\r")

    def hang_up(self):
        if self.client:
            try: self.client.close()
            except OSError: pass

avr = FakeAVR()
HOST = f"127.0.0.1:{avr.port}"
d = denon.Denon()
d.refresh(HOST)
for _ in range(50):
    if d.status.get("connected"): break
    time.sleep(0.1)
assert d.status["connected"], d.status
print(f"connected after 1 session; status = {d.status}")
assert d.status["volume_db"] == -7.0 and d.status["power"] == "on", d.status

# --- the burst that used to lose messages ---
avr.got.clear()
before = avr.conns
t0 = time.time()
for v in range(60, 70):
    d.send(HOST, [denon.db_to_mv(v - 80)], settle=0)
time.sleep(0.8)
vols = [c for c in avr.got if c.startswith("MV") and c != "MV?"]
print(f"10 rapid volume commands in {time.time()-t0:.1f}s -> receiver got {len(vols)}: {vols}")
assert len(vols) == 10, f"lost commands: {vols}"
assert avr.conns == before, f"it reconnected {avr.conns - before} times; it must reuse the one session"
assert d.status["volume_db"] == -11.0, d.status
print("   no reconnects, nothing lost, status followed along")

# --- a change made at the receiver itself shows up without being asked ---
avr.announce("MV50")
time.sleep(0.5)
assert d.status["volume_db"] == -30.0, d.status
avr.announce("MUON")
time.sleep(0.5)
assert d.status["muted"] is True, d.status
print(f"turned down at the front panel -> dashboard followed on its own: {d.status['volume_db']} dB, muted")

# --- the session dying is survivable ---
sessions = avr.conns
avr.hang_up()
for _ in range(100):
    if avr.conns > sessions and d.status.get("connected"): break
    time.sleep(0.1)
assert avr.conns > sessions and d.status["connected"], (avr.conns, d.status)
print(f"after the receiver hung up: reconnected ({avr.conns} sessions total) and healthy")

print(f"\ntotal sessions opened for all of that: {avr.conns}")
print("OK: one held session, no lost commands, live status")
avr.kill.set()
