#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$ROOT" || true

GW_BASE="${GW_BASE:-http://localhost:8200}"
ROLE="${ROLE:-paper}"
SCHEMA="mina_${ROLE}"

if command -v jq >/dev/null 2>&1; then
  JQ="jq"
else
  JQ="cat"
fi

echo "[kill_switch] enabling kill switch..."
curl -sS -X POST "$GW_BASE/api/unified/$ROLE/commands/kill_switch" \
  -H "Content-Type: application/json" \
  -d '{"enabled":true,"reason":"kill_switch_regression"}' | $JQ >/dev/null

before_count="$(docker compose exec -T postgres psql -U trading -d trading -c \
  "select count(*) from ${SCHEMA}.trades;" | awk 'NR==3{print $1}')"

echo "[kill_switch] trades before: $before_count"

echo "[kill_switch] publishing signal..."
PUB_JSON="$(curl -sS -X POST "$GW_BASE/api/unified/$ROLE/signals/publish" \
  -H "Content-Type: application/json" \
  -d '{"symbol":"BTCUSDT","side":"BUY","strategy":"kill_switch_regression","confidence":0.55}')"

SIG_ID=""
if [ "$JQ" = "jq" ]; then
  SIG_ID="$(echo "$PUB_JSON" | jq -r '.id // .signal_id // empty')"
fi

if [ -n "$SIG_ID" ]; then
  echo "[kill_switch] approving signal id=$SIG_ID (should be blocked for opens)..."
  curl -sS -X POST "$GW_BASE/api/unified/$ROLE/signals/$SIG_ID/approve" \
    -H "Content-Type: application/json" \
    -d '{"note":"kill_switch_regression approve"}' | $JQ >/dev/null
else
  echo "[kill_switch] no signal id returned; skipping approve"
fi

sleep 5

after_count="$(docker compose exec -T postgres psql -U trading -d trading -c \
  "select count(*) from ${SCHEMA}.trades;" | awk 'NR==3{print $1}')"

echo "[kill_switch] trades after: $after_count"

if [ "$after_count" != "$before_count" ]; then
  echo "[kill_switch] FAIL: trades count changed while kill_switch=1"
  exit 1
fi

echo "[kill_switch] close_all should still be allowed..."
curl -sS -X POST "$GW_BASE/api/unified/$ROLE/commands/close_all" \
  -H "Content-Type: application/json" \
  -d '{"reason":"kill_switch_regression"}' | $JQ >/dev/null

echo "[kill_switch] clearing kill switch..."
curl -sS -X POST "$GW_BASE/api/unified/$ROLE/commands/kill_switch" \
  -H "Content-Type: application/json" \
  -d '{"enabled":false,"reason":"kill_switch_regression"}' | $JQ >/dev/null

echo "[kill_switch] ✅ regression passed"
