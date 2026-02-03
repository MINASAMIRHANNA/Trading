# Trading (Monorepo)

Single unified repo that contains:
- Mina_Bot (execution + risk + pump hunter + dashboards)
- Brain (trading-intelligence-platform: analytics/ML/decision + dashboard)
- Gateway (API gateway + official home of shared contracts)

## Folders
- services/mina_bot/
- services/brain/
- gateway/ (Contracts v1 in gateway/shared_contracts/)
- docs/ (ports, runbook, checklist)
- phase0_artifacts/ (Phase 0 snapshots)

## Ports (Phase 0)
- Mina_Bot: 8000 (paper), 8001 (live), 8002 (pump)
- Brain API: 8100
- Brain UI (Vite): 5173 (or 5174 if busy)

## Quick start (local)
See `docs/DEV_COMMANDS.md`.

## GitHub
See `docs/GITHUB_SETUP.md`.


## Batch-30 (Gateway Unified Endpoints)
- Gateway unified overview: `GET /api/unified/overview`
- Role snapshot: `GET /api/unified/{paper|live|pump}/snapshot`
- Run: `bash scripts/smoke_unified.sh`


## Runbook

See `docs/RUNBOOK.md` for Docker start/stop, seed, smoke tests, and troubleshooting.


## Docker (All-in-one)

See: `docs/DOCKER_ALLINONE.md`
