import pandas as pd
import numpy as np


def build_trade_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Build deterministic, explainable features from trade + market joined data.
    Assumes NO lookahead.
    """

    features = df.copy()

    # -----------------------------
    # Price-based features
    # -----------------------------

    # Entry vs market close
    features["entry_vs_close_pct"] = (
        (features["price"] - features["close"]) / features["close"]
    )

    # Entry vs EMA distances
    if "ema_20" in features.columns:
        features["entry_vs_ema_20_pct"] = (
            (features["price"] - features["ema_20"]) / features["ema_20"]
        )

    if "ema_50" in features.columns:
        features["entry_vs_ema_50_pct"] = (
            (features["price"] - features["ema_50"]) / features["ema_50"]
        )

    # -----------------------------
    # Volatility & momentum features
    # -----------------------------

    # ATR relative to price
    if "atr_14" in features.columns:
        features["atr_pct_at_entry"] = features["atr_14"] / features["price"]

    # RSI bucketization (behavioral friendly)
    if "rsi_14" in features.columns:
        features["rsi_bucket"] = pd.cut(
            features["rsi_14"],
            bins=[0, 30, 45, 55, 70, 100],
            labels=[
                "oversold",
                "weak_bearish",
                "neutral",
                "weak_bullish",
                "overbought"
            ],
            include_lowest=True
        )

    # -----------------------------
    # Regime encoding
    # -----------------------------

    def encode_regime(regime: str):
        if not isinstance(regime, str):
            return np.nan

        mapping = {
            "uptrend__normal_volatility": 1,
            "downtrend__normal_volatility": -1,
            "range__normal_volatility": 0,
            "uptrend__high_volatility": 2,
            "downtrend__high_volatility": -2,
            "range__high_volatility": 0.5,
        }

        return mapping.get(regime, np.nan)

    if "market_regime" in features.columns:
        features["market_regime_encoded"] = features["market_regime"].apply(
            encode_regime
        )

    # -----------------------------
    # Direction-aware context
    # -----------------------------

    if "side" in features.columns:
        features["direction"] = features["side"].map({
            "BUY": 1,
            "SELL": -1
        })

        # Bias: did trade align with regime?
        features["directional_alignment"] = (
            features["direction"] * features["market_regime_encoded"]
        )

    # -----------------------------
    # Outcome-related (label-adjacent)
    # -----------------------------

    if "realized_pnl" in features.columns and "price" in features.columns:
        features["pnl_pct"] = features["realized_pnl"] / features["price"]

    # -----------------------------
    # Cleanup
    # -----------------------------

    features.replace([np.inf, -np.inf], np.nan, inplace=True)

    return features
