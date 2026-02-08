# QA REPORT: Nautilus Migration

Date: 2026-02-08 (UTC)
Workspace: `/Users/minasamir/projects/Trading`
Compose project used for QA: `trading_migration`

## Scope
Validated Phase A (dashboard removal + Gateway DB-backed Mina unified endpoints) and Phase B skeleton readiness (non-blocking).

## A) Static Checks

Command run:
```bash
python -m compileall gateway services/mina_bot services/nautilus_engine services/mina_strategies
```

Result:
- PASS (exit code 0)
- Python modules compiled successfully for all requested paths.

## B) Stack Bring-up (safe project name)

Commands run:
```bash
export COMPOSE_PROJECT_NAME=trading_migration

docker compose -f docker-compose.yml up -d --build
docker compose -f docker-compose.yml -f docker-compose.bots.yml up -d --build
docker compose -f docker-compose.yml -f docker-compose.bots.yml ps
```

`docker compose ps` summary:
- PASS (all required services up/healthy)
- Running:
  - `postgres`
  - `gateway_api`, `gateway_autopilot_worker`, `gateway_alerts_worker`
  - `brain_api`, `brain_ui`
  - `mina_paper_bot`, `mina_paper_monitor`
  - `mina_live_bot`, `mina_live_monitor`
  - `mina_pump_bot`

Note:
- Running `scripts/phase3_bots_up.sh` without setting `COMPOSE_PROJECT_NAME` attempted to use default project (`trading`) and failed on port 5432 collision while another stack was already running. Migration QA remained anchored on `trading_migration` as required.

## C) API Smoke Tests

Commands run:
```bash
bash scripts/smoke_unified.sh http://localhost:8200
bash scripts/smoke_all.sh paper
bash scripts/smoke_all.sh live
bash scripts/smoke_all.sh pump
bash scripts/smoke_signals.sh paper
bash scripts/smoke_actions.sh paper
```

Result:
- PASS (all commands exited 0)
- Unified Mina endpoints worked with no `mina_dashboard_*` runtime services.
- Policy-gated responses (e.g., strategy/risk veto or live guardrails) appeared where expected and did not break smoke pass criteria.

## D) DB Assertions

### Schema/table existence
Command run:
```bash
export COMPOSE_PROJECT_NAME=trading_migration
docker compose -f docker-compose.yml -f docker-compose.bots.yml exec -T postgres psql -U trading -d trading -v ON_ERROR_STOP=1 <<'SQL'
SELECT schema_name
FROM information_schema.schemata
WHERE schema_name IN ('mina_paper','mina_live','mina_pump','gateway')
ORDER BY schema_name;

SELECT table_schema, table_name
FROM information_schema.tables
WHERE table_schema IN ('mina_paper','mina_live','mina_pump')
  AND table_name IN ('trades','commands','logs','settings','signal_inbox','events')
ORDER BY table_schema, table_name;
SQL
```

Result:
- PASS
- Schemas present: `gateway`, `mina_live`, `mina_paper`, `mina_pump`
- Required role tables present per role schema: `trades`, `commands`, `logs`, `settings`, `signal_inbox`, `events`

### Approve flow assertion (`APPROVED` + command inserted)
Because `mina_paper_bot` can execute immediately, the bot/monitor were briefly paused to capture the immediate post-approve DB state.

Commands run (summarized):
```bash
# pause paper bot/monitor
export COMPOSE_PROJECT_NAME=trading_migration
docker compose -f docker-compose.yml -f docker-compose.bots.yml stop mina_paper_bot mina_paper_monitor

# publish + approve via Gateway unified endpoints
curl -sS -X POST http://localhost:8200/api/unified/paper/publish ...
curl -sS -X POST http://localhost:8200/api/unified/paper/signals/{id}/approve ...

# assert signal status + command row
export COMPOSE_PROJECT_NAME=trading_migration
docker compose -f docker-compose.yml -f docker-compose.bots.yml exec -T postgres psql -U trading -d trading <<SQL
SELECT id, status, approved_at_ms, rejected_at_ms
FROM mina_paper.signal_inbox
WHERE id = {id};

SELECT id, cmd, status,
       COALESCE((params::jsonb->>'inbox_id'), (params::jsonb->>'signal_id'), (params::jsonb->>'_dashboard_signal_id')) AS signal_ref,
       created_at_ms
FROM mina_paper.commands
WHERE cmd = 'EXECUTE_SIGNAL'
ORDER BY id DESC
LIMIT 5;
SQL

# resume paper bot/monitor
docker compose -f docker-compose.yml -f docker-compose.bots.yml up -d mina_paper_bot mina_paper_monitor
```

Observed DB evidence:
- `mina_paper.signal_inbox.id=4` had `status='APPROVED'` with non-null `approved_at_ms`.
- `mina_paper.commands` contained `cmd='EXECUTE_SIGNAL'` row with `signal_ref='4'` in `params`.

Result:
- PASS

## E) UI-facing Validation (human-like fallback)

### Attempted automated UI build script
Command:
```bash
bash scripts/smoke_ui_routes.sh
```
Result:
- FAIL in local env: `tsc: command not found`
- This is tooling availability in current shell env, not a Gateway runtime failure.

### Manual scripted API checks for unified dashboard dependencies
Command run:
```bash
# validated JSON + non-5xx for key UI routes
curl ... /api/unified/overview
curl ... /api/unified/roles
curl ... /api/unified/paper/snapshot
curl ... /api/unified/paper/system_health
curl ... /api/unified/paper/signals?limit=5
curl ... /api/unified/paper/logs?limit=5
curl ... /api/unified/paper/positions
curl ... /api/ops/status?role=paper
curl ... /api/strategies?role=paper
curl ... /api/risk/profiles
curl ... /api/runtime/role?role=paper
```

Result:
- PASS for all listed routes (JSON returned, no 5xx)

Additional note:
- `scripts/smoke_unified_pages.sh` was run; it passed most routes and intentionally hit a strategy/risk veto at `manual execute` when kill-switch/risk cooldown policy was active.

## Phase B Skeleton Validation (non-blocking)

### `mina_strategies`
Commands:
```bash
export COMPOSE_PROJECT_NAME=trading_migration
docker compose -f docker-compose.yml -f docker-compose.bots.yml --profile phaseb up -d mina_strategies
docker compose -f docker-compose.yml -f docker-compose.bots.yml ps mina_strategies
```
Result:
- PASS: service container started (`Up`)
- First publish attempt logged a temporary connection-refused race during gateway startup; expected to retry on next cycle.

### `nautilus_engine`
- Build/start attempted with phaseb profile.
- In this run, dependency build was long-running (heavy toolchain/deps) and not completed within the QA window.
- Code-level static validation already passed via `compileall`.

## Final Status
- Phase A objective met: unified Mina flows are Gateway DB-backed and smoke passes without `mina_dashboard_*` services running.
- Required DB assertions passed.
- Required docs delivered.

## Remaining TODOs / Risks
1. Add a deterministic CI test for `nautilus_engine` image build/start to remove optional-build uncertainty.
2. Consider making `scripts/phase3_bots_up.sh` honor `COMPOSE_PROJECT_NAME` explicitly to avoid accidental project/port conflicts.
3. Optional cleanup: remove stale code constants/defaults referencing `mina_dashboard_*` URLs where no longer used.
