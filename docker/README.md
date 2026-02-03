# Docker (Dev) — Trading Monorepo

This setup is meant for **local testing on Mac/Linux** with a single command.
It runs:
- Postgres (shared)
- Mina_Bot stacks (dashboards + bots)
- Brain API + optional Brain UI
- (Optional) Gateway API

## Quick start

From the repo root (`Trading/`):

```bash
# 1) Start Postgres + Mina (live+pump) + Brain (API+UI)
docker compose --profile mina --profile brain up -d --build

# Optional: start paper stack too
docker compose --profile mina --profile paper --profile brain up -d --build

# Optional: start gateway
docker compose --profile gateway up -d --build
```

## URLs

- Mina Paper Dashboard: http://localhost:8000  (profile: `paper`)
- Mina Live Dashboard:  http://localhost:8001
- Mina Pump Dashboard:  http://localhost:8002
- Brain API:            http://localhost:8100/api/overview
- Brain UI (Vite):      http://localhost:5173
- Gateway API:          http://localhost:8200/health

## Logs / Stop

```bash
# Follow logs (example)
docker compose logs -f mina_live_dashboard

# Stop and remove containers
docker compose down
```

## Notes

- Postgres credentials (dev default): `trading / trading` on database `trading`.
- Mina_Bot uses **Postgres PRIMARY** in Docker (`MINA_DB_BACKEND=postgres`).
- Each Mina stack gets its own schema via `BOT_ROLE`:
  - `mina_paper`, `mina_live`, `mina_pump`
- Brain uses an **internal SQLite file** by default in Docker for safety. We'll unify it to Postgres later.


## Bots/Monitors (optional)

Run the bots/monitors (not started by default):

```bash
docker compose -f docker-compose.yml -f docker-compose.bots.yml up -d --build
```
