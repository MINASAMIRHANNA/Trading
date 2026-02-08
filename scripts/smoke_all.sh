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

HDR=(-H "X-API-Key: ${KEY}")

echo "BASE_URL=${BASE}"
echo

echo "== Health =="
curl_json "${BASE}/health" "${HDR[@]}" || exit 1
echo

echo "== Unified overview =="
curl_capture "${BASE}/api/unified/overview" "${HDR[@]}" | head -c 4000 || true
echo
echo

echo "== Unified signals (${ROLE}) =="
SIGS="$(mktemp)"
curl_capture "${BASE}/api/unified/${ROLE}/signals?limit=3" "${HDR[@]}" >"${SIGS}" || true
cat "${SIGS}" | head -c 4000
echo
echo

echo "== Try approve first signal (if any) =="
FIRST_ID=""
if command -v jq >/dev/null 2>&1; then
  FIRST_ID="$(cat "${SIGS}" | jq -r 'if type=="array" and length>0 then .[0].id elif (type=="object" and (.items|type=="array") and (.items|length>0)) then .items[0].id else empty end' 2>/dev/null || true)"
else
  FIRST_ID="$(cat "${SIGS}" | python3 -c 'import sys,json
try:
  d=json.load(sys.stdin)
  if isinstance(d,list) and d:
    print(d[0].get("id","") or "")
  elif isinstance(d,dict) and isinstance(d.get("items"),list) and d.get("items"):
    print((d["items"][0] or {}).get("id","") or "")
  else:
    print("")
except Exception:
  pass' 2>/dev/null || true)"
fi

if [[ -n "${FIRST_ID}" ]]; then
  curl_capture "${BASE}/api/unified/${ROLE}/signals/${FIRST_ID}/approve" -X POST "${HDR[@]}" -H "Content-Type: application/json" -d '{"note":"smoke approve"}' | head -c 4000 || true
  echo
else
  echo "No signals to approve."
fi
echo

echo "== Try queue CLOSE_ALL_POSITIONS (${ROLE}) =="
curl_capture "${BASE}/api/unified/${ROLE}/commands" -X POST "${HDR[@]}" -H "Content-Type: application/json" -d '{"cmd":"CLOSE_ALL_POSITIONS","params":{"reason":"smoke_all"}}' | head -c 4000 || true
echo
echo

echo "== Positions after CLOSE_ALL_POSITIONS (${ROLE}) =="
# Give the monitor a moment to consume the command (async).
for i in 1 2 3 4 5; do
  RESP="$(curl_capture "${BASE}/api/unified/${ROLE}/positions" "${HDR[@]}" || true)"
  echo "${RESP}" | head -c 4000 || true
  echo
  if command -v jq >/dev/null 2>&1; then
    if echo "${RESP}" | jq -e 'type=="array" and length==0' >/dev/null 2>&1; then
      break
    fi
  else
    # naive empty-array check without jq
    if [[ "${RESP}" =~ ^\[\s*\]\s*$ ]]; then
      break
    fi
  fi
  if [[ "${i}" != "5" ]]; then
    echo "--- waiting for monitor (${i}/5) ---"
    sleep 2
  fi
done
echo


echo "== Audit (limit=5) =="
curl_capture "${BASE}/api/audit?limit=5" "${HDR[@]}" | head -c 4000 || true
echo
echo

echo "== Events (limit=5) =="
curl_capture "${BASE}/api/events?limit=5" "${HDR[@]}" | head -c 4000 || true
echo
echo

echo "== Brain decision (via gateway) =="
curl_capture -G "${BASE}/api/decision" "${HDR[@]}" --data-urlencode "symbol=BTCUSDT" | head -c 4000 || true
echo

rm -f "${SIGS}" || true
