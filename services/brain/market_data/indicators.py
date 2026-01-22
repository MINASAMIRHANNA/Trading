import pandas as pd
from ta.momentum import RSIIndicator
from ta.volatility import AverageTrueRange
from ta.trend import EMAIndicator


def add_rsi(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """
    Add RSI indicator to DataFrame.
    """
    rsi = RSIIndicator(close=df["close"], window=period)
    df[f"rsi_{period}"] = rsi.rsi()
    return df


def add_atr(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """
    Add ATR indicator to DataFrame.
    """
    atr = AverageTrueRange(
        high=df["high"],
        low=df["low"],
        close=df["close"],
        window=period
    )
    df[f"atr_{period}"] = atr.average_true_range()
    return df


def add_ema(df: pd.DataFrame, period: int) -> pd.DataFrame:
    """
    Add EMA indicator to DataFrame.
    """
    ema = EMAIndicator(close=df["close"], window=period)
    df[f"ema_{period}"] = ema.ema_indicator()
    return df


def add_basic_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add a basic set of indicators commonly used for analysis.
    """
    df = add_rsi(df, period=14)
    df = add_atr(df, period=14)
    df = add_ema(df, period=20)
    df = add_ema(df, period=50)
    return df
