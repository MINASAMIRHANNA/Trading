#!/usr/bin/env bash
ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$ROOT" || true
set -euo pipefail

BASE="${GW_BASE:-http://localhost:8200}"
ROLE="${ROLE:-paper}"

curlx() {
  curl --fail -sS "$@"
}

echo "== Settings (GET) =="
curlx "$BASE/api/unified/$ROLE/settings" | head -c 800

echo ""
echo "== Kill Switch ON (POST settings) =="
curlx -X POST "$BASE/api/unified/$ROLE/settings" \
  -H "Content-Type: application/json" \
  -d '{"kill_switch":"1","kill_switch_reason":"smoke_control"}' | head -c 800

echo ""
echo "== Clear Kill Switch (POST control) =="
curlx -X POST "$BASE/api/unified/$ROLE/control/clear_kill_switch" \
  -H "Content-Type: application/json" \
  -d '{}' | head -c 800

echo ""
echo "== Env Secrets (GET) =="
curlx "$BASE/api/unified/$ROLE/env_secrets" | head -c 800

echo ""
echo "== Restart Monitor (POST control) =="
curlx -X POST "$BASE/api/unified/$ROLE/control/restart_monitor" \
  -H "Content-Type: application/json" \
  -d '{}' | head -c 800

echo ""
echo "== Restart Bot (POST control) =="
curlx -X POST "$BASE/api/unified/$ROLE/control/restart_bot" \
  -H "Content-Type: application/json" \
  -d '{}' | head -c 800

echo ""
echo "✅ smoke_control OK"
