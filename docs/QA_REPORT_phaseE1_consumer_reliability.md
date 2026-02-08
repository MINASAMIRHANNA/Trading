# QA REPORT: Phase E1 Consumer Reliability

Date: 2026-02-08 (UTC)
Workspace: `/Users/minasamir/projects/Trading`
Branch: `codex/nautilus-migration-phaseA`
Compose project: `trading_migration`

## Scope
Validated reliability hardening for `nautilus_engine` consumer across roles:
- retry/backoff on failed commands
- dead-letter terminal handling
- `EXECUTE_SIGNAL` idempotency with `signal_inbox_id`

Also verified Phase D smoke coverage remains green.

## Commands Run

```bash
python -m compileall gateway services/mina_strategies services/nautilus_engine

export COMPOSE_PROJECT_NAME=trading_migration
docker compose -f docker-compose.yml up -d --build
docker compose -f docker-compose.yml -f docker-compose.bots.yml up -d --build

bash scripts/smoke_all.sh paper
bash scripts/smoke_all.sh live
bash scripts/smoke_all.sh pump
bash scripts/smoke_live_cutover.sh
bash scripts/smoke_pump_cutover.sh
bash scripts/smoke_consumer_reliability.sh
```

## Initial Failure + Resolution During QA

Observed during first E1 run:
- `nautilus_live_engine` loop error:
  - `ProgrammingError: only '%s', '%b', '%t' are allowed as placeholders, got '%'`
- Root cause:
  - unescaped `%` in `LIKE 'CLOSE_%'` / `LIKE 'REDUCE_%'` in claim priority SQL.
- Fix:
  - escaped to `LIKE 'CLOSE_%%'` and `LIKE 'REDUCE_%%'`.

Observed during first reliability smoke:
- `ack_meta->>'idempotent'` failed on environments where `ack_meta` is text.
- Fix:
  - updated smoke script to parse `ack_meta::text` via Python JSON parser.

After both fixes, all required smokes passed.

## Result Summary

- `compileall`: PASS
- `smoke_all.sh paper`: PASS
- `smoke_all.sh live`: PASS
- `smoke_all.sh pump`: PASS
- `smoke_live_cutover.sh`: PASS
- `smoke_pump_cutover.sh`: PASS
- `smoke_consumer_reliability.sh`: PASS

## Reliability Evidence (pump schema)

From `scripts/smoke_consumer_reliability.sh`:
- `retry_cmd_id=30`
- `dead_cmd_id=31`
- `dead_letter_rows=1`
- `idempotency_signal_id=8`
- `idempotency_first_command_id=32`
- `idempotency_duplicate_command_id=33`
- `idempotency_trade_id=5`
- `idempotency_trade_count=1`

### Retry/backoff proof
DB rows:
- `mina_pump.commands.id=30`
  - `cmd=TEST_FAIL_ONCE`
  - final `status=DONE`
  - `attempt_count=1`
  - `last_error='RuntimeError: synthetic_transient_fail_once'`

Log proof:
- `mina_pump.logs.msg`
  - `command retry scheduled id=30 cmd=TEST_FAIL_ONCE attempt=1/5 ... next_retry_at_ms=...`

This shows transition through retry scheduling before successful completion.

### Dead-letter proof
DB rows:
- `mina_pump.commands.id=31`
  - `cmd=TEST_ALWAYS_FAIL`
  - `status=DEAD`
  - `attempt_count=2`
  - `max_attempts=2`
  - `dead_lettered=true`
- `mina_pump.command_dead_letters`
  - row exists for `command_id=31`
  - snapshot includes cmd/status/attempt metadata and last error

Log proof:
- `dead-lettered command id=31 cmd=TEST_ALWAYS_FAIL attempt=2/2 ...`

### Idempotency proof
DB rows:
- `mina_pump.commands.id=32` (`EXECUTE_SIGNAL`)
  - `status=DONE`
  - `ack_meta` includes `trade_id=5`, `signal_inbox_id=8`
- `mina_pump.commands.id=33` (duplicate `EXECUTE_SIGNAL` same signal id)
  - `status=DONE`
  - `ack_meta.idempotent=true`
  - same `trade_id=5`, `signal_inbox_id=8`
- `SELECT COUNT(*) FROM mina_pump.trades WHERE signal_inbox_id=8` returned `1`

Conclusion:
- duplicate execution request did not open a second trade.

## Phase D Regression Check

Live cutover smoke evidence:
- `signal1_id=18 command1_id=37 trade_id=9`
- `signal2_id=19 signal2_status=REJECTED`
- `close_command_id=39 close_status=DONE`

Pump cutover smoke evidence:
- `pump_signal1_id=6`
- `pump_command1_id=26`
- `pump_trade_id=4`
- `pump_signal2_id=7` rejected with kill-switch
- `pump_close_command_id=29` done while kill-switch ON

## Final Status

Phase E1 target achieved:
- add-only reliability schema in place
- retry/backoff + dead-letter behavior verified
- strong `EXECUTE_SIGNAL` idempotency verified
- existing Phase D smokes remain passing

