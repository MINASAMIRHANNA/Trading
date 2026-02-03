#!/usr/bin/env bash
set -euo pipefail

# Smoke test for the unified shared event stream (Postgres shared_events).
#
# What this validates
# - Gateway can read from shared_events via /api/events
# - Mina dashboards can emit a HealthEvent which (with TRADING_PG_MIRROR=1)
#   is mirrored into public.shared_events
#
# Usage:
#   bash scripts/smoke_events.sh [paper|live|pump]

ROLE="${1:-paper}"
BASE="${GATEWAY_URL:-http://localhost:8200}"

case "$ROLE" in
  paper) CNAME="mina_dashboard_paper";;
  live)  CNAME="mina_dashboard_live";;
  pump)  CNAME="mina_dashboard_pump";;
  *)
    echo "Usage: $0 [paper|live|pump]" >&2
    exit 2
    ;;
esac

curlx() {
  if [[ -n "${GATEWAY_API_KEY:-}" ]]; then
    curl -s -H "X-API-Key: ${GATEWAY_API_KEY}" "$@"
  else
    curl -s "$@"
  fi
}

echo "== Gateway health =="
curl -s "${BASE}/health" || true
echo

echo "== Emit HealthEvent via ${CNAME} (should mirror into shared_events) =="
docker compose exec -T "${CNAME}" python - <<'PY'
import os, uuid
from mina_core.db.database import DatabaseManager

db = DatabaseManager()
db.log_health_event(
    {
        "service_name": os.getenv("BOT_ID") or ("dashboard-" + (os.getenv("BOT_ROLE") or "unknown")),
        "status": "ok",
        "note": "smoke_events.sh",
        "trace_id": uuid.uuid4().hex,
    },
    source="smoke",
)
print("ok")
PY
echo

echo "== Fetch recent events (role=${ROLE}, event_type=HealthEvent) =="
curlx "${BASE}/api/events?limit=20&role=${ROLE}&event_type=HealthEvent" | head -c 1200
echo

echo "== OK =="
