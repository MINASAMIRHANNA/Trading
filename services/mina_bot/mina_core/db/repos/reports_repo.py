from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from .trades_repo import TradesRepo


def _pnl_of_trade(t: Dict[str, Any]) -> float:
    try:
        return float(t.get("pnl", t.get("realized_pnl", 0)) or 0)
    except Exception:
        return 0.0


def _parse_iso(ts: Any) -> Optional[datetime]:
    if not ts:
        return None
    s = str(ts)
    try:
        # tolerate Z
        s2 = s.replace('Z', '+00:00')
        dt = datetime.fromisoformat(s2)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _day_utc_from_trade(t: Dict[str, Any]) -> str:
    dt = _parse_iso(t.get('closed_at') or t.get('timestamp') or t.get('created_at'))
    if dt is None:
        return 'UNKNOWN'
    return dt.date().isoformat()


def _safe_symbol(t: Dict[str, Any]) -> str:
    return str(t.get('symbol') or 'UNKNOWN').upper()


def _strategy(t: Dict[str, Any]) -> str:
    return str(t.get('strategy') or t.get('strategy_tag') or t.get('algo_mode') or t.get('mode') or 'UNKNOWN').upper()


class ReportsRepo:
    """Read-only reporting utilities used by the Dashboard.

    This repo is intentionally **backend-agnostic**:
    - It reads trades via TradesRepo (SQLite + pg_compat).
    - It computes aggregates in Python to avoid SQL dialect differences.

    All methods are safe on empty datasets and return stable shapes.
    """

    @staticmethod
    def _get_closed_trades(conn, lock=None, *, limit: int = 10000) -> List[Dict[str, Any]]:
        if conn is None:
            return []
        try:
            return TradesRepo.list_closed(conn, lock, limit=limit)
        except Exception:
            return []

    @staticmethod
    def advanced_stats(conn, lock=None, *, db=None) -> Dict[str, Any]:
        """Return advanced stats used by /api/advanced_stats."""
        stats: Dict[str, Any] = {}
        try:
            if db is not None and hasattr(db, 'get_stats'):
                stats = db.get_stats() or {}
        except Exception:
            stats = {}

        all_trades = ReportsRepo._get_closed_trades(conn, lock)

        winning_trades = [t for t in all_trades if _pnl_of_trade(t) > 0]
        total_volume = 0.0
        for t in all_trades:
            try:
                total_volume += float(t.get('entry_price', 0) or 0) * float(t.get('quantity', 0) or 0)
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

        # Max drawdown: prefer equity curve if DB manager exposes it.
        equity_curve: List[float] = []
        if db is not None and hasattr(db, 'get_equity_curve'):
            try:
                eq = db.get_equity_curve(limit=200) or []
                equity_curve = [float(d.get('total_balance', 0) or 0) for d in eq]
            except Exception:
                equity_curve = []
        
        max_drawdown = 0.0
        if equity_curve:
            peak = equity_curve[0]
            for val in equity_curve:
                if val > peak:
                    peak = val
                dd = (peak - val) / peak if peak > 0 else 0.0
                if dd > max_drawdown:
                    max_drawdown = dd

        return {
            'pnl': stats.get('pnl', 0),
            'win_rate': stats.get('win_rate', 0),
            'total_fees': round(float(total_fees or 0), 2),
            'profit_factor': round(float(profit_factor or 0), 2),
            'max_drawdown': round(float(max_drawdown or 0) * 100.0, 2),
            'avg_duration': 'Dynamic',
        }

    @staticmethod
    def daily_summary(conn, lock=None, *, days: int = 7) -> List[Dict[str, Any]]:
        days = max(1, min(int(days or 7), 365))
        trades = ReportsRepo._get_closed_trades(conn, lock)
        by_day: Dict[str, Dict[str, Any]] = {}
        for t in trades:
            d = _day_utc_from_trade(t)
            if d == 'UNKNOWN':
                continue
            rec = by_day.setdefault(d, {'day_utc': d, 'trades': 0, 'wins': 0, 'losses': 0, 'pnl_sum': 0.0})
            pnl = _pnl_of_trade(t)
            rec['trades'] += 1
            rec['pnl_sum'] += pnl
            if pnl > 0:
                rec['wins'] += 1
            elif pnl < 0:
                rec['losses'] += 1
        items = list(by_day.values())
        items.sort(key=lambda x: x['day_utc'], reverse=True)
        items = items[:days]
        for rec in items:
            tr = rec.get('trades', 0) or 0
            wins = rec.get('wins', 0) or 0
            rec['win_rate'] = round((wins / tr) * 100.0, 2) if tr else 0.0
            rec['pnl_sum'] = round(float(rec.get('pnl_sum', 0) or 0), 6)
        return items

    @staticmethod
    def pnl_series(conn, lock=None, *, days: int = 30) -> Dict[str, Any]:
        days = max(1, min(int(days or 30), 365))
        daily = ReportsRepo.daily_summary(conn, lock, days=days)
        # convert to chronological series
        daily2 = list(reversed(daily))
        labels = [d['day_utc'] for d in daily2]
        pnl = [float(d.get('pnl_sum', 0) or 0) for d in daily2]
        return {'labels': labels, 'pnl': pnl}

    @staticmethod
    def top_symbols(conn, lock=None, *, limit: int = 10) -> List[Dict[str, Any]]:
        limit = max(1, min(int(limit or 10), 100))
        trades = ReportsRepo._get_closed_trades(conn, lock)
        agg: Dict[str, Dict[str, Any]] = {}
        for t in trades:
            sym = _safe_symbol(t)
            rec = agg.setdefault(sym, {'symbol': sym, 'trades': 0, 'pnl_sum': 0.0, 'wins': 0})
            pnl = _pnl_of_trade(t)
            rec['trades'] += 1
            rec['pnl_sum'] += pnl
            if pnl > 0:
                rec['wins'] += 1
        items = list(agg.values())
        for rec in items:
            tr = rec['trades'] or 0
            rec['win_rate'] = round((rec.get('wins', 0) / tr) * 100.0, 2) if tr else 0.0
            rec['pnl_sum'] = round(float(rec.get('pnl_sum', 0) or 0), 6)
        items.sort(key=lambda x: (x['pnl_sum'], x['trades']), reverse=True)
        return items[:limit]

    @staticmethod
    def winrate_breakdown(conn, lock=None, *, days: int = 30) -> List[Dict[str, Any]]:
        days = max(1, min(int(days or 30), 365))
        trades = ReportsRepo._get_closed_trades(conn, lock)
        # keep only last N days by closed_at
        def _dt_or_min(t):
            return _parse_iso(t.get('closed_at')) or datetime(1970, 1, 1, tzinfo=timezone.utc)

        trades.sort(key=_dt_or_min, reverse=True)
        # filter by date window
        cutoff = datetime.now(timezone.utc).date().toordinal() - days
        filt = []
        for t in trades:
            dt = _parse_iso(t.get('closed_at'))
            if dt is None:
                continue
            if dt.date().toordinal() >= cutoff:
                filt.append(t)
        agg: Dict[str, Dict[str, Any]] = {}
        for t in filt:
            key = _strategy(t)
            rec = agg.setdefault(key, {'key': key, 'trades': 0, 'wins': 0, 'losses': 0, 'pnl_sum': 0.0})
            pnl = _pnl_of_trade(t)
            rec['trades'] += 1
            rec['pnl_sum'] += pnl
            if pnl > 0:
                rec['wins'] += 1
            elif pnl < 0:
                rec['losses'] += 1
        items = list(agg.values())
        for rec in items:
            tr = rec['trades'] or 0
            rec['win_rate'] = round((rec.get('wins', 0) / tr) * 100.0, 2) if tr else 0.0
            rec['pnl_sum'] = round(float(rec.get('pnl_sum', 0) or 0), 6)
        items.sort(key=lambda x: (x['win_rate'], x['trades']), reverse=True)
        return items
