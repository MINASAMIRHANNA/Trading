# Gateway (Phase 1)

This folder will become the **Gateway repo**.

Phase 1 deliverable here: **Contracts v1** in `shared_contracts/`.

## Run tests
```bash
cd gateway
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
python -m pytest -q
python scripts/export_schemas.py
```


## Proxy Mina dashboards

Gateway proxies Mina dashboards using `X-API-Key`.

Examples:
- `GET /api/mina/paper/signals?limit=10`
- `GET /api/mina/live/system_health`

Environment:
- `DASHBOARD_API_KEY` (default: trading-dev)
- `MINA_PAPER_URL`, `MINA_LIVE_URL`, `MINA_PUMP_URL`
- `BRAIN_API_URL`

## Optional: protect gateway endpoints

You can require an API key on gateway routes (disabled by default).

Environment:
- `GATEWAY_API_KEY` (if set, clients must send `X-API-Key: <value>`)
