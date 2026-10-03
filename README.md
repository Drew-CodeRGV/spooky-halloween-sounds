# Spooky Halloween Sounds 🎃

A Raspberry Pi 4 + motion sensor that plays a random creepy sound from **one** hidden yard speaker at a time, at a low volume, so people walking by can't tell where it's coming from.

Audio goes from the Pi's HDMI port to a **Denon AVR-1912** as 7.1 surround, so each of the receiver's speaker terminals (front L/R, center, surround L/R, surround back L/R) can be a separate hiding spot.

## Hardware

| Part | Notes |
|---|---|
| Raspberry Pi 4 | Use the micro HDMI port **next to the USB-C power port** (HDMI 0) |
| Micro HDMI → HDMI cable | Micro, not mini. Pi → any HDMI input on the Denon |
| PIR motion sensor (HC-SR501) | ~$2. Set the jumper to "single trigger" |
| Denon AVR-1912 + speakers | Up to 7 hiding spots, plus the subwoofer channel if you want ground-shaking rumbles |

### PIR wiring
```
PIR VCC → Pi pin 2  (5V)
PIR GND → Pi pin 6  (GND)
PIR OUT → Pi pin 11 (GPIO17)
```
The HC-SR501 outputs 3.3 V, so it's safe to connect straight to the Pi.

## Setup on the Pi

Use **Raspberry Pi OS Lite** (no desktop). The desktop version's audio system can turn 7.1 into stereo.

```bash
sudo apt install -y python3-numpy python3-gpiozero ffmpeg alsa-utils
# copy this folder to /home/pi/spooky-halloween-sounds
cd ~/spooky-halloween-sounds
python3 make_placeholder_sounds.py     # optional starter sounds
```

### 1. Make sure the Pi sees the Denon
```bash
aplay -L | grep hdmi
```
You should see `hdmi:CARD=vc4hdmi0,DEV=0`. If you plugged into the other HDMI port it'll be `vc4hdmi1`, so change `AUDIO_DEVICE` in `spooky.py`.

If you hear nothing with no TV attached, force the HDMI port on by adding this to the end of the single line in `/boot/firmware/cmdline.txt`, then reboot:
```
video=HDMI-A-1:1280x720@60D
```

### 2. Set up the Denon
- **Speaker config** (Setup → Speakers → Speaker Config): set every channel you're using to Small or Large, **not "None"**. Otherwise the Denon mixes that channel into the other speakers.
- Select the Pi's HDMI input. The display should show **MULTI CH IN**. If it says "Stereo" or "Neural", press the sound mode button until you see **Direct** or **Multi Ch In**.
- Turn off Dynamic Volume and Dynamic EQ (Audyssey menu). They'd make quiet growls louder, which you don't want.

### 3. Find out which channel comes out of which speaker
```bash
python3 spooky.py --identify
```
It beeps once on channel 0, twice on channel 1, and so on. Walk around and note which speaker plays which count. The receiver itself can also announce each channel:
```bash
speaker-test -D hdmi:CARD=vc4hdmi0,DEV=0 -c 8 -t wav -l 1
```

Then edit `SPEAKERS` in `spooky.py`, **listing them in order along the sidewalk** so the creep effect moves the way someone is walking:
```python
SPEAKERS = [
    {"name": "bushes",  "channel": 0},
    {"name": "tree",    "channel": 1},
    {"name": "porch",   "channel": 4},
    {"name": "mailbox", "channel": 6},
]
```

### 4. Test, then go live
```bash
python3 spooky.py --test     # press Enter to trigger
python3 spooky.py            # with the motion sensor
```
Run at boot:
```bash
sudo cp spooky.service /etc/systemd/system/
sudo systemctl enable --now spooky
```

## Sounds
Put any `.wav`, `.mp3`, `.ogg`, `.flac` or `.m4a` files in `sounds/`. Each one can play on any speaker, so you don't need a separate file per spot.

Free sources:
- **freesound.org**: search "growl", "dog bark distant", "wolf howl", "creepy whisper", "chains", "branch snap". Filter by the **CC0** license.
- **pixabay.com/sound-effects**: free, no attribution needed
- **BBC Sound Effects** (sound-effects.bbcrewind.co.uk): free for personal use

Short clips (2–6 s) work best. Trim any silence at the start. **Low-pitched** sounds are hardest to locate, so they're the most confusing.

## Tuning (top of `spooky.py`)
- `VOLUME`: keep it low; use the Denon's master volume for the overall level
- `COOLDOWN`: silence after each scare
- `ANSWER_CHANCE`: how often a different speaker "answers"
- `CREEP_CHANCE`: how often a sound moves across 2–3 neighboring speakers
- `ACTIVE_HOURS`: so the neighbors don't hear growling at 3 a.m.
