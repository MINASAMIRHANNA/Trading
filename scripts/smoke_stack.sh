#!/usr/bin/env bash
ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$ROOT" || true
set -euo pipefail


curlx() {
  if [[ -n "${GATEWAY_API_KEY:-}" ]]; then
    curl -s -H "X-API-Key: ${GATEWAY_API_KEY}" "$@"
  else
    curl -s "$@"
  fi
}

API_KEY="${DASHBOARD_API_KEY:-trading-dev}"

echo "== Gateway =="
curlx http://localhost:8200/health && echo

echo "== Brain via Gateway (/api/overview) =="
curlx http://localhost:8200/api/overview && echo

echo "== Mina (paper) signals via Gateway =="
curl -sS -H "X-API-Key: ${API_KEY}" "http://localhost:8200/api/mina/paper/signals?limit=1" && echo

echo "== Mina (paper) system_health via Gateway =="
curl -sS -H "X-API-Key: ${API_KEY}" "http://localhost:8200/api/mina/paper/system_health" && echo

echo "== Stack Health (aggregate) =="
curlx http://localhost:8200/api/stack/health && echo

echo "✅ Smoke OK"
