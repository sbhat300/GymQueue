#!/usr/bin/env bash
# Turn this laptop into a small Wi-Fi hotspot for the ESP32 camera, while the laptop stays on its
# normal Wi-Fi (home, or RU Wireless Secure) for internet.
#
#   ./firmware/laptop_hotspot.sh on       start "GymQueueCam" (asks for your password, for sudo)
#   ./firmware/laptop_hotspot.sh off      stop it and put your normal Wi-Fi back how it was
#   ./firmware/laptop_hotspot.sh status   is it on, and is the camera connected?
#
# Needs hostapd once:  sudo apt install hostapd
#
# The hotspot's name and password come from firmware/esp32cam/secrets.h (WIFI_SSID / WIFI_PASSWORD),
# so the camera and the laptop always agree.
#
# How: a second Wi-Fi interface in access-point mode, run by hostapd (NetworkManager can't do this
# on Intel cards: it tries to make the second interface a normal connection first, which the card
# refuses), and dnsmasq to hand the camera an address (10.42.0.x).
#
# Why the 2.4 GHz switch: the ESP32 only does 2.4 GHz, and the Wi-Fi card can only run the hotspot
# on the channel it's already connected on. If your normal Wi-Fi is on 5 GHz, "on" moves it to
# 2.4 GHz (a bit slower internet) and "off" moves it back.
set -euo pipefail
cd "$(dirname "$0")"

SECRETS=esp32cam/secrets.h
AP_IF=gqap0
AP_IP=10.42.0.1
RUN="${XDG_RUNTIME_DIR:-/tmp}/gymqueue-hotspot"
STATE="$RUN/band.state"
OLD_NM_PROFILE=GymQueueCam-hotspot   # from an earlier version of this script

die() { echo "error: $*" >&2; exit 1; }
need() { command -v "$1" >/dev/null || die "$1 is not installed${2:+ ($2)}"; }
need nmcli; need iw; need ip

secret() { sed -n "s/^#define $1  *\"\(.*\)\".*/\1/p" "$SECRETS" | head -1; }
[ -f "$SECRETS" ] || die "$SECRETS not found"
SSID=$(secret WIFI_SSID)
PASS=$(secret WIFI_PASSWORD)
[ -n "$SSID" ] && [ ${#PASS} -ge 8 ] || die "WIFI_SSID / WIFI_PASSWORD (8+ chars) missing in $SECRETS"

wifi_dev() { nmcli -t -f DEVICE,TYPE device | awk -F: '$2=="wifi" && $1 !~ /^p2p/ && $1 != "'"$AP_IF"'" {print $1; exit}'; }
client_con() { nmcli -t -f NAME,DEVICE connection show --active | awk -F: -v d="$1" '$2==d {print $1; exit}'; }
freq_of() { iw dev "$1" link 2>/dev/null | awk '/freq:/ {print int($2); exit}'; }
chan_of_freq() { local f=$1; if [ "$f" = 2484 ]; then echo 14; else echo $(( (f - 2407) / 5 )); fi; }
running() { [ -f "$RUN/$1.pid" ] && [ -d "/proc/$(cat "$RUN/$1.pid")" ]; }

cmd_on() {
  need hostapd "sudo apt install hostapd"
  need dnsmasq "sudo apt install dnsmasq-base"
  local dev con freq chan mac
  mkdir -p "$RUN"
  dev=$(wifi_dev); [ -n "$dev" ] || die "no Wi-Fi card found"
  con=$(client_con "$dev")

  chan=6  # not on any Wi-Fi: any 2.4 GHz channel works
  if [ -n "$con" ]; then
    freq=$(freq_of "$dev")
    if [ -n "$freq" ] && [ "$freq" -ge 5000 ]; then
      echo "Your Wi-Fi ($con) is on 5 GHz - moving it to 2.4 GHz so the camera can join the hotspot..."
      [ -f "$STATE" ] || printf '%s\n%s\n' "$con" "$(nmcli -g 802-11-wireless.band connection show "$con")" > "$STATE"
      nmcli connection modify "$con" 802-11-wireless.band bg
      nmcli connection up "$con" >/dev/null || die "couldn't reconnect $con on 2.4 GHz (run '$0 off' to undo)"
      sleep 2
      freq=$(freq_of "$dev")
      [ -n "$freq" ] && [ "$freq" -lt 5000 ] || die "$con has no 2.4 GHz signal here (run '$0 off' to undo)"
    fi
    [ -n "$freq" ] && chan=$(chan_of_freq "$freq")
  fi

  # the earlier NetworkManager-based attempt left a profile behind; NetworkManager must leave gqap0 alone
  nmcli connection delete "$OLD_NM_PROFILE" >/dev/null 2>&1 || true
  if ! iw dev "$AP_IF" info >/dev/null 2>&1; then
    echo "Adding the hotspot's network interface (needs sudo)..."
    sudo iw dev "$dev" interface add "$AP_IF" type __ap
  fi
  nmcli device set "$AP_IF" managed no 2>/dev/null || true
  # its own MAC address (the main card's, with the "locally administered" bit set)
  mac=$(cat "/sys/class/net/$dev/address")
  mac=$(printf '%02x%s' $(( 0x${mac:0:2} | 0x02 )) "${mac:2}")
  sudo ip link set "$AP_IF" down
  sudo iw dev "$AP_IF" set type __ap
  sudo ip link set "$AP_IF" address "$mac"
  sudo ip addr flush dev "$AP_IF"
  sudo ip addr add "$AP_IP/24" dev "$AP_IF"

  cat > "$RUN/hostapd.conf" <<EOF
interface=$AP_IF
driver=nl80211
ssid=$SSID
hw_mode=g
channel=$chan
ieee80211n=1
wmm_enabled=1
auth_algs=1
wpa=2
wpa_key_mgmt=WPA-PSK
rsn_pairwise=CCMP
wpa_passphrase=$PASS
EOF
  chmod 600 "$RUN/hostapd.conf"

  running hostapd && sudo kill "$(cat "$RUN/hostapd.pid")" && sleep 1
  sudo hostapd -B -P "$RUN/hostapd.pid" -f "$RUN/hostapd.log" "$RUN/hostapd.conf" >/dev/null \
    || die "hostapd didn't start - see $RUN/hostapd.log (run '$0 off' to undo)"

  running dnsmasq && sudo kill "$(cat "$RUN/dnsmasq.pid")" && sleep 1
  sudo dnsmasq --interface="$AP_IF" --bind-interfaces --except-interface=lo --port=0 \
    --dhcp-range=10.42.0.10,10.42.0.60,12h --dhcp-option=3 --dhcp-option=6 \
    --dhcp-leasefile="$RUN/dnsmasq.leases" --pid-file="$RUN/dnsmasq.pid" \
    || die "dnsmasq didn't start (run '$0 off' to undo)"

  sleep 2
  if ! running hostapd; then
    tail -5 "$RUN/hostapd.log" >&2 || true
    die "hostapd stopped right after starting (run '$0 off' to undo)"
  fi
  echo "Hotspot \"$SSID\" is on (2.4 GHz, channel $chan, laptop at $AP_IP). The camera joins within ~30 s."
  echo "Check with: $0 status"
}

cmd_off() {
  local con band
  for p in dnsmasq hostapd; do
    if running "$p"; then sudo kill "$(cat "$RUN/$p.pid")"; fi
    rm -f "$RUN/$p.pid"
  done
  nmcli connection delete "$OLD_NM_PROFILE" >/dev/null 2>&1 || true
  if iw dev "$AP_IF" info >/dev/null 2>&1; then
    echo "Removing the hotspot's network interface (needs sudo)..."
    sudo iw dev "$AP_IF" del
  fi
  if [ -f "$STATE" ]; then
    con=$(sed -n 1p "$STATE"); band=$(sed -n 2p "$STATE")
    echo "Putting $con back on its normal band..."
    nmcli connection modify "$con" 802-11-wireless.band "$band"
    nmcli connection up "$con" >/dev/null || echo "warning: reconnect to $con yourself"
    rm -f "$STATE"
  fi
  echo "Hotspot off."
}

cmd_status() {
  if running hostapd; then
    local n
    n=$(iw dev "$AP_IF" station dump 2>/dev/null | grep -c '^Station' || true)
    echo "Hotspot \"$SSID\" is ON, $n device(s) connected."
    [ -r "$RUN/dnsmasq.leases" ] && awk '{print "  " $3 "  " $4}' "$RUN/dnsmasq.leases"
  else
    echo "Hotspot is off."
  fi
}

case "${1:-}" in
  on) cmd_on ;;
  off) cmd_off ;;
  status) cmd_status ;;
  *) echo "usage: $0 {on|off|status}"; exit 1 ;;
esac
