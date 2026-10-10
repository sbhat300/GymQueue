#!/usr/bin/env bash
# Start/stop the laptop-webcam stand-in for ESP32 cameras (scripts/esp32_sim.py).
#
# Your laptop has one usable camera, so this and a browser face scan can't both
# hold it at once. Run `stop` before enrolling/re-enrolling a face in the browser,
# then `start` again to resume testing live machine recognition.
#
# Usage: ./scripts/fake_camera.sh {start|stop|status}
#        PORT=8081 SOURCE=webcam:0 ./scripts/fake_camera.sh start
set -euo pipefail
cd "$(dirname "$0")/.."

PIDFILE=".esp32_sim.pid"
LOGFILE=".esp32_sim.log"
PORT="${PORT:-8081}"
SOURCE="${SOURCE:-webcam:0}"

running() {
  [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null
}

status() {
  if running; then
    echo "running (pid $(cat "$PIDFILE"), port $PORT)"
  else
    echo "stopped"
  fi
}

start() {
  if running; then
    echo "already running (pid $(cat "$PIDFILE"))"
    exit 0
  fi
  PYTHONPATH= .venv/bin/python scripts/esp32_sim.py --source "$SOURCE" --port "$PORT" >"$LOGFILE" 2>&1 &
  disown
  echo $! >"$PIDFILE"
  echo "started (pid $(cat "$PIDFILE")), logging to $LOGFILE"
}

stop() {
  if running; then
    kill "$(cat "$PIDFILE")"
    echo "stopped (was pid $(cat "$PIDFILE"))"
  else
    echo "not running"
  fi
  rm -f "$PIDFILE"
}

case "${1:-}" in
  start) start ;;
  stop) stop ;;
  status) status ;;
  *) echo "usage: $0 {start|stop|status}  (env overrides: PORT, SOURCE)"; exit 1 ;;
esac
