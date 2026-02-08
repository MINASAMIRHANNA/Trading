# PATCH NOTES: Phase D Pump Cutover

Date: 2026-02-08 (UTC)
Workspace: `/Users/minasamir/projects/Trading`
Branch: `codex/nautilus-migration-phaseA`

## Summary
Phase D moves execution ownership for `pump` to `nautilus_engine` so all roles are now engine-owned:
- `paper` -> `nautilus_paper_engine`
- `live` -> `nautilus_live_engine`
- `pump` -> `nautilus_pump_engine`

Legacy pump consumers were removed from runtime to prevent double command consumption.

## Runtime Changes

### `docker-compose.bots.yml`
- Added `nautilus_pump_engine`:
  - `ROLE=pump`
  - `DB_SCHEMA=mina_pump`
  - `EXECUTION_MODE=SIM` (safe default)
  - `ENGINE_ID=nautilus_pump_engine`
- Removed legacy pump runtime services:
  - `mina_pump_bot`
  - `mina_pump_monitor`
- Kept paper/live nautilus engines unchanged.
- Kept optional `mina_strategies` publisher profile.

## Engine Updates

### `services/nautilus_engine/nautilus_engine/main.py`
- Added `ENGINE_NAME` fallback for worker identity resolution:
  - `ENGINE_ID` -> `ENGINE_NAME` -> `HOSTNAME` -> `nautilus_engine`
- Existing role/schema routing, atomic claim flow, command lifecycle, and kill-switch behavior continue to apply to pump:
  - `PENDING -> CLAIMED -> DONE/REJECTED/FAILED`
  - kill-switch blocks OPEN commands
  - CLOSE commands remain allowed

## Script Updates

### Phase scripts
- `scripts/phase3_bots_up.sh`
- `scripts/phase3_bots_logs.sh`
- `scripts/phase3_bots_stop.sh`

Updated to manage nautilus engines only (`paper/live/pump`) and no legacy pump services.

### New smoke
- Added `scripts/smoke_pump_cutover.sh`

This smoke validates pump ownership end-to-end:
1. Publish/approve pump signal via Gateway.
2. Confirm command insertion and engine claim by `nautilus_pump_engine`.
3. Confirm trade creation in `mina_pump.trades`.
4. Enable kill-switch and verify second signal rejection.
5. Verify open-command rejection under kill-switch.
6. Verify `CLOSE_ALL_POSITIONS` still reaches `DONE` while kill-switch is ON.

## Safety / Compatibility
- Runtime remains dashboard-free (no `mina_dashboard_*` services).
- Pump execution remains safe by default (`EXECUTION_MODE=SIM`).
- Unified role-agnostic Gateway endpoints remain in place.
- No breaking DB schema changes introduced.
- UTC-only timestamp behavior preserved.

