# Trading (Monorepo)

Single unified repo that contains:
- `mina_bot` role runtimes (paper/live/pump schemas)
- Brain (`brain_api` + unified dashboard UI)
- Gateway (single control plane/API + shared contracts)

## Folders
- services/mina_bot/
- services/brain/
- gateway/ (Contracts v1 in gateway/shared_contracts/)
- services/nautilus_engine/ (Phase B skeleton)
- services/mina_strategies/ (Phase B skeleton)
- docs/ (ports, runbook, checklist)
- phase0_artifacts/ (Phase 0 snapshots)

## Runtime Architecture
- Unified UI calls Gateway only (`/api/unified/*`, `/api/decision`, `/api/audit`, ...).
- Gateway is DB-backed for Mina roles (`mina_paper`, `mina_live`, `mina_pump`) and keeps `gateway` schema audit/queue state.
- Legacy `mina_dashboard_*` services are removed from the runtime stack.
- Fixed events contracts remain in place (`SignalEvent`, `TradeEvent`, `HealthEvent`) with `trace_id`, `decision_id`, `schema_version`.

## Ports
- Gateway API: 8200
- Brain API: 8100
- Brain UI (Vite): 5173
- Postgres: 5432

## Quick Start (Full Stack)
```bash
export COMPOSE_PROJECT_NAME=trading_migration
docker compose -f docker-compose.yml up -d --build
docker compose -f docker-compose.yml -f docker-compose.bots.yml up -d --build
docker compose -f docker-compose.yml -f docker-compose.bots.yml ps
```

## GitHub
See `docs/GITHUB_SETUP.md`.

## Core Unified Endpoints
- `GET /api/unified/overview`
- `GET /api/unified/{paper|live|pump}/snapshot`
- `POST /api/unified/{paper|live|pump}/publish`
- `POST /api/unified/{paper|live|pump}/signals/{id}/approve`
- `POST /api/unified/{paper|live|pump}/commands`

## Runbook

See `docs/RUNBOOK.md` for Docker start/stop, seed, smoke tests, and troubleshooting.


## Docker (All-in-one)

See: `docs/DOCKER_ALLINONE.md`
