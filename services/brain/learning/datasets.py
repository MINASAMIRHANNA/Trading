import pandas as pd

from database.session import get_session
from database.models.trade_features import TradeFeature

try:
    from ingestion.mina.sync_trades import sync_mina_trades
except Exception:  # pragma: no cover
    sync_mina_trades = None


# Stable column set expected by the API/aggregations.
FEATURE_COLUMNS = [
    "trade_time",
    "symbol",
    "entry_vs_close_pct",
    "entry_vs_ema_20_pct",
    "entry_vs_ema_50_pct",
    "atr_pct_at_entry",
    "rsi_bucket",
    "market_regime_encoded",
    "directional_alignment",
    "pnl_pct",
    "market_join_valid",
]


def _features_dict(obj) -> dict:
    f = getattr(obj, "features", None)
    return f if isinstance(f, dict) else {}


def load_feature_dataset(
    only_valid: bool = True,
    symbol: str | None = None,
) -> pd.DataFrame:
    """Load engineered trade features from the DB.

    Current schema stores most fields inside TradeFeature.features (JSON). This loader
    flattens the JSON into a consistent DataFrame.

    If there is no data yet, returns an empty DataFrame WITH the expected columns.
    """

    rows: list[dict] = []

    for session in get_session():
        query = session.query(TradeFeature)

        if symbol:
            query = query.filter(TradeFeature.symbol == symbol)

        results = query.all()

        for r in results:
            f = _features_dict(r)

            # Some pipelines mark validity inside JSON.
            valid = f.get("market_join_valid", True)
            if only_valid and valid is False:
                continue

            # Prefer timestamp_utc if present, otherwise allow JSON fallback.
            trade_time = getattr(r, "timestamp_utc", None) or f.get("trade_time")

            rows.append(
                {
                    "trade_time": trade_time,
                    "symbol": r.symbol,
                    "entry_vs_close_pct": f.get("entry_vs_close_pct"),
                    "entry_vs_ema_20_pct": f.get("entry_vs_ema_20_pct"),
                    "entry_vs_ema_50_pct": f.get("entry_vs_ema_50_pct"),
                    "atr_pct_at_entry": f.get("atr_pct_at_entry"),
                    "rsi_bucket": f.get("rsi_bucket"),
                    "market_regime_encoded": f.get("market_regime_encoded"),
                    "directional_alignment": f.get("directional_alignment"),
                    "pnl_pct": f.get("pnl_pct"),
                    "market_join_valid": valid,
                }
            )

    # Always return a DataFrame with known columns (prevents KeyError in empty state)
    return pd.DataFrame(rows, columns=FEATURE_COLUMNS)
