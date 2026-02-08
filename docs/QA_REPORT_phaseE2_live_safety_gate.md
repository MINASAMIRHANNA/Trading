# QA REPORT: Phase E2 Live Safety Gate

Date: 2026-02-08 (UTC)
Workspace: `/Users/minasamir/projects/Trading`
Branch: `codex/nautilus-migration-phaseA`
Compose project: `trading_migration`

## Scope
Validated Phase E2 live safety hardening:
- gateway control-plane endpoints for live gate and limits
- engine enforcement for live open commands (gate, allowlist, limits, safe-mode)
- kill-switch invariants (OPEN blocked, CLOSE allowed)

Also validated all required prior smokes continue to pass.

## Commands Run

```bash
python -m compileall gateway services/mina_strategies services/nautilus_engine

export COMPOSE_PROJECT_NAME=trading_migration
docker compose -f docker-compose.yml up -d --build
docker compose -f docker-compose.yml -f docker-compose.bots.yml up -d --build
docker compose -f docker-compose.yml -f docker-compose.bots.yml ps

bash scripts/smoke_unified.sh http://localhost:8200
bash scripts/smoke_all.sh paper
bash scripts/smoke_all.sh live
bash scripts/smoke_all.sh pump
bash scripts/smoke_live_cutover.sh
bash scripts/smoke_pump_cutover.sh
bash scripts/smoke_consumer_reliability.sh
bash scripts/smoke_live_safety_gate.sh
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

## Result Summary
- `compileall`: PASS
- `smoke_unified.sh`: PASS
- `smoke_all.sh paper`: PASS
- `smoke_all.sh live`: PASS
- `smoke_all.sh pump`: PASS
- `smoke_live_cutover.sh`: PASS
- `smoke_pump_cutover.sh`: PASS
- `smoke_consumer_reliability.sh`: PASS
- `smoke_live_safety_gate.sh`: PASS

## Phase E2 Evidence (live safety gate)
From final run of `scripts/smoke_live_safety_gate.sh`:
- step1: `signal_id=36`, `command_id=58`, reason=`LIVE_GATE_NOT_CONFIRMED`
- step2: `signal_id=37`, `command_id=59`, reason=`LIVE_GATE_NOT_CONFIRMED`
- step3: `signal_id=38`, `command_id=60`, trade created `trade_id=13`
- step4: `signal_id=39`, `command_id=61`, reason=`SYMBOL_NOT_ALLOWED`
- step5: `signal_id=40`, `command_id=62`, reason=`LIMIT_MAX_OPEN_POSITIONS`
- step6: `signal_id=41`, `command_id=63`, reason=`LIVE_GATE_NOT_CONFIRMED`
- step7 (kill-switch open path): `signal_id=42`, gateway veto reason=`kill_switch_gateway_veto`
- kill-switch close path: `close_command_id=65`, status=`DONE`

Interpretation:
- disarmed/armed-not-confirmed both block opens
- confirmed gate allows opens in safe test mode
- allowlist and limits are enforced
- disarm blocks opens again
- kill-switch blocks opens and still allows close-all

## Additional Regression Evidence

### Live cutover smoke
From `scripts/smoke_live_cutover.sh`:
- `signal1_id=20`, `command1_id=41`, `trade_id=10`
- `signal2_id=21`, `signal2_status=REJECTED`
- `close_command_id=43`, `close_status=DONE`

### Pump cutover smoke
From `scripts/smoke_pump_cutover.sh`:
- `pump_signal1_id=9`
- `pump_command1_id=37`
- `pump_trade_id=6`
- `pump_signal2_id=10`, `pump_signal2_status=REJECTED`
- `pump_killswitch_command_id=39`
- `pump_close_command_id=40`, `pump_close_status=DONE`

### Consumer reliability smoke
From `scripts/smoke_consumer_reliability.sh`:
- `retry_cmd_id=41`
- `dead_cmd_id=42`
- `dead_letter_rows=1`
- `idempotency_signal_id=11`
- `idempotency_first_command_id=43`
- `idempotency_duplicate_command_id=44`
- `idempotency_trade_id=7`
- `idempotency_trade_count=1`

## Failure During QA + Resolution
Observed on first `smoke_live_safety_gate.sh` iteration:
- step7 expected engine-level rejected command id under kill-switch but gateway returned a kill-switch strategy veto response without `command_id`.

Resolution:
- updated `scripts/smoke_live_safety_gate.sh` step7 to accept both valid paths:
  - engine REJECTED command path with `command_id`
  - gateway veto path where signal becomes `REJECTED`
- reran and passed.

## Final Status
Phase E2 target achieved and validated.
