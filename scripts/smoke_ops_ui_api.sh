#!/usr/bin/env bash
ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$ROOT" || true
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_curl_json.sh
source "${HERE}/_curl_json.sh"

BASE="${BASE_URL:-http://localhost:8200}"
KEY="${X_API_KEY:-${API_KEY:-trading-dev}}"
HDR=(-H "X-API-Key: ${KEY}")

fail() {
  echo "[FAIL] $*" >&2
  exit 1
}

capture_json() {
  local url="$1"
  shift || true
  local tmp
  tmp="$(mktemp)"
  if ! curl_capture "${url}" "$@" >"${tmp}"; then
    CAPTURE_BODY="$(cat "${tmp}")"
    rm -f "${tmp}"
    return 1
  fi
  CAPTURE_BODY="$(cat "${tmp}")"
  rm -f "${tmp}"
  return 0
}

expect_2xx() {
  local code="$1"
  local label="$2"
  if [[ ! "${code}" =~ ^(2|3) ]]; then
    fail "${label} expected 2xx, got ${code}"
  fi
}

validate_json_shape() {
  local raw="$1"
  local mode="$2"
  JSON_RAW="${raw}" JSON_MODE="${mode}" python3 - <<'PY'
import json
import os
import sys

raw = os.environ.get("JSON_RAW", "")
mode = os.environ.get("JSON_MODE", "")

try:
    obj = json.loads(raw)
except Exception as exc:
    print(f"[FAIL] invalid JSON for mode={mode}: {exc}", file=sys.stderr)
    sys.exit(1)

if mode == "observability":
    if obj.get("ok") is not True:
        print("[FAIL] observability missing ok=true", file=sys.stderr)
        sys.exit(1)
    if not isinstance(obj.get("items"), list):
        print("[FAIL] observability items must be list", file=sys.stderr)
        sys.exit(1)
elif mode == "live_status":
    if obj.get("ok") is not True:
        print("[FAIL] live status missing ok=true", file=sys.stderr)
        sys.exit(1)
    gate = obj.get("gate")
    if not isinstance(gate, dict) or not str(gate.get("state") or ""):
        print("[FAIL] live status missing gate.state", file=sys.stderr)
        sys.exit(1)
elif mode in {"dead_letters", "commands"}:
    if obj.get("ok") is not True:
        print(f"[FAIL] {mode} missing ok=true", file=sys.stderr)
        sys.exit(1)
    if not isinstance(obj.get("items"), list):
        print(f"[FAIL] {mode} items must be list", file=sys.stderr)
        sys.exit(1)
else:
    print(f"[FAIL] unknown validation mode={mode}", file=sys.stderr)
    sys.exit(1)
PY
}

echo "== OPS UI API smoke =="

CAPTURE_BODY=""
capture_json "${BASE}/api/unified/observability" "${HDR[@]}" || true
expect_2xx "${CURL_LAST_CODE}" "GET /api/unified/observability"
validate_json_shape "${CAPTURE_BODY}" "observability"

echo "observability_ok=true"

CAPTURE_BODY=""
capture_json "${BASE}/api/control/live/status" "${HDR[@]}" || true
expect_2xx "${CURL_LAST_CODE}" "GET /api/control/live/status"
validate_json_shape "${CAPTURE_BODY}" "live_status"
echo "live_status_ok=true"

for role in paper live pump; do
  CAPTURE_BODY=""
  capture_json "${BASE}/api/unified/dead_letters?role=${role}&limit=50" "${HDR[@]}" || true
  expect_2xx "${CURL_LAST_CODE}" "GET /api/unified/dead_letters role=${role}"
  validate_json_shape "${CAPTURE_BODY}" "dead_letters"

  CAPTURE_BODY=""
  capture_json "${BASE}/api/unified/${role}/commands?limit=50" "${HDR[@]}" || true
  expect_2xx "${CURL_LAST_CODE}" "GET /api/unified/${role}/commands"
  validate_json_shape "${CAPTURE_BODY}" "commands"

  CAPTURE_BODY=""
  capture_json "${BASE}/api/unified/${role}/commands?limit=50&status=DONE" "${HDR[@]}" || true
  expect_2xx "${CURL_LAST_CODE}" "GET /api/unified/${role}/commands?status=DONE"
  validate_json_shape "${CAPTURE_BODY}" "commands"

  echo "role=${role} dead_letters_ok=true commands_ok=true"
done

echo "✅ smoke_ops_ui_api passed"
