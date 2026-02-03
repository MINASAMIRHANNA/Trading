from typing import List
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

    for session in get_session():
        for _, row in rows.iterrows():
            tf = TradeFeature(
                trade_time=row["trade_time"],
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
                market_join_valid=bool(row.get("market_join_valid", True))
            )
            session.add(tf)
            saved += 1

    return saved
