import pandas as pd
from database.session import get_session
from database.models.trade_features import TradeFeature


def load_feature_dataset(
    only_valid: bool = True,
    symbol: str | None = None
) -> pd.DataFrame:
    rows = []

    for session in get_session():
        query = session.query(TradeFeature)

        if only_valid:
            query = query.filter(TradeFeature.market_join_valid == True)

        if symbol:
            query = query.filter(TradeFeature.symbol == symbol)

        results = query.all()

        for r in results:
            rows.append({
                "trade_time": r.trade_time,
                "symbol": r.symbol,
                "entry_vs_close_pct": r.entry_vs_close_pct,
                "entry_vs_ema_20_pct": r.entry_vs_ema_20_pct,
                "entry_vs_ema_50_pct": r.entry_vs_ema_50_pct,
                "atr_pct_at_entry": r.atr_pct_at_entry,
                "rsi_bucket": r.rsi_bucket,
                "market_regime_encoded": r.market_regime_encoded,
                "directional_alignment": r.directional_alignment,
                "pnl_pct": r.pnl_pct
            })

    return pd.DataFrame(rows)
