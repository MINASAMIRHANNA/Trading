from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence, Set

from .base import row_to_dict


def _execute(conn, sql: str, params: Sequence[Any] = ()):  # noqa: ANN401
    if hasattr(conn, "execute"):
        return conn.execute(sql, tuple(params))
    cur = conn.cursor()
    cur.execute(sql, tuple(params))
    return cur


def _table_cols(conn, table: str, lock=None) -> Set[str]:
    try:
        q = f"PRAGMA table_info({table})"
        if lock is None:
            rows = _execute(conn, q).fetchall() or []
        else:
            with lock:
                rows = _execute(conn, q).fetchall() or []
        return {r[1] for r in rows}
    except Exception:
        return set()


class AnalyticsRepo:
    """Compute dashboard analytics from DB tables.

    This is a direct lift of the existing /api/analytics logic from dashboard/app.py,
    moved into a repo so it can be shared and tested more easily.
    """

    @staticmethod
    def generate(conn, lock=None) -> Dict[str, Any]:
        errors: Dict[str, str] = {}

        trades_cols = _table_cols(conn, "trades", lock=lock)
        rej_cols = _table_cols(conn, "rejections", lock=lock)

        now_utc = datetime.utcnow()
        cutoff_14d = (now_utc - timedelta(days=14)).strftime("%Y-%m-%dT%H:%M:%SZ")
        cutoff_30d = (now_utc - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")

        # Build a robust time expression for SQLite (string timestamps).
        time_expr = None
        if "closed_at" in trades_cols and "timestamp" in trades_cols:
            time_expr = "COALESCE(NULLIF(closed_at,''), timestamp)"
        elif "closed_at" in trades_cols:
            time_expr = "NULLIF(closed_at,'')"
        elif "timestamp" in trades_cols:
            time_expr = "timestamp"

        # Trade is "closed" if status != OPEN, or closed_at is set (for older schemas).
        where_closed_parts: List[str] = []
        if "status" in trades_cols:
            where_closed_parts.append("status != 'OPEN'")
        if "closed_at" in trades_cols:
            where_closed_parts.append("(closed_at IS NOT NULL AND closed_at != '')")
        where_closed_base = "(" + " OR ".join(where_closed_parts) + ")" if where_closed_parts else "1=1"

        # 1) Rejections
        rejections: List[Dict[str, Any]] = []
        if "reason" in rej_cols:
            try:
                if "timestamp" in rej_cols:
                    rows = _execute(
                        conn,
                        """
                        SELECT reason, COUNT(*) AS count
                        FROM rejections
                        WHERE timestamp >= ?
                        GROUP BY reason
                        ORDER BY count DESC
                        LIMIT 10
                        """,
                        (cutoff_14d,),
                    ).fetchall()
                else:
                    rows = _execute(
                        conn,
                        """
                        SELECT reason, COUNT(*) AS count
                        FROM rejections
                        GROUP BY reason
                        ORDER BY count DESC
                        LIMIT 10
                        """,
                    ).fetchall()
                rejections = [{"reason": r["reason"], "count": int(r["count"] or 0)} for r in (rows or [])]
            except Exception as e:
                errors["rejections"] = str(e)
        else:
            errors["rejections"] = "rejections table/columns not available"

        # 2) Recent closed trades
        recent_trades: List[Dict[str, Any]] = []
        if {"symbol", "signal"}.issubset(trades_cols):
            try:
                conf_expr = "0"
                if "ai_confidence" in trades_cols and "confidence" in trades_cols:
                    conf_expr = "COALESCE(ai_confidence, confidence, 0)"
                elif "ai_confidence" in trades_cols:
                    conf_expr = "COALESCE(ai_confidence, 0)"
                elif "confidence" in trades_cols:
                    conf_expr = "COALESCE(confidence, 0)"

                order_expr = time_expr if time_expr else ("timestamp" if "timestamp" in trades_cols else "id")

                where_parts = [where_closed_base]
                params: List[Any] = []
                if time_expr:
                    where_parts.append(f"{time_expr} >= ?")
                    params.append(cutoff_30d)

                where_sql = " AND ".join(where_parts) if where_parts else "1=1"

                q = f"""
                    SELECT
                        {order_expr} AS closed_at,
                        symbol,
                        signal,
                        entry_price,
                        close_price,
                        pnl,
                        {conf_expr} AS confidence,
                        COALESCE(close_reason, 'CLOSED') AS close_reason
                    FROM trades
                    WHERE {where_sql}
                    ORDER BY {order_expr} DESC
                    LIMIT 50
                """
                rows = _execute(conn, q, tuple(params)).fetchall()
                recent_trades = [
                    {
                        "closed_at": r["closed_at"],
                        "symbol": r["symbol"],
                        "signal": r["signal"],
                        "entry_price": float(r["entry_price"] or 0),
                        "close_price": float(r["close_price"] or 0),
                        "pnl": float(r["pnl"] or 0),
                        "confidence": float(r["confidence"] or 0),
                        "close_reason": r["close_reason"] or "CLOSED",
                    }
                    for r in (rows or [])
                ]
            except Exception as e:
                errors["recent_trades"] = str(e)
        else:
            errors["recent_trades"] = "trades table/columns not available"

        # 3) Golden hours
        golden_hours: List[Dict[str, Any]] = []
        try:
            if time_expr and "pnl" in trades_cols:
                where_sql = f"{where_closed_base} AND {time_expr} >= ?"
                rows = _execute(
                    conn,
                    f"""
                    SELECT
                        CAST(substr({time_expr}, 12, 2) AS INTEGER) AS hour,
                        SUM(COALESCE(pnl, 0)) AS total_pnl,
                        COUNT(*) AS trades
                    FROM trades
                    WHERE {where_sql}
                    GROUP BY hour
                    ORDER BY hour ASC
                    """,
                    (cutoff_30d,),
                ).fetchall()

                golden_hours = [
                    {
                        "hour": str(int(r["hour"])).zfill(2),
                        "total_pnl": float(r["total_pnl"] or 0),
                        "trades": int(r["trades"] or 0),
                    }
                    for r in (rows or [])
                    if r["hour"] is not None
                ]
            else:
                errors["golden_hours"] = "closed_at/timestamp not available for golden hours"
        except Exception as e:
            errors["golden_hours"] = str(e)

        # 4) Calibration buckets
        calibration: List[Dict[str, Any]] = []
        try:
            conf_col = "ai_confidence" if "ai_confidence" in trades_cols else (
                "confidence" if "confidence" in trades_cols else None
            )
            if conf_col and "pnl" in trades_cols and time_expr:
                where_sql = f"{where_closed_base} AND {time_expr} >= ?"
                rows = _execute(
                    conn,
                    f"SELECT COALESCE({conf_col}, 0) AS conf, COALESCE(pnl, 0) AS pnl FROM trades WHERE {where_sql}",
                    (cutoff_30d,),
                ).fetchall()

                buckets = {f"{lo}-{lo+20}": {"bucket": f"{lo}-{lo+20}", "avg_pnl": 0.0, "trades": 0} for lo in range(0, 100, 20)}
                sums = {k: 0.0 for k in buckets}

                for r in (rows or []):
                    conf = float(r["conf"] or 0)
                    pnl = float(r["pnl"] or 0)
                    conf_pct = max(0.0, min(100.0, conf))
                    lo = int(conf_pct // 20) * 20
                    if lo >= 100:
                        lo = 80
                    key = f"{lo}-{lo+20}"
                    buckets[key]["trades"] += 1
                    sums[key] += pnl

                for k, v in buckets.items():
                    n = v["trades"]
                    v["avg_pnl"] = (sums[k] / n) if n > 0 else 0.0

                calibration = list(buckets.values())
            else:
                errors["calibration"] = "confidence/pnl/time columns not available"
        except Exception as e:
            errors["calibration"] = str(e)

        return {
            "rejections": rejections,
            "golden_hours": golden_hours,
            "calibration": calibration,
            "recent_trades": recent_trades,
            "generated_at": now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "errors": errors,
        }
