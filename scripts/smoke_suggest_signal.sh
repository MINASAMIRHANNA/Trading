#!/usr/bin/env bash
set -euo pipefail

ROLE="${1:-paper}"
SYMBOL="${2:-BTCUSDT}"
SIDE="${3:-BUY}"
BASE="${BASE_URL:-http://localhost:8200}"

curlx() {
  if [[ -n "${GATEWAY_API_KEY:-}" ]]; then
    curl -s -H "X-API-Key: ${GATEWAY_API_KEY}" "$@"
  else
    curl -s "$@"
  fi
}

echo "== Health =="
curl -s "$BASE/health" && echo

echo "== Brain decision via gateway =="
curlx -G "$BASE/api/decision" --data-urlencode "symbol=${SYMBOL}" && echo

echo "== Stage Mina inbox signal from decision (shadow) =="
payload=$(cat <<JSON
{"side":"${SIDE}","timeframe":"1m","note":"smoke stage from decision"}
JSON
)
curlx -X POST "$BASE/api/unified/${ROLE}/signals/suggest_from_decision?symbol=${SYMBOL}" \
  -H "Content-Type: application/json" \
  -d "$payload" && echo

echo "== Unified Signals (${ROLE}) =="
curlx "$BASE/api/unified/${ROLE}/signals?limit=5" && echo

echo "== Audit (limit=5) =="
curlx "$BASE/api/audit?limit=5" && echo

echo "== Done =="
