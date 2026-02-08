# PATCH NOTES: Nautilus Migration (Phase A + Phase B Skeleton)

Date: 2026-02-08 (UTC)
Workspace: `/Users/minasamir/projects/Trading`

## Summary
This patch removes legacy Mina dashboard services from runtime and moves Mina unified API behavior into Gateway using Postgres-backed reads/writes.

Kept intact:
- Fixed event contracts (`SignalEvent`, `TradeEvent`, `HealthEvent`) with `trace_id`, `decision_id`, `schema_version`
- Gateway, Brain, Postgres, and one unified dashboard path (Brain UI -> Gateway)
- Postgres role schemas: `mina_paper`, `mina_live`, `mina_pump`
- Gateway schema: `gateway`
- Gateway API key (`X-API-Key`) behavior where already enforced

Removed from runtime stack:
- `mina_dashboard_paper`
- `mina_dashboard_live`
- `mina_dashboard_pump`

## Phase A: Gateway DB-Backed Unified Endpoints

### New module
Added `gateway/gateway_api/mina_pg.py`:
- DSN fallback order: `TRADING_PG_DSN` -> `DATABASE_URL` -> `postgresql://trading:trading@postgres:5432/trading`
- Helpers:
  - `safe_execute(schema, sql, params, ...)` (missing-table safe)
  - `now_utc_iso()`
  - `now_ms()`
- Role->schema mapping:
  - `paper` -> `mina_paper`
  - `live` -> `mina_live`
  - `pump` -> `mina_pump`
- DB-backed accessors for health, stats, signals, logs, commands, positions, publish, approve/reject flow, snapshots

### Gateway endpoint behavior switched to DB-backed Mina
Updated `gateway/gateway_api/main.py` to serve Mina unified/runtime endpoints without dashboard service dependency:
- `GET /api/unified/roles`
- `GET /api/unified/overview`
- `GET /api/unified/{role}/snapshot`
- `GET /api/unified/{role}/system_health`
- `GET /api/unified/{role}/stats`
- `GET /api/unified/{role}/signals?limit=...`
- `POST /api/unified/{role}/signals/{id}/approve`
- `POST /api/unified/{role}/signals/{id}/reject`
- `POST /api/unified/{role}/commands`
- `GET /api/unified/{role}/logs?limit=...`
- `GET /api/unified/{role}/positions`
- `POST /api/unified/{role}/publish`
- alias kept: `POST /api/unified/{role}/signals/publish`

Signal approve workflow now DB-backed:
- fetch inbox row + payload merge
- validate/normalize symbol + side
- update signal status transitions
- queue `EXECUTE_SIGNAL` into `{schema}.commands`

System health logic mirrors Mina dashboard health behavior by reading Postgres settings/logs directly.

### Legacy Mina route compatibility
Legacy `/api/mina/{role}/...` now:
- maps key routes to DB-backed unified behavior where possible, OR
- returns HTTP `410` JSON for unmapped dashboard-only routes with guidance to `/api/unified/...`

Backward compatibility principle preserved: key script paths continue to work without dashboard services.

### Non-Mina behavior kept
- `/api/audit` behavior unchanged
- Brain proxy endpoints (`/api/decision`, etc.) unchanged

## Compose Changes

### `docker-compose.yml`
- removed `mina_dashboard_*` services
- removed gateway env dependencies `MINA_*_URL`
- kept:
  - `TRADING_PG_DSN`
  - `BRAIN_API_URL`

### `docker-compose.bots.yml`
- removed `depends_on` dashboard services
- bots/monitors now publish to Gateway unified endpoints:
  - paper: `http://gateway_api:8200/api/unified/paper/publish`
  - live: `http://gateway_api:8200/api/unified/live/publish`
  - pump: `http://gateway_api:8200/api/unified/pump/publish`
- `DASHBOARD_URL` pointed to Gateway base (`http://gateway_api:8200`)

## Script Changes
Updated:
- `scripts/phase3_bots_up.sh`
  - dashboard DB-ready checks replaced with Gateway unified health checks
- `scripts/phase3_apply_safe_defaults.sh`
  - role `DASHBOARD_PUBLISH_URL` defaults point to Gateway unified publish endpoints
- smoke scripts adapted for DB-backed responses + compatibility:
  - `scripts/smoke_unified.sh`
  - `scripts/smoke_all.sh`
  - `scripts/smoke_signals.sh`
  - `scripts/smoke_signal_decision.sh`
- fixed request construction bug in:
  - `scripts/smoke_actions.sh`

## Phase B Skeleton Added (non-blocking)

### `services/nautilus_engine`
Added skeleton executor service:
- polls pending role commands from Postgres
- claim lifecycle (`PENDING` -> `CLAIMED` -> `DONE`/`REJECTED`)
- supports at least:
  - `EXECUTE_SIGNAL`
  - `CLOSE_ALL_POSITIONS`
  - `CLOSE_TRADE`
- writes simulated trades/logs/events/trade_events in paper-safe mode
- kill-switch rule enforced:
  - blocks opening trades when enabled
  - allows close commands always

### `services/mina_strategies`
Added strategy-only publisher skeleton:
- emits signal payloads with `trace_id`/`decision_id`/`schema_version`
- no execution ownership
- publishes only through Gateway unified publish endpoint

### Compose wiring
`docker-compose.bots.yml` now includes optional `phaseb` profile services:
- `nautilus_engine`
- `mina_strategies`

## Run Instructions

```bash
export COMPOSE_PROJECT_NAME=trading_migration

docker compose -f docker-compose.yml up -d --build
docker compose -f docker-compose.yml -f docker-compose.bots.yml up -d --build

docker compose -f docker-compose.yml -f docker-compose.bots.yml ps
```

Optional Phase B profile:

```bash
docker compose -f docker-compose.yml -f docker-compose.bots.yml --profile phaseb up -d --build
```

## Safety + Compatibility Notes
- Live trading remains policy-gated; no default change to force live execution.
- Kill-switch logic preserves close-path allowance while blocking opens when enabled.
- UTC timestamp handling preserved.
- No breaking table/column removals were introduced in this migration path.
