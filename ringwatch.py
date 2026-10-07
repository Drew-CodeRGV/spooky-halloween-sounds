"""Listen for Ring doorbell motion and button presses, and hand them to the engine.

Uses the open-source ring_doorbell library's push listener (the same alerts the Ring
app gets), so events arrive within a few seconds. Sign in once with ring_setup.py.
"""
import asyncio
import json
import os
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TOKEN = ROOT / "ring_token.json"
FCM_CREDS = ROOT / "ring_fcm.json"
USER_AGENT = "SpookyHalloweenSounds/1.0"


def _save(path, data):
    path.write_text(json.dumps(data))
    os.chmod(path, 0o600)


class RingWatcher:
    def __init__(self, on_event, log):
        self.on_event = on_event      # called with (kind, device_name); kind is "motion" or "ding"
        self.log = log
        self.status = {"state": "starting", "devices": [], "error": None, "last_event": None}
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        try:
            import ring_doorbell  # noqa: F401
        except ImportError:
            self.status = {"state": "not installed", "devices": [], "last_event": None,
                           "error": "The Ring library isn't installed. Run the installer again."}
            return
        delay = 10
        while True:
            if not TOKEN.exists():
                self.status.update(state="not signed in", error=None)
                time.sleep(30)
                continue
            try:
                asyncio.run(self._listen())
                delay = 10
            except Exception as e:
                self.status.update(state="error", error=f"{type(e).__name__}: {e}")
                self.log(f"Ring connection problem: {e} (retrying)")
                time.sleep(delay)
                delay = min(delay * 2, 600)

    async def _listen(self):
        from ring_doorbell import Auth, Ring, RingEventListener
        auth = Auth(USER_AGENT, json.loads(TOKEN.read_text()), lambda t: _save(TOKEN, t))
        try:
            ring = Ring(auth)
            await ring.async_create_session()
            await ring.async_update_data()
            self.status["devices"] = [d.name for d in ring.get_device_list()]
            creds = json.loads(FCM_CREDS.read_text()) if FCM_CREDS.exists() else None
            listener = RingEventListener(ring, creds, lambda c: _save(FCM_CREDS, c))
            listener.add_notification_callback(self._event)
            if not await listener.start():
                raise RuntimeError("couldn't subscribe to Ring alerts")
            self.status.update(state="connected", error=None)
            self.log(f"Ring connected ({', '.join(self.status['devices']) or 'no devices'})")
            try:
                while listener.started:
                    await asyncio.sleep(5)
            finally:
                await listener.stop()
            raise RuntimeError("Ring listener stopped")
        finally:
            await auth.async_close()

    def _event(self, ev):
        if getattr(ev, "is_update", False):
            return  # a follow-up to an event we already handled
        kind = ev.kind if ev.kind in ("motion", "ding") else None
        if not kind:
            return
        self.status["last_event"] = {"kind": kind, "device": ev.device_name, "t": time.strftime("%-I:%M:%S %p")}
        try:
            self.on_event(kind, ev.device_name)
        except Exception as e:
            self.log(f"Ring event error: {e}")
