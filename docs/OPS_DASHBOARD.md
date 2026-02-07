# Ops Dashboard (Mina-style)

Two dashboards are available:
- Unified React dashboard: `http://localhost:5173` (Vite, Gateway `/api` proxy)
- Gateway server-rendered UI: `http://localhost:8200/ui`

## Routes
- `/ui/ops` – Ops Live (positions, logs, status, errors, restart + kill switch)
- `/ui/portfolio` – KPIs + trades + symbol exposure + exports
- `/ui/manual` – Publish/approve/reject signals, close trades, risk settings
- `/ui/reports` – Paper/Arena, Analytics, Deep Audit, extra reports
- `/ui/doctor` – Doctor checks + fix actions
- `/ui/api` – API index + webhooks
- `/ui/learn` – Learning status + triggers
- `/ui/alerts` – Telegram settings + rules
- `/ui/go_live` – Ready-for-live checklist

## Data Sources
- Gateway endpoints (`/api/ops/*`, `/api/portfolio/*`, `/api/reports/*`, `/api/doctor/*`, `/api/learn/*`, `/api/alerts/*`)
- Mina dashboards via gateway proxy (`/api/mina/{role}/*`)

## Secrets Configuration
- Binance keys: `Portfolio` page (`/portfolio`) via Gateway endpoint `/api/integrations/binance/connect`.
- Telegram token/chat id: `Alerts` page (`/alerts`) via Gateway endpoint `/api/alerts/telegram/settings`.
- Set `TRADING_MASTER_KEY` in Gateway env for encrypted secret storage.

## Unified DB Wiring
- Verification endpoint: `/api/system/db_wiring`
- Per-service datasource meta:
  - Gateway: `/api/meta/datasource`
  - Brain (via Gateway): `/api/brain/meta/datasource`
  - Mina per role (via Gateway): `/api/mina/{role}/meta/datasource`
- Verifies one Postgres DB + expected schemas + service startup registrations.
- Startup registrations are written by:
  - `gateway_api`
  - `brain_api` / `brain_sync_worker`
  - `mina_dashboard` per role
  - `mina_bot` / `mina_monitor` per role
  - `pump_hunter` (pump role)

## Project Mode Toggle
- In Unified `Portfolio`, use `Project Trading Mode`:
  - `Switch to TESTNET`
  - `Switch to LIVE`
- Routed through Gateway endpoint `/api/project/mode`.
- Safety policy: `paper` stays `PAPER` mode even when project mode is `LIVE`.

## Notes
- Uses Mina dashboard styling from `services/mina_bot/dashboard/static/style.css`.
- UI uses vanilla JS fetch polling (2s by default on Ops Live).
- Existing React UI on `/` remains unchanged.

## Quick Check
```
open http://localhost:8200/ui/ops
```

## Readiness
Run:
```
bash scripts/smoke_stack.sh
bash scripts/smoke_e2e_trade.sh
bash scripts/diag_mesh.sh
bash scripts/check_unified_db.sh
bash scripts/smoke_db_singleton.sh
```
