# Unified Dashboard Runbook

## Endpoints
- Gateway API: `http://localhost:8200`
- Unified UI: `http://localhost:5173`

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

## 6) Strategies + Risk & Execution (Pre-LIVE)
1. Open `http://localhost:5173/strategies`.
2. Choose role (`paper/live/pump`), toggle strategy, edit thresholds, then `Save`.
3. Open `http://localhost:5173/risk-execution`.
4. Assign active risk profile per role and keep `execution_mode` on `PAPER` or `TEST`.
5. Save runtime settings and verify metrics + incident/veto reasons refresh.

## Smoke Commands
```bash
bash scripts/smoke_stack.sh
bash scripts/smoke_unified_pages.sh
bash scripts/smoke_e2e_trade.sh
bash scripts/smoke_ui_e2e.sh
bash scripts/smoke_ops_ui_api.sh
```

## Gateway Ops UI (Server-Rendered)
- Base: `http://localhost:8200/ui`
- Observability: `http://localhost:8200/ui/ops/observability`
- Live Control: `http://localhost:8200/ui/ops/live-control`
- Go-Live Cockpit: `http://localhost:8200/ui/ops/go-live`
- Dead Letters: `http://localhost:8200/ui/ops/dead-letters`
- Dead Letter Detail: `http://localhost:8200/ui/ops/dead-letters/<role>/<dead_letter_id>`
- Commands: `http://localhost:8200/ui/ops/commands`
- Signals Inbox: `http://localhost:8200/ui/ops/signals`
- Actions: `http://localhost:8200/ui/ops/actions`
- Strategies: `http://localhost:8200/ui/ops/strategies`
- Audit: `http://localhost:8200/ui/ops/audit`
- If Gateway API key protection is enabled, UI API calls require Gateway auth:
  - either send `X-API-Key` on API requests
  - or create a browser session with `POST /api/auth/login` then use cookie-based auth

## Ops Signals + Actions
1. Open `/ui/ops/signals`, select role, filter by status/symbol, then approve/reject inbox signals.
2. For `live` role approvals, signal execution still depends on live safety checks in engine:
   - gate must be `CONFIRMED`
   - allowlist and limits must pass
   - kill-switch/live safety can still reject opens.
3. Open `/ui/ops/actions` to enqueue `CLOSE_ALL_POSITIONS` and inspect latest commands per role.
4. Open `/ui/ops/dead-letters/<role>/<dead_letter_id>` to inspect full dead-letter snapshot and perform safe one-time requeue.

## Ops Strategies
1. Open `/ui/ops/strategies` and select role (`paper/live/pump`).
2. Review discovered strategy list (auto-discovered from `services/mina_strategies` code).
3. Choose profile:
   - `conservative` -> `min_conf=0.80`
   - `balanced` -> `min_conf=0.65`
   - `aggressive` -> `min_conf=0.50`
4. Set global params (`strategy_params_global`) from the top controls.
5. Click `Edit Params` on any strategy to set per-strategy overrides (`strategy_params_by_name`) from discovered schema fields.
6. Toggle `strategies_enabled` and click `Apply`.
7. For `live`, apply requires:
   - `confirm_live_change=true`
   - `live_confirm_ack=I_UNDERSTAND`
   - live gate `CONFIRMED`
   - kill-switch OFF

## Go-Live Readiness
1. Open `/ui/ops/go-live`.
2. Confirm top status is `READY` before enabling any live rollout.
3. Review blocking checks:
   - `live_gate_confirmed`
   - `kill_switch_off`
   - `allowlist_nonempty`
   - `limits_set`
   - `engine_online`
   - `dead_letters_zero`
   - `command_backlog_ok`
   - `observability_errors_ok`
4. `brain_optional` may be null/unavailable and is non-blocking.
5. Use the embedded controls on the same page for ARM/CONFIRM/DISARM, allowlist, and limits.

## Ops Audit + Replay (Paper)
1. Open `/ui/ops/audit`.
2. Use filters (`role`, `symbol`, `since_ms`) or direct `trace_id` input.
3. Open a trace to inspect timeline (`gateway_audit`, `events`, `commands`, `trades`).
4. To replay safely, enable confirm checkbox and click `Replay to Paper`.
5. Replay enqueues a new paper command with:
   - new `trace_id`
   - `old_trace_id` link back to source
   - idempotent replay key to avoid duplicate replays of the same source.

API equivalents:
- `GET /api/audit/traces`
- `GET /api/audit/trace/{trace_id}`
- `POST /api/audit/replay/paper`

## Notes
- Unified Dashboard is the only control plane for writes.
- Browser calls must stay under `/api/*` (Gateway proxy).
- Legacy `mina_dashboard_*` runtime services are removed.
- Legacy `/api/mina/{role}/...` routes remain compatibility bridges or return `410` with guidance to `/api/unified/...`.
