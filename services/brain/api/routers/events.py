from __future__ import annotations

from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Query
from sqlalchemy import text

from database.engine import get_engine

router = APIRouter(tags=["events"])


@router.get("")
def list_events(
    limit: int = Query(50, ge=1, le=500),
    role: Optional[str] = Query(None, description="Filter by bot_role"),
):
    """
    Read-only view over the shared_events table (written by gateway audit/events).
    This exists primarily to support the Brain UI Events page.
    """
    engine = get_engine()
    if engine.url.drivername.startswith("sqlite"):
        return {"ok": False, "error": "events_unavailable_sqlite", "items": [], "count": 0}

    where = ""
    params: Dict[str, Any] = {"limit": limit}
    if role:
        where = "WHERE bot_role = :role"
        params["role"] = role

    sql = text(f"""
        SELECT id, bot_role, event_type, data, created_at
        FROM shared_events
        {where}
        ORDER BY id DESC
        LIMIT :limit
    """)

    items: List[Dict[str, Any]] = []
    try:
        with engine.connect() as conn:
            rows = conn.execute(sql, params).mappings().all()
            for r in rows:
                items.append(
                    {
                        "id": r["id"],
                        "bot_role": r["bot_role"],
                        "event_type": r["event_type"],
                        "data": r["data"],
                        "created_at": (r["created_at"].isoformat() if hasattr(r["created_at"], "isoformat") else r["created_at"]),
                    }
                )
    except Exception as e:
        return {"ok": False, "error": str(e), "items": [], "count": 0}

    return {"ok": True, "items": items, "count": len(items)}
