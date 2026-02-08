# QA REPORT: Phase E3 Unified Observability

Date: 2026-02-08 (UTC)  
Workspace: `/Users/minasamir/projects/Trading`  
Branch: `codex/nautilus-migration-phaseA`  
Compose project: `trading_migration`

## Scope
Validated Phase E3 deliverables:
- new unified observability endpoint across `paper/live/pump`
- role filter support
- smoke coverage for response shape and role summaries
- regression coverage for prior Phase D/E1/E2 smoke suite

## Commands Run
```bash
python -m compileall gateway services/mina_strategies services/nautilus_engine

export COMPOSE_PROJECT_NAME=trading_migration
docker compose -f docker-compose.yml up -d --build
docker compose -f docker-compose.yml -f docker-compose.bots.yml up -d --build
docker compose -f docker-compose.yml -f docker-compose.bots.yml ps

bash scripts/smoke_all.sh paper
bash scripts/smoke_all.sh live
bash scripts/smoke_all.sh pump
bash scripts/smoke_live_cutover.sh
bash scripts/smoke_pump_cutover.sh
bash scripts/smoke_consumer_reliability.sh
bash scripts/smoke_live_safety_gate.sh
bash scripts/smoke_observability.sh
```

## Compose Status
From `docker compose -f docker-compose.yml -f docker-compose.bots.yml ps`:
- `postgres`: Up (healthy)
- `gateway_api`: Up
- `brain_api`: Up (healthy)
- `brain_ui`: Up
- `nautilus_paper_engine`: Up
- `nautilus_live_engine`: Up
- `nautilus_pump_engine`: Up
- `gateway_alerts_worker`: Up
- `gateway_autopilot_worker`: Up

## Result Summary
- `compileall`: PASS
- `smoke_all.sh paper`: PASS
- `smoke_all.sh live`: PASS
- `smoke_all.sh pump`: PASS
- `smoke_live_cutover.sh`: PASS
- `smoke_pump_cutover.sh`: PASS
- `smoke_consumer_reliability.sh`: PASS
- `smoke_live_safety_gate.sh`: PASS
- `smoke_observability.sh`: PASS

## Phase E3 Evidence

### `smoke_observability.sh` output
```text
paper online=True last_claim=60/CLOSE_ALL_POSITIONS/DONE last_trade=3/SOLUSDT/CLOSED
live  online=True gate=CONFIRMED kill=False last_claim=94/KILL_SWITCH_OFF/DONE last_trade=17/SOLUSDT/CLOSED
pump  online=True last_claim=67/CLOSE_ALL_POSITIONS/DONE last_trade=11/RELIAB8562/CLOSED
errors_count=0
filtered_roles=live,paper
```

### API sample (`GET /api/unified/observability`)
```json
{
  "ok": true,
  "generated_at": "2026-02-08T13:35:29Z",
  "items": [
    {
      "role": "paper",
      "engine": {"name": "nautilus_paper_engine", "online": true, "last_seen_seconds": 16},
      "kill_switch": {"on": true, "reason": "smoke_unified"}
    },
    {
      "role": "live",
      "engine": {"name": "nautilus_live_engine", "online": true, "last_seen_seconds": 15},
      "live_gate": {"state": "CONFIRMED", "allowlist_count": 3}
    },
    {
      "role": "pump",
      "engine": {"name": "nautilus_pump_engine", "online": true, "last_seen_seconds": 15}
    }
  ],
  "errors": []
}
```

## Resilience Note (Missing Tables/Schemas)
The endpoint is implemented to degrade safely per role:
- missing `settings/commands/trades` tables (or missing required columns) do not crash the endpoint
- corresponding role item is still returned with safe defaults (`online=false`)
- a structured diagnostic is appended to `errors[]`

This fallback path was verified by code path review in `gateway/gateway_api/observability.py`; current QA environment had all required tables present, so `errors_count=0`.

## Failure + Resolution During QA
Observed one transient failure in early `smoke_observability.sh` run:
- root cause: script used heredoc/pipe pattern that passed empty JSON into python parser

Resolution:
- updated `scripts/smoke_observability.sh` to pass captured JSON via environment variables (`RESP_JSON`, `RESP_FILTER_JSON`) to Python checks
- reran smoke successfully

## Final Status
Phase E3 target is complete and validated with full requested regression suite passing.
