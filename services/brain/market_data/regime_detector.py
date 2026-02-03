import pandas as pd


def detect_trend(df: pd.DataFrame) -> pd.Series:
    """
    Detect basic market trend using EMA structure.
    Requires ema_20 and ema_50.
    """
    conditions = []

    for _, row in df.iterrows():
        if pd.isna(row.get("ema_20")) or pd.isna(row.get("ema_50")):
            conditions.append("unknown")
        elif row["ema_20"] > row["ema_50"]:
            conditions.append("uptrend")
        elif row["ema_20"] < row["ema_50"]:
            conditions.append("downtrend")
        else:
            conditions.append("range")

    return pd.Series(conditions, index=df.index)


def detect_volatility(df: pd.DataFrame, threshold: float = 0.015) -> pd.Series:
    """
    Detect volatility regime using ATR relative to price.
    Requires atr_14.
    """
    vol = []

    for _, row in df.iterrows():
        if pd.isna(row.get("atr_14")) or row["close"] == 0:
            vol.append("unknown")
        else:
            atr_ratio = row["atr_14"] / row["close"]
            if atr_ratio >= threshold:
                vol.append("high_volatility")
            else:
                vol.append("normal_volatility")

    return pd.Series(vol, index=df.index)


def build_market_regime(df: pd.DataFrame) -> pd.DataFrame:
    """
    Build combined market regime labels.
    """
    df = df.copy()

    df["trend_regime"] = detect_trend(df)
    df["volatility_regime"] = detect_volatility(df)

    def combine(row):
        if row["trend_regime"] == "unknown" or row["volatility_regime"] == "unknown":
            return "unknown"
        return f"{row['trend_regime']}__{row['volatility_regime']}"

    df["market_regime"] = df.apply(combine, axis=1)

    return df
