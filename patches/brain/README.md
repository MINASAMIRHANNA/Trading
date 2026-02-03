# Brain patches

These are **copy-over** patches for `services/brain` (trading-intelligence-platform) when you move it into this repo.

Included fixes:
- Adds missing `database/models/trade_features.py` to prevent `ModuleNotFoundError: database.models`.
- Sets dashboard Axios baseURL to `/api`.
- Adds Vite proxy `/api` -> `http://127.0.0.1:8100`.

## Apply
From repo root:
```bash
rsync -a patches/brain/ services/brain/
```
