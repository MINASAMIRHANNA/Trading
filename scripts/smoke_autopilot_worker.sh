#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$ROOT" || true

GW_BASE="${GW_BASE:-http://localhost:8200}"

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

echo "== Autopilot GET =="
curl -sS "$GW_BASE/api/autopilot" | show_json

echo "== Set Global SHADOW =="
curl -sS -X POST "$GW_BASE/api/unified/autopilot" \
  -H "Content-Type: application/json" \
  -d '{"global_mode":"SHADOW"}' | show_json

sleep 2

echo "== Audit Log (check heartbeat) =="
AUDIT_JSON="$(curl -sS "$GW_BASE/api/audit?limit=50")"
echo "$AUDIT_JSON" | show_json

if [ "$JQ" = "jq" ]; then
  echo "$AUDIT_JSON" | jq -r '.items[].action' | grep -q "AUTOPILOT_WORKER_HEARTBEAT" || {
    echo "FAIL: missing AUTOPILOT_WORKER_HEARTBEAT in audit"
    exit 1
  }
else
  echo "$AUDIT_JSON" | grep -q "AUTOPILOT_WORKER_HEARTBEAT" || {
    echo "FAIL: missing AUTOPILOT_WORKER_HEARTBEAT in audit"
    exit 1
  }
fi

echo "== Optional shadow no-op check =="
PENDING_BEFORE="$(curl -sS "$GW_BASE/api/unified/paper/signals?limit=50")"
sleep 1
PENDING_AFTER="$(curl -sS "$GW_BASE/api/unified/paper/signals?limit=50")"

if [ "$JQ" = "jq" ]; then
  ids_before=$(echo "$PENDING_BEFORE" | jq -r '.[]? | select(.status=="PENDING") | .id' || true)
  if [ -n "$ids_before" ]; then
    while read -r sid; do
      [ -z "$sid" ] && continue
      st=$(echo "$PENDING_AFTER" | jq -r --arg id "$sid" '.[]? | select((.id|tostring)==$id) | .status' || true)
      if [ -n "$st" ] && [ "$st" != "PENDING" ]; then
        echo "FAIL: signal $sid status changed in SHADOW"
        exit 1
      fi
    done <<< "$ids_before"
  fi
fi

echo "== Set Global OFF =="
curl -sS -X POST "$GW_BASE/api/unified/autopilot" \
  -H "Content-Type: application/json" \
  -d '{"global_mode":"OFF"}' | show_json

echo "✅ smoke_autopilot_worker done"
