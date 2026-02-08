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
APPROVE_BODY='{"note":"smoke approve"}'

if [[ "${ROLE}" == "live" ]]; then
  LIVE_HDR=(-H "X-Live-Confirm: true" -H "X-Live-Confirm-Ack: true")
  APPROVE_BODY='{"note":"smoke approve","live_confirm":true,"live_confirm_ack":true}'
fi

echo "== Health =="
curl_json "${BASE}/health" || exit 1

echo "== Unified Signals (${ROLE}) =="
SIG="$(curl_capture "${BASE}/api/unified/${ROLE}/signals?limit=5" "${HDR[@]}" || true)"
if [[ "${CURL_LAST_CODE}" == "404" ]]; then
  SIG="$(curl_capture "${BASE}/api/mina/${ROLE}/api/signals?limit=5" "${HDR[@]}" || true)"
fi
if [[ "${CURL_LAST_CODE}" == "0" ]]; then
  echo "[ERROR] Gateway not reachable at ${BASE}" >&2
  exit 1
fi
printf '%s\n' "${SIG}"

echo "== Approve first signal (if any) =="
FIRST_ID="$(python3 - <<'PY'
import sys, json
try:
    data = json.load(sys.stdin)
    if isinstance(data, list) and data:
        print(data[0].get('id','') or '')
    elif isinstance(data, dict) and isinstance(data.get('items'), list) and data.get('items'):
        print((data['items'][0] or {}).get('id','') or '')
except Exception:
    print('')
PY
<<< "${SIG}")"

if [[ -z "${FIRST_ID}" ]]; then
  echo "No signals to approve."
  exit 0
fi

# Try unified approve
if [[ "${ROLE}" == "live" ]]; then
  APP="$(curl_capture -X POST "${BASE}/api/unified/${ROLE}/signals/${FIRST_ID}/approve" "${HDR[@]}" "${LIVE_HDR[@]}" -H "Content-Type: application/json" -d "${APPROVE_BODY}" || true)"
else
  APP="$(curl_capture -X POST "${BASE}/api/unified/${ROLE}/signals/${FIRST_ID}/approve" "${HDR[@]}" -H "Content-Type: application/json" -d "${APPROVE_BODY}" || true)"
fi
if [[ "${CURL_LAST_CODE}" == "404" ]]; then
  # Fallback: dashboard approve via proxy (expects {id, note})
  APP="$(curl_capture -X POST "${BASE}/api/mina/${ROLE}/api/signals/approve" "${HDR[@]}" -H "Content-Type: application/json" -d "{\"id\":${FIRST_ID},\"note\":\"smoke approve\"}" || true)"
fi
printf '%s\n' "${APP}"

echo "== Audit (limit=5) =="
AUD="$(curl_capture "${BASE}/api/audit?limit=5" || true)"
if [[ "${CURL_LAST_CODE}" == "404" ]]; then
  AUD="$(curl_capture "${BASE}/api/audit_log?limit=5" || true)"
fi
printf '%s\n' "${AUD}"
