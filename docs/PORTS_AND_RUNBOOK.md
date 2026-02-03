# Ports & Runbook (Local Dev)

## Phase 0 verified ports

### Mina_Bot
- Paper Dashboard: `8000`
- Live Dashboard: `8001`
- Pump Dashboard: `8002`

### Brain (trading-intelligence-platform)
- API: `8100` (moved to avoid Mina_Bot ports)
- React/Vite UI: `5173` (or `5174` if `5173` is busy)

## Brain dashboard proxy (recommended)
To avoid CORS and hard-coded API base URLs, use a Vite proxy.

- Brain API: `uvicorn api.main:app --host 127.0.0.1 --port 8100`
- Brain UI: set Axios baseURL to `/api` and proxy `/api` -> `http://127.0.0.1:8100` in `vite.config.ts`.

This keeps Mina_Bot and Brain running together without port conflicts.
