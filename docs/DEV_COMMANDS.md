# Dev commands (suggested)

## Mina_Bot
Run your existing Mina_Bot run scripts as-is (after copying into `services/mina_bot`).

Example (adjust to your current Mina_Bot runbook):
```bash
cd services/mina_bot
bash ops/run_paper_stack.sh
bash ops/run_live_stack.sh
bash ops/run_pump_stack.sh
```

## Brain (trading-intelligence-platform)
API on 8100:
```bash
cd services/brain
uvicorn api.main:app --host 127.0.0.1 --port 8100
```

Brain dashboard (Vite) will likely start on 5173 or fallback to 5174:
```bash
cd services/brain/dashboard
npm install
npm run dev
```

## Gateway (Phase 1)
```bash
cd gateway
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
python -m pytest -q
python scripts/export_schemas.py
```


## API Key for curl/tests (Batch-28)

You can call protected /api/* endpoints without the login cookie using an API key header:

```bash
curl -H "X-API-Key: trading-dev" http://localhost:8000/api/signals?limit=1
```

You can override the key via `DASHBOARD_API_KEY` in docker-compose.
