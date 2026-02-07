# Production Readiness Guide

This document describes how to run the Trading stack safely end‑to‑end and verify the full pipeline:
Learning → Signal → Execute → Monitor → Close → Sync → Reports.

## Safe Mode Progression (TEST → PAPER → LIVE)
1. Start in `TEST` (no real orders) and verify:
   - Bots and monitors are online.
   - Signals can be approved and executed.
   - Trades open/close and appear in `mina_*` schemas.
2. Move to `PAPER` and confirm the E2E smoke path passes.
3. Move to `LIVE` only after:
   - Kill switch behavior is verified (blocks **opens**, allows **closes**).
   - Binance permissions are correct.
   - Alerts are working.

**Rule:** Never enable LIVE unless `kill_switch=0` and the E2E smoke test passes.

## Required Environment Variables
Set these in your Docker environment or compose file:
- `BINANCE_API_KEY`, `BINANCE_API_SECRET` (for LIVE)
- `USE_TESTNET=TRUE` for testnet routing
- `TRADING_MASTER_KEY` (encryption for secrets)
- `GATEWAY_API_KEY` (Gateway auth)

## Kill Switch
- `kill_switch=1` blocks **new** opens only.
- **Closing commands are always allowed.**

## E2E Smoke Tests
Run:
```
bash scripts/smoke_stack.sh
bash scripts/check_unified_db.sh
bash scripts/smoke_unified.sh
bash scripts/smoke_control.sh
bash scripts/smoke_autopilot.sh
bash scripts/smoke_ui_static.sh
bash scripts/smoke_e2e_trade.sh
```

`smoke_e2e_trade.sh` creates a test signal, approves it, opens a paper trade, closes it, and verifies Brain sync.

## Restart Loop Regression (Manual)
1. Trigger a restart from the dashboard (Restart Bot/Monitor).
2. Confirm the container restarts once.
3. Confirm it stays UP after restart and does **not** exit again.

If it loops: clear restart flags via `/ui/doctor` → "Clear Restart Flags".

## Operational Checklist
- Dashboard health:
  - http://localhost:8000/health
  - http://localhost:8001/health
  - http://localhost:8002/health
- Gateway health:
  - http://localhost:8200/health
- Brain overview:
  - http://localhost:8200/api/overview

If any item fails, stop and resolve before switching to LIVE.

## No-SQLite Policy
- Runtime services now default to Postgres.
- SQLite fallback is blocked unless explicitly enabled for local-only work:
  - `ALLOW_SQLITE_DEV=1` (Mina services)
  - `BRAIN_ALLOW_SQLITE_DEV=1` (Brain service)
