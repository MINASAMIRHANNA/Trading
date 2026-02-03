#!/usr/bin/env bash
set -euo pipefail

GATEWAY="http://localhost:8200"
BRAIN="http://localhost:8100"

echo "BASE gateway=$GATEWAY brain=$BRAIN"

echo ""
echo "== Health (gateway) =="
curl -s "$GATEWAY/health" | jq

echo ""
echo "== Health (brain_api) =="
curl -s "$BRAIN/health" | jq

echo ""
echo "== Unified overview (gateway) =="
curl -s "$GATEWAY/api/unified/overview" | jq '.schema_version,.ts_utc,.brain,.dashboards.paper.stats'

echo ""
echo "== Mina paper snapshot (via gateway) =="
curl -s "$GATEWAY/api/mina/paper/snapshot" | jq '.role,.system_health.backend,.stats'

echo ""
echo "== Mina live snapshot (via gateway) =="
curl -s "$GATEWAY/api/mina/live/snapshot" | jq '.role,.system_health.backend,.stats'

echo ""
echo "== Mina pump snapshot (via gateway) =="
curl -s "$GATEWAY/api/mina/pump/snapshot" | jq '.role,.system_health.backend,.stats'

echo ""
echo "== Brain sync (paper, limit=500) =="
# jq will fail if endpoint returns non-JSON; in that case show raw response.
RESP="$(curl -s -X POST "$BRAIN/api/sync/run?role=paper&limit=500" || true)"
echo "$RESP" | jq . 2>/dev/null || { echo "$RESP"; echo "(non-JSON response)"; }

echo ""
echo "== Brain trade_features count =="
docker exec -it trading-postgres-1 psql -U trading -d trading -c "select count(*) as trade_features from brain.trade_features;"

echo ""
echo "✅ Batch-35 smoke done."
