from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Sequence

from .base import row_to_dict, safe_json_loads


def _execute(conn, sql: str, params: Sequence[Any] = ()):  # noqa: ANN401
    if hasattr(conn, "execute"):
        return conn.execute(sql, tuple(params))
    cur = conn.cursor()
    cur.execute(sql, tuple(params))
    return cur


class TradesRepo:
    """Canonical access layer for the trades table.

    Dashboard uses this repo to read trades (OPEN/CLOSED) in a backend-agnostic
    way (SQLite + Postgres via pg_compat).
    """

    @staticmethod
    def _row_to_trade(d: Dict[str, Any]) -> Dict[str, Any]:
        # Match DatabaseManager._row_to_trade semantics.
        d2 = dict(d)
        d2["realized_pnl"] = d2.get("pnl", 0.0)
        d2["take_profits"] = safe_json_loads(d2.get("take_profits"), [])
        d2["explain"] = safe_json_loads(d2.get("explain"), {})

        # Sprint 8: protection_details can be JSON or raw string.
        pd = d2.get("protection_details")
        if pd is not None:
            try:
                d2["protection_details"] = json.loads(pd) if isinstance(pd, str) and pd else pd
            except Exception:
                d2["protection_details"] = pd
        return d2

    @staticmethod
    def list_active(conn, lock=None) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM trades WHERE status='OPEN'"
        if lock is None:
            rows = _execute(conn, sql).fetchall() or []
        else:
            with lock:
                rows = _execute(conn, sql).fetchall() or []
        out: List[Dict[str, Any]] = []
        for r in rows:
            d = row_to_dict(r)
            out.append(TradesRepo._row_to_trade(d))
        return out

    @staticmethod
    def list_closed(conn, lock=None, *, limit: int = 1000) -> List[Dict[str, Any]]:
        lim = max(1, min(int(limit or 1000), 10000))
        sql = "SELECT * FROM trades WHERE status='CLOSED' ORDER BY id DESC LIMIT ?"
        if lock is None:
            rows = _execute(conn, sql, (lim,)).fetchall() or []
        else:
            with lock:
                rows = _execute(conn, sql, (lim,)).fetchall() or []
        out: List[Dict[str, Any]] = []
        for r in rows:
            d = row_to_dict(r)
            out.append(TradesRepo._row_to_trade(d))
        return out
