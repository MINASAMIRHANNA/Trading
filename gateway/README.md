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
