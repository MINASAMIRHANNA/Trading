#!/usr/bin/env bash
set -euo pipefail

ROLE="${1:-paper}"
LIMIT="${2:-500}"
HOST="${BRAIN_API_HOST:-http://localhost:8100}"
URL="${HOST}/api/sync/run?role=${ROLE}&limit=${LIMIT}"

echo "== Sync Request =="
echo "POST ${URL}"
curl -i -s -X POST "${URL}"
echo

echo "== brain_api logs (tail 120) =="
docker compose -f docker-compose.allinone.yml logs --tail=120 brain_api
echo

echo "== trade_features count =="
SCHEMA="${BRAIN_SCHEMA:-brain}"
docker compose -f docker-compose.allinone.yml exec -T postgres sh -lc "PGPASSWORD=trading psql -U trading -d trading -c \"SELECT count(*) AS trade_features_count FROM ${SCHEMA}.trade_features;\""
