#!/usr/bin/env bash
ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$ROOT" || true
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_curl_json.sh
source "${HERE}/_curl_json.sh"

ROLE="${1:-paper}"
BASE="${BASE_URL:-http://localhost:8200}"
KEY="${X_API_KEY:-${API_KEY:-trading-dev}}"
HDR=("-H" "X-API-Key: ${KEY}")
LIVE_HDR=()
BODY='{"cmd":"CLOSE_ALL_POSITIONS","params":{"reason":"smoke_test","ts_utc":"'"$(date -u +%Y-%m-%dT%H:%M:%SZ)"'"}}'

if [[ "${ROLE}" == "live" ]]; then
  LIVE_HDR=(-H "X-Live-Confirm: true" -H "X-Live-Confirm-Ack: true")
  BODY='{"cmd":"CLOSE_ALL_POSITIONS","params":{"reason":"smoke_test","ts_utc":"'"$(date -u +%Y-%m-%dT%H:%M:%SZ)"'"},"live_confirm":true,"live_confirm_ack":true}'
fi

echo "== Health =="
curl_json "${BASE}/health" || exit 1

echo "== Unified overview (gateway) =="
OV="$(curl_capture "${BASE}/api/unified/overview" || true)"
if [[ "${CURL_LAST_CODE}" == "404" ]]; then
  OV="$(curl_capture "${BASE}/api/overview" || true)"
fi
printf '%s\n' "${OV}"

echo "== Try queue CLOSE_ALL_POSITIONS (${ROLE}) =="
if [[ "${ROLE}" == "live" ]]; then
  RESP="$(curl_capture "${BASE}/api/unified/${ROLE}/commands" -X POST "${HDR[@]}" "${LIVE_HDR[@]}" -H "Content-Type: application/json" -d "${BODY}" || true)"
else
  RESP="$(curl_capture "${BASE}/api/unified/${ROLE}/commands" -X POST "${HDR[@]}" -H "Content-Type: application/json" -d "${BODY}" || true)"
fi
if [[ "${CURL_LAST_CODE}" == "404" ]]; then
  # Fallback: proxy to dashboard
  RESP="$(curl_capture "${BASE}/api/mina/${ROLE}/api/commands/queue" -X POST "${HDR[@]}" -H "Content-Type: application/json" -d "${BODY}" || true)"
fi
printf '%s\n' "${RESP}"

echo "== Done =="
