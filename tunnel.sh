#!/usr/bin/env bash
# One command: expose localhost:8000 through a cloudflared quick tunnel, point
# the ElevenLabs tools at the new URL, and mount the widget on the console.
# Re-run it whenever the tunnel restarts (the URL changes every time).
#
#   ./tunnel.sh              # normal
#   PORT=8010 ./tunnel.sh    # another port
#   pkill cloudflared        # stop the tunnel
set -euo pipefail
cd "$(dirname "$0")"
PORT="${PORT:-8000}"
LOG="${TMPDIR:-/tmp}/clement-cloudflared.log"
PY="${PY:-.venv/bin/python}"

if ! curl -sf "http://localhost:$PORT/api/health" >/dev/null; then
  echo "nothing answering on :$PORT. Start the server first:"
  echo "  .venv/bin/uvicorn server:app --reload --port $PORT"
  exit 1
fi

pkill -f "cloudflared tunnel --url http://localhost:$PORT" 2>/dev/null || true
: > "$LOG"
nohup cloudflared tunnel --url "http://localhost:$PORT" >"$LOG" 2>&1 &
echo "cloudflared started (log: $LOG)"

URL=""
for _ in $(seq 1 40); do
  URL=$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOG" | head -1 || true)
  [ -n "$URL" ] && break
  sleep 1
done
if [ -z "$URL" ]; then
  echo "no tunnel URL after 40s. Last lines of $LOG:"; tail -5 "$LOG"; exit 1
fi
echo "PUBLIC_URL=$URL"

touch .env
if grep -q '^PUBLIC_URL=' .env; then
  sed -i '' "s#^PUBLIC_URL=.*#PUBLIC_URL=$URL#" .env
else
  echo "PUBLIC_URL=$URL" >> .env
fi

for _ in $(seq 1 15); do
  if curl -sf "$URL/api/health" >/dev/null; then echo "tunnel reachable: $URL/api/health"; break; fi
  sleep 1
done

PUBLIC_URL="$URL" "$PY" setup_agent.py "$@"
