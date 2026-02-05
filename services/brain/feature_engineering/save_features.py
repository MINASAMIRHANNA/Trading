from typing import List
import math
import pandas as pd

from database.session import get_session
from database.models.trade_features import TradeFeature


FEATURE_COLUMNS = [
    "trade_time",
    "symbol",
    "price",
    "close",
    "entry_vs_close_pct",
    "entry_vs_ema_20_pct",
    "entry_vs_ema_50_pct",
    "atr_pct_at_entry",
    "rsi_bucket",
    "market_regime",
    "market_regime_encoded",
    "directional_alignment",
    "pnl_pct",
    "market_join_valid"
]


def save_trade_features(features_df: pd.DataFrame) -> int:
    saved = 0

    rows = features_df.copy()
    base_id = int(pd.Timestamp.utcnow().timestamp() * 1000)
    def _clean(v):
        try:
            if v is None:
                return None
            if isinstance(v, float) and math.isnan(v):
                return None
        except Exception:
            pass
        return v

    for session in get_session():
        for idx, row in rows.iterrows():
            source_role = row.get("source_role") or "paper"
            source_trade_id = row.get("source_trade_id")
            if not source_trade_id:
                source_trade_id = base_id + int(idx) + 1
            payload = {k: _clean(row.get(k)) for k in FEATURE_COLUMNS}
            tf = TradeFeature(
                trade_time=row["trade_time"],
                timestamp_utc=row.get("trade_time"),
                symbol=row.get("symbol"),
                entry_price=row.get("price"),
                market_close_price=row.get("close"),
                entry_vs_close_pct=row.get("entry_vs_close_pct"),
                entry_vs_ema_20_pct=row.get("entry_vs_ema_20_pct"),
                entry_vs_ema_50_pct=row.get("entry_vs_ema_50_pct"),
                atr_pct_at_entry=row.get("atr_pct_at_entry"),
                rsi_bucket=row.get("rsi_bucket"),
                market_regime=row.get("market_regime"),
                market_regime_encoded=row.get("market_regime_encoded"),
                directional_alignment=row.get("directional_alignment"),
                pnl_pct=row.get("pnl_pct"),
                market_join_valid=bool(row.get("market_join_valid", True)),
                features=payload,
                source_role=source_role,
                source_trade_id=int(source_trade_id),
            )
            session.add(tf)
            saved += 1

    return saved
