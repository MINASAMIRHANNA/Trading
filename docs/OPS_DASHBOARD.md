# Ops Dashboard

## Runtime Surfaces
- Unified React dashboard: `http://localhost:5173` (primary control plane)
- Gateway server-rendered UI: `http://localhost:8200/ui`
- Gateway Ops pages:
  - `http://localhost:8200/ui/ops/observability`
  - `http://localhost:8200/ui/ops/live-control`
  - `http://localhost:8200/ui/ops/go-live`
  - `http://localhost:8200/ui/ops/dead-letters`
  - `http://localhost:8200/ui/ops/dead-letters/<role>/<dead_letter_id>`
  - `http://localhost:8200/ui/ops/commands`
  - `http://localhost:8200/ui/ops/signals`
  - `http://localhost:8200/ui/ops/actions`
  - `http://localhost:8200/ui/ops/strategies`
  - `http://localhost:8200/ui/ops/audit`

Legacy `mina_dashboard_*` services are removed from runtime.

## Core Data Sources
- Gateway DB-backed unified endpoints (`/api/unified/*`)
- Gateway control/audit/ops endpoints (`/api/control/*`, `/api/ops/*`, `/api/audit/*`)
- Brain API through Gateway proxy (`/api/brain/*`)

## Live Safety Controls
- Status: `GET /api/control/live/status`
- Readiness: `GET /api/control/live/readiness`
- Arm: `POST /api/control/live/arm`
- Confirm: `POST /api/control/live/confirm`
- Disarm: `POST /api/control/live/disarm`
- Allowlist: `POST /api/control/live/allowlist`
- Limits: `POST /api/control/live/limits`

Go-Live Cockpit:
- URL: `/ui/ops/go-live`
- Shows aggregated `READY/NOT READY` state and check details.
- `READY` requires all blocking checks to pass:
  - live gate is `CONFIRMED`
  - kill-switch is OFF
  - allowlist is non-empty
  - limits are set
  - live engine is online
  - dead letters count is zero
  - command backlog (`pending/failed`) is clean
  - observability errors are zero
- `brain_optional` is reported but does not block readiness.

Two-step live enable flow:
1. `ARM` to rotate and receive a short-lived token.
2. `CONFIRM` with token to set gate state to `CONFIRMED`.
3. Use `DISARM` to immediately return to safe state.

Signals approvals behavior:
- `approve`/`reject` in Ops Signals updates inbox status through Gateway unified endpoints.
- For `live`, approval can still end as command rejection if gate/allowlist/limits/kill-switch checks fail in `nautilus_live_engine`.

Manual actions behavior:
- Ops Actions page enqueues `CLOSE_ALL_POSITIONS` via unified commands endpoint.
- Close actions remain allowed even when kill-switch is ON.

Dead-letters workflow:
- Use `/ui/ops/dead-letters` to inspect per-role dead-letter rows.
- Open `/ui/ops/dead-letters/<role>/<dead_letter_id>` for full snapshot:
  - command payload/params
  - last error + attempt counters
  - timestamps + claiming metadata
  - linked command current status
- Optional safe requeue (`Requeue once`) creates a NEW command row and keeps old dead letter immutable.

Requeue safety rules:
- `paper` and `pump`: allowed by default.
- `live`: blocked unless gate is `CONFIRMED`, kill-switch is OFF, and explicit live confirm is checked in UI.
- Requeue is idempotent per dead-letter ID; repeated clicks return the existing requeue command.

If Gateway API key auth is enabled, browser API calls must authenticate via:
- `X-API-Key` header on API requests, or
- session cookie via `POST /api/auth/login`.

## Strategies Control (Code-Discovered + DB-Backed)
- Discovery endpoint: `GET /api/control/strategies/discover`
- Status endpoint: `GET /api/control/strategies/status?role=paper|live|pump`
- Apply endpoint: `POST /api/control/strategies/apply`
- Ops page: `/ui/ops/strategies`

What "discovered strategies" means:
- Source of truth is `services/mina_strategies` code discovery (`discover_strategies()`).
- Gateway returns discovered strategy metadata (`name`, `label`, `module`, `enabled_by_default`, `tags`).
- Role config keys are stored in each role schema settings table:
  - `strategies_enabled` (JSON map)
  - `active_profile` (`conservative|balanced|aggressive`)
  - `strategy_params` (legacy JSON alias, includes `min_conf`)
  - `strategy_params_global` (JSON global params shared across discovered strategies)
  - `strategy_params_by_name` (JSON map per strategy name)
  - `updated_at_ms`

Profile mapping for `min_conf`:
- `conservative`: `0.80`
- `balanced`: `0.65`
- `aggressive`: `0.50`
- If `strategy_params.min_conf` is set, it overrides the profile default.
- Status API also returns `effective_params_by_name` (resolved defaults + global + per-strategy overrides).

Per-strategy params v2:
- Discovery exposes `params_schema` for each strategy.
- Ops UI (`/ui/ops/strategies`) renders schema-driven expandable parameter editors per strategy.
- `POST /api/control/strategies/apply` validates `strategy_params_global` and `strategy_params_by_name` against discovered schemas.

Live apply safety requirements:
- `confirm_live_change=true`
- `live_confirm_ack="I_UNDERSTAND"`
- live gate state must be `CONFIRMED`
- live kill-switch must be OFF

## Audit Explorer + Paper Replay
- Traces list: `GET /api/audit/traces?limit=&role=&symbol=&since_ms=`
- Trace detail: `GET /api/audit/trace/{trace_id}`
- Trace detail includes `brain` drill-in fields (when available):
  - `decision`, `conf_pct`, `final_score`, `gate`
  - `rule_signal`, `ai_vote`, `ai_confidence`, `pump_score`
  - `indicators` (`rsi`, `adx`, `vol_spike`, `funding`, `oi_change`, `atr_pct`, ...)
  - If Brain data is unavailable for that trace, `brain` is `null` and `errors[]` contains a non-fatal reason.
- Replay (paper only): `POST /api/audit/replay/paper` with body:
  - `{"trace_id":"...","mode":"replay"}` OR
  - `{"signal_inbox_id":123,"mode":"replay"}` OR
  - `{"command_id":456,"mode":"replay"}`
- Ops page: `/ui/ops/audit`

Replay safety and behavior:
- Replay is `paper` scope only and always creates a fresh `trace_id`.
- Original trace is linked via `old_trace_id` in replay command params/meta.
- Replay is idempotent per source tuple `(source_type, source_role, source_id)`; repeated replay returns existing command.

## Quick Validation
```bash
bash scripts/smoke_observability.sh
bash scripts/smoke_live_safety_gate.sh
bash scripts/smoke_qa_pack.sh
bash scripts/smoke_ops_ui_api.sh
```
