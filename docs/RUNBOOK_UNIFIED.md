# Unified Dashboard Runbook

## Endpoints
- Gateway API: `http://localhost:8200`
- Unified UI: `http://localhost:5173`
- Legacy dashboards (display-only): `http://localhost:8000`, `http://localhost:8001`, `http://localhost:8002`

## 1) Signals (paper) -> Approve -> Track
1. Open `http://localhost:5173/signals`.
2. Set role to `paper`.
3. Open tab `Inbox (PENDING_APPROVAL)`.
4. Select signal row (for example pending signal like `id=23` if present).
5. Click `Approve`.
6. Verify status changes from `PENDING_APPROVAL` to `APPROVED` (or later `EXECUTED`).
7. Open `http://localhost:5173/trades-positions` and refresh to follow trade lifecycle.

## 2) Manual Execution
1. Open `http://localhost:5173/manual-execution`.
2. Fill `symbol`, `amount`, `market`, `direction`.
3. Click `Execute Trade`.
4. Confirm returned `trace_id` and command status progression (`queued -> acked -> executed`).

## 3) Historical Snapshot (UTC)
1. Open `http://localhost:5173/historical-snapshot-utc`.
2. Enter local datetime in `At (Local Time)`.
3. Click `Run Snapshot`.
4. Confirm response shows candle + `RSI/ADX/ATR/ATR%` + regime + pump score.

## 4) Teach AI
1. Open `http://localhost:5173/teach-ai`.
2. Select role.
3. Run:
   - `Run Training`
   - `Promote Candidate`
   - `Rollback Deployed`
4. Validate status/result messages and audit trace propagation.

## 5) Status & Doctor
1. Open `http://localhost:5173/status-maintenance`.
2. Verify runtime assertions:
   - pump entrypoint includes `pump_hunter.py`
   - single DB fingerprint host/db = `postgres/trading`
3. Open `Doctor` tab and run quick/full checks.

## Smoke Commands
```bash
bash scripts/smoke_stack.sh
bash scripts/smoke_unified_pages.sh
bash scripts/smoke_e2e_trade.sh
bash scripts/smoke_ui_e2e.sh
```

## Notes
- Unified Dashboard is the only control plane for writes.
- Browser calls must stay under `/api/*` (Gateway proxy).
- Legacy Mina dashboards are read-only and should return:
  - `403`
  - `"Dashboard is read-only. Use Unified Dashboard."`
