"""Legacy (pre-repo) report helpers.

Batch-13 goal
-------------
Keep the Dashboard stable while we progressively move reporting logic into
canonical repos (mina_core.db.repos). This module contains the previous
in-dashboard implementations so `dashboard/app.py` can be smaller and easier
to maintain.

These functions are **best-effort** and should never raise in normal usage.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List


def _pnl_of_trade(t: Dict[str, Any]) -> float:
    try:
        return float(t.get("pnl", t.get("realized_pnl", 0)) or 0)
    except Exception:
        return 0.0


def advanced_stats_legacy(db) -> Dict[str, Any]:
    stats = {}
    try:
        stats = db.get_stats() or {}
    except Exception:
        stats = {}

    try:
        all_trades = db.get_all_closed_trades() or []
    except Exception:
        all_trades = []

    winning_trades = [t for t in all_trades if _pnl_of_trade(t) > 0]
    total_volume = 0.0
    for t in all_trades:
        try:
            total_volume += float(t.get("entry_price", 0) or 0) * float(t.get("quantity", 0) or 0)
        except Exception:
            pass
    total_volume *= 2.0
    total_fees = total_volume * 0.00075

    gross_profits = sum(_pnl_of_trade(t) for t in winning_trades)
    gross_losses = abs(sum(_pnl_of_trade(t) for t in all_trades if _pnl_of_trade(t) < 0))

    if gross_losses > 0:
        profit_factor = gross_profits / gross_losses
    elif gross_profits > 0:
        profit_factor = 99.9
    else:
        profit_factor = 0.0

    equity_curve = []
    try:
        equity_curve = [float(d.get("total_balance", 0) or 0) for d in (db.get_equity_curve(limit=200) or [])]
    except Exception:
        equity_curve = []

    max_drawdown = 0.0
    if equity_curve:
        peak = equity_curve[0]
        for val in equity_curve:
            if val > peak:
                peak = val
            dd = (peak - val) / peak if peak > 0 else 0
            if dd > max_drawdown:
                max_drawdown = dd

    return {
        "pnl": stats.get("pnl", 0),
        "win_rate": stats.get("win_rate", 0),
        "total_fees": round(float(total_fees or 0), 2),
        "profit_factor": round(float(profit_factor or 0), 2),
        "max_drawdown": round(float(max_drawdown or 0) * 100.0, 2),
        "avg_duration": "Dynamic",
    }


def _parse_iso(ts: Any):
    if not ts:
        return None
    s = str(ts).replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def daily_summary_legacy(db, *, days: int = 7) -> List[Dict[str, Any]]:
    days = max(1, min(int(days or 7), 365))
    try:
        trades = db.get_all_closed_trades() or []
    except Exception:
        trades = []

    by_day = {}
    for t in trades:
        dt = _parse_iso(t.get("closed_at") or t.get("timestamp"))
        if dt is None:
            continue
        day = dt.date().isoformat()
        rec = by_day.setdefault(day, {"day_utc": day, "trades": 0, "wins": 0, "losses": 0, "pnl_sum": 0.0})
        pnl = _pnl_of_trade(t)
        rec["trades"] += 1
        rec["pnl_sum"] += pnl
        if pnl > 0:
            rec["wins"] += 1
        elif pnl < 0:
            rec["losses"] += 1

    items = list(by_day.values())
    items.sort(key=lambda x: x["day_utc"], reverse=True)
    items = items[:days]
    for rec in items:
        tr = rec.get("trades", 0) or 0
        wins = rec.get("wins", 0) or 0
        rec["win_rate"] = round((wins / tr) * 100.0, 2) if tr else 0.0
        rec["pnl_sum"] = round(float(rec.get("pnl_sum", 0) or 0), 6)
    return items


def pnl_series_legacy(db, *, days: int = 30) -> Dict[str, Any]:
    items = daily_summary_legacy(db, days=days)
    items = list(reversed(items))
    return {
        "labels": [d["day_utc"] for d in items],
        "pnl": [float(d.get("pnl_sum", 0) or 0) for d in items],
    }


def top_symbols_legacy(db, *, limit: int = 10) -> List[Dict[str, Any]]:
    limit = max(1, min(int(limit or 10), 100))
    try:
        trades = db.get_all_closed_trades() or []
    except Exception:
        trades = []

    agg = {}
    for t in trades:
        sym = str(t.get("symbol") or "UNKNOWN").upper()
        rec = agg.setdefault(sym, {"symbol": sym, "trades": 0, "wins": 0, "pnl_sum": 0.0})
        pnl = _pnl_of_trade(t)
        rec["trades"] += 1
        rec["pnl_sum"] += pnl
        if pnl > 0:
            rec["wins"] += 1

    items = list(agg.values())
    for rec in items:
        tr = rec.get("trades", 0) or 0
        rec["win_rate"] = round((rec.get("wins", 0) / tr) * 100.0, 2) if tr else 0.0
        rec["pnl_sum"] = round(float(rec.get("pnl_sum", 0) or 0), 6)

    items.sort(key=lambda x: (x["pnl_sum"], x["trades"]), reverse=True)
    return items[:limit]


def winrate_breakdown_legacy(db, *, days: int = 30) -> List[Dict[str, Any]]:
    days = max(1, min(int(days or 30), 365))
    try:
        trades = db.get_all_closed_trades() or []
    except Exception:
        trades = []

    cutoff = datetime.now(timezone.utc).date().toordinal() - days
    filt = []
    for t in trades:
        dt = _parse_iso(t.get("closed_at") or t.get("timestamp"))
        if dt is None:
            continue
        if dt.date().toordinal() >= cutoff:
            filt.append(t)

    agg = {}
    for t in filt:
        key = str(t.get("strategy") or t.get("strategy_tag") or t.get("algo_mode") or t.get("mode") or "UNKNOWN").upper()
        rec = agg.setdefault(key, {"key": key, "trades": 0, "wins": 0, "losses": 0, "pnl_sum": 0.0})
        pnl = _pnl_of_trade(t)
        rec["trades"] += 1
        rec["pnl_sum"] += pnl
        if pnl > 0:
            rec["wins"] += 1
        elif pnl < 0:
            rec["losses"] += 1

    items = list(agg.values())
    for rec in items:
        tr = rec.get("trades", 0) or 0
        rec["win_rate"] = round((rec.get("wins", 0) / tr) * 100.0, 2) if tr else 0.0
        rec["pnl_sum"] = round(float(rec.get("pnl_sum", 0) or 0), 6)

    items.sort(key=lambda x: (x.get("win_rate", 0), x.get("trades", 0)), reverse=True)
    return items
