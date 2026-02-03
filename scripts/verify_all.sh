#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8200}"
ROLE="${ROLE:-paper}"
ROLES="${ROLES:-$ROLE}"

echo
echo "=============================="
echo " Trading verify_all"
echo "=============================="
echo "BASE_URL=$BASE_URL"
echo "ROLES=$ROLES"
echo

curl_json() {
  # args: url
  curl -sS --max-time 5 "$1"
}

check_http_ok() {
  # args: url label
  local url="$1"
  local label="${2:-$1}"
  local code
  code="$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "$url" || true)"
  if [[ "$code" == "200" ]]; then
    echo "✅ $label"
    return 0
  fi
  echo "❌ $label (HTTP $code)"
  curl_json "$url" || true
  return 1
}

check_http_any() {
  # args: url label acceptable_codes_csv
  local url="$1"; local label="$2"; local ok_codes="${3:-200}"
  local code
  code="$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "$url" || true)"
  if [[ ",$ok_codes," == *",$code,"* ]]; then
    echo "✅ $label (HTTP $code)"
    return 0
  fi
  echo "❌ $label (HTTP $code)"
  curl_json "$url" || true
  return 1
}

echo
echo "=============================="
echo " Gateway health"
echo "=============================="
check_http_ok "$BASE_URL/health" "gateway /health" || exit 1
check_http_ok "$BASE_URL/openapi.json" "gateway openapi" || exit 1

echo
echo "=============================="
echo " Unified endpoints (Gateway)"
echo "=============================="
check_http_ok "$BASE_URL/api/overview" "unified overview" || exit 1
check_http_ok "$BASE_URL/api/paper/signals" "paper signals" || exit 1
check_http_ok "$BASE_URL/api/paper/positions" "paper positions" || exit 1

echo
echo "=============================="
echo " Events endpoints"
echo "=============================="
check_http_ok "$BASE_URL/api/events?limit=5" "events list" || exit 1

# SSE: confirm we at least get the initial ': connected' comment OR an event id line.
SSE_SNIP="$( (timeout 3 curl -sN --no-buffer -H "Accept:text/event-stream" "$BASE_URL/api/events/stream?since_id=0" || true) | head -n 3 || true )"
if echo "$SSE_SNIP" | grep -qE "connected|^id:"; then
  echo "✅ events SSE reachable"
else
  echo "⚠️  events SSE not confirmed (may be fine)"
fi

echo
echo "=============================="
echo " Brain direct (optional)"
echo "=============================="
if check_http_ok "http://localhost:8100/health" "brain /health" 2>/dev/null; then
  check_http_ok "http://localhost:8100/api/overview" "brain /api/overview" || true
  check_http_ok "http://localhost:8100/api/decision" "brain /api/decision" || true
  check_http_ok "http://localhost:8100/api/ml/importance" "brain /api/ml/importance" || true
  check_http_ok "http://localhost:8100/api/sync/status" "brain /api/sync/status" || true
else
  echo "ℹ️  brain direct not reachable on localhost:8100 (this can be OK if you only use gateway)"
fi

echo
echo "=============================="
echo " Brain via gateway"
echo "=============================="
check_http_ok "$BASE_URL/api/brain/probe" "brain probe" || exit 1
check_http_ok "$BASE_URL/api/brain/overview" "brain overview via gateway" || exit 1
check_http_ok "$BASE_URL/api/brain/decision" "brain decision via gateway" || exit 1
check_http_ok "$BASE_URL/api/brain/ml/importance" "brain importance via gateway" || exit 1
check_http_ok "$BASE_URL/api/brain/sync/status" "brain sync status via gateway" || exit 1

echo
echo "=============================="
echo " Brain sync run (roles)"
echo "=============================="
IFS=',' read -ra _roles <<< "$ROLES"
for r in "${_roles[@]}"; do
  r="$(echo "$r" | xargs)"
  [[ -z "$r" ]] && continue
  echo "➡️  sync/run role=$r"
  # We don't hard-fail on inserted=0; we only fail on HTTP errors.
  check_http_any "$BASE_URL/api/brain/sync/run?role=$r" "brain sync run ($r)" "200,201" || exit 1
done

echo
echo "=============================="
echo " Smoke test (paper)"
echo "=============================="
if [[ -f scripts/smoke_all.sh ]]; then
  # run a small smoke focused on paper unless overridden
  ROLE_FOR_SMOKE="${ROLE_FOR_SMOKE:-paper}"
  OUT="/tmp/smoke_${ROLE_FOR_SMOKE}_verify.log"
  (bash scripts/smoke_all.sh "$ROLE_FOR_SMOKE" || true) | tee "$OUT" >/dev/null
  echo "ℹ️  wrote $OUT"
else
  echo "⚠️  scripts/smoke_all.sh missing"
fi

echo
echo "=============================="
echo " Docker summary"
echo "=============================="
docker compose ps || true

echo
echo "✅ verify_all finished."
