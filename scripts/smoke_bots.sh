#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$ROOT" || true

echo "[smoke_bots] bringing up bots stack..."
docker compose -f docker-compose.yml -f docker-compose.bots.yml up -d --build

echo "[smoke_bots] checking unified overview online flags..."

attempts=6
sleep_sec=10
for i in $(seq 1 $attempts); do
  OVERVIEW="$(curl -s http://localhost:8200/api/unified/overview || true)"

  RESULT="$(OVERVIEW_JSON="$OVERVIEW" python - <<'PY' || true
import json, os, sys
raw = os.environ.get("OVERVIEW_JSON", "")
if not raw:
    print("ERROR: empty response")
    sys.exit(2)
try:
    data = json.loads(raw)
except Exception as e:
    print("ERROR: invalid JSON:", e)
    sys.exit(2)

dash = data.get("dashboards", {})
def get_online(role):
    try:
        return bool(dash.get(role, {}).get("system_health", {}).get("online"))
    except Exception:
        return False

paper = get_online("paper")
live = get_online("live")
pump = get_online("pump")
print(f"paper={paper} live={live} pump={pump}")
sys.exit(0 if (paper and live) else 1)
PY
  )"
  if echo "$RESULT" | rg -q "paper=True live=True"; then
    echo "[smoke_bots] online: $RESULT"
    exit 0
  fi

  echo "[smoke_bots] attempt $i/$attempts not ready: $RESULT"
  sleep "$sleep_sec"
done

echo "[smoke_bots] FAIL: paper/live must be online=true"
exit 1
