from __future__ import annotations

from typing import Any, Dict


def get_advanced_stats(db: Any) -> Dict:
    """Advanced stats for the UI (repo-first, legacy fallback)."""
    try:
        from mina_core.db.repos.reports_repo import ReportsRepo  # type: ignore
        conn = getattr(db, "conn", None)
        lock = getattr(db, "lock", None)
        return ReportsRepo.advanced_stats(conn, lock, db=db)
    except Exception:
        pass

    try:
        from dashboard.legacy_reports import advanced_stats_legacy  # type: ignore
        return advanced_stats_legacy(db)
    except Exception:
        try:
            return db.get_stats()
        except Exception:
            return {"pnl": 0, "win_rate": 0, "total_fees": 0, "profit_factor": 0, "max_drawdown": 0, "avg_duration": "Dynamic"}


def daily(db: Any, days: int = 7) -> Dict:
    d = max(1, min(int(days or 7), 365))
    try:
        from mina_core.db.repos.reports_repo import ReportsRepo  # type: ignore
        conn = getattr(db, "conn", None)
        lock = getattr(db, "lock", None)
        items = ReportsRepo.daily_summary(conn, lock, days=d)
        return {"ok": True, "items": items, "count": len(items)}
    except Exception:
        pass

    try:
        from dashboard.legacy_reports import daily_summary_legacy  # type: ignore
        items = daily_summary_legacy(db, days=d)
        return {"ok": True, "items": items, "count": len(items)}
    except Exception as e:
        return {"ok": False, "items": [], "count": 0, "error": str(e)}


def pnl(db: Any, days: int = 30) -> Dict:
    d = max(1, min(int(days or 30), 365))
    try:
        from mina_core.db.repos.reports_repo import ReportsRepo  # type: ignore
        conn = getattr(db, "conn", None)
        lock = getattr(db, "lock", None)
        return {"ok": True, "data": ReportsRepo.pnl_series(conn, lock, days=d)}
    except Exception:
        pass

    try:
        from dashboard.legacy_reports import pnl_series_legacy  # type: ignore
        return {"ok": True, "data": pnl_series_legacy(db, days=d)}
    except Exception as e:
        return {"ok": False, "data": {"labels": [], "pnl": []}, "error": str(e)}


def top_symbols(db: Any, limit: int = 10) -> Dict:
    lim = max(1, min(int(limit or 10), 100))
    try:
        from mina_core.db.repos.reports_repo import ReportsRepo  # type: ignore
        conn = getattr(db, "conn", None)
        lock = getattr(db, "lock", None)
        items = ReportsRepo.top_symbols(conn, lock, limit=lim)
        return {"ok": True, "items": items, "count": len(items)}
    except Exception:
        pass

    try:
        from dashboard.legacy_reports import top_symbols_legacy  # type: ignore
        items = top_symbols_legacy(db, limit=lim)
        return {"ok": True, "items": items, "count": len(items)}
    except Exception as e:
        return {"ok": False, "items": [], "count": 0, "error": str(e)}


def winrate(db: Any, days: int = 30) -> Dict:
    d = max(1, min(int(days or 30), 365))
    try:
        from mina_core.db.repos.reports_repo import ReportsRepo  # type: ignore
        conn = getattr(db, "conn", None)
        lock = getattr(db, "lock", None)
        items = ReportsRepo.winrate_breakdown(conn, lock, days=d)
        return {"ok": True, "items": items, "count": len(items)}
    except Exception:
        pass

    try:
        from dashboard.legacy_reports import winrate_breakdown_legacy  # type: ignore
        items = winrate_breakdown_legacy(db, days=d)
        return {"ok": True, "items": items, "count": len(items)}
    except Exception as e:
        return {"ok": False, "items": [], "count": 0, "error": str(e)}
