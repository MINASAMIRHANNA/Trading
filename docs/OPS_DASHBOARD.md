# Ops Dashboard

## Runtime Surfaces
- Unified React dashboard: `http://localhost:5173` (primary control plane)
- Gateway server-rendered UI: `http://localhost:8200/ui`
- Gateway Ops pages:
  - `http://localhost:8200/ui/ops/observability`
  - `http://localhost:8200/ui/ops/live-control`
  - `http://localhost:8200/ui/ops/dead-letters`
  - `http://localhost:8200/ui/ops/commands`

Legacy `mina_dashboard_*` services are removed from runtime.

## Core Data Sources
- Gateway DB-backed unified endpoints (`/api/unified/*`)
- Gateway control/audit/ops endpoints (`/api/control/*`, `/api/ops/*`, `/api/audit/*`)
- Brain API through Gateway proxy (`/api/brain/*`)

## Live Safety Controls
- Status: `GET /api/control/live/status`
- Arm: `POST /api/control/live/arm`
- Confirm: `POST /api/control/live/confirm`
- Disarm: `POST /api/control/live/disarm`
- Allowlist: `POST /api/control/live/allowlist`
- Limits: `POST /api/control/live/limits`

Two-step live enable flow:
1. `ARM` to rotate and receive a short-lived token.
2. `CONFIRM` with token to set gate state to `CONFIRMED`.
3. Use `DISARM` to immediately return to safe state.

If Gateway API key auth is enabled, browser API calls must authenticate via:
- `X-API-Key` header on API requests, or
- session cookie via `POST /api/auth/login`.

## Quick Validation
```bash
bash scripts/smoke_observability.sh
bash scripts/smoke_live_safety_gate.sh
bash scripts/smoke_qa_pack.sh
bash scripts/smoke_ops_ui_api.sh
```
