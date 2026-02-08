#!/usr/bin/env bash
set -euo pipefail

# Writes safe defaults to Postgres settings tables (so bots won't place exchange orders).
# Default: mode=PAPER + ENABLE_LIVE_TRADING=FALSE across live/paper/pump.

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "== Phase 3: apply safe defaults to Postgres settings =="

docker compose exec -T postgres psql -U trading -d trading <<'SQL'
-- Safe defaults (Phase 3)
-- NOTE: settings.value is TEXT; Mina config normalizes booleans.

INSERT INTO mina_live.settings(key, value, updated_at, source) VALUES
  ('mode','PAPER', now()::text, 'phase3'),
  ('USE_TESTNET','TRUE', now()::text, 'phase3'),
  ('ENABLE_LIVE_TRADING','FALSE', now()::text, 'phase3'),
  ('DASHBOARD_URL','http://gateway_api:8200', now()::text, 'phase3'),
  ('DASHBOARD_PUBLISH_URL','http://gateway_api:8200/api/unified/live/publish', now()::text, 'phase3')
ON CONFLICT (key) DO UPDATE SET
  value=EXCLUDED.value,
  updated_at=EXCLUDED.updated_at,
  source=EXCLUDED.source;

INSERT INTO mina_paper.settings(key, value, updated_at, source) VALUES
  ('mode','PAPER', now()::text, 'phase3'),
  ('USE_TESTNET','TRUE', now()::text, 'phase3'),
  ('ENABLE_LIVE_TRADING','FALSE', now()::text, 'phase3'),
  ('DASHBOARD_URL','http://gateway_api:8200', now()::text, 'phase3'),
  ('DASHBOARD_PUBLISH_URL','http://gateway_api:8200/api/unified/paper/publish', now()::text, 'phase3')
ON CONFLICT (key) DO UPDATE SET
  value=EXCLUDED.value,
  updated_at=EXCLUDED.updated_at,
  source=EXCLUDED.source;

INSERT INTO mina_pump.settings(key, value, updated_at, source) VALUES
  ('mode','PAPER', now()::text, 'phase3'),
  ('USE_TESTNET','TRUE', now()::text, 'phase3'),
  ('ENABLE_LIVE_TRADING','FALSE', now()::text, 'phase3'),
  ('DASHBOARD_URL','http://gateway_api:8200', now()::text, 'phase3'),
  ('DASHBOARD_PUBLISH_URL','http://gateway_api:8200/api/unified/pump/publish', now()::text, 'phase3')
ON CONFLICT (key) DO UPDATE SET
  value=EXCLUDED.value,
  updated_at=EXCLUDED.updated_at,
  source=EXCLUDED.source;

\echo 'OK'
SQL

echo "== Verify (mode) =="
docker compose exec -T postgres psql -U trading -d trading -c "SELECT key,value FROM mina_live.settings WHERE key IN ('mode','ENABLE_LIVE_TRADING','USE_TESTNET') ORDER BY key;"
docker compose exec -T postgres psql -U trading -d trading -c "SELECT key,value FROM mina_paper.settings WHERE key IN ('mode','ENABLE_LIVE_TRADING','USE_TESTNET') ORDER BY key;"
docker compose exec -T postgres psql -U trading -d trading -c "SELECT key,value FROM mina_pump.settings WHERE key IN ('mode','ENABLE_LIVE_TRADING','USE_TESTNET') ORDER BY key;"
