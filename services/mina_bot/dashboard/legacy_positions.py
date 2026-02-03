"""
Positions building logic extracted from dashboard/app.py.

This keeps dashboard/app.py smaller while preserving behavior.
"""

from __future__ import annotations

from typing import Callable, Dict, Any, List


def get_positions_data(
    db: Any,
    get_real_positions: Callable[[], Dict[str, Any]],
    positions_status_map: Callable[[], Dict[str, Any]],
    normalize_side: Callable[[str], str],
    public_price: Callable[[str, str], float],
) -> List[dict]:
    # Prefer repo (backend-agnostic). Fallback keeps legacy behavior.
    try:
        from mina_core.db.repos.trades_repo import TradesRepo
        conn = getattr(db, 'conn', None)
        lock = getattr(db, 'lock', None)
        db_trades = TradesRepo.list_active(conn, lock=lock) if conn is not None else db.get_all_active_trades()
    except Exception:
        db_trades = db.get_all_active_trades()

    real_pos = get_real_positions()
    ps_map = positions_status_map()
    final_list: List[dict] = []

    for t in db_trades:
        sym = t.get("symbol")
        if real_pos and sym in real_pos:
            r = real_pos[sym]
            t["unrealized_pnl"] = r.get("pnl")
            t["current_price"] = r.get("mark")
            t["verified"] = True
            try:
                t["direction"] = r.get("direction")
            except Exception:
                t["direction"] = None
            # Infer direction from signal text only if not already provided by exchange/monitor
            if not t.get("direction") or str(t.get("direction")).upper() in {"", "UNKNOWN", "NONE"}:
                sig_u = str(t.get("signal") or "").upper()
                side = normalize_side(sig_u)
                if side == "BUY":
                    t["direction"] = "LONG"
                elif side == "SELL":
                    t["direction"] = "SHORT"
                else:
                    t["direction"] = "UNKNOWN"
        elif ps_map and sym and str(sym).upper() in ps_map:
            p = ps_map[str(sym).upper()]
            try:
                t["current_price"] = float(p.get("markPrice") or p.get("mark") or p.get("mark_price") or 0.0)
            except Exception:
                pass
            try:
                t["unrealized_pnl"] = float(p.get("unrealizedProfit") or p.get("unRealizedProfit") or p.get("pnl") or 0.0)
            except Exception:
                pass
            try:
                amt = float(p.get("positionAmt") or 0.0)
                if amt > 0:
                    t["direction"] = "LONG"
                elif amt < 0:
                    t["direction"] = "SHORT"
            except Exception:
                pass
            t["verified"] = True
            t["verified_source"] = "execution_monitor"

        elif real_pos and sym not in real_pos and str(db.get_setting("mode")).upper() == "LIVE":
            # close stale trade
            try:
                db.close_trade(sym, "SYNC_FIX_DASHBOARD", t.get("entry_price", 0))
            except Exception:
                pass
            continue
        else:
            # Not LIVE verified (paper/test). Compute best-effort unrealized PnL from public prices.
            t["verified"] = False
            try:
                sym_u = str(t.get("symbol") or "").upper()
                entry = float(t.get("entry_price") or 0.0)
                qty = float(t.get("quantity") or 0.0)
                sig = str(t.get("signal") or "").upper()
                mt = str(t.get("market_type") or "futures").lower()

                cur = public_price(sym_u, mt)
                if cur > 0:
                    t["current_price"] = cur
                    side_sig = normalize_side(sig)
                    is_long = side_sig == "BUY"
                    is_short = side_sig == "SELL"
                    t["direction"] = "LONG" if is_long else ("SHORT" if is_short else "UNKNOWN")
                    pnl = 0.0
                    if entry > 0 and qty > 0:
                        if is_long and not is_short:
                            pnl = (cur - entry) * qty
                        elif is_short and not is_long:
                            pnl = (entry - cur) * qty
                    t["unrealized_pnl"] = pnl
            except Exception:
                pass

        # Infer direction from signal text only if not already provided by exchange/monitor
        if not t.get("direction") or str(t.get("direction")).upper() in {"", "UNKNOWN", "NONE"}:
            sig_u = str(t.get("signal") or "").upper()
            side = normalize_side(sig_u)
            if side == "BUY":
                t["direction"] = "LONG"
            elif side == "SELL":
                t["direction"] = "SHORT"
            else:
                t["direction"] = "UNKNOWN"

        # Backward-compat: ensure `pnl` reflects OPEN unrealized PnL (some UIs read `pnl` only)
        try:
            if str(t.get("status", "")).upper() == "OPEN":
                up = t.get("unrealized_pnl")
                if up is not None:
                    t["pnl"] = float(up)
        except Exception:
            pass

        # Backward-compat: ensure `ai_confidence` is populated (some UIs expect it)
        try:
            if t.get("ai_confidence") is None and t.get("confidence") is not None:
                t["ai_confidence"] = float(t["confidence"])
            elif t.get("confidence") is None and t.get("ai_confidence") is not None:
                t["confidence"] = float(t["ai_confidence"])
        except Exception:
            pass

        final_list.append(t)

    return final_list
