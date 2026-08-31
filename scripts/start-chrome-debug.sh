#!/usr/bin/env bash
# Launch the dedicated Chromium-family browser used by ChatGPT Web Bridge.
# macOS / Linux. Windows users: use start-chrome-debug.ps1.
#
# Default: headless (no window/focus stealing).
# Login:   ./scripts/start-chrome-debug.sh --login
# Stop:    ./scripts/start-chrome-debug.sh --stop
#
# Headless and login mode use the SAME persistent browser profile, so logging in
# once in visible mode also authenticates later headless runs.
#
# Override the browser with:
#   BROWSER="/Applications/Brave Browser.app/Contents/MacOS/Brave Browser" \
#     ./scripts/start-chrome-debug.sh
set -euo pipefail

MODE="headless"
case "${1:-}" in
  ""|--headless) MODE="headless" ;;
  --login) MODE="login" ;;
  --stop) MODE="stop" ;;
  -h|--help)
    cat <<'EOF'
Usage: ./scripts/start-chrome-debug.sh [--headless|--login|--stop]

  --headless  Start the dedicated browser without a visible window (default).
  --login     Start the same persistent profile visibly so you can log in.
  --stop      Stop the browser instance started for this dedicated profile.
EOF
    exit 0
    ;;
  *)
    echo "Unknown option: $1" >&2
    echo "Run $0 --help for usage." >&2
    exit 2
    ;;
esac

PORT="${CHATGPT_BRIDGE_CDP_PORT:-${PRO_BRIDGE_CDP_PORT:-9222}}"
PROFILE="${CHATGPT_BRIDGE_PROFILE_DIR:-${PRO_BRIDGE_PROFILE_DIR:-$HOME/.pro-bridge-chrome}}"
PIDFILE="$PROFILE/.bridge-browser.pid"
mkdir -p "$PROFILE"

cdp_alive() {
  curl -s -o /dev/null -m 1 "http://127.0.0.1:${PORT}/json/version"
}

if [ "$MODE" = "stop" ]; then
  if [ -f "$PIDFILE" ]; then
    pid="$(cat "$PIDFILE" 2>/dev/null || true)"
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      echo "Stopping bridge browser (PID $pid)..."
      kill "$pid"
      for _ in $(seq 1 30); do
        kill -0 "$pid" 2>/dev/null || break
        sleep 0.1
      done
      if kill -0 "$pid" 2>/dev/null; then
        echo "Bridge browser did not stop cleanly; forcing it." >&2
        kill -9 "$pid" 2>/dev/null || true
      fi
    else
      echo "Recorded bridge browser process is no longer running."
    fi
    rm -f "$PIDFILE"
  elif cdp_alive; then
    echo "A browser is listening on CDP port $PORT, but no bridge PID is recorded." >&2
    echo "Close that dedicated browser manually before switching modes." >&2
    exit 1
  else
    echo "Bridge browser is not running."
  fi
  exit 0
fi

if cdp_alive; then
  echo "Bridge browser already running on CDP port $PORT."
  if [ "$MODE" = "login" ]; then
    echo "To switch to visible login mode:"
    echo "  $0 --stop"
    echo "  $0 --login"
  fi
  exit 0
fi

# Candidate executables, in priority order. BROWSER env (if set) goes first.
candidates=()
[ -n "${BROWSER:-}" ] && candidates+=("$BROWSER")
candidates+=(
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
  "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"
  "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"
  "/Applications/Chromium.app/Contents/MacOS/Chromium"
  google-chrome google-chrome-stable chromium chromium-browser
  brave-browser microsoft-edge microsoft-edge-stable
)

bin=""
for c in "${candidates[@]}"; do
  if [ -x "$c" ]; then bin="$c"; break; fi
  if command -v "$c" >/dev/null 2>&1; then bin="$(command -v "$c")"; break; fi
done

if [ -z "$bin" ]; then
  echo "No Chromium-family browser found. Set BROWSER=/path/to/browser and retry." >&2
  exit 127
fi

args=(
  --remote-debugging-port="$PORT"
  --remote-debugging-address=127.0.0.1
  --user-data-dir="$PROFILE"
  --no-first-run
  --no-default-browser-check
)

if [ "$MODE" = "headless" ]; then
  args+=(--headless=new --window-size=1440,1000)
fi

echo "Starting bridge browser: $bin"
echo "  mode: $MODE   CDP port: $PORT"
echo "  profile: $PROFILE"

# exec keeps the shell PID as the browser PID, which makes --stop reliable.
echo "$$" > "$PIDFILE"
exec "$bin" "${args[@]}" "https://chatgpt.com/"
