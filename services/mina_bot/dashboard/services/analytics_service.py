from __future__ import annotations

from typing import Any, Dict


def get_analytics(db: Any) -> Dict:
    """Analytics endpoint payload (repo-first, with legacy fallback)."""
    conn = getattr(db, "conn", None)
    if conn is None:
        return {
            "rejections": [],
            "golden_hours": [],
            "calibration": [],
            "recent_trades": [],
            "generated_at": None,
            "errors": {"db": "Database connection not available"},
        }

    try:
        from mina_core.db.repos.analytics_repo import AnalyticsRepo  # type: ignore
        return AnalyticsRepo.generate(conn, lock=getattr(db, "lock", None))
    except Exception:
        try:
            from dashboard.legacy_analytics import generate_analytics_legacy  # type: ignore
            return generate_analytics_legacy(conn)
        except Exception:
            return {
                "rejections": [],
                "golden_hours": [],
                "calibration": [],
                "recent_trades": [],
                "generated_at": None,
                "errors": {"analytics": "Failed to generate analytics"},
            }
