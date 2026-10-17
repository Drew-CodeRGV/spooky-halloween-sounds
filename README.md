# Spooky Halloween Sounds 🎃

A Raspberry Pi 4 that hides creepy sounds around your yard. When someone walks by (or on a timer), a random growl, moan or heartbeat plays from **one** hidden speaker at a time, at a low volume, so nobody can tell where it's coming from. A web dashboard lets you control everything from your phone, and it can also play Halloween internet radio.

- Up to **7 hiding spots** using the 7.1 outputs of a Denon AVR-1912 (connected to the Pi by HDMI)
- **Motion sensor**, **automatic timer**, or both
- Another speaker can "answer" a sound, and a sound can "creep" from speaker to speaker
- Choose which sounds play from which speaker, upload your own sounds, and set active hours
- **Flicker** between scares, with speed and depth sliders, from a slow breathing to a guttering candle
- **Background atmospheres** that loop quietly underneath the scares (graveyard, sewer, abandoned asylum, thunderstorm, haunted forest, mad scientist lab, witch's cauldron)
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

## Phone remote (installable app)
Open **http://spooky.local/remote** on your phone. It has a big **Scare Now** button, a button for each speaker, a soundboard, mode switches, radio, and Denon power and volume. To put it on your home screen:
- **iPhone:** in Safari, tap Share → **Add to Home Screen**. It opens full-screen like an app.
- **Android:** in Chrome, tap ⋮ → **Add to Home screen**. Long-press the icon for **Scare now** and **Stop** shortcuts.

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
6. **Govee Lights:** press **Find lights**, then give each light a yard spot so it flares when that speaker plays.

## Govee light chains
A string of bulbs is one light to Govee but many points in the yard, so turn on **Chain across the yard** for it. Only the bulbs nearest each sound light up, and sweeps travel along the string.

Because a string usually covers only part of the yard, each one has a **span**: *covers the yard from X% to Y%*, where 0% is the west edge of the yard map and 100% is the east edge. A sound outside a string's span leaves it at its idle ripple, and the bulb at the near end glows as the sound comes closer.

Two strings, one west and one east, with the spans this yard actually measured at:

| String | Chain | Segments | Covers | Bulbs | First bulb east |
|---|---|---|---|---|---|
| West | on | 4 | 10% to 50% | 1-4 | off |
| East | on | 4 | 50% to 78% | 5-8 | off |

The east string stops at 78% rather than the fence because that's where the bulbs stop - it turns back along the house. Spans describe the bulbs, not the yard.

The bulbs are numbered as one run from west to east, so the two strings read as bulbs 1 through 8. A sound lights the bulb that is really beside it, measured off the yard map, so each span wants to be where that string's bulbs actually are.

**Don't guess the spans, walk them.** `python3 walk_bulbs.py` lights one bulb at a time, solid white, and steps on when you press Enter. Stand outside with it and note where each bulb falls relative to your speakers. It pauses light sync while it runs and switches it back on at the end. Over ssh, `python3 walk_bulbs.py --file &` takes the bulb number from `/tmp/spooky_walk` instead, so you can walk the yard and change it from your phone.

Walking it is also the only reliable way to settle **first bulb is on the east end**. Two strings of the same model can be wired opposite ways round, and a mirrored string is hard to spot from the porch but makes every scare on that half light the wrong place. Light bulb 1, then the next: if the second one appears further *west*, that string is reversed.

If the first or last bulb of the run never flares, the chains reach further out than your outermost speakers. That's expected, not a fault - a sound at the westmost speaker lights the bulb beside *it*, not the one at the fence. Shorten that chain's span if you'd rather the end bulbs joined in.

## Notes on the hardware
Things that cost an evening to work out, kept here so they don't have to be worked out twice.

### Govee (tested on H8066 permanent outdoor lights)
- **Re-arming segment mode makes the string blink.** Sending the mode packet to a light already in that mode still flashes it. The engine therefore re-arms only when the frame stream has actually lapsed, and otherwise rarely, by preference while a sound is playing so the flash hides inside the flare.
- **Segment mode lapses after about a minute without a frame**, and the string drops back to whatever scene the Govee app had on - you'll see it start cycling colours. A light that lost power comes back out of the mode too, which is why the re-arm can't go away entirely.
- **Multi-colour frames need to be streamed.** A single frame gets ignored or overwritten. If you're testing by hand, loop it.
- **`devStatus` lies about what the string is showing.** It reports the last whole-string colour command and is never updated by segment frames.
- Segment order follows the wiring, not the compass. Two identical strings here are wired opposite ways round.

### Denon AVR-1912
- **One connection at a time, and it refuses a new one for a moment after the last closes.** Ten connections opened back to back got one through. Anything that connects per command falls apart exactly when it's used most - a button press and the status read after it knock each other out. The engine holds a single session open for its whole life instead.
- **It announces its own changes on that session**, unsolicited: set `MV72` and `MV72` comes back. So the dashboard doesn't poll for status. It stays quiet when a command changes nothing, which makes "set it to what it already is" a useless test.
- Answers arrive with company: `MV?` brings `MV73` *and* `MVMAX 98`, `PW?` can bring `Z2ON`. Parse per line and ignore the rest.
- Commands sent down one session want about 0.15 s between them, and 1.5 s after `PWON`.

## Tests
`python3 tests/run.py`, or `python3 tests/run.py track` for a subset. No framework - each file asserts and prints what it checked. They cover the light-chain geometry, sweeps handing off between chains, the segment-mode re-arm, flicker speed and depth, and the Denon session against a stand-in receiver that refuses concurrent connections the way the real one does.

## Sounds
The repo comes with original sounds, all made from scratch by `make_spooky_sounds.py`, so they're free to use and share:

- **Scares** (`sounds/`): monster roar, zombie groan, wolf howl, ghost wail, evil whisper, witch cackle, door creak, chains rattle, bell toll, thunder crack, knock knock, crow caws, plus the starter growls, heartbeat, breathing and moan.
- **Background atmospheres** (`sounds/ambience/`): 60-second seamless loops of a graveyard, sewer, abandoned asylum, thunderstorm, haunted forest, mad scientist lab and witch's cauldron.

Add your own from the dashboard: **Add sounds** for scares, **Add background** for loops. Or copy `.wav`, `.mp3`, `.ogg`, `.flac` or `.m4a` files into `sounds/` or `sounds/ambience/`. Any recording works as a background loop, because the Pi blends its end into its start.

Sounds you upload stay on the Pi. Only add files to this repo if you're allowed to share them.

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
- `denon.py`: Denon network control (one held session on port 23)
- `engine.py`: the audio engine (always-on 7.1 mixer to HDMI), scare scheduler, motion sensor and radio
- `static/`: dashboard (`index.html`), phone remote (`remote.html`), app manifest, service worker, icons
- `make_icons.py`: draws the app icons
- `make_spooky_sounds.py`: synthesizes the scare sounds and background loops
- `make_placeholder_sounds.py`: makes the starter growls, heartbeat, breathing and moan
- `walk_bulbs.py`: lights the chains one bulb at a time, for working out each chain's span
- `tests/`: `python3 tests/run.py` - light geometry, sweeps, segment-mode re-arm, flicker, Denon session
- `config.json`: your settings (created on the Pi, not in git)

To try the dashboard on a laptop: `pip install flask numpy` and then `SPOOKY_PORT=8080 python3 app.py`. On a laptop it runs without making sound.
