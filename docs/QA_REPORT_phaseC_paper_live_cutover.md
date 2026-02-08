# QA REPORT: Phase C Paper + Live Cutover

Date: 2026-02-08 (UTC)
Workspace: `/Users/minasamir/projects/Trading`
Branch: `codex/nautilus-migration-phaseA`
Compose project: `trading_migration`

## Scope
Validated Phase C target:
- runtime has no legacy dashboards
- `paper` + `live` execution owned by `nautilus_engine`
- `pump` remains legacy
- live remains safe by default
- kill-switch blocks opens and allows closes

## A) Static checks

Command:
```bash
python -m compileall gateway services/mina_strategies services/nautilus_engine
```

Result:
- PASS (exit code 0)

## B) Stack bring-up (clean project name)

Commands:
```bash
export COMPOSE_PROJECT_NAME=trading_migration
docker compose -f docker-compose.yml up -d --build
docker compose -f docker-compose.yml -f docker-compose.bots.yml up -d --build
docker compose -f docker-compose.yml -f docker-compose.bots.yml ps
```

`docker compose ps` summary (PASS):
- `postgres` healthy
- `gateway_api` healthy
- `brain_api` healthy
- `brain_ui` up
- `nautilus_paper_engine` up
- `nautilus_live_engine` up
- `mina_pump_bot` up
- `mina_pump_monitor` up

No legacy paper/live bot/monitor consumers were running.

## C) Required smoke suite

Commands:
```bash
bash scripts/smoke_unified.sh http://localhost:8200
bash scripts/smoke_all.sh paper
bash scripts/smoke_all.sh live
bash scripts/smoke_all.sh pump
bash scripts/smoke_signals.sh paper
bash scripts/smoke_actions.sh paper
```

Result:
- PASS (all exited 0)

Additional live variants run:
```bash
bash scripts/smoke_signals.sh live
bash scripts/smoke_actions.sh live
```
- PASS

## D) Live cutover verification (new)

Command:
```bash
bash scripts/smoke_live_cutover.sh
```

Result:
- PASS

Evidence from run:
- `signal1_id=11`
- `command1_id=22`
- `trade_id=5`
- `signal2_id=12`
- `signal2_status=REJECTED`
- `close_command_id=24`
- `close_status=DONE`

DB assertions executed:
```sql
SELECT 'signal1:'||id||':'||status FROM mina_live.signal_inbox WHERE id=11;
SELECT 'cmd1:'||id||':'||status||':'||COALESCE(claimed_by,'') FROM mina_live.commands WHERE id=22;
SELECT 'trade1:'||id||':'||COALESCE(status,'')||':'||COALESCE(symbol,'') FROM mina_live.trades WHERE id=5;
SELECT 'signal2:'||id||':'||status FROM mina_live.signal_inbox WHERE id=12;
SELECT 'close_cmd:'||id||':'||status||':'||COALESCE(claimed_by,'') FROM mina_live.commands WHERE id=24;
SELECT id,status,ack_meta FROM mina_live.commands WHERE id IN (22,24) ORDER BY id;
```

Observed rows:
- `signal1:11:APPROVED`
- `cmd1:22:DONE:nautilus_live_engine`
- `trade1:5:CLOSED:SOLUSDT` (was opened by command #22, then closed by close-all)
- `signal2:12:REJECTED` (kill-switch open-block path)
- `close_cmd:24:DONE:nautilus_live_engine`
- `ack_meta` for #22 and #24 confirms simulated execution and close behavior.

## E) Schema/table assertions

Checked schemas:
- `gateway`
- `mina_paper`
- `mina_live`
- `mina_pump`

Checked key tables per role schema:
- `trades`
- `commands`
- `logs`
- `settings`
- `signal_inbox`
- `events`

Result:
- PASS (all present)

## Safety verification notes

- Live default safety:
  - `nautilus_live_engine` starts with `EXECUTION_MODE=SIM_OR_TESTNET`
  - `LIVE_EXECUTION_ALLOWED` default is `0` in compose
- Kill-switch behavior confirmed in live cutover smoke:
  - open path rejected under kill-switch
  - `CLOSE_ALL_POSITIONS` still executes to `DONE`

## Issues encountered and fixes during QA

1. Live smoke scripts needed live confirmation headers/body for live write paths.
   - fixed in `smoke_all.sh`, `smoke_signals.sh`, `smoke_actions.sh`.
2. `smoke_live_cutover.sh` initially failed with live policy cooldown/risk variance.
   - fixed by setting deterministic safe policy keys in `gateway.shared_settings` for test setup.
3. Kill-switch rejection path can return either command-level rejection or strategy-veto response without `command_id`.
   - script updated to accept both valid rejection paths with DB-backed status assertion.

## Final status

Phase C cutover is validated:
- `paper` + `live` owned by nautilus engines
- `pump` remains legacy
- smoke suite passes
- live cutover scenario passes with DB evidence
- safety gates and kill-switch behavior are preserved

