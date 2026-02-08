# PATCH NOTES: Phase C Paper + Live Cutover

Date: 2026-02-08 (UTC)
Workspace: `/Users/minasamir/projects/Trading`
Branch: `codex/nautilus-migration-phaseA`

## Summary
Phase C moves execution ownership for `paper` and `live` to `nautilus_engine`, keeps `pump` on legacy runtime, and preserves Gateway/Brain/Postgres unified architecture with no legacy Mina dashboards in runtime.

## Runtime Ownership Changes

### `docker-compose.bots.yml`
- Removed legacy paper/live consumers from runtime:
  - `mina_paper_bot`
  - `mina_paper_monitor`
  - `mina_live_bot`
  - `mina_live_monitor`
- Added two role-specific engine instances:
  - `nautilus_paper_engine`
    - `ROLE=paper`
    - `DB_SCHEMA=mina_paper`
    - `EXECUTION_MODE=SIM`
  - `nautilus_live_engine`
    - `ROLE=live`
    - `DB_SCHEMA=mina_live`
    - `EXECUTION_MODE=SIM_OR_TESTNET`
    - `LIVE_EXECUTION_ALLOWED=${LIVE_EXECUTION_ALLOWED:-0}` (safe default)
- Kept pump legacy runtime:
  - `mina_pump_bot`
  - `mina_pump_monitor`
- Kept optional strategy publisher (`mina_strategies`) and switched target env to `ROLE_TARGETS`.

## Nautilus Engine (paper + live owner)

Updated `services/nautilus_engine/nautilus_engine/main.py`:

- Multi-role config by environment:
  - preferred: `ROLE` + `DB_SCHEMA`
  - backward compatible: `NAUTILUS_ROLE` / `NAUTILUS_ROLES`
- Atomic command claiming:
  - `WITH picked ... FOR UPDATE SKIP LOCKED`
  - `PENDING -> CLAIMED`
  - writes `claimed_by`, `claimed_at_ms` when present
- Command status lifecycle normalized:
  - terminal statuses: `DONE`, `REJECTED`, `FAILED`
- Live safety gate for opening commands:
  - requires `execution_enabled` (`execution_enabled` or `live_execution_enabled` or `ENABLE_LIVE_TRADING`)
  - and safe runtime (`USE_TESTNET`/sandbox/safe mode) or explicit `LIVE_EXECUTION_ALLOWED=1`
  - otherwise command is `REJECTED`
- Kill-switch enforcement:
  - if `kill_switch=1`, opening commands are rejected
  - close commands (`CLOSE_ALL_POSITIONS`, etc.) still execute
- DB write behavior preserved:
  - commands status transitions + `ack_meta`/`last_error`
  - simulated trade inserts/updates in `{schema}.trades`
  - logs in `{schema}.logs`
  - fixed-contract event payloads in `{schema}.events`/`{schema}.trade_events` (`trace_id`, `decision_id`, `schema_version`)
- Added periodic heartbeats:
  - updates settings keys: `last_heartbeat`, `bot_heartbeat`, `execution_monitor_heartbeat`
  - emits `HealthEvent`

## Strategy Publisher

Updated `services/mina_strategies/mina_strategies/main.py`:
- Added runtime target split support:
  - new env: `ROLE_TARGETS=paper,live`
  - backward compatibility preserved for `MINA_STRATEGIES_ROLES`
- No trade execution responsibilities added; publish-only behavior retained.

## Script Changes

### Runtime scripts
- `scripts/phase3_bots_up.sh`
- `scripts/phase3_bots_logs.sh`
- `scripts/phase3_bots_stop.sh`

Updated service names to engine ownership model (`nautilus_paper_engine`, `nautilus_live_engine`, `mina_pump_bot`, `mina_pump_monitor`) and retained unified health checks via Gateway.

### Smoke scripts
- `scripts/smoke_all.sh`
- `scripts/smoke_signals.sh`
- `scripts/smoke_actions.sh`
- Added `scripts/smoke_live_cutover.sh`

Live write paths now include required double-confirm headers/body fields, and the new live cutover smoke verifies:
- publish live signal
- approve -> command consumed by `nautilus_live_engine`
- command reaches `DONE` and trade is created
- kill-switch blocks new opens
- `CLOSE_ALL_POSITIONS` remains allowed while kill-switch is on

## Safety Defaults
- Live remains safe by default:
  - `LIVE_EXECUTION_ALLOWED` defaults to `0`
  - live engine execution mode defaults to simulated/testnet-safe mode (`SIM_OR_TESTNET`)
- Kill-switch rule remains strict:
  - blocks opening commands
  - always allows close path commands

