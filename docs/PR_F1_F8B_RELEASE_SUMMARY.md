# PR Release Summary: F1 -> F8b (Engine-Only Control Plane)

## Scope shipped

This branch delivers the unified, engine-owned control plane from F1 through F8b with no dashboard runtime dependency.

### F1-F3 Ops UI foundations
- Added Ops UI pages and wiring for:
  - observability (`/ui/ops/observability`)
  - live control (`/ui/ops/live-control`)
  - dead letters (`/ui/ops/dead-letters`)
  - commands (`/ui/ops/commands`)
- Added additive API helpers for ops views:
  - dead letters list/detail and safe requeue support
  - commands listing

### F4-F5 Strategy controls
- Added strategy discovery and DB-backed per-role strategy config endpoints.
- Added Ops strategies page (`/ui/ops/strategies`) with live-confirm safety flow.
- Added v2 per-strategy schema-driven params support and validation.

### F6-F7 Audit and drill-in
- Added audit explorer API and UI:
  - traces list
  - trace detail timeline
  - paper replay (safe scope)
- Extended trace detail with Brain decision drill-in fields when available.

### F8b Go-Live cockpit
- Added readiness aggregator endpoint:
  - `GET /api/control/live/readiness`
- Added Go-Live cockpit page:
  - `/ui/ops/go-live`
  - alias `/ui/ops/live-readiness`
- Added nav link and auto-refresh readiness checks in UI.

## Key routes

### Control/Read APIs
- `GET /api/control/live/status`
- `POST /api/control/live/arm`
- `POST /api/control/live/confirm`
- `POST /api/control/live/disarm`
- `POST /api/control/live/allowlist`
- `POST /api/control/live/limits`
- `GET /api/control/live/readiness`
- `GET /api/control/strategies/discover`
- `GET /api/control/strategies/status?role=...`
- `POST /api/control/strategies/apply`

### Unified Ops APIs
- `GET /api/unified/observability`
- `GET /api/unified/dead_letters?role=...&limit=...`
- `GET /api/unified/dead_letters/detail?role=...&id=...`
- `POST /api/unified/dead_letters/requeue`
- `GET /api/unified/{role}/commands?limit=...&status=...`
- `GET /api/unified/{role}/signals`
- `POST /api/unified/{role}/signals/{id}/approve`
- `POST /api/unified/{role}/signals/{id}/reject`
- `POST /api/unified/{role}/commands`

### Audit APIs
- `GET /api/audit/traces`
- `GET /api/audit/trace/{trace_id}`
- `POST /api/audit/replay/paper`

### UI pages
- `/ui/ops/observability`
- `/ui/ops/live-control`
- `/ui/ops/go-live`
- `/ui/ops/dead-letters`
- `/ui/ops/dead-letters/{role}/{dead_letter_id}`
- `/ui/ops/commands`
- `/ui/ops/signals`
- `/ui/ops/actions`
- `/ui/ops/strategies`
- `/ui/ops/audit`

## Safety notes

- Live open-trade actions are guarded by live gate + policy checks.
- Kill-switch semantics remain unchanged: block OPEN, allow CLOSE.
- Live control and strategy apply flows require explicit confirmation paths.
- Readiness endpoint is additive and resilient (partial sources return `errors[]`, no hard 500 by design).

## Validation evidence

Commands run for release verification:

```bash
python -m compileall gateway services/mina_strategies services/nautilus_engine

export COMPOSE_PROJECT_NAME=trading_release
docker compose -f docker-compose.yml up -d --build
docker compose -f docker-compose.yml -f docker-compose.bots.yml up -d --build

# bootstrap on fresh project volumes + qa pack run
COMPOSE_PROJECT_NAME=trading_release ARTIFACT_DIR=/tmp/trading_release_artifacts bash scripts/ci_run_qa_pack.sh

# required smoke commands
bash scripts/smoke_qa_pack.sh
bash scripts/smoke_ops_ui_api.sh

curl -s -o /tmp/go_live.out -w '%{http_code}' http://localhost:8200/ui/ops/go-live
```

Observed results:
- `compileall`: pass
- compose up (base + bots): pass after freeing conflicting local ports
- `smoke_qa_pack.sh`: pass
- `smoke_ops_ui_api.sh`: pass
- `/ui/ops/go-live`: HTTP 200
