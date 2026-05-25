#!/usr/bin/env bash
#
# expose-cabtest.sh — open a public HTTPS tunnel to the local bench so a phone
# (or any external device) can hit cabtest.local for driver GPS testing.
#
# Why: driver_gps_pinger.js calls navigator.geolocation.watchPosition, which
# modern browsers refuse on insecure origins (anything other than localhost).
# ngrok terminates TLS for free and rewrites the Host header so Frappe routes
# the tunnelled request to the right site.
#
# Requires: ngrok (≥3.x) on PATH, already authenticated via
#   `ngrok config add-authtoken <YOUR_TOKEN>`
#
# Usage:
#   ./apps/transport_management/scripts/expose-cabtest.sh
#   SITE=othersite.local PORT=8001 ./apps/transport_management/scripts/expose-cabtest.sh

set -euo pipefail

SITE="${SITE:-cabtest.local}"
PORT="${PORT:-8002}"
LOG=/tmp/ngrok-${SITE}.log

# ── 1. preflight ──────────────────────────────────────────────────────────────
if ! command -v ngrok >/dev/null 2>&1; then
	echo "ERROR: ngrok is not on PATH." >&2
	echo "Install from https://ngrok.com/download then run:" >&2
	echo "  ngrok config add-authtoken <YOUR_TOKEN>" >&2
	exit 1
fi

# Confirm bench is actually serving the site locally.
status=$(curl -s -o /dev/null -w "%{http_code}" \
	-H "Host: $SITE" "http://127.0.0.1:${PORT}/" || echo "000")
case "$status" in
	200|301|302|403)
		: # bench is responding
		;;
	*)
		echo "WARNING: http://127.0.0.1:${PORT}/ returned HTTP $status for Host: $SITE."
		echo "         Is 'bench start' running in another terminal?"
		echo "         Continuing — the tunnel will start, but requests may 404."
		;;
esac

echo "Starting ngrok tunnel for http://127.0.0.1:${PORT} (rewriting Host -> $SITE)..."
echo "(log: $LOG)"
echo

# ── 2. start ngrok in background; tear it down on exit ─────────────────────────
ngrok http --host-header="$SITE" --log=stdout "$PORT" >"$LOG" 2>&1 &
NGROK_PID=$!
trap 'kill $NGROK_PID 2>/dev/null || true' EXIT INT TERM

# ── 3. poll the ngrok local admin API for the assigned https URL ───────────────
URL=""
for _ in $(seq 1 30); do
	URL=$(curl -s http://127.0.0.1:4040/api/tunnels 2>/dev/null \
		| python3 -c 'import json,sys
try:
    d=json.load(sys.stdin)
    print(next((t["public_url"] for t in d.get("tunnels", []) if t.get("proto")=="https"), ""))
except Exception:
    print("")' 2>/dev/null || true)
	[ -n "$URL" ] && break
	sleep 0.5
done

if [ -z "$URL" ]; then
	echo "ERROR: failed to detect ngrok URL after 15s. Tail of $LOG:" >&2
	tail -20 "$LOG" >&2
	exit 1
fi

cat <<EOF

================================================================================
  Tunnel up:   $URL
  Forwarding:  http://127.0.0.1:${PORT}   (Host header rewritten -> $SITE)
================================================================================

On the phone:
  1. Open  $URL/app/cab-request/<request-name>
  2. Log in as the driver user
  3. Allow the geolocation prompt
  4. Look for the green "🟢 Live · ping @ ..." panel at the top of the form

Verify pings server-side (run on the bench host):
  bench --site $SITE mariadb -e \\
    "SELECT vehicle, COUNT(*) AS pings, MAX(recorded_at) AS latest
     FROM \\\`tabVehicle GPS Log\\\`
     WHERE recorded_at > DATE_SUB(NOW(), INTERVAL 2 MINUTE)
     GROUP BY vehicle;"

ngrok admin UI:  http://127.0.0.1:4040
Press Ctrl-C to stop the tunnel.
EOF

# Block on the ngrok process so Ctrl-C tears down the tunnel cleanly.
wait $NGROK_PID
