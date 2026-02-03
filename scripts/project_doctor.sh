#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

BASE_URL="${BASE_URL:-http://localhost:8200}"
BRAIN_URL="${BRAIN_URL:-http://localhost:8100}"

need() { command -v "$1" >/dev/null 2>&1 || { echo "❌ missing dependency: $1"; exit 1; }; }
need curl
need jq
need docker

echo
echo "=============================="
echo " Trading Project Doctor"
echo "=============================="
echo "ℹ️  Project root: $ROOT"
echo "ℹ️  BASE_URL:  $BASE_URL"
echo "ℹ️  BRAIN_URL: $BRAIN_URL"
echo "ℹ️  Dashboards: paper=http://localhost:8000 live=http://localhost:8001 pump=http://localhost:8002"
echo "ℹ️  Compose: ${COMPOSE_FILE:-$ROOT/docker-compose.yml}"

section(){ echo; echo "------------------------------"; echo " $*"; echo "------------------------------"; }

section "Docker Compose status"
if [[ -f "${COMPOSE_FILE:-$ROOT/docker-compose.yml}" ]]; then
  docker compose -f "${COMPOSE_FILE:-$ROOT/docker-compose.yml}" ps || true
  echo
  echo "Compose services:"
  docker compose -f "${COMPOSE_FILE:-$ROOT/docker-compose.yml}" config --services | sed 's/^/  - /'
else
  echo "⚠️  docker-compose.yml not found at $ROOT"
fi

is_running() { docker compose -f "${COMPOSE_FILE:-$ROOT/docker-compose.yml}" ps --status=running -q "$1" >/dev/null 2>&1; }

is_running gateway_api && echo "✅ gateway_api running" || echo "⚠️  gateway_api NOT running"
is_running postgres && echo "✅ postgres running" || echo "⚠️  postgres NOT running"
is_running brain_api && echo "✅ brain_api running" || echo "⚠️  brain_api NOT running (may be crash-looping)"
is_running mina_dashboard_paper && echo "✅ mina_dashboard_paper running" || echo "⚠️  mina_dashboard_paper NOT running"
is_running mina_dashboard_live && echo "✅ mina_dashboard_live running" || echo "⚠️  mina_dashboard_live NOT running"
is_running mina_dashboard_pump && echo "✅ mina_dashboard_pump running" || echo "⚠️  mina_dashboard_pump NOT running"

section "Gateway health & routes"
if curl -fsS "$BASE_URL/health" >/dev/null; then echo "✅ Gateway /health OK"; curl -s "$BASE_URL/health" | jq .; else echo "❌ Gateway /health FAIL"; fi

# OpenAPI may not be JSON if gateway is not ready; be tolerant
if curl -fsS "$BASE_URL/openapi.json" >/dev/null; then
  echo "✅ Gateway OpenAPI reachable"
  if curl -fsS "$BASE_URL/openapi.json" | jq -e '.paths' >/dev/null 2>&1; then
    echo "✅ OpenAPI JSON valid"
    # a couple of important routes
    for p in "/api/unified/overview" "/api/events" "/api/brain/{path:path}"; do
      if curl -fsS "$BASE_URL/openapi.json" | jq -e --arg p "$p" '.paths[$p]' >/dev/null 2>&1; then
        echo "✅ Route present: $p"
      else
        echo "⚠️  Route missing in OpenAPI: $p"
      fi
    done
  else
    echo "⚠️  OpenAPI not valid JSON (gateway might still be starting)"
  fi
else
  echo "⚠️  Gateway OpenAPI not reachable"
fi

section "Events API (Gateway)"
if curl -fsS "$BASE_URL/api/events?limit=5" >/dev/null; then
  echo "✅ GET /api/events OK"
  curl -s "$BASE_URL/api/events?limit=5" | jq .
else
  echo "❌ GET /api/events FAIL"
fi

echo
echo "SSE /api/events/stream:"
if command -v timeout >/dev/null 2>&1; then
  if timeout 2s curl -Ns "$BASE_URL/api/events/stream" | head -n 2 | grep -E "data:|event:|:" >/dev/null 2>&1; then
    echo "OK"
  else
    echo "⚠️  SSE not confirmed (may be fine)"
  fi
else
  echo "⚠️  timeout not available; skipping"
fi

section "Brain API"
if curl -fsS "$BRAIN_URL/health" >/dev/null; then
  echo "✅ Brain direct /health OK"
else
  echo "⚠️  Brain direct /health FAIL. Trying gateway proxy..."
fi

for url in \
  "$BASE_URL/api/brain/health" \
  "$BASE_URL/api/brain/overview" \
  "$BASE_URL/api/brain/decision?symbol=BTCUSDT" \
  "$BASE_URL/api/brain/ml/importance" \
  "$BASE_URL/api/brain/sync/status" \
  "$BASE_URL/api/brain/sync/run?role=paper"
do
  code="$(curl -s -o /dev/null -w "%{http_code}" "$url" || true)"
  if [[ "$code" == "200" ]]; then
    echo "✅ Gateway->Brain OK: $url"
  else
    echo "⚠️  Gateway->Brain FAIL: $url (HTTP $code)"
  fi
done

section "Mina Dashboards (direct checks)"
for port in 8000 8001 8002; do
  url="http://localhost:${port}/"
  code="$(curl -s -o /dev/null -w "%{http_code}" "$url" || true)"
  if [[ "$code" =~ ^2|3 ]]; then
    echo "✅ Dashboard on :$port reachable (HTTP $code)"
  else
    echo "⚠️  Dashboard on :$port not reachable (HTTP $code)"
  fi
done

section "Postgres sanity checks"
if is_running postgres; then
  PG_CID="$(docker compose -f "${COMPOSE_FILE:-$ROOT/docker-compose.yml}" ps -q postgres | head -n 1)"
  echo "✅ Running psql checks inside postgres container..."
  docker exec -i "$PG_CID" psql -U trading -d trading -c "select schema_name from information_schema.schemata where schema_name like 'mina_%' order by 1;" || true
  echo
  docker exec -i "$PG_CID" psql -U trading -d trading -c "select table_schema, table_name from information_schema.tables where table_name in ('signal_inbox','trades') and table_schema like 'mina_%' order by 1,2;" || true
  echo
  docker exec -i "$PG_CID" psql -U trading -d trading -c "select count(*) as shared_events from information_schema.tables where table_name='shared_events';" || true
else
  echo "⚠️  postgres not running; skipping DB checks"
fi

section "Recent error scan (logs)"
for svc in gateway_api brain_api mina_dashboard_paper mina_dashboard_live mina_dashboard_pump; do
  echo "-- $svc --"
  docker compose -f "${COMPOSE_FILE:-$ROOT/docker-compose.yml}" logs --tail=60 "$svc" 2>/dev/null | egrep -i "traceback|error|exception|failed|importerror|nameerror" || true
done

echo
echo "=============================="
echo " Doctor finished."
echo "=============================="
