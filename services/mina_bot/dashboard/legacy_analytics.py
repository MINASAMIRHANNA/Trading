"""Legacy analytics implementation.

Used as a fallback when the shared AnalyticsRepo is unavailable.
This module contains the previous inlined logic from dashboard.app.
"""

import json
from datetime import datetime, timedelta
from typing import Any, Dict


def _utc_iso_now() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _table_cols(conn, table: str):
    """Best-effort column discovery for SQLite."""
    try:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        return {r[1] for r in rows}
    except Exception:
        return set()


def generate_analytics_legacy(conn) -> Dict[str, Any]:
    """Generate analytics payload using legacy logic.

    Returns the same shape expected by analytics.html.
    """

    errors: Dict[str, str] = {}

    trades_cols = _table_cols(conn, "trades")
    rej_cols = _table_cols(conn, "rejections")

    now_utc = datetime.utcnow()
    cutoff_14d = (now_utc - timedelta(days=14)).strftime("%Y-%m-%dT%H:%M:%SZ")
    cutoff_30d = (now_utc - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Build a robust time expression for SQLite (string timestamps).
    time_expr = None
    if "closed_at" in trades_cols and "timestamp" in trades_cols:
        # If closed_at is missing/empty, fall back to timestamp.
        time_expr = "COALESCE(NULLIF(closed_at,''), timestamp)"
    elif "closed_at" in trades_cols:
        time_expr = "NULLIF(closed_at,'')"
    elif "timestamp" in trades_cols:
        time_expr = "timestamp"

    # Trade is "closed" if status != OPEN, or closed_at is set (for older schemas).
    where_closed_parts = []
    if "status" in trades_cols:
        where_closed_parts.append("status != 'OPEN'")
    if "closed_at" in trades_cols:
        where_closed_parts.append("(closed_at IS NOT NULL AND closed_at != '')")
    where_closed_base = "(" + " OR ".join(where_closed_parts) + ")" if where_closed_parts else "1=1"

    # 1) Rejections
    rejections = []
    if "reason" in rej_cols:
        try:
            if "timestamp" in rej_cols:
                rows = conn.execute(
                    """
                    SELECT reason, COUNT(*) AS count
                    FROM rejections
                    WHERE timestamp >= ?
                    GROUP BY reason
                    ORDER BY count DESC
                    LIMIT 20
                    """,
                    (cutoff_30d,),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT reason, COUNT(*) AS count
                    FROM rejections
                    GROUP BY reason
                    ORDER BY count DESC
                    LIMIT 20
                    """
                ).fetchall()

            for r in rows or []:
                reason = r[0]
                count = r[1]
                if reason is not None:
                    rejections.append({"reason": str(reason), "count": int(count or 0)})
        except Exception as e:
            errors["rejections"] = str(e)

    # 2) Golden Hours (hour-of-day performance)
    golden_hours = []
    if time_expr and "pnl" in trades_cols:
        try:
            rows = conn.execute(
                f"""
                SELECT SUBSTR({time_expr}, 12, 2) AS hour,
                       COUNT(*) AS n,
                       AVG(CAST(pnl AS REAL)) AS avg_pnl
                FROM trades
                WHERE {where_closed_base}
                  AND {time_expr} >= ?
                GROUP BY hour
                ORDER BY avg_pnl DESC
                """,
                (cutoff_30d,),
            ).fetchall()
            for r in rows or []:
                h = r[0]
                golden_hours.append({"hour": int(h or 0), "count": int(r[1] or 0), "avg_pnl": float(r[2] or 0.0)})
        except Exception as e:
            errors["golden_hours"] = str(e)

    # 3) Calibration (confidence vs outcome)
    calibration = []
    if "confidence" in trades_cols and "pnl" in trades_cols:
        try:
            # bucket confidence into 10% bins
            rows = conn.execute(
                f"""
                SELECT (CAST(confidence AS REAL) / 10) * 10 AS bin,
                       COUNT(*) AS n,
                       AVG(CASE WHEN CAST(pnl AS REAL) > 0 THEN 1 ELSE 0 END) AS win_rate
                FROM trades
                WHERE {where_closed_base}
                GROUP BY bin
                ORDER BY bin ASC
                """
            ).fetchall()
            for r in rows or []:
                calibration.append({"bin": int(r[0] or 0), "count": int(r[1] or 0), "win_rate": float(r[2] or 0.0)})
        except Exception as e:
            errors["calibration"] = str(e)

    # 4) Recent Trades
    recent_trades = []
    if trades_cols:
        try:
            cols = ["id", "symbol", "status", "pnl", "confidence"]
            cols = [c for c in cols if c in trades_cols]
            if not cols:
                cols = [next(iter(trades_cols))]
            cols_sql = ", ".join(cols)
            order_expr = time_expr or ("timestamp" if "timestamp" in trades_cols else "id")
            rows = conn.execute(
                f"""
                SELECT {cols_sql}
                FROM trades
                WHERE {where_closed_base}
                ORDER BY {order_expr} DESC
                LIMIT 50
                """
            ).fetchall()
            for r in rows or []:
                d = {}
                for i, c in enumerate(cols):
                    d[c] = r[i]
                # meta parsing
                if "meta" in trades_cols and "meta" in d and d.get("meta"):
                    try:
                        d["meta"] = json.loads(d["meta"]) if isinstance(d["meta"], str) else d["meta"]
                    except Exception:
                        pass
                recent_trades.append(d)
        except Exception as e:
            errors["recent_trades"] = str(e)

    return {
        "rejections": rejections,
        "golden_hours": golden_hours,
        "calibration": calibration,
        "recent_trades": recent_trades,
        "generated_at": _utc_iso_now(),
        "errors": errors,
    }
