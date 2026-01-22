# Living Checklist

Update this file **only after** each phase passes its tests.

## Phase 0 — Baseline Freeze & Feature Inventory
- [x] Mina_Bot smoke tests passed (dashboards on 8000/8001/8002; DB ok; WS ok)
- [x] Brain smoke tests passed (API on 8100; Vite UI on 5173/5174; proxy `/api` -> 8100)

## Phase 1 — Contracts v1 (Gateway)
- [ ] `gateway/shared_contracts` present with: `SignalEvent`, `TradeEvent`, `HealthEvent`
- [ ] Tests pass: `cd gateway && python -m pytest -q`
- [ ] Schemas exported: `cd gateway && python scripts/export_schemas.py` (creates `gateway/schemas/`)
- [ ] After you confirm output, mark Phase 1 as done.

## Phase 2 — API Normalization (Gateway facade)
- [ ] Create Gateway HTTP endpoints that match the unified dashboard needs
- [ ] Backward-compatible aliases for existing services

## Phase 3 — Unified Dashboard (Frontend)
- [ ] Single UI talks only to Gateway

## Phase 4 — Event Bus + Audit Replay
- [ ] Append-only events + replay

## Phase 5 — Shadow -> Testnet -> Live Rollout
- [ ] Guardrails + staged rollout
