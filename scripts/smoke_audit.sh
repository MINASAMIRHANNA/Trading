#!/usr/bin/env bash
ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$ROOT" || true
set -euo pipefail

BASE="${BASE:-http://localhost:8200}"

curlx() {
  if [[ -n "${GATEWAY_API_KEY:-}" ]]; then
    curl -s -H "X-API-Key: ${GATEWAY_API_KEY}" "$@"
  else
    curl -s "$@"
  fi
}


echo "== Health =="
curl -s "$BASE/health" || true
echo

echo "== Audit (limit=5) =="
curlx "$BASE/api/audit_log?limit=5" | head
echo
