# Spooky Halloween Sounds 🎃

A Raspberry Pi 4 that hides creepy sounds around your yard. When someone walks by (or on a timer), a random growl, moan or heartbeat plays from **one** hidden speaker at a time, at a low volume, so nobody can tell where it's coming from. A web dashboard lets you control everything from your phone, and it can also play Halloween internet radio.

- Up to **7 hiding spots** using the 7.1 outputs of a Denon AVR-1912 (connected to the Pi by HDMI)
- **Motion sensor**, **automatic timer**, or both
- Another speaker can "answer" a sound, and a sound can "creep" from speaker to speaker
- Choose which sounds play from which speaker, upload your own sounds, and set active hours
- **Halloween radio** from the free radio-browser.info directory, which can replace the spooky sounds while it plays
- **Denon controls** on the dashboard: power, input, sound mode, volume (with a safety limit), and automatic on/off with your active hours

## Install (fresh Raspberry Pi)

1. Flash **Raspberry Pi OS Lite (64-bit)** with Raspberry Pi Imager. In its settings, set your Wi-Fi, a username/password, and turn on SSH.
2. Connect the Pi's **HDMI 0** port (the one next to the USB-C power port) to any HDMI input on the Denon with a **micro HDMI → HDMI** cable.
   Also run an **Ethernet cable from the Pi to the Denon**. The Pi shares its Wi-Fi with the Denon over it, which lets the dashboard control the receiver.
3. Wire the motion sensor (below), power up the Pi, SSH in, and run:

```bash
curl -sSL https://raw.githubusercontent.com/Drew-CodeRGV/spooky-halloween-sounds/main/install.sh | sudo bash
```
```bash
sudo reboot
```

4. On your phone or laptop (on the same Wi-Fi), open **http://spooky.local**

The installer:
- installs everything the project needs
- downloads this repo
- creates the starter sounds
- keeps the HDMI port on with no TV attached
- shares the Pi's Wi-Fi with the Denon over Ethernet (skip with `SPOOKY_DENON_LINK=0`)
- names the Pi `spooky`
- sets it up to start at boot

Run it again any time to update.

## Motion sensor wiring (HC-SR501)
```
PIR VCC → Pi pin 2  (5V)
PIR GND → Pi pin 6  (GND)
PIR OUT → Pi pin 11 (GPIO17)
```
Set the sensor's jumper to "single trigger". The two knobs adjust sensitivity and how long it stays triggered.

## Denon AVR-1912 setup
- Select the HDMI input the Pi is plugged into (the inputs are named after devices, e.g. DVD or GAME). Check under Input Setup that its audio mode is **Auto** or **HDMI**.
- Setup → Speakers → Speaker Config: set every speaker you use to **Small** or **Large**, not "None". Otherwise the Denon mixes that channel into the other speakers.
- With the Pi playing, the display should show **MULTI CH IN**. If it shows Stereo or Neural, press the sound mode button until it's **Direct / Multi Ch In**.
- Turn off **Dynamic Volume** and **Dynamic EQ** (Audyssey menu). They'd make the quiet growls louder.
- Setup → Network → **Network Standby: On**. Without it, the Denon can't be turned on from the dashboard while it's in standby.

## Using the dashboard
1. **Speaker Placements:** turn on the spots that have speakers and press **Beep** on each one. If the beep comes from the wrong speaker, change the HDMI channel number until it's right. Rename the spots to match your yard.
2. **When to Play:** choose **Motion sensor**, **Automatic** (e.g. every 1–3 minutes), or **Both**. Set active hours so the neighbors get some sleep.
3. **Sounds × Speakers:** uncheck any sound you don't want from a given spot. For example, keep the dog barks by the gate and the ghost moans by the porch.
4. **Denon Receiver:** the Pi finds the Denon on its own. **Get ready** turns it on and sets the input, sound mode and volume you chose. **Never louder than** caps the volume so nobody can blast the yard from their phone. With the auto option on, the Denon turns on when active hours start and goes to standby when they end.
5. **Halloween Radio:** search or tap a tag, then press Play. Choose which speakers the radio plays on. With "Radio replaces the spooky sounds" on, scares pause while the radio plays.

## Sounds
Upload sounds from the dashboard, or copy `.wav`, `.mp3`, `.ogg`, `.flac` or `.m4a` files into `sounds/`.

Free sources:
- **freesound.org**: search "growl", "dog bark distant", "wolf howl", "creepy whisper", "chains", "branch snap". Filter by the **CC0** license.
- **pixabay.com/sound-effects**: free, no attribution needed
- **BBC Sound Effects** (sound-effects.bbcrewind.co.uk): free for personal use

Short clips (2–6 s) work best. Trim any silence at the start. **Low-pitched** sounds are hardest to locate, so they're the most confusing.

## About Pandora
Pandora doesn't let other devices play its stations without a paid account and login, so the dashboard uses radio-browser.info instead. It's a free, open directory of more than 50,000 internet stations, with plenty tagged halloween, horror and spooky. You can also paste any stream link.

## Troubleshooting
| Problem | Fix |
|---|---|
| Can't open http://spooky.local | Use the IP address the installer printed. Some Android phones don't support `.local` names. |
| Red "audio device stopped" banner | Check the HDMI cable and that the Denon is on. Run `aplay -L \| grep hdmi`. If you used the other HDMI port, change the device under **Advanced** to `hdmi:CARD=vc4hdmi1,DEV=0`. |
| Denon shows "PCM 2ch" or plays from every speaker | Check Speaker Config (no "None") and set the sound mode to Direct. |
| Sensor shows "not available" | Check the wiring, then run `sudo systemctl restart spooky`. |
| Denon shows "Not connected" | Check the Ethernet cable and the Denon's Network Standby setting, then press **Find Denon**. Run `nmcli con show denon-link` on the Pi to check the link. |
| See what it's doing | `journalctl -u spooky -f` |

## Files
- `install.sh`: sets up a fresh Pi
- `app.py`: the web dashboard and its API
- `denon.py`: Denon network control (port 23 commands)
- `engine.py`: the audio engine (always-on 7.1 mixer to HDMI), scare scheduler, motion sensor and radio
- `static/`: dashboard page
- `make_placeholder_sounds.py`: makes the starter sounds
- `config.json`: your settings (created on the Pi, not in git)

To try the dashboard on a laptop: `pip install flask numpy` and then `SPOOKY_PORT=8080 python3 app.py`. On a laptop it runs without making sound.
