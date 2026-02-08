# PATCH NOTES: Phase E1 Consumer Reliability

Date: 2026-02-08 (UTC)
Workspace: `/Users/minasamir/projects/Trading`
Branch: `codex/nautilus-migration-phaseA`

## Summary
Implemented reliability hardening for `nautilus_engine` command consumption across all roles (`paper/live/pump`):
- retry/backoff for failed command execution
- terminal dead-letter flow with persistent dead-letter table
- strong idempotency for `EXECUTE_SIGNAL` using `signal_inbox_id`

Kill-switch behavior remains unchanged:
- OPEN blocked when kill-switch is ON
- CLOSE commands remain allowed

## Engine Changes

Updated: `services/nautilus_engine/nautilus_engine/main.py`

### 1) Add-only schema ensure at startup
At engine startup (per target schema), `ensure_consumer_schema(...)` now performs add-only reliability DDL:

- `ALTER TABLE {schema}.commands ADD COLUMN IF NOT EXISTS`:
  - `attempt_count INTEGER NOT NULL DEFAULT 0`
  - `max_attempts INTEGER NOT NULL DEFAULT 5`
  - `next_retry_at_ms BIGINT NULL`
  - `last_error TEXT NULL`
  - `last_error_at_ms BIGINT NULL`
  - `dead_lettered BOOLEAN NOT NULL DEFAULT FALSE`

- `CREATE TABLE IF NOT EXISTS {schema}.command_dead_letters (...)`
- `CREATE INDEX IF NOT EXISTS commands_status_next_retry_idx ON {schema}.commands(status, next_retry_at_ms)`
- `CREATE INDEX IF NOT EXISTS command_dead_letters_command_id_idx ON {schema}.command_dead_letters(command_id)`

Idempotency schema (also add-only):
- `ALTER TABLE {schema}.trades ADD COLUMN IF NOT EXISTS signal_inbox_id BIGINT NULL`
- `CREATE UNIQUE INDEX IF NOT EXISTS trades_unique_signal_inbox_id ON {schema}.trades(signal_inbox_id) WHERE signal_inbox_id IS NOT NULL`

### 2) Robust claim + scheduling
Claim logic now:
- picks only eligible commands:
  - `status IN ('PENDING','FAILED')`
  - `next_retry_at_ms IS NULL OR next_retry_at_ms <= now_ms`
  - `dead_lettered = FALSE`
- claims atomically (`WITH picked ... FOR UPDATE SKIP LOCKED ... UPDATE ... RETURNING`)
- sets `status='CLAIMED'`, `claimed_by`, `claimed_at(_ms)`, clears `next_retry_at_ms` on claim

Priority ordering added to reduce close-path starvation:
- `CLOSE_ALL_POSITIONS`, then `CLOSE_*`/`REDUCE_*`, then other commands, with `EXECUTE_SIGNAL` lower priority.

### 3) Retry/backoff + dead-letter
On command execution exception:
- attempt increments (`attempt_count += 1`)
- if attempts remain:
  - `status='FAILED'`
  - `next_retry_at_ms = now + exponential_backoff_with_jitter`
  - `last_error`, `last_error_at_ms` updated
- if max attempts reached:
  - `status='DEAD'`
  - `dead_lettered=TRUE`
  - dead-letter snapshot inserted into `{schema}.command_dead_letters`
  - explicit engine log written

Backoff tunables (env):
- `NAUTILUS_RETRY_BASE_MS` (default 1000)
- `NAUTILUS_RETRY_CAP_MS` (default 60000)
- `NAUTILUS_RETRY_JITTER_MS` (default 250)

### 4) Strong idempotency for `EXECUTE_SIGNAL`
`EXECUTE_SIGNAL` now:
- derives stable signal key from params:
  - `signal_inbox_id`, `signal_id`, `inbox_id`, `_dashboard_signal_id`
- checks existing trade by `trades.signal_inbox_id` before insert
- if found:
  - command marked `DONE` with idempotent ack meta
  - no new trade is created
- insert path uses `ON CONFLICT DO NOTHING RETURNING id` when `signal_inbox_id` present
  - if conflict happens, existing trade id is fetched and treated as idempotent success

## Test Support Command Handlers
Added harmless synthetic commands for reliability smoke:
- `TEST_FAIL_ONCE`: fails first attempt, succeeds on retry
- `TEST_ALWAYS_FAIL`: always fails (used to verify dead-letter path)

## Script Added
- `scripts/smoke_consumer_reliability.sh`
  - validates retry/backoff transitions
  - validates dead-letter insertion
  - validates `EXECUTE_SIGNAL` idempotency (single trade for duplicated signal)

