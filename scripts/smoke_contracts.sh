#!/usr/bin/env bash
set -euo pipefail

BASE="${GATEWAY_URL:-http://localhost:8200}"

curlx() {
  if [[ -n "${GATEWAY_API_KEY:-}" ]]; then
    curl -s -H "X-API-Key: ${GATEWAY_API_KEY}" "$@"
  else
    curl -s "$@"
  fi
}


echo "== Health =="
curl -s "${BASE}/health"; echo

echo "== Contracts index =="
curlx "${BASE}/api/contracts" | head; echo

echo "== Contracts v1 schema (truncated) =="
curlx "${BASE}/api/contracts/v1" | head -c 500; echo
echo
echo "== Done =="
