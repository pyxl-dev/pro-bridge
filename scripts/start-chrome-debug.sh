#!/usr/bin/env bash
# Launch the dedicated Chromium-family browser used by ChatGPT Web Bridge.
# macOS / Linux. Windows users: use start-chrome-debug.ps1.
#
# Default: background headed browser. On macOS the real browser is launched
# hidden, so ChatGPT sees a normal browser while it does not steal focus.
# Login:   ./scripts/start-chrome-debug.sh --login
# Stop:    ./scripts/start-chrome-debug.sh --stop
# Headless is retained only for diagnostics; ChatGPT may serve a verification
# page to HeadlessChrome instead of hydrating the application.
#
# All modes use the SAME persistent browser profile.
set -euo pipefail

MODE="background"
case "${1:-}" in
  ""|--background) MODE="background" ;;
  --login) MODE="login" ;;
  --headless) MODE="headless" ;;
  --stop) MODE="stop" ;;
  -h|--help)
    cat <<'EOF'
Usage: ./scripts/start-chrome-debug.sh [--background|--login|--headless|--stop]

  --background  Start a normal browser hidden/in-background (default).
  --login       Start the same persistent profile visibly so you can log in.
  --headless    Start Chromium headless (diagnostic only; ChatGPT may block it).
  --stop        Stop the browser instance for this dedicated profile.
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

profile_pids() {
  pgrep -f -- "--user-data-dir=${PROFILE}" 2>/dev/null || true
}

if [ "$MODE" = "stop" ]; then
  pids="$(profile_pids)"
  if [ -n "$pids" ]; then
    echo "Stopping bridge browser..."
    # shellcheck disable=SC2086
    kill $pids 2>/dev/null || true
    for _ in $(seq 1 30); do
      sleep 0.1
      [ -z "$(profile_pids)" ] && break
    done
    remaining="$(profile_pids)"
    if [ -n "$remaining" ]; then
      echo "Bridge browser did not stop cleanly; forcing it." >&2
      # shellcheck disable=SC2086
      kill -9 $remaining 2>/dev/null || true
    fi
    rm -f "$PIDFILE"
  elif cdp_alive; then
    echo "A browser is listening on CDP port $PORT, but it does not match the bridge profile." >&2
    echo "Close that browser manually before switching modes." >&2
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
  --disable-background-timer-throttling
  --disable-backgrounding-occluded-windows
  --disable-renderer-backgrounding
)

if [ "$MODE" = "headless" ]; then
  args+=(--headless=new --window-size=1440,1000)
elif [ "$MODE" = "background" ] && [ "$(uname -s)" != "Darwin" ]; then
  # Best effort on Linux. macOS uses `open -gj` below, which is more reliable
  # at preventing focus stealing while keeping a genuine headed browser.
  args+=(--start-minimized)
fi

echo "Starting bridge browser: $bin"
echo "  mode: $MODE   CDP port: $PORT"
echo "  profile: $PROFILE"

if [ "$(uname -s)" = "Darwin" ] && [ "$MODE" = "background" ]; then
  # Extract the .app bundle from a standard macOS Chromium executable path.
  app_bundle="${bin%%/Contents/MacOS/*}"
  if [[ "$app_bundle" == *.app ]] && [ -d "$app_bundle" ]; then
    echo "  macOS: launching genuine browser hidden and without focus"
    open -gj -n "$app_bundle" --args "${args[@]}" "https://chatgpt.com/"

    # `open` returns immediately. Wait for CDP so callers can use the bridge as
    # soon as this script exits.
    for _ in $(seq 1 100); do
      if cdp_alive; then
        echo "Bridge browser ready on CDP port $PORT."
        exit 0
      fi
      sleep 0.1
    done
    echo "Browser launched but CDP did not become ready on port $PORT." >&2
    exit 1
  fi

  echo "Could not resolve a macOS .app bundle from '$bin'; falling back to direct launch." >&2
fi

# Login/headless/Linux fallback: run the browser in the foreground process.
# exec keeps signal handling simple. The dedicated user-data-dir still isolates
# this browser from the user's everyday profile.
echo "$$" > "$PIDFILE"
exec "$bin" "${args[@]}" "https://chatgpt.com/"
