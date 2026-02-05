#!/usr/bin/env bash
ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$ROOT" || true
set -euo pipefail

GW_BASE="${GW_BASE:-http://localhost:8200}"
ROLE="${ROLE:-paper}"

if command -v jq >/dev/null 2>&1; then
  JQ="jq"
else
  JQ="cat"
fi

show_json() {
  if [ "$JQ" = "jq" ]; then
    jq
  else
    cat
  fi
}

echo "== Health =="
curl -sS "$GW_BASE/health" | show_json

echo "== Unified Overview =="
curl -sS "$GW_BASE/api/unified/overview" | show_json

echo "== Signals List =="
SIG_JSON=$(curl -sS "$GW_BASE/api/unified/$ROLE/signals?limit=10")
echo "$SIG_JSON" | show_json

echo "== Publish Signals =="
P1=$(curl -sS -X POST "$GW_BASE/api/unified/$ROLE/signals/publish" \
  -H "Content-Type: application/json" \
  -d '{"symbol":"BTCUSDT","side":"BUY","strategy":"smoke_unified","confidence":0.55,"note":"smoke publish 1"}')
P2=$(curl -sS -X POST "$GW_BASE/api/unified/$ROLE/signals/publish" \
  -H "Content-Type: application/json" \
  -d '{"symbol":"ETHUSDT","side":"SELL","strategy":"smoke_unified","confidence":0.51,"note":"smoke publish 2"}')

echo "$P1" | show_json
echo "$P2" | show_json

if [ "$JQ" = "jq" ]; then
  ID1=$(echo "$P1" | jq -r '.id // ._dashboard_inbox_id // empty')
  ID2=$(echo "$P2" | jq -r '.id // ._dashboard_inbox_id // empty')

  if [ -n "$ID1" ]; then
    echo "== Approve Signal #$ID1 =="
    curl -sS -X POST "$GW_BASE/api/unified/$ROLE/signals/$ID1/approve" \
      -H "Content-Type: application/json" \
      -d '{"note":"smoke approve"}' | show_json
  else
    echo "No signal id from publish 1"
  fi

  if [ -n "$ID2" ]; then
    echo "== Reject Signal #$ID2 =="
    curl -sS -X POST "$GW_BASE/api/unified/$ROLE/signals/$ID2/reject" \
      -H "Content-Type: application/json" \
      -d '{"reason":"smoke_reject","note":"smoke reject"}' | show_json
  else
    echo "No signal id from publish 2"
  fi
else
  echo "jq not found; skipping approve/reject"
fi

echo "== Trades (open) =="
OPEN_JSON=$(curl -sS "$GW_BASE/api/unified/$ROLE/trades?status=OPEN&limit=5")
echo "$OPEN_JSON" | show_json

if [ "$JQ" = "jq" ]; then
  OPEN_COUNT=$(echo "$OPEN_JSON" | jq -r '.count // (.items|length) // 0')
  if [ "${OPEN_COUNT:-0}" -eq 0 ]; then
    echo "No OPEN trades yet. Diagnostics:"
    echo "== Commands History (latest) =="
    curl -sS "$GW_BASE/api/unified/$ROLE/commands/history?limit=5" | show_json
    echo "== ExecMon / System Health =="
    curl -sS "$GW_BASE/api/mina/$ROLE/system_health" | show_json
  fi
fi

echo "== Equity History =="
curl -sS "$GW_BASE/api/unified/$ROLE/equity_history?limit=5" | show_json

echo "== Perf Metrics =="
curl -sS "$GW_BASE/api/unified/$ROLE/perf_metrics?limit=5" | show_json

echo "== Queue Close All =="
curl -sS -X POST "$GW_BASE/api/unified/$ROLE/commands/close_all" \
  -H "Content-Type: application/json" \
  -d '{"reason":"smoke_unified_v2"}' | show_json

echo "== Commands History =="
curl -sS "$GW_BASE/api/unified/$ROLE/commands/history?limit=5" | show_json

echo "== Events Last ID =="
curl -sS "$GW_BASE/api/unified/events/last" | show_json

echo "== Sync Run + Refresh =="
curl -sS -X POST "$GW_BASE/api/unified/sync/run?role=$ROLE&limit=500" | show_json

echo "== Sync Cleanup =="
curl -sS -X POST "$GW_BASE/api/unified/sync/cleanup?role=$ROLE" | show_json

echo "== Sync Reset =="
curl -sS -X POST "$GW_BASE/api/unified/sync/reset?role=$ROLE" | show_json

echo "✅ smoke_unified_v2 done"
