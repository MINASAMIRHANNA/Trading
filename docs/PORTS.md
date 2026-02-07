# Ports and Runtime Entry Points

## Core Services
- `Gateway API`: `http://localhost:8200`
- `Brain API`: `http://localhost:8100`
- `Unified React Dashboard (dev)`: `http://localhost:5173`
- `Postgres`: `localhost:5432` (`trading` DB)

## Mina Dashboards (legacy, kept intact)
- `paper`: `http://localhost:8000`
- `live`: `http://localhost:8001`
- `pump`: `http://localhost:8002`

## Database Schemas
- `mina_paper`
- `mina_live`
- `mina_pump`
- `brain`
- `gateway`

## Notes
- Unified React UI talks to Gateway only via `/api/*`.
- Gateway proxies to Brain and Mina dashboards.
- No SQLite fallback is used for runtime services.
