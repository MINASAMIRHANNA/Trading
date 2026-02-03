from __future__ import annotations

from typing import Any


def ensure_dashboard_bootstrap(db: Any) -> None:
    """Best-effort dashboard bootstrap.

    Must NEVER prevent the dashboard from starting.

    Batch-27: dashboards now bootstrap the shared schema consistently:
    - core tables (settings/logs/commands/equity/rejections/meta)
    - learning tables (daily learning stats + threshold adjustments)
    - signal inbox (approvals)

    All operations are idempotent.
    """
    try:
        from mina_core.db.ddl import bootstrap_dashboard  # includes learning in Batch-27
        bootstrap_dashboard(db.conn, lock=getattr(db, "lock", None))
    except Exception:
        # never block startup
        pass
