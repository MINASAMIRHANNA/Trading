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

if [ "$JQ" = "jq" ]; then
  APPROVE_ID=$(echo "$SIG_JSON" | jq -r '((if type=="array" then . else (.items // []) end)[] | select(.status=="RECEIVED" or .status=="PENDING" or .status=="PENDING_APPROVAL") | .id)' | head -n1)
  REJECT_ID=$(echo "$SIG_JSON" | jq -r '((if type=="array" then . else (.items // []) end)[] | select(.status=="RECEIVED" or .status=="PENDING" or .status=="PENDING_APPROVAL") | .id)' | tail -n1)

  if [ -n "$APPROVE_ID" ] && [ "$APPROVE_ID" != "null" ]; then
    echo "== Approve Signal #$APPROVE_ID =="
    curl -sS -X POST "$GW_BASE/api/unified/$ROLE/signals/$APPROVE_ID/approve" \
      -H "Content-Type: application/json" \
      -d '{"note":"smoke approve"}' | show_json
  else
    echo "No pending signals to approve (skip)"
  fi

  if [ -n "$REJECT_ID" ] && [ "$REJECT_ID" != "null" ] && [ "$REJECT_ID" != "$APPROVE_ID" ]; then
    echo "== Reject Signal #$REJECT_ID =="
    curl -sS -X POST "$GW_BASE/api/unified/$ROLE/signals/$REJECT_ID/reject" \
      -H "Content-Type: application/json" \
      -d '{"reason":"smoke_reject","note":"smoke reject"}' | show_json
  else
    echo "No pending signals to reject (skip)"
  fi
else
  echo "jq not found; skipping approve/reject smoke"
fi

echo "== Trades (open) =="
TRADES_JSON=$(curl -sS "$GW_BASE/api/unified/$ROLE/trades?status=open&limit=5")
echo "$TRADES_JSON" | show_json

if [ "$JQ" = "jq" ]; then
  TRADE_ID=$(echo "$TRADES_JSON" | jq -r '.items[0].id // .items[0].trade_id // empty')
  if [ -n "$TRADE_ID" ]; then
    echo "== Trade Detail #$TRADE_ID =="
    curl -sS "$GW_BASE/api/unified/$ROLE/trades/$TRADE_ID" | show_json
  else
    echo "No trade id found for details (skip)"
  fi
fi

echo "== Queue Close All =="
curl -sS -X POST "$GW_BASE/api/unified/$ROLE/commands/close_all" \
  -H "Content-Type: application/json" \
  -d '{"reason":"smoke_unified"}' | show_json

echo "== Kill Switch ON =="
curl -sS -X POST "$GW_BASE/api/unified/$ROLE/commands/kill_switch" \
  -H "Content-Type: application/json" \
  -d '{"enabled":true,"reason":"smoke_unified"}' | show_json

echo "== Audit Log =="
curl -sS "$GW_BASE/api/audit?limit=5" | show_json

echo "== Events Stream (connection check) =="
python - <<PY
import sys, urllib.request
url = "${GW_BASE}/api/unified/events/stream?role=${ROLE}&since_id=0&interval_ms=500"
try:
    with urllib.request.urlopen(url, timeout=2) as r:
        lines = []
        for _ in range(20):
            try:
                line = r.readline()
            except Exception:
                break
            if not line:
                break
            lines.append(line.decode(errors="ignore").rstrip())
        for ln in lines:
            print(ln)
except Exception as e:
    # non-fatal; SSE may time out quickly
    print(f"(sse check skipped: {e})")
PY

echo "== Sync Run + Refresh =="
curl -sS -X POST "$GW_BASE/api/unified/sync/run?role=$ROLE&limit=500" | show_json

echo "== Sync Status =="
curl -sS "$GW_BASE/api/unified/sync/status?role=$ROLE" | show_json

echo "✅ smoke_unified done"
