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
curl -sS "$GW_BASE/api/unified/autopilot" | show_json

echo "== Set Global SHADOW =="
curl -sS -X POST "$GW_BASE/api/unified/autopilot" \
  -H "Content-Type: application/json" \
  -d '{"global_mode":"SHADOW"}' | show_json

echo "== Set paper Role LIVE =="
curl -sS -X POST "$GW_BASE/api/unified/autopilot/paper" \
  -H "Content-Type: application/json" \
  -d '{"role_mode":"LIVE"}' | show_json

echo "== Set Global OFF =="
curl -sS -X POST "$GW_BASE/api/unified/autopilot" \
  -H "Content-Type: application/json" \
  -d '{"global_mode":"OFF"}' | show_json

echo "== Autopilot GET (assert effective OFF) =="
AUTO_JSON="$(curl -sS "$GW_BASE/api/unified/autopilot")"
echo "$AUTO_JSON" | show_json

if [ "$JQ" = "jq" ]; then
  eff_paper=$(echo "$AUTO_JSON" | jq -r '.roles.paper.effective_mode')
  eff_live=$(echo "$AUTO_JSON" | jq -r '.roles.live.effective_mode')
  eff_pump=$(echo "$AUTO_JSON" | jq -r '.roles.pump.effective_mode')
  if [ "$eff_paper" != "OFF" ] || [ "$eff_live" != "OFF" ] || [ "$eff_pump" != "OFF" ]; then
    echo "FAIL: effective modes not OFF"
    exit 1
  fi
else
  echo "$AUTO_JSON" | grep -q '"effective_mode":"OFF"' || {
    echo "FAIL: effective modes not OFF"
    exit 1
  }
fi

echo "== Set active_strategy for paper =="
curl -sS -X POST "$GW_BASE/api/unified/paper/settings" \
  -H "Content-Type: application/json" \
  -d '{"active_strategy":"demo_strategy_v1","trace_id":"smoke_autopilot"}' | show_json

echo "== Get paper settings (assert active_strategy) =="
SET_JSON="$(curl -sS "$GW_BASE/api/unified/paper/settings")"
echo "$SET_JSON" | show_json

if [ "$JQ" = "jq" ]; then
  val=$(echo "$SET_JSON" | jq -r '.active_strategy')
  if [ "$val" != "demo_strategy_v1" ]; then
    echo "FAIL: active_strategy mismatch ($val)"
    exit 1
  fi
else
  echo "$SET_JSON" | grep -q "demo_strategy_v1" || {
    echo "FAIL: active_strategy not found"
    exit 1
  }
fi

echo "== Audit Log (last 50) =="
AUDIT_JSON="$(curl -sS "$GW_BASE/api/audit?limit=50")"
echo "$AUDIT_JSON" | show_json

if [ "$JQ" = "jq" ]; then
  echo "$AUDIT_JSON" | jq -r '.items[].action' | grep -q "AUTOPILOT_SET_GLOBAL" || {
    echo "FAIL: missing AUTOPILOT_SET_GLOBAL in audit"
    exit 1
  }
  echo "$AUDIT_JSON" | jq -r '.items[].action' | grep -q "AUTOPILOT_SET_ROLE" || {
    echo "FAIL: missing AUTOPILOT_SET_ROLE in audit"
    exit 1
  }
else
  echo "$AUDIT_JSON" | grep -q "AUTOPILOT_SET_GLOBAL" || exit 1
  echo "$AUDIT_JSON" | grep -q "AUTOPILOT_SET_ROLE" || exit 1
fi

echo "✅ smoke_autopilot done"
