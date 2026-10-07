#!/usr/bin/env python3
"""One-time Ring sign-in for Spooky Halloween Sounds.

Run this yourself on the Pi:
    ~/spooky-halloween-sounds/.venv/bin/python ~/spooky-halloween-sounds/ring_setup.py

It asks for your Ring email, password and the 2-factor code Ring sends you, then saves
only a sign-in token (never your password) to ring_token.json next to this script.
To revoke it later: Ring app → Control Center → Authorized Client Devices.
"""
import asyncio
import getpass
import json
import os
import sys
from pathlib import Path

try:
    from ring_doorbell import Auth, Requires2FAError, Ring
except ImportError:
    sys.exit("The Ring library isn't installed. Run the installer again: sudo ~/spooky-halloween-sounds/install.sh")

TOKEN = Path(__file__).resolve().parent / "ring_token.json"
USER_AGENT = "SpookyHalloweenSounds/1.0"


def save_token(token):
    TOKEN.write_text(json.dumps(token))
    os.chmod(TOKEN, 0o600)


async def main():
    print("🎃 Connect Spooky Halloween Sounds to your Ring account\n")
    email = input("Ring email: ").strip()
    password = getpass.getpass("Ring password (not shown, not saved): ")
    auth = Auth(USER_AGENT, None, save_token)
    try:
        try:
            await auth.async_fetch_token(email, password)
        except Requires2FAError:
            code = input("Ring just sent you a verification code. Enter it: ").strip()
            await auth.async_fetch_token(email, password, code)
        ring = Ring(auth)
        await ring.async_create_session()
        await ring.async_update_data()
        names = [d.name for d in ring.get_device_list()]
    finally:
        await auth.async_close()
    print(f"\n✅ Connected. Ring devices: {', '.join(names) or '(none found)'}")
    print("The dashboard will connect within about 30 seconds.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nCancelled.")
    except Exception as e:
        sys.exit(f"\n❌ Couldn't sign in: {e}")
