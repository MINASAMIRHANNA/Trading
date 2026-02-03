from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from database.models.sync_state import SyncState
from database.models.trade_features import TradeFeature


# Map human roles to Postgres schemas used by Mina bots
_ROLE_TO_SCHEMA = {
    "paper": "mina_paper",
    "live": "mina_live",
    "pump": "mina_pump",
}


def _env(*names: str, default: Optional[str] = None) -> Optional[str]:
    for n in names:
        v = os.getenv(n)
        if v:
            return v
    return default



def _normalize_source_dsn(dsn: str) -> str:
    # Prefer psycopg (v3) driver for Postgres.
    if dsn.startswith('postgres://'):
        dsn = 'postgresql://' + dsn[len('postgres://'):]
    if dsn.startswith('postgresql+psycopg2://'):
        dsn = 'postgresql+psycopg://' + dsn[len('postgresql+psycopg2://'):]
    if dsn.startswith('postgresql://'):
        dsn = 'postgresql+psycopg://' + dsn[len('postgresql://'):]
    return dsn


def get_source_engine() -> Engine:
    # Prefer unified env name used by docker-compose.allinone.yml, then keep
    # backward compatibility with older names.
    dsn = _env("BRAIN_SOURCE_DSN", "MINA_TRADING_PG_DSN", "TRADING_PG_DSN")
    if not dsn:
        raise RuntimeError(
            "Missing BRAIN_SOURCE_DSN (or TRADING_PG_DSN / MINA_TRADING_PG_DSN) for Mina Postgres source"
        )
    dsn = _normalize_source_dsn(dsn)

    # pool_pre_ping avoids stale connections in long-running containers
    return create_engine(dsn, pool_pre_ping=True, future=True)


def _get_table_columns(engine: Engine, schema: str, table: str) -> List[str]:
    q = text(
        """        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = :schema AND table_name = :table
        ORDER BY ordinal_position
        """
    )
    with engine.connect() as conn:
        rows = conn.execute(q, {"schema": schema, "table": table}).fetchall()
    return [r[0] for r in rows]


def _parse_dt_from_text(s: str) -> Optional[datetime]:
    if not s:
        return None
    s = s.strip()
    # Handle common Z suffix
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None


def _timestamp_from_row(row: Dict[str, Any]) -> datetime:
    # Prefer close time, then trade timestamp
    for k in ("closed_at", "timestamp"):
        if k in row and row[k]:
            dt = _parse_dt_from_text(str(row[k]))
            if dt:
                return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    for k in ("closed_at_ms", "timestamp_ms", "candle_close_ms"):
        v = row.get(k)
        if v is not None:
            try:
                return datetime.fromtimestamp(int(v) / 1000.0, tz=timezone.utc)
            except Exception:
                pass
    return datetime.now(timezone.utc)


def _infer_side(signal: Optional[str]) -> str:
    s = (signal or "").upper()
    if any(x in s for x in ["SELL", "SHORT"]):
        return "SHORT"
    if any(x in s for x in ["BUY", "LONG"]):
        return "LONG"
    # fallback
    return "LONG"


def _safe_float(x: Any) -> Optional[float]:
    if x is None:
        return None
    try:
        return float(x)
    except Exception:
        return None


def _safe_int(x: Any) -> Optional[int]:
    if x is None:
        return None
    try:
        return int(x)
    except Exception:
        return None


def _parse_take_profits(tp_text: Any) -> List[float]:
    if tp_text is None:
        return []
    if isinstance(tp_text, (list, tuple)):
        return [float(x) for x in tp_text if _safe_float(x) is not None]
    s = str(tp_text).strip()
    if not s:
        return []
    # Try JSON list first
    try:
        obj = json.loads(s)
        if isinstance(obj, list):
            return [float(x) for x in obj if _safe_float(x) is not None]
    except Exception:
        pass
    # Sometimes stored as '1,2,3'
    if "," in s:
        out = []
        for part in s.split(","):
            v = _safe_float(part.strip())
            if v is not None:
                out.append(v)
        return out
    v = _safe_float(s)
    return [v] if v is not None else []


def _encode_market_regime(label: Optional[str], regime_json: Optional[str]) -> int:
    # 1 = uptrend/bull, 0 = everything else (including downtrend/unknown)
    txt = (label or "").lower()
    if any(k in txt for k in ["up", "bull", "uptrend", "green", "risk-on"]):
        return 1
    # Try JSON fields if present
    if regime_json:
        try:
            j = json.loads(regime_json)
            if isinstance(j, dict):
                # common keys that might indicate uptrend
                for key in ("trend", "regime", "label"):
                    v = str(j.get(key, "")).lower()
                    if any(k in v for k in ["up", "bull", "uptrend"]):
                        return 1
        except Exception:
            pass
    return 0


def _directional_alignment(side: str, market_regime_encoded: int) -> int:
    # 1 aligned, -1 misaligned
    if market_regime_encoded == 1 and side == "LONG":
        return 1
    if market_regime_encoded == 0 and side == "SHORT":
        return 1
    return -1


def _bucket_from_atr_pct(atr_pct: Optional[float]) -> Optional[int]:
    if atr_pct is None:
        return None
    # Buckets are heuristic and stable:
    # 0 low, 1 medium, 2 high
    if atr_pct < 0.2:
        return 0
    if atr_pct < 0.5:
        return 1
    return 2


def _compute_pnl_pct(
    side: str,
    entry_price: Optional[float],
    close_price: Optional[float],
    pnl_abs: Optional[float],
    quantity: Optional[float],
) -> Optional[float]:
    # Prefer price-based return when close_price exists
    if entry_price and close_price:
        if side == "SHORT":
            return (entry_price - close_price) / entry_price * 100.0
        return (close_price - entry_price) / entry_price * 100.0
    # Fallback: infer from absolute pnl and notional (entry*qty)
    if pnl_abs is not None and entry_price and quantity:
        notional = abs(entry_price * quantity)
        if notional > 0:
            return (pnl_abs / notional) * 100.0
    return None


def _compute_stop_loss_distance(side: str, entry_price: Optional[float], stop_loss: Optional[float]) -> Optional[float]:
    if not entry_price or not stop_loss or stop_loss <= 0:
        return None
    if side == "SHORT":
        return (stop_loss - entry_price) / entry_price * 100.0
    return (entry_price - stop_loss) / entry_price * 100.0


def _compute_take_profit_distance(side: str, entry_price: Optional[float], tps: Sequence[float]) -> Optional[float]:
    if not entry_price or not tps:
        return None
    tp = tps[0]
    if tp <= 0:
        return None
    if side == "SHORT":
        return (entry_price - tp) / entry_price * 100.0
    return (tp - entry_price) / entry_price * 100.0


def _momentum_bucket_from_tech_score(tech_score: Optional[float]) -> Optional[int]:
    if tech_score is None:
        return None
    if tech_score >= 0.7:
        return 2
    if tech_score >= 0.4:
        return 1
    return 0


def _build_features(row: Dict[str, Any], role: str) -> Dict[str, Any]:
    side = _infer_side(row.get("signal") or row.get("side") or row.get("ai_vote"))
    entry_price = _safe_float(row.get("entry_price"))
    close_price = _safe_float(row.get("close_price"))
    qty = _safe_float(row.get("quantity"))
    pnl_abs = _safe_float(row.get("pnl"))

    atr_pct = _safe_float(row.get("atr_pct_entry")) or _safe_float(row.get("atr_pct")) or _safe_float(row.get("atr_pct_at_entry"))
    market_regime_encoded = _encode_market_regime(str(row.get("micro_regime_label") or ""), row.get("micro_regime_json"))
    # Normalize market_regime_encoded to 0/1
    market_regime_encoded = 1 if market_regime_encoded == 1 else 0

    pnl_pct = _compute_pnl_pct(side, entry_price, close_price, pnl_abs, qty)
    entry_vs_close_pct = _compute_pnl_pct(side, entry_price, close_price, None, None)  # price-based only

    stop_loss_distance = _compute_stop_loss_distance(side, entry_price, _safe_float(row.get("stop_loss")))
    tps = _parse_take_profits(row.get("take_profits"))
    take_profit_distance = _compute_take_profit_distance(side, entry_price, tps)

    tech_score = _safe_float(row.get("tech_score"))
    vol_spike = _safe_int(row.get("vol_spike"))

    features: Dict[str, Any] = {
        # Core outcomes
        "pnl_pct": pnl_pct,
        "side": 1 if side == "LONG" else 0,  # keep numeric for models
        # Simple engineered fields
        "entry_vs_close_pct": entry_vs_close_pct,
        # If we don't have EMA20, keep 0.0 so ML can run without dropping rows.
        "entry_vs_ema_20_pct": 0.0,
        "atr_pct_at_entry": atr_pct,
        "market_regime_encoded": market_regime_encoded,
        "directional_alignment": _directional_alignment(side, market_regime_encoded),
        "stop_loss_distance": stop_loss_distance,
        "take_profit_distance": take_profit_distance,
        "funding": _safe_float(row.get("funding")),
        "oi_change": _safe_float(row.get("oi_change")),
        "volatility_bucket": _bucket_from_atr_pct(atr_pct),
        "volume_spike_flag": 1 if (vol_spike or 0) > 0 else 0,
        "momentum_bucket": _momentum_bucket_from_tech_score(tech_score),
        # Provenance / debug (kept in features for now)
        "bot_role": role,
        "source_trade_id": row.get("id"),
        "raw_status": row.get("status"),
        "raw_signal": row.get("signal"),
    }
    # Drop nulls to keep DB small
    return {k: v for k, v in features.items() if v is not None}


def _build_trade_query(
    schema: str,
    available_cols: Sequence[str],
    after_id: int,
    symbol: Optional[str],
    limit: int,
    ignore_before_ms: Optional[int] = None,
    ignore_before_ts: Optional[str] = None,
) -> Tuple[str, Dict[str, Any]]:
    cols = set(available_cols)
    table = f"{schema}.trades"

    wanted = [
        "id",
        "symbol",
        "signal",
        "side",
        "entry_price",
        "close_price",
        "quantity",
        "pnl",
        "status",
        "timestamp",
        "timestamp_ms",
        "closed_at",
        "closed_at_ms",
        "stop_loss",
        "take_profits",
        "funding",
        "oi_change",
        "atr_pct_entry",
        "micro_regime_label",
        "micro_regime_json",
        "vol_spike",
        "tech_score",
        "deriv_score",
        "ai_vote",
    ]
    select_cols = [c for c in wanted if c in cols]
    # Always select id at minimum
    if "id" not in select_cols:
        select_cols.insert(0, "id")

    where_parts = ["id > :after_id"]
    params: Dict[str, Any] = {"after_id": after_id}

    if symbol and "symbol" in cols:
        where_parts.append("symbol = :symbol")
        params["symbol"] = symbol

    # Only closed trades (best effort based on available columns)
    closed_parts = []
    if "status" in cols:
        closed_parts.append("status <> 'OPEN'")
    if "closed_at_ms" in cols:
        closed_parts.append("closed_at_ms IS NOT NULL")
    if "closed_at" in cols:
        closed_parts.append("closed_at IS NOT NULL")
    if closed_parts:
        where_parts.append("(" + " OR ".join(closed_parts) + ")")

    if "pnl" in cols:
        where_parts.append("pnl IS NOT NULL")

    # Optional: ignore trades before a timestamp. Prefer numeric millis when available.
    if ignore_before_ms is not None and "timestamp_ms" in cols:
        where_parts.append("timestamp_ms >= :ignore_before_ms")
        params["ignore_before_ms"] = int(ignore_before_ms)
    elif ignore_before_ts is not None and "timestamp" in cols:
        where_parts.append("timestamp >= :ignore_before_ts")
        params["ignore_before_ts"] = ignore_before_ts

    # Clamp limit to a safe range (used as a literal in the SQL string)
    limit_i = 5000
    try:
        limit_i = int(limit)
    except Exception:
        limit_i = 5000
    limit_i = max(1, min(limit_i, 50000))

    sql = f"SELECT {', '.join(select_cols)} FROM {table} WHERE " + " AND ".join(where_parts) + f" ORDER BY id ASC LIMIT {limit_i}"
    return sql, params


def sync_mina_trades(
    db,
    role: str = "paper",
    symbol: Optional[str] = None,
    limit: int = 5000,
    dry_run: bool = False,
    ignore_before_ts: Optional[str] = None,
) -> Dict[str, Any]:
    """Pull CLOSED trades from Mina Postgres schemas into Brain's feature store.

    - role: paper|live|pump (maps to mina_paper/mina_live/mina_pump)
    - symbol: optional symbol filter (e.g. BTCUSDT)
    """
    schema = _ROLE_TO_SCHEMA.get(role, role)

    engine = get_source_engine()

    # Determine incremental cursor
    state = db.get(SyncState, role)
    after_id = int(state.last_trade_id) if state else 0

    # Introspect columns to remain compatible with schema drift
    cols = _get_table_columns(engine, schema, "trades")
    if not cols:
        return {"ok": False, "error": f"Source table not found: {schema}.trades", "role": role, "schema": schema}

    # Optional time lower-bound (used mainly for backfills)
    ignore_before_ms: Optional[int] = None
    ignore_before_iso: Optional[str] = None
    if ignore_before_ts:
        try:
            dt = datetime.fromisoformat(ignore_before_ts.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            dt_utc = dt.astimezone(timezone.utc)
            ignore_before_ms = int(dt_utc.timestamp() * 1000)
            ignore_before_iso = dt_utc.isoformat().replace("+00:00", "Z")
        except Exception:
            # Fallback: keep raw string for text-based timestamp columns.
            ignore_before_iso = ignore_before_ts

    sql, params = _build_trade_query(
        schema,
        cols,
        after_id=after_id,
        symbol=symbol,
        limit=limit,
        ignore_before_ms=ignore_before_ms,
        ignore_before_ts=ignore_before_iso,
    )

    with engine.connect() as conn:
        rows = conn.execute(text(sql), params).mappings().all()

    inserted = 0
    would_insert = 0
    last_id = after_id

    for r in rows:
        row = dict(r)
        trade_id = int(row.get("id") or 0)
        if trade_id <= after_id:
            continue

        last_id = max(last_id, trade_id)

        sym = str(row.get("symbol") or "").upper()
        if not sym:
            # If symbol missing in source (shouldn't happen), skip safely.
            continue

        ts = _timestamp_from_row(row)
        feats = _build_features(row, role=role)

        if dry_run:
            would_insert += 1
            continue

        db.add(
            TradeFeature(
                symbol=sym,
                timestamp_utc=ts,
                pnl_pct=_safe_float(feats.get("pnl_pct")) or 0.0,
                features=feats,
            )
        )
        inserted += 1

    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "role": role,
            "schema": schema,
            "after_id": after_id,
            "last_id": last_id,
            "would_insert": would_insert,
            "symbol": symbol,
            "ignore_before_ts": ignore_before_iso,
            "ts_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }

    # Update sync cursor
    if state is None:
        state = SyncState(role=role, last_trade_id=last_id)
        db.add(state)
    else:
        state.last_trade_id = last_id

    db.commit()

    return {
        "ok": True,
        "role": role,
        "schema": schema,
        "after_id": after_id,
        "last_id": last_id,
        "inserted": inserted,
        "dry_run": False,
        "would_insert": would_insert,
        "symbol": symbol,
        "ignore_before_ts": ignore_before_iso,
        "ts_utc": datetime.now(timezone.utc).isoformat(),
    }
