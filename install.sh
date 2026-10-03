#!/usr/bin/env bash
# Spooky Halloween Sounds: one-shot installer for a fresh Raspberry Pi 4.
#
# On the Pi, run:
#   curl -sSL https://raw.githubusercontent.com/Drew-CodeRGV/spooky-halloween-sounds/main/install.sh | sudo bash
# or, from inside a copy of this repo:
#   sudo ./install.sh
#
# Options (environment variables):
#   SPOOKY_HOSTNAME=spooky   Pi's network name -> http://spooky.local  (set to "" to leave it alone)
#   SPOOKY_PORT=80           web dashboard port
#   SPOOKY_DENON_LINK=1      share the Pi's Wi-Fi with the Denon over the Ethernet cable (0 to skip)
#   SPOOKY_DENON_NET=10.10.10.1/24   extra Pi address on the cable, for a Denon set to a fixed
#                            address (Drew's AVR-1912 is fixed at 10.10.10.4). "" to skip.
set -euo pipefail

REPO_URL="https://github.com/Drew-CodeRGV/spooky-halloween-sounds.git"
SPOOKY_HOSTNAME="${SPOOKY_HOSTNAME-spooky}"
SPOOKY_PORT="${SPOOKY_PORT:-80}"
SPOOKY_DENON_LINK="${SPOOKY_DENON_LINK:-1}"
SPOOKY_DENON_NET="${SPOOKY_DENON_NET-10.10.10.1/24}"

say()  { printf '\n\033[1;35m🎃 %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m⚠  %s\033[0m\n' "$*"; }

if [[ $EUID -ne 0 ]]; then
  echo "Please run with sudo:  sudo $0"
  exit 1
fi

RUN_USER="${SUDO_USER:-}"
if [[ -z "$RUN_USER" || "$RUN_USER" == "root" ]]; then
  RUN_USER="$(getent passwd 1000 | cut -d: -f1)"
fi
RUN_HOME="$(getent passwd "$RUN_USER" | cut -d: -f6)"
[[ -n "$RUN_USER" && -d "$RUN_HOME" ]] || { echo "Couldn't find a normal user account to run as."; exit 1; }

# ---- 1. Packages ----------------------------------------------------------------
say "Installing software (this can take a few minutes on a new Pi)…"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y --no-install-recommends \
  git python3 python3-numpy python3-flask python3-gpiozero \
  ffmpeg alsa-utils avahi-daemon ca-certificates curl dnsmasq-base
# GPIO backend for the motion sensor (name varies a little between OS releases)
apt-get install -y --no-install-recommends python3-lgpio || apt-get install -y python3-rpi-lgpio || true

# ---- 2. Get the code ----------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || true)"
if [[ -n "$SCRIPT_DIR" && -f "$SCRIPT_DIR/app.py" && -f "$SCRIPT_DIR/engine.py" ]]; then
  APP_DIR="$SCRIPT_DIR"
  say "Using the copy in $APP_DIR"
else
  APP_DIR="$RUN_HOME/spooky-halloween-sounds"
  if [[ -d "$APP_DIR/.git" ]]; then
    say "Updating $APP_DIR"
    sudo -u "$RUN_USER" git -C "$APP_DIR" pull --ff-only
  else
    say "Downloading to $APP_DIR"
    sudo -u "$RUN_USER" git clone "$REPO_URL" "$APP_DIR"
  fi
fi
chown -R "$RUN_USER:$RUN_USER" "$APP_DIR"

# ---- 3. Permissions for audio and the motion sensor ---------------------------------
usermod -aG audio,gpio,video "$RUN_USER" 2>/dev/null || usermod -aG audio "$RUN_USER"

# ---- 4. Starter sounds -----------------------------------------------------------------
if ! ls "$APP_DIR"/sounds/*.* >/dev/null 2>&1; then
  say "Creating starter sounds"
  sudo -u "$RUN_USER" python3 "$APP_DIR/make_placeholder_sounds.py"
fi

# ---- 5. HDMI: keep the port on even with no TV, so the Denon always gets audio ----------
CMDLINE=/boot/firmware/cmdline.txt
[[ -f $CMDLINE ]] || CMDLINE=/boot/cmdline.txt
NEED_REBOOT=0
if [[ -f $CMDLINE ]] && ! grep -q "video=HDMI-A-1" "$CMDLINE"; then
  say "Forcing HDMI port 0 on (so audio works without a TV)"
  cp "$CMDLINE" "$CMDLINE.spooky-backup"
  sed -i '1 s/$/ video=HDMI-A-1:1280x720@60D/' "$CMDLINE"
  NEED_REBOOT=1
fi

# ---- 6. Network name: http://spooky.local ----------------------------------------------
if [[ -n "$SPOOKY_HOSTNAME" && "$(hostname)" != "$SPOOKY_HOSTNAME" ]]; then
  say "Naming this Pi '$SPOOKY_HOSTNAME' so you can open http://$SPOOKY_HOSTNAME.local"
  if command -v raspi-config >/dev/null; then
    raspi-config nonint do_hostname "$SPOOKY_HOSTNAME"
  else
    hostnamectl set-hostname "$SPOOKY_HOSTNAME"
    sed -i "s/127\.0\.1\.1.*/127.0.1.1\t$SPOOKY_HOSTNAME/" /etc/hosts
  fi
  NEED_REBOOT=1
fi
# Announce spooky.local with the regular IPv4 address only. Some Macs and phones try the
# IPv6 address first, can't reach it, and report "No route to host".
AVAHI_CONF=/etc/avahi/avahi-daemon.conf
if [[ -f $AVAHI_CONF ]]; then
  set_avahi() {  # set_avahi section key value
    if grep -q "^#\?$2=" "$AVAHI_CONF"; then
      sed -i "s/^#\?$2=.*/$2=$3/" "$AVAHI_CONF"
    else
      sed -i "/^\[$1\]/a $2=$3" "$AVAHI_CONF"
    fi
  }
  set_avahi server use-ipv6 no
  set_avahi publish publish-aaaa-on-ipv4 no
fi
systemctl enable avahi-daemon >/dev/null 2>&1 || true
systemctl restart avahi-daemon >/dev/null 2>&1 || true

# ---- 7. Ethernet cable to the Denon: share the Pi's Wi-Fi with it --------------------------
if [[ "$SPOOKY_DENON_LINK" == "1" ]]; then
  if ip route show default 2>/dev/null | grep -q "dev eth0"; then
    warn "This Pi is using its Ethernet port for internet, so I won't turn it into the Denon link."
    warn "Connect the Pi to Wi-Fi, then run this installer again."
  elif command -v nmcli >/dev/null; then
    if ! nmcli -t -f NAME con show | grep -qx "denon-link"; then
      say "Sharing Wi-Fi with the Denon over the Ethernet cable"
      # Remove the default "use Ethernet for internet" profile so it doesn't fight the shared one
      nmcli -t -f NAME,TYPE con show | awk -F: '$2=="802-3-ethernet"{print $1}' | while read -r c; do
        [[ "$c" != "denon-link" ]] && nmcli con delete "$c" >/dev/null 2>&1 || true
      done
      nmcli con add type ethernet ifname eth0 con-name denon-link \
        ipv4.method shared ipv4.addresses 10.42.0.1/24 ipv6.method ignore \
        connection.autoconnect yes >/dev/null
    fi
    # "shared" = NetworkManager runs a DHCP server (dnsmasq) on eth0 handing out 10.42.0.x,
    # and routes the Denon's traffic out through the Pi's Wi-Fi.
    LINK_ADDRS="10.42.0.1/24"
    if [[ -n "$SPOOKY_DENON_NET" ]]; then
      # Skip the extra address if the home Wi-Fi already uses that network
      if ip -4 route show dev wlan0 2>/dev/null | grep -q "^${SPOOKY_DENON_NET%.*}\."; then
        warn "Your Wi-Fi uses ${SPOOKY_DENON_NET%.*}.x, so I won't add $SPOOKY_DENON_NET on the Denon cable."
      else
        LINK_ADDRS="$LINK_ADDRS,$SPOOKY_DENON_NET"
      fi
    fi
    nmcli con modify denon-link ipv4.method shared ipv4.addresses "$LINK_ADDRS" >/dev/null 2>&1 || true
    nmcli con up denon-link >/dev/null 2>&1 || true   # fine if the cable isn't plugged in yet
  else
    warn "NetworkManager not found; skipping the Denon Ethernet link."
  fi
  # Only announce spooky.local on Wi-Fi, so phones never get the Denon cable's private address
  if [[ -f /etc/avahi/avahi-daemon.conf ]] && ip link show wlan0 >/dev/null 2>&1; then
    if grep -q "^#\?allow-interfaces=" /etc/avahi/avahi-daemon.conf; then
      sed -i "s/^#\?allow-interfaces=.*/allow-interfaces=wlan0/" /etc/avahi/avahi-daemon.conf
    else
      sed -i "/^\[server\]/a allow-interfaces=wlan0" /etc/avahi/avahi-daemon.conf
    fi
    systemctl restart avahi-daemon || true
  fi
fi

# ---- 8. Desktop audio servers grab the HDMI device; warn if one is running ------------
if pgrep -x pipewire >/dev/null || pgrep -x pulseaudio >/dev/null; then
  warn "This Pi is running the desktop audio system (PipeWire/PulseAudio)."
  warn "It can block 7.1 HDMI audio. Raspberry Pi OS Lite is recommended."
fi

# ---- 9. Run at boot -----------------------------------------------------------------------
say "Setting up the spooky service"
cat > /etc/systemd/system/spooky.service <<EOF
[Unit]
Description=Spooky Halloween Sounds
After=network-online.target sound.target
Wants=network-online.target

[Service]
User=$RUN_USER
WorkingDirectory=$APP_DIR
Environment=SPOOKY_PORT=$SPOOKY_PORT
Environment=PYTHONUNBUFFERED=1
ExecStart=/usr/bin/python3 $APP_DIR/app.py
AmbientCapabilities=CAP_NET_BIND_SERVICE
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable spooky.service
systemctl restart spooky.service

# ---- Done -----------------------------------------------------------------------------------
IP="$(hostname -I | awk '{print $1}')"
PORT_SUFFIX=""; [[ "$SPOOKY_PORT" != "80" ]] && PORT_SUFFIX=":$SPOOKY_PORT"
NAME="${SPOOKY_HOSTNAME:-$(hostname)}"
# ---- Denon link check ------------------------------------------------------------------------
DENON_IP=""
if [[ "$SPOOKY_DENON_LINK" == "1" ]] && ip link show eth0 >/dev/null 2>&1; then
  for _ in $(seq 1 10); do   # give the Denon a few seconds to ask for an address
    DENON_IP="$(awk '{print $3}' /var/lib/NetworkManager/dnsmasq-eth0.leases 2>/dev/null | tail -1)"
    [[ -n "$DENON_IP" ]] && break
    sleep 1
  done
fi

say "All set!"
echo "  Dashboard:  http://$NAME.local$PORT_SUFFIX   (or http://$IP$PORT_SUFFIX)"
echo "  Logs:       journalctl -u spooky -f"
if [[ "$SPOOKY_DENON_LINK" == "1" ]]; then
  if [[ -n "$DENON_IP" ]]; then
    echo "  Denon:      got address $DENON_IP from the Pi ✔"
  elif [[ "$(cat /sys/class/net/eth0/carrier 2>/dev/null)" != "1" ]]; then
    echo "  Denon:      no Ethernet cable detected yet. Plug it in; the Denon will get a 10.42.0.x address."
  else
    echo "  Denon:      cable connected but no address handed out yet. On the Denon: Setup → Network → DHCP: On."
  fi
fi
echo
echo "  Denon checklist: pick the Pi's HDMI input, set the speakers you use to Small/Large"
echo "  (not None), and look for MULTI CH IN on the display."
echo "  For dashboard power control: Denon Setup → Network → Network Standby: On."
sync   # make sure everything is written to the SD card before anyone pulls the plug
echo
echo "  Before unplugging the Pi, shut it down first:  sudo shutdown -h now"
if [[ $NEED_REBOOT -eq 1 ]]; then
  echo
  warn "Reboot once to finish setup:  sudo reboot"
fi
