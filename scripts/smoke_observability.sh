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

echo "== Unified Observability =="
CAPTURE_BODY=""
capture_json "${BASE}/api/unified/observability" "${HDR[@]}" || true
RESP="${CAPTURE_BODY}"
if [[ ! "${CURL_LAST_CODE}" =~ ^(2|3) ]]; then
  fail "GET /api/unified/observability expected 2xx, got ${CURL_LAST_CODE} body=${RESP}"
fi

RESP_JSON="${RESP}" python3 - <<'PY'
import json
import os
import sys

raw = os.environ.get("RESP_JSON", "")
try:
    obj = json.loads(raw)
except Exception as exc:
    print(f"[FAIL] invalid JSON: {exc}", file=sys.stderr)
    sys.exit(1)

if obj.get("ok") is not True:
    print("[FAIL] expected ok=true", file=sys.stderr)
    sys.exit(1)

items = obj.get("items")
if not isinstance(items, list) or len(items) < 3:
    print("[FAIL] expected items length >= 3", file=sys.stderr)
    sys.exit(1)

by_role = {}
for item in items:
    if not isinstance(item, dict):
        print("[FAIL] item must be object", file=sys.stderr)
        sys.exit(1)
    role = str(item.get("role") or "")
    if not role:
        print("[FAIL] item.role missing", file=sys.stderr)
        sys.exit(1)
    eng = item.get("engine")
    if not isinstance(eng, dict) or not isinstance(eng.get("online"), bool):
        print(f"[FAIL] role={role} missing engine.online bool", file=sys.stderr)
        sys.exit(1)
    ks = item.get("kill_switch")
    if not isinstance(ks, dict) or not isinstance(ks.get("on"), bool):
        print(f"[FAIL] role={role} missing kill_switch.on bool", file=sys.stderr)
        sys.exit(1)
    by_role[role] = item

for req in ("paper", "live", "pump"):
    if req not in by_role:
        print(f"[FAIL] missing role item: {req}", file=sys.stderr)
        sys.exit(1)

live_gate = by_role["live"].get("live_gate")
if not isinstance(live_gate, dict) or not str(live_gate.get("state") or "").strip():
    print("[FAIL] live role missing live_gate.state", file=sys.stderr)
    sys.exit(1)

def claim_str(item):
    claim = item.get("last_claim")
    if not isinstance(claim, dict):
        return "-"
    cid = claim.get("command_id")
    cmd = str(claim.get("cmd") or "")
    st = str(claim.get("status") or "")
    return f"{cid}/{cmd}/{st}" if cid is not None else f"-/{cmd}/{st}"

def trade_str(item):
    tr = item.get("last_trade")
    if not isinstance(tr, dict):
        return "-"
    tid = tr.get("trade_id")
    sym = str(tr.get("symbol") or "")
    st = str(tr.get("status") or "")
    return f"{tid}/{sym}/{st}" if tid is not None else f"-/{sym}/{st}"

paper = by_role["paper"]
live = by_role["live"]
pump = by_role["pump"]

print(
    "paper online="
    + str(bool(paper.get("engine", {}).get("online")))
    + " last_claim="
    + claim_str(paper)
    + " last_trade="
    + trade_str(paper)
)
print(
    "live  online="
    + str(bool(live.get("engine", {}).get("online")))
    + " gate="
    + str((live.get("live_gate") or {}).get("state") or "")
    + " kill="
    + str(bool((live.get("kill_switch") or {}).get("on")))
    + " last_claim="
    + claim_str(live)
    + " last_trade="
    + trade_str(live)
)
print(
    "pump  online="
    + str(bool(pump.get("engine", {}).get("online")))
    + " last_claim="
    + claim_str(pump)
    + " last_trade="
    + trade_str(pump)
)
print("errors_count=" + str(len(obj.get("errors") or [])))
PY

echo "== Observability roles filter =="
CAPTURE_BODY=""
capture_json "${BASE}/api/unified/observability?roles=paper,live" "${HDR[@]}" || true
RESP_FILTER="${CAPTURE_BODY}"
if [[ ! "${CURL_LAST_CODE}" =~ ^(2|3) ]]; then
  fail "GET /api/unified/observability?roles=paper,live expected 2xx, got ${CURL_LAST_CODE}"
fi
RESP_FILTER_JSON="${RESP_FILTER}" python3 - <<'PY'
import json
import os
import sys
obj = json.loads(os.environ.get("RESP_FILTER_JSON", ""))
items = obj.get("items") or []
roles = sorted(str((x or {}).get("role") or "") for x in items if isinstance(x, dict))
if roles != ["live", "paper"]:
    print(f"[FAIL] filtered roles mismatch: {roles}", file=sys.stderr)
    sys.exit(1)
print("filtered_roles=" + ",".join(roles))
PY

echo "✅ smoke_observability passed"
