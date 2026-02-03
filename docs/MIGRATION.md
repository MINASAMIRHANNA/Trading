# Migration into Trading repo

## Goal
Bring **both projects** under one workspace without losing any features.

## Copy projects (recommended: copy, not move)

### Mina_Bot
```bash
rsync -a --delete ~/projects/Mina_Bot_v1/ ./services/mina_bot/
```

### Brain (trading-intelligence-platform)
```bash
rsync -a --delete ~/projects/trading-intelligence-platform/ ./services/brain/
```

> If you prefer not to delete anything, remove `--delete`.

## Baseline run commands

### Mina (unchanged)
Run using your existing `ops/run_*_stack.sh` scripts inside `services/mina_bot`.

### Brain (avoid port collision)
- API on **8100**
- Vite proxies `/api` to `8100`

Example:
```bash
cd services/brain
uvicorn api.main:app --host 127.0.0.1 --port 8100

cd dashboard
npm install
npm run dev
```

### Gateway (contracts tests)
```bash
cd gateway
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
pytest -q
python scripts/export_schemas.py
```
