#!/usr/bin/env bash
ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$ROOT" || true
set -euo pipefail

compose=(docker compose)
if [[ -f docker-compose.allinone.yml ]]; then
  compose+=( -f docker-compose.allinone.yml )
fi

run_in_gateway() {
  "${compose[@]}" exec -T gateway_api sh -lc "$1"
}

SCRIPT='set -e
ok=1
key="${DASHBOARD_API_KEY:-trading-dev}"
hdr=""
if [ -n "$key" ]; then
  hdr="X-API-Key: ${key}"
fi
check() {
  name="$1"; url="$2"; url2="$3"
  if [ -n "$hdr" ]; then
    if curl -sf -H "$hdr" "$url" >/dev/null || ( [ -n "$url2" ] && curl -sf -H "$hdr" "$url2" >/dev/null ); then
      echo "OK  - $name"
    else
      echo "FAIL- $name"
      ok=0
    fi
  else
    if curl -sf "$url" >/dev/null || ( [ -n "$url2" ] && curl -sf "$url2" >/dev/null ); then
      echo "OK  - $name"
    else
      echo "FAIL- $name"
      ok=0
    fi
  fi
}

check "brain_api /health" "http://brain_api:8100/healthz" "http://brain_api:8100/health"
check "brain_api /api/overview" "http://brain_api:8100/api/overview"

check "mina_paper /health" "http://mina_dashboard_paper:8000/healthz" "http://mina_dashboard_paper:8000/health"
check "mina_paper /api/system_health" "http://mina_dashboard_paper:8000/api/system_health"

check "mina_live /health" "http://mina_dashboard_live:8001/healthz" "http://mina_dashboard_live:8001/health"
check "mina_live /api/system_health" "http://mina_dashboard_live:8001/api/system_health"

check "mina_pump /health" "http://mina_dashboard_pump:8002/healthz" "http://mina_dashboard_pump:8002/health"
check "mina_pump /api/system_health" "http://mina_dashboard_pump:8002/api/system_health"

exit $((1-ok))
'

echo "== Connectivity matrix from gateway_api =="
run_in_gateway "$SCRIPT"
