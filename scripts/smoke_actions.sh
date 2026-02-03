#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_curl_json.sh
source "${HERE}/_curl_json.sh"

ROLE="${1:-paper}"
BASE="${BASE_URL:-http://localhost:8200}"
KEY="${X_API_KEY:-${API_KEY:-trading-dev}}"
HDR=("-H" "X-API-Key: ${KEY}")

echo "== Health =="
curl_json "${BASE}/health" || exit 1

echo "== Unified overview (gateway) =="
OV="$(curl_capture "${BASE}/api/unified/overview" || true)"
if [[ "${CURL_LAST_CODE}" == "404" ]]; then
  OV="$(curl_capture "${BASE}/api/overview" || true)"
fi
printf '%s\n' "${OV}"

echo "== Try queue CLOSE_ALL_POSITIONS (${ROLE}) =="
BODY='{"cmd":"CLOSE_ALL_POSITIONS","params":{"reason":"smoke_test","ts_utc":"'"$(date -u +%Y-%m-%dT%H:%M:%SZ)"'"}}'
RESP="$(curl_capture -X POST "${BASE}/api/unified/${ROLE}/commands" "${HDR[@]}" -H "Content-Type: application/json" -d "${BODY}" || true)"
if [[ "${CURL_LAST_CODE}" == "404" ]]; then
  # Fallback: proxy to dashboard
  RESP="$(curl_capture -X POST "${BASE}/api/mina/${ROLE}/api/commands/queue" "${HDR[@]}" -H "Content-Type: application/json" -d "${BODY}" || true)"
fi
printf '%s\n' "${RESP}"

echo "== Done =="
