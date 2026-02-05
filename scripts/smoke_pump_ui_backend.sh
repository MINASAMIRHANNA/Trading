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

echo "== Pump Status =="
curl -sS "$GW_BASE/api/mina/pump/pump/status" | show_json

echo "== Pump Candidates (limit=5) =="
CAND_JSON="$(curl -sS "$GW_BASE/api/mina/pump/pump/candidates?limit=5")"
echo "$CAND_JSON" | show_json

CID=""
if [ "$JQ" = "jq" ]; then
  CID=$(echo "$CAND_JSON" | jq -r '.items[0].id // empty')
fi

if [ -n "$CID" ]; then
  echo "== Pump Reject Candidate #$CID =="
  RESP="$(curl -sS -X POST "$GW_BASE/api/mina/pump/pump/candidates/reject" \
    -H "Content-Type: application/json" \
    -d "{\"id\":$CID,\"note\":\"smoke_pump_reject\",\"trace_id\":\"smoke_pump_ui\"}")"
  echo "$RESP" | show_json
  if [ "$JQ" = "jq" ]; then
    STATUS=$(echo "$RESP" | jq -r '.status // .ok // empty')
    if [ "$STATUS" != "ok" ] && [ "$STATUS" != "true" ]; then
      echo "FAIL: reject did not return ok"
      exit 1
    fi
  else
    echo "$RESP" | grep -q "ok" || {
      echo "FAIL: reject did not return ok"
      exit 1
    }
  fi
else
  echo "No candidates to reject (skip)"
fi

echo "✅ smoke_pump_ui_backend done"
