# QA REPORT: Phase D Pump Cutover

Date: 2026-02-08 (UTC)
Workspace: `/Users/minasamir/projects/Trading`
Branch: `codex/nautilus-migration-phaseA`
Compose project: `trading_migration`

## Scope
Validated pump cutover to `nautilus_engine` as the only runtime command consumer for `mina_pump`, while keeping paper/live on engines.

## 1) Commands Run

### Static check
```bash
python -m compileall gateway services/mina_strategies services/nautilus_engine
```

### Bring up stack
```bash
export COMPOSE_PROJECT_NAME=trading_migration
docker compose -f docker-compose.yml up -d --build
docker compose -f docker-compose.yml -f docker-compose.bots.yml up -d --build
docker compose -f docker-compose.yml -f docker-compose.bots.yml ps
```

### Required smoke suite
```bash
bash scripts/smoke_unified.sh http://localhost:8200
bash scripts/smoke_all.sh paper
bash scripts/smoke_all.sh live
bash scripts/smoke_all.sh pump
bash scripts/smoke_live_cutover.sh
bash scripts/smoke_pump_cutover.sh
```

## 2) Initial Failure + Resolution

### Failure observed
- First validation run failed before smoke completion:
  - `smoke_unified` hit `curl: (56) Recv failure: Connection reset by peer` while `gateway_api` was still starting.
  - `docker compose` also reported orphan containers from removed legacy pump services:
    - `trading_migration-mina_pump_bot-1`
    - `trading_migration-mina_pump_monitor-1`

### Resolution
Executed:
```bash
docker rm -f trading_migration-mina_pump_bot-1 trading_migration-mina_pump_monitor-1
```
Then waited for Gateway health and reran full smoke suite. All required smokes passed.

## 3) Final Runtime Verification

Final `docker compose ps` (post-fix) showed:
- `nautilus_paper_engine` up
- `nautilus_live_engine` up
- `nautilus_pump_engine` up
- no legacy pump consumer containers running

Schemas and role tables check:
- Schemas present: `gateway`, `mina_paper`, `mina_live`, `mina_pump`
- Required tables present per role schema:
  - `trades`, `commands`, `logs`, `settings`, `signal_inbox`, `events`

## 4) Smoke Results

- `smoke_unified.sh`: PASS
- `smoke_all.sh paper`: PASS
- `smoke_all.sh live`: PASS
- `smoke_all.sh pump`: PASS
- `smoke_live_cutover.sh`: PASS
- `smoke_pump_cutover.sh`: PASS

## 5) Pump Cutover Evidence (DB + smoke outputs)

From `scripts/smoke_pump_cutover.sh` output:
- `pump_signal1_id=1`
- `pump_command1_id=10`
- `pump_trade_id=1`
- `pump_signal2_id=2`
- `pump_signal2_status=REJECTED`
- `pump_killswitch_command_id=12`
- `pump_close_command_id=13`
- `pump_close_status=DONE`

DB checks:
- `pump_cmd1:10:DONE:nautilus_pump_engine`
- `pump_kill_cmd:12:REJECTED:nautilus_pump_engine`
- `pump_close_cmd:13:DONE:nautilus_pump_engine`
- `pump_ack1:10:{"ok": true, "simulated": true, "trade_id": 1, "cmd": "EXECUTE_SIGNAL"}`
- `pump_ack_close:13:{"ok": true, "simulated": true, "closed": 1, "cmd": "CLOSE_ALL_POSITIONS"}`

Notes:
- `pump_trade_id=1` was created by first open flow, then closed later by `CLOSE_ALL_POSITIONS`, so final row status is `CLOSED`.

## 6) Safety Assertions

- Pump default mode is safe:
  - `EXECUTION_MODE=SIM` in compose.
- Kill-switch semantics verified:
  - OPEN path rejected (signal veto + rejected command path)
  - CLOSE path allowed and completed (`DONE`) while kill-switch was ON.

## 7) Final Status

Phase D target achieved:
- Pump execution ownership cut over to `nautilus_engine`.
- Legacy pump consumers removed from runtime.
- Existing unified flows still operational.
- Required validations passed with evidence recorded.

