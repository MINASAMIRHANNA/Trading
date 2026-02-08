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
elif mode == "live_readiness":
    if obj.get("ok") is not True:
        print("[FAIL] live readiness missing ok=true", file=sys.stderr)
        sys.exit(1)
    if not isinstance(obj.get("ready"), bool):
        print("[FAIL] live readiness missing ready boolean", file=sys.stderr)
        sys.exit(1)
    checks = obj.get("checks")
    if not isinstance(checks, list):
        print("[FAIL] live readiness checks must be list", file=sys.stderr)
        sys.exit(1)
    required_ids = {
        "live_gate_confirmed",
        "kill_switch_off",
        "allowlist_nonempty",
        "limits_set",
        "engine_online",
        "dead_letters_zero",
        "command_backlog_ok",
        "observability_errors_ok",
        "brain_optional",
    }
    have = {str((it or {}).get("id") or "") for it in checks if isinstance(it, dict)}
    missing = sorted(required_ids - have)
    if missing:
        print(f"[FAIL] live readiness missing required checks: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)
elif mode == "signals":
    if obj.get("ok") is not True:
        print("[FAIL] signals missing ok=true", file=sys.stderr)
        sys.exit(1)
    if not isinstance(obj.get("items"), list):
        print("[FAIL] signals items must be list", file=sys.stderr)
        sys.exit(1)
elif mode == "dead_letter_detail":
    if obj.get("ok") is not True:
        print("[FAIL] dead_letter_detail missing ok=true", file=sys.stderr)
        sys.exit(1)
    if not isinstance(obj.get("dead_letter"), dict):
        print("[FAIL] dead_letter_detail dead_letter must be object", file=sys.stderr)
        sys.exit(1)
    rq = obj.get("requeue")
    if not isinstance(rq, dict) or "allowed" not in rq:
        print("[FAIL] dead_letter_detail requeue object missing", file=sys.stderr)
        sys.exit(1)
elif mode in {"dead_letters", "commands"}:
    if obj.get("ok") is not True:
        print(f"[FAIL] {mode} missing ok=true", file=sys.stderr)
        sys.exit(1)
    if not isinstance(obj.get("items"), list):
        print(f"[FAIL] {mode} items must be list", file=sys.stderr)
        sys.exit(1)
elif mode == "strategies_discover":
    if obj.get("ok") is not True:
        print("[FAIL] strategies discover missing ok=true", file=sys.stderr)
        sys.exit(1)
    items = obj.get("items")
    if not isinstance(items, list) or not items:
        print("[FAIL] strategies discover items must be non-empty list", file=sys.stderr)
        sys.exit(1)
    for it in items:
        if not isinstance(it, dict):
            print("[FAIL] strategies discover item must be object", file=sys.stderr)
            sys.exit(1)
        schema = it.get("params_schema")
        if not isinstance(schema, dict) or not schema:
            print("[FAIL] strategies discover item missing params_schema", file=sys.stderr)
            sys.exit(1)
elif mode == "strategies_status":
    if obj.get("ok") is not True:
        print("[FAIL] strategies status missing ok=true", file=sys.stderr)
        sys.exit(1)
    if not isinstance(obj.get("discovered"), list):
        print("[FAIL] strategies status discovered must be list", file=sys.stderr)
        sys.exit(1)
    if not isinstance(obj.get("config"), dict):
        print("[FAIL] strategies status config must be object", file=sys.stderr)
        sys.exit(1)
    cfg = obj.get("config") or {}
    if not isinstance(cfg.get("strategy_params_global"), dict):
        print("[FAIL] strategies status missing strategy_params_global object", file=sys.stderr)
        sys.exit(1)
    if not isinstance(cfg.get("strategy_params_by_name"), dict):
        print("[FAIL] strategies status missing strategy_params_by_name object", file=sys.stderr)
        sys.exit(1)
elif mode == "audit_traces":
    if obj.get("ok") is not True:
        print("[FAIL] audit traces missing ok=true", file=sys.stderr)
        sys.exit(1)
    if not isinstance(obj.get("items"), list):
        print("[FAIL] audit traces items must be list", file=sys.stderr)
        sys.exit(1)
elif mode == "audit_trace_detail":
    if obj.get("ok") is not True:
        print("[FAIL] audit trace detail missing ok=true", file=sys.stderr)
        sys.exit(1)
    if not isinstance(obj.get("timeline"), list):
        print("[FAIL] audit trace detail timeline must be list", file=sys.stderr)
        sys.exit(1)
    if "brain" not in obj:
        print("[FAIL] audit trace detail missing brain key", file=sys.stderr)
        sys.exit(1)
    brain = obj.get("brain")
    if brain is not None and not isinstance(brain, dict):
        print("[FAIL] audit trace detail brain must be object or null", file=sys.stderr)
        sys.exit(1)
elif mode == "audit_replay":
    if obj.get("ok") is not True:
        print("[FAIL] audit replay missing ok=true", file=sys.stderr)
        sys.exit(1)
    if not (obj.get("command_id") or obj.get("new_command_id")):
        print("[FAIL] audit replay missing command id", file=sys.stderr)
        sys.exit(1)
    if not isinstance(obj.get("source"), dict):
        print("[FAIL] audit replay missing source object", file=sys.stderr)
        sys.exit(1)
else:
    print(f"[FAIL] unknown validation mode={mode}", file=sys.stderr)
    sys.exit(1)
PY
}

command_status_for_id() {
  local raw="$1"
  local cmd_id="$2"
  python3 - "$raw" "$cmd_id" <<'PY'
import json
import sys
raw = sys.argv[1]
cmd_id = str(sys.argv[2])
try:
    obj = json.loads(raw)
except Exception:
    print("")
    raise SystemExit(0)
items = obj.get("items") or []
for it in items:
    if not isinstance(it, dict):
        continue
    if str(it.get("id")) == cmd_id:
        print(str(it.get("status") or ""))
        raise SystemExit(0)
print("")
PY
}

command_param_field_for_id() {
  local raw="$1"
  local cmd_id="$2"
  local field="$3"
  python3 - "$raw" "$cmd_id" "$field" <<'PY'
import json
import sys
raw = sys.argv[1]
cmd_id = str(sys.argv[2])
field = str(sys.argv[3])
try:
    obj = json.loads(raw)
except Exception:
    print("")
    raise SystemExit(0)
items = obj.get("items") or []
for it in items:
    if not isinstance(it, dict):
        continue
    if str(it.get("id")) != cmd_id:
        continue
    params = it.get("params")
    if isinstance(params, str):
        try:
            params = json.loads(params)
        except Exception:
            params = {}
    if not isinstance(params, dict):
        params = {}
    val = params.get(field)
    print("" if val is None else val)
    raise SystemExit(0)
print("")
PY
}

dead_letter_id_for_command() {
  local raw="$1"
  local cmd_id="$2"
  python3 - "$raw" "$cmd_id" <<'PY'
import json
import sys
raw = sys.argv[1]
cmd_id = str(sys.argv[2])
try:
    obj = json.loads(raw)
except Exception:
    print("")
    raise SystemExit(0)
items = obj.get("items") or []
for it in items:
    if not isinstance(it, dict):
        continue
    if str(it.get("command_id")) == cmd_id:
        did = it.get("id")
        print("" if did is None else did)
        raise SystemExit(0)
print("")
PY
}

first_discovered_name() {
  local raw="$1"
  python3 - "$raw" <<'PY'
import json
import sys
try:
    obj = json.loads(sys.argv[1])
except Exception:
    print("")
    raise SystemExit(0)
items = obj.get("items") or []
for it in items:
    if not isinstance(it, dict):
        continue
    name = str(it.get("name") or "").strip()
    if name:
        print(name)
        raise SystemExit(0)
print("")
PY
}

first_trace_id() {
  local raw="$1"
  python3 - "$raw" <<'PY'
import json
import sys
try:
    obj = json.loads(sys.argv[1])
except Exception:
    print("")
    raise SystemExit(0)
items = obj.get("items") or []
for it in items:
    if not isinstance(it, dict):
        continue
    trace_id = str(it.get("trace_id") or "").strip()
    if trace_id:
        print(trace_id)
        raise SystemExit(0)
print("")
PY
}

strategies_status_field() {
  local raw="$1"
  local field="$2"
  python3 - "$raw" "$field" <<'PY'
import json
import sys
raw = sys.argv[1]
field = sys.argv[2]
try:
    obj = json.loads(raw)
except Exception:
    print("")
    raise SystemExit(0)
cfg = obj.get("config") or {}
if field == "profile":
    print(str(cfg.get("active_profile") or ""))
elif field == "min_conf":
    params = cfg.get("strategy_params_global")
    if not isinstance(params, dict):
        params = cfg.get("strategy_params") or {}
    if isinstance(params, dict):
        val = params.get("min_conf")
        print("" if val is None else val)
    else:
        print("")
elif field == "enabled_json":
    enabled = cfg.get("strategies_enabled")
    if isinstance(enabled, dict):
        print(json.dumps(enabled, ensure_ascii=True))
    else:
        print("{}")
else:
    print("")
PY
}

strategy_param_by_name_field() {
  local raw="$1"
  local strategy_name="$2"
  local field="$3"
  python3 - "$raw" "$strategy_name" "$field" <<'PY'
import json
import sys
raw = sys.argv[1]
strategy_name = str(sys.argv[2] or "").strip()
field = str(sys.argv[3] or "").strip()
try:
    obj = json.loads(raw)
except Exception:
    print("")
    raise SystemExit(0)
cfg = obj.get("config") or {}
by_name = cfg.get("strategy_params_by_name") or {}
if isinstance(by_name, dict):
    params = by_name.get(strategy_name)
    if isinstance(params, dict):
        value = params.get(field)
        print("" if value is None else value)
        raise SystemExit(0)
print("")
PY
}

wait_for_command_status() {
  local role="$1"
  local cmd_id="$2"
  local wanted="$3"
  local tries="${4:-80}"
  local i status
  for ((i=1; i<=tries; i++)); do
    CAPTURE_BODY=""
    capture_json "${BASE}/api/unified/${role}/commands?limit=300" "${HDR[@]}" || true
    if [[ ! "${CURL_LAST_CODE}" =~ ^(2|3) ]]; then
      sleep 1
      continue
    fi
    status="$(command_status_for_id "${CAPTURE_BODY}" "${cmd_id}")"
    if [[ "${status}" == "${wanted}" ]]; then
      echo "${status}"
      return 0
    fi
    sleep 1
  done
  return 1
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

CAPTURE_BODY=""
capture_json "${BASE}/api/control/live/readiness" "${HDR[@]}" || true
expect_2xx "${CURL_LAST_CODE}" "GET /api/control/live/readiness"
validate_json_shape "${CAPTURE_BODY}" "live_readiness"
echo "live_readiness_ok=true"

curl_capture "${BASE}/ui/ops/go-live" "${HDR[@]}" >/dev/null || true
expect_2xx "${CURL_LAST_CODE}" "GET /ui/ops/go-live"
echo "ui_ops_go_live_ok=true"

for role in paper live pump; do
  CAPTURE_BODY=""
  capture_json "${BASE}/api/unified/${role}/signals?limit=20" "${HDR[@]}" || true
  expect_2xx "${CURL_LAST_CODE}" "GET /api/unified/${role}/signals"
  validate_json_shape "${CAPTURE_BODY}" "signals"

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

  echo "role=${role} signals_ok=true dead_letters_ok=true commands_ok=true"
done

echo "== Strategies discover/status/apply =="
CAPTURE_BODY=""
capture_json "${BASE}/api/control/strategies/discover" "${HDR[@]}" || true
expect_2xx "${CURL_LAST_CODE}" "GET /api/control/strategies/discover"
validate_json_shape "${CAPTURE_BODY}" "strategies_discover"
FIRST_STRATEGY_NAME="$(first_discovered_name "${CAPTURE_BODY}")"
[[ -n "${FIRST_STRATEGY_NAME}" ]] || fail "no discovered strategy name found"
echo "strategies_discover_ok=true first_strategy=${FIRST_STRATEGY_NAME}"

CAPTURE_BODY=""
capture_json "${BASE}/api/control/strategies/status?role=paper" "${HDR[@]}" || true
expect_2xx "${CURL_LAST_CODE}" "GET /api/control/strategies/status?role=paper"
validate_json_shape "${CAPTURE_BODY}" "strategies_status"
PAPER_PROFILE="$(strategies_status_field "${CAPTURE_BODY}" "profile")"
PAPER_MIN_CONF="$(strategies_status_field "${CAPTURE_BODY}" "min_conf")"
PAPER_ENABLED_JSON="$(strategies_status_field "${CAPTURE_BODY}" "enabled_json")"
[[ -n "${PAPER_PROFILE}" ]] || PAPER_PROFILE="conservative"
[[ -n "${PAPER_MIN_CONF}" ]] || PAPER_MIN_CONF="0.0"

PAPER_APPLY_OFF_JSON="$(
python3 - "${PAPER_ENABLED_JSON}" "${FIRST_STRATEGY_NAME}" <<'PY'
import json
import sys
enabled = {}
try:
    enabled = json.loads(sys.argv[1] or "{}")
except Exception:
    enabled = {}
name = str(sys.argv[2] or "").strip()
if name:
    enabled[name] = False
print(json.dumps(enabled, ensure_ascii=True))
PY
)"

CAPTURE_BODY=""
capture_json "${BASE}/api/control/strategies/apply" -X POST "${HDR[@]}" -H "Content-Type: application/json" -d "{\"role\":\"paper\",\"active_profile\":\"${PAPER_PROFILE}\",\"strategies_enabled\":${PAPER_APPLY_OFF_JSON},\"strategy_params\":{\"min_conf\":${PAPER_MIN_CONF}}}" || true
expect_2xx "${CURL_LAST_CODE}" "POST /api/control/strategies/apply paper off"
echo "strategies_apply_paper_off_ok=true strategy=${FIRST_STRATEGY_NAME}"

PAPER_APPLY_ON_JSON="$(
python3 - "${PAPER_ENABLED_JSON}" "${FIRST_STRATEGY_NAME}" <<'PY'
import json
import sys
enabled = {}
try:
    enabled = json.loads(sys.argv[1] or "{}")
except Exception:
    enabled = {}
name = str(sys.argv[2] or "").strip()
if name:
    enabled[name] = True
print(json.dumps(enabled, ensure_ascii=True))
PY
)"
CAPTURE_BODY=""
capture_json "${BASE}/api/control/strategies/apply" -X POST "${HDR[@]}" -H "Content-Type: application/json" -d "{\"role\":\"paper\",\"active_profile\":\"${PAPER_PROFILE}\",\"strategies_enabled\":${PAPER_APPLY_ON_JSON},\"strategy_params\":{\"min_conf\":${PAPER_MIN_CONF}}}" || true
expect_2xx "${CURL_LAST_CODE}" "POST /api/control/strategies/apply paper on"
echo "strategies_apply_paper_revert_ok=true strategy=${FIRST_STRATEGY_NAME}"

PAPER_COOLDOWN_OVERRIDE=123
CAPTURE_BODY=""
capture_json "${BASE}/api/control/strategies/apply" -X POST "${HDR[@]}" -H "Content-Type: application/json" -d "{\"role\":\"paper\",\"active_profile\":\"${PAPER_PROFILE}\",\"strategy_params_global\":{\"min_conf\":${PAPER_MIN_CONF}},\"strategy_params_by_name\":{\"${FIRST_STRATEGY_NAME}\":{\"cooldown_sec\":${PAPER_COOLDOWN_OVERRIDE}}}}" || true
expect_2xx "${CURL_LAST_CODE}" "POST /api/control/strategies/apply paper per-strategy cooldown"

CAPTURE_BODY=""
capture_json "${BASE}/api/control/strategies/status?role=paper" "${HDR[@]}" || true
expect_2xx "${CURL_LAST_CODE}" "GET /api/control/strategies/status?role=paper (verify per-strategy)"
validate_json_shape "${CAPTURE_BODY}" "strategies_status"
PAPER_COOLDOWN_READ="$(strategy_param_by_name_field "${CAPTURE_BODY}" "${FIRST_STRATEGY_NAME}" "cooldown_sec")"
[[ "${PAPER_COOLDOWN_READ}" == "${PAPER_COOLDOWN_OVERRIDE}" ]] || fail "expected paper cooldown_sec=${PAPER_COOLDOWN_OVERRIDE}, got ${PAPER_COOLDOWN_READ}"
echo "strategies_apply_paper_by_name_ok=true strategy=${FIRST_STRATEGY_NAME} cooldown_sec=${PAPER_COOLDOWN_READ}"

CAPTURE_BODY=""
capture_json "${BASE}/api/control/strategies/apply" -X POST "${HDR[@]}" -H "Content-Type: application/json" -d "{\"role\":\"paper\",\"active_profile\":\"${PAPER_PROFILE}\",\"strategy_params_global\":{\"min_conf\":${PAPER_MIN_CONF}},\"strategy_params_by_name\":{\"${FIRST_STRATEGY_NAME}\":{\"cooldown_sec\":99999999}}}" || true
if [[ "${CURL_LAST_CODE}" =~ ^(2|3) ]]; then
  fail "POST /api/control/strategies/apply paper invalid cooldown expected 4xx, got ${CURL_LAST_CODE}"
fi
echo "strategies_apply_paper_by_name_invalid_rejected=true code=${CURL_LAST_CODE}"

CAPTURE_BODY=""
capture_json "${BASE}/api/control/strategies/apply" -X POST "${HDR[@]}" -H "Content-Type: application/json" -d "{\"role\":\"paper\",\"active_profile\":\"${PAPER_PROFILE}\",\"strategy_params_global\":{\"min_conf\":${PAPER_MIN_CONF}},\"strategy_params_by_name\":{\"${FIRST_STRATEGY_NAME}\":null}}" || true
expect_2xx "${CURL_LAST_CODE}" "POST /api/control/strategies/apply paper clear per-strategy override"

CAPTURE_BODY=""
capture_json "${BASE}/api/control/strategies/status?role=live" "${HDR[@]}" || true
expect_2xx "${CURL_LAST_CODE}" "GET /api/control/strategies/status?role=live"
validate_json_shape "${CAPTURE_BODY}" "strategies_status"
LIVE_PROFILE="$(strategies_status_field "${CAPTURE_BODY}" "profile")"
LIVE_MIN_CONF="$(strategies_status_field "${CAPTURE_BODY}" "min_conf")"
LIVE_ENABLED_JSON="$(strategies_status_field "${CAPTURE_BODY}" "enabled_json")"
[[ -n "${LIVE_PROFILE}" ]] || LIVE_PROFILE="conservative"
[[ -n "${LIVE_MIN_CONF}" ]] || LIVE_MIN_CONF="0.0"

CAPTURE_BODY=""
capture_json "${BASE}/api/control/strategies/apply" -X POST "${HDR[@]}" -H "Content-Type: application/json" -d "{\"role\":\"live\",\"active_profile\":\"${LIVE_PROFILE}\",\"strategies_enabled\":${LIVE_ENABLED_JSON},\"strategy_params\":{\"min_conf\":${LIVE_MIN_CONF}}}" || true
if [[ "${CURL_LAST_CODE}" =~ ^(2|3) ]]; then
  fail "POST /api/control/strategies/apply live without confirm expected 4xx, got ${CURL_LAST_CODE}"
fi
echo "strategies_apply_live_without_confirm_rejected=true code=${CURL_LAST_CODE}"

# Prepare deterministic live gate + kill-switch state for confirmed apply.
CAPTURE_BODY=""
capture_json "${BASE}/api/control/live/disarm" -X POST "${HDR[@]}" -H "Content-Type: application/json" -d '{}' || true
expect_2xx "${CURL_LAST_CODE}" "POST /api/control/live/disarm (strategies)"

CAPTURE_BODY=""
capture_json "${BASE}/api/control/live/arm" -X POST "${HDR[@]}" -H "Content-Type: application/json" -d '{}' || true
expect_2xx "${CURL_LAST_CODE}" "POST /api/control/live/arm (strategies)"
LIVE_GATE_TOKEN="$(
python3 - "${CAPTURE_BODY}" <<'PY'
import json
import sys
try:
    obj = json.loads(sys.argv[1])
except Exception:
    print("")
    raise SystemExit(0)
print(str(obj.get("token") or ""))
PY
)"
[[ -n "${LIVE_GATE_TOKEN}" ]] || fail "missing token from /api/control/live/arm"

CAPTURE_BODY=""
capture_json "${BASE}/api/control/live/confirm" -X POST "${HDR[@]}" -H "Content-Type: application/json" -d "{\"token\":\"${LIVE_GATE_TOKEN}\"}" || true
expect_2xx "${CURL_LAST_CODE}" "POST /api/control/live/confirm (strategies)"

CAPTURE_BODY=""
capture_json "${BASE}/api/unified/live/commands/kill_switch" -X POST "${HDR[@]}" -H "Content-Type: application/json" -d '{"enabled":false,"reason":"smoke_ops_ui_api_strategies","live_confirm":true,"live_confirm_ack":true}' || true
expect_2xx "${CURL_LAST_CODE}" "POST /api/unified/live/commands/kill_switch OFF (strategies)"

CAPTURE_BODY=""
capture_json "${BASE}/api/control/strategies/apply" -X POST "${HDR[@]}" -H "Content-Type: application/json" -d "{\"role\":\"live\",\"active_profile\":\"${LIVE_PROFILE}\",\"strategies_enabled\":${LIVE_ENABLED_JSON},\"strategy_params\":{\"min_conf\":${LIVE_MIN_CONF}},\"confirm_live_change\":true,\"live_confirm_ack\":\"I_UNDERSTAND\"}" || true
expect_2xx "${CURL_LAST_CODE}" "POST /api/control/strategies/apply live confirmed"
echo "strategies_apply_live_confirmed_ok=true"

PAPER_SIGNAL_BODY='{"symbol":"OPSUIBTC","side":"BUY","price":101.5,"confidence":0.91,"score":0.91,"strategy":"BASELINE_SCALP","execution_allowed":false,"source":"smoke_ops_ui_api"}'

# Keep paper strategy/risk gate permissive so approve endpoint is deterministic.
CAPTURE_BODY=""
capture_json "${BASE}/api/unified/paper/settings" -X POST "${HDR[@]}" -H "Content-Type: application/json" -d '{"kill_switch":"0","kill_switch_reason":""}' || true
expect_2xx "${CURL_LAST_CODE}" "POST /api/unified/paper/settings"

CAPTURE_BODY=""
capture_json "${BASE}/api/risk/profiles" -X POST "${HDR[@]}" -H "Content-Type: application/json" -d '{"profile_id":"qa_ops_ui_api","name":"QA Ops UI API","params_json":{"min_score":0.0,"min_confidence":0.0,"max_concurrent_positions":200,"cooldown_sec":0,"max_loss_streak":999,"account_size_usd":10000,"max_drawdown_pct":100.0,"max_daily_loss_pct":100.0,"max_notional_per_trade":1000000}}' || true
expect_2xx "${CURL_LAST_CODE}" "POST /api/risk/profiles (paper profile)"

CAPTURE_BODY=""
capture_json "${BASE}/api/runtime/role" -X POST "${HDR[@]}" -H "Content-Type: application/json" -d '{"role":"paper","active_risk_profile":"qa_ops_ui_api","execution_mode":"PAPER","allow_auto_approve":true,"allow_manual_execute":true}' || true
expect_2xx "${CURL_LAST_CODE}" "POST /api/runtime/role (paper runtime)"

CAPTURE_BODY=""
capture_json "${BASE}/api/strategies" -X POST "${HDR[@]}" -H "Content-Type: application/json" -d '{"strategy_id":"BASELINE_SCALP","role":"paper","enabled":true,"min_confidence":0.0,"min_score":0.0,"max_positions":200,"cooldown_sec":0,"params_json":{}}' || true
expect_2xx "${CURL_LAST_CODE}" "POST /api/strategies (paper baseline)"

CAPTURE_BODY=""
capture_json "${BASE}/api/unified/paper/publish" -X POST "${HDR[@]}" -H "Content-Type: application/json" -d "${PAPER_SIGNAL_BODY}" || true
expect_2xx "${CURL_LAST_CODE}" "POST /api/unified/paper/publish (approve scenario)"
PAPER_APPROVE_SIGNAL_ID="$(
python3 - "${CAPTURE_BODY}" <<'PY'
import json
import sys
try:
    obj = json.loads(sys.argv[1])
except Exception:
    print("")
    raise SystemExit(0)
sid = obj.get("id")
print("" if sid is None else sid)
PY
)"
[[ -n "${PAPER_APPROVE_SIGNAL_ID}" ]] || fail "missing signal id from paper publish (approve scenario)"

CAPTURE_BODY=""
capture_json "${BASE}/api/unified/paper/signals/${PAPER_APPROVE_SIGNAL_ID}/approve" -X POST "${HDR[@]}" -H "Content-Type: application/json" -d '{"note":"smoke_ops_ui_api_approve"}' || true
expect_2xx "${CURL_LAST_CODE}" "POST /api/unified/paper/signals/{id}/approve"
PAPER_APPROVE_TRACE_ID="$(
python3 - "${CAPTURE_BODY}" <<'PY'
import json
import sys
try:
    obj = json.loads(sys.argv[1])
except Exception:
    print("")
    raise SystemExit(0)
trace_id = str(obj.get("trace_id") or "").strip()
print(trace_id)
PY
)"
echo "paper_approve_ok=true signal_id=${PAPER_APPROVE_SIGNAL_ID}"

CAPTURE_BODY=""
capture_json "${BASE}/api/unified/paper/publish" -X POST "${HDR[@]}" -H "Content-Type: application/json" -d "${PAPER_SIGNAL_BODY}" || true
expect_2xx "${CURL_LAST_CODE}" "POST /api/unified/paper/publish (reject scenario)"
PAPER_REJECT_SIGNAL_ID="$(
python3 - "${CAPTURE_BODY}" <<'PY'
import json
import sys
try:
    obj = json.loads(sys.argv[1])
except Exception:
    print("")
    raise SystemExit(0)
sid = obj.get("id")
print("" if sid is None else sid)
PY
)"
[[ -n "${PAPER_REJECT_SIGNAL_ID}" ]] || fail "missing signal id from paper publish (reject scenario)"

CAPTURE_BODY=""
capture_json "${BASE}/api/unified/paper/signals/${PAPER_REJECT_SIGNAL_ID}/reject" -X POST "${HDR[@]}" -H "Content-Type: application/json" -d '{"reason":"smoke_ops_ui_api_reject","note":"smoke_ops_ui_api_reject"}' || true
expect_2xx "${CURL_LAST_CODE}" "POST /api/unified/paper/signals/{id}/reject"
echo "paper_reject_ok=true signal_id=${PAPER_REJECT_SIGNAL_ID}"

CAPTURE_BODY=""
capture_json "${BASE}/api/unified/paper/commands" -X POST "${HDR[@]}" -H "Content-Type: application/json" -d '{"cmd":"CLOSE_ALL_POSITIONS","params":{"reason":"smoke_ops_ui_api"}}' || true
expect_2xx "${CURL_LAST_CODE}" "POST /api/unified/paper/commands CLOSE_ALL_POSITIONS"
PAPER_CLOSE_CMD_ID="$(
python3 - "${CAPTURE_BODY}" <<'PY'
import json
import sys
try:
    obj = json.loads(sys.argv[1])
except Exception:
    print("")
    raise SystemExit(0)
cid = obj.get("command_id")
print("" if cid is None else cid)
PY
)"
[[ -n "${PAPER_CLOSE_CMD_ID}" ]] || fail "missing command_id from CLOSE_ALL_POSITIONS enqueue"
echo "paper_close_all_enqueue_ok=true command_id=${PAPER_CLOSE_CMD_ID}"

echo "== Dead-letter detail + requeue =="
CAPTURE_BODY=""
capture_json "${BASE}/api/unified/paper/commands" -X POST "${HDR[@]}" -H "Content-Type: application/json" -d '{"cmd":"TEST_ALWAYS_FAIL","params":{"source":"smoke_ops_ui_api_dead"}}' || true
expect_2xx "${CURL_LAST_CODE}" "POST /api/unified/paper/commands TEST_ALWAYS_FAIL"
PAPER_FAIL_CMD_ID="$(
python3 - "${CAPTURE_BODY}" <<'PY'
import json
import sys
try:
    obj = json.loads(sys.argv[1])
except Exception:
    print("")
    raise SystemExit(0)
cid = obj.get("command_id")
print("" if cid is None else cid)
PY
)"
[[ -n "${PAPER_FAIL_CMD_ID}" ]] || fail "missing command_id for TEST_ALWAYS_FAIL"

wait_for_command_status "paper" "${PAPER_FAIL_CMD_ID}" "DEAD" 90 >/dev/null || fail "paper TEST_ALWAYS_FAIL command ${PAPER_FAIL_CMD_ID} did not reach DEAD"

CAPTURE_BODY=""
capture_json "${BASE}/api/unified/dead_letters?role=paper&limit=200" "${HDR[@]}" || true
expect_2xx "${CURL_LAST_CODE}" "GET /api/unified/dead_letters?role=paper"
validate_json_shape "${CAPTURE_BODY}" "dead_letters"
PAPER_DEAD_LETTER_ID="$(dead_letter_id_for_command "${CAPTURE_BODY}" "${PAPER_FAIL_CMD_ID}")"
[[ -n "${PAPER_DEAD_LETTER_ID}" ]] || fail "could not locate dead_letter row for command_id=${PAPER_FAIL_CMD_ID}"

CAPTURE_BODY=""
capture_json "${BASE}/api/unified/dead_letters/detail?role=paper&id=${PAPER_DEAD_LETTER_ID}" "${HDR[@]}" || true
expect_2xx "${CURL_LAST_CODE}" "GET /api/unified/dead_letters/detail"
validate_json_shape "${CAPTURE_BODY}" "dead_letter_detail"
echo "dead_letter_detail_ok=true role=paper id=${PAPER_DEAD_LETTER_ID}"

CAPTURE_BODY=""
capture_json "${BASE}/api/unified/dead_letters/requeue" -X POST "${HDR[@]}" -H "Content-Type: application/json" -d "{\"role\":\"paper\",\"id\":${PAPER_DEAD_LETTER_ID}}" || true
expect_2xx "${CURL_LAST_CODE}" "POST /api/unified/dead_letters/requeue first"
REQUEUE_NEW_CMD_ID="$(
python3 - "${CAPTURE_BODY}" <<'PY'
import json
import sys
try:
    obj = json.loads(sys.argv[1])
except Exception:
    print("")
    raise SystemExit(0)
if bool(obj.get("idempotent")):
    print("")
else:
    cid = obj.get("new_command_id")
    print("" if cid is None else cid)
PY
)"
[[ -n "${REQUEUE_NEW_CMD_ID}" ]] || fail "expected first requeue to create new_command_id"
echo "dead_letter_requeue_first_ok=true new_command_id=${REQUEUE_NEW_CMD_ID}"

CAPTURE_BODY=""
capture_json "${BASE}/api/unified/dead_letters/requeue" -X POST "${HDR[@]}" -H "Content-Type: application/json" -d "{\"role\":\"paper\",\"id\":${PAPER_DEAD_LETTER_ID}}" || true
expect_2xx "${CURL_LAST_CODE}" "POST /api/unified/dead_letters/requeue second"
REQUEUE_IDEMPOTENT="$(
python3 - "${CAPTURE_BODY}" <<'PY'
import json
import sys
try:
    obj = json.loads(sys.argv[1])
except Exception:
    print("false")
    raise SystemExit(0)
print("true" if bool(obj.get("idempotent")) else "false")
PY
)"
REQUEUE_EXISTING_CMD_ID="$(
python3 - "${CAPTURE_BODY}" <<'PY'
import json
import sys
try:
    obj = json.loads(sys.argv[1])
except Exception:
    print("")
    raise SystemExit(0)
cid = obj.get("existing_command_id")
print("" if cid is None else cid)
PY
)"
[[ "${REQUEUE_IDEMPOTENT}" == "true" ]] || fail "expected second requeue to be idempotent=true"
[[ "${REQUEUE_EXISTING_CMD_ID}" == "${REQUEUE_NEW_CMD_ID}" ]] || fail "idempotent existing_command_id mismatch (expected ${REQUEUE_NEW_CMD_ID}, got ${REQUEUE_EXISTING_CMD_ID})"
echo "dead_letter_requeue_idempotent_ok=true existing_command_id=${REQUEUE_EXISTING_CMD_ID}"

echo "== Audit traces/detail/replay =="
CAPTURE_BODY=""
capture_json "${BASE}/api/audit/traces?limit=50&role=paper" "${HDR[@]}" || true
expect_2xx "${CURL_LAST_CODE}" "GET /api/audit/traces?role=paper"
validate_json_shape "${CAPTURE_BODY}" "audit_traces"
AUDIT_TRACE_ID="${PAPER_APPROVE_TRACE_ID:-}"
if [[ -z "${AUDIT_TRACE_ID}" ]]; then
  AUDIT_TRACE_ID="$(first_trace_id "${CAPTURE_BODY}")"
fi
[[ -n "${AUDIT_TRACE_ID}" ]] || fail "could not resolve audit trace_id for replay test"
echo "audit_trace_pick_ok=true trace_id=${AUDIT_TRACE_ID}"

CAPTURE_BODY=""
capture_json "${BASE}/api/audit/trace/${AUDIT_TRACE_ID}" "${HDR[@]}" || true
expect_2xx "${CURL_LAST_CODE}" "GET /api/audit/trace/{trace_id}"
validate_json_shape "${CAPTURE_BODY}" "audit_trace_detail"
echo "audit_trace_detail_ok=true trace_id=${AUDIT_TRACE_ID}"

CAPTURE_BODY=""
capture_json "${BASE}/api/audit/replay/paper" -X POST "${HDR[@]}" -H "Content-Type: application/json" -d "{\"trace_id\":\"${AUDIT_TRACE_ID}\",\"mode\":\"replay\"}" || true
expect_2xx "${CURL_LAST_CODE}" "POST /api/audit/replay/paper"
validate_json_shape "${CAPTURE_BODY}" "audit_replay"
AUDIT_REPLAY_CMD_ID="$(
python3 - "${CAPTURE_BODY}" <<'PY'
import json
import sys
try:
    obj = json.loads(sys.argv[1])
except Exception:
    print("")
    raise SystemExit(0)
cid = obj.get("new_command_id") or obj.get("command_id") or obj.get("existing_command_id")
print("" if cid is None else cid)
PY
)"
AUDIT_REPLAY_NEW_TRACE_ID="$(
python3 - "${CAPTURE_BODY}" <<'PY'
import json
import sys
try:
    obj = json.loads(sys.argv[1])
except Exception:
    print("")
    raise SystemExit(0)
print(str(obj.get("new_trace_id") or "").strip())
PY
)"
[[ -n "${AUDIT_REPLAY_CMD_ID}" ]] || fail "missing command id from audit replay response"
echo "audit_replay_ok=true command_id=${AUDIT_REPLAY_CMD_ID} new_trace_id=${AUDIT_REPLAY_NEW_TRACE_ID:-none}"

CAPTURE_BODY=""
capture_json "${BASE}/api/unified/paper/commands?limit=300" "${HDR[@]}" || true
expect_2xx "${CURL_LAST_CODE}" "GET /api/unified/paper/commands (replay verify)"
validate_json_shape "${CAPTURE_BODY}" "commands"
REPLAY_OLD_TRACE="$(
command_param_field_for_id "${CAPTURE_BODY}" "${AUDIT_REPLAY_CMD_ID}" "old_trace_id"
)"
[[ "${REPLAY_OLD_TRACE}" == "${AUDIT_TRACE_ID}" ]] || fail "replay command old_trace_id mismatch (expected ${AUDIT_TRACE_ID}, got ${REPLAY_OLD_TRACE})"
echo "audit_replay_link_ok=true command_id=${AUDIT_REPLAY_CMD_ID} old_trace_id=${REPLAY_OLD_TRACE}"

echo "✅ smoke_ops_ui_api passed"
