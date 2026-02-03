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

# Try unified signals
SIGRAW="$(curl_capture "${BASE}/api/unified/${ROLE}/signals?limit=1" "${HDR[@]}" || true)"
if [[ "${CURL_LAST_CODE}" == "404" ]]; then
  SIGRAW="$(curl_capture "${BASE}/api/mina/${ROLE}/api/signals?limit=1" "${HDR[@]}" || true)"
fi

SID="$(python3 - <<'PY'
import sys,json
try:
    d=json.load(sys.stdin)
    if isinstance(d,list) and d:
        print(d[0].get('id','') or '')
except Exception:
    print('')
PY
<<< "${SIGRAW}")"

echo "signal_id=${SID}"
if [[ -z "${SID}" ]]; then
  echo "No signals."
  exit 0
fi

echo "== Signal decision precheck (${ROLE}) =="
RESP="$(curl_capture "${BASE}/api/unified/${ROLE}/signals/${SID}/decision" "${HDR[@]}" || true)"
if [[ "${CURL_LAST_CODE}" == "404" ]]; then
  # Fallback: call dashboard path if exists
  RESP="$(curl_capture "${BASE}/api/mina/${ROLE}/api/signals/${SID}/decision" "${HDR[@]}" || true)"
fi
printf '%s
' "${RESP}"

echo "== Done =="
