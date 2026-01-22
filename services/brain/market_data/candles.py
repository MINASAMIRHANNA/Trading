from datetime import datetime
from typing import Optional
import pandas as pd

from ingestion.binance.client import get_binance_client


def fetch_klines(
    symbol: str,
    interval: str = "5m",
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    limit: int = 500
) -> pd.DataFrame:
    """
    Fetch historical candlesticks (klines) from Binance Futures.

    Returns a DataFrame with:
    time, open, high, low, close, volume
    """
    client = get_binance_client()

    params = {
        "symbol": symbol,
        "interval": interval,
        "limit": limit
    }

    if start_time:
        params["startTime"] = int(start_time.timestamp() * 1000)
    if end_time:
        params["endTime"] = int(end_time.timestamp() * 1000)

    raw_klines = client.futures_klines(**params)

    if not raw_klines:
        return pd.DataFrame()

    df = pd.DataFrame(
        raw_klines,
        columns=[
            "open_time",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "close_time",
            "quote_asset_volume",
            "number_of_trades",
            "taker_buy_base",
            "taker_buy_quote",
            "ignore"
        ]
    )

    df = df[["open_time", "open", "high", "low", "close", "volume"]]

    df["time"] = pd.to_datetime(df["open_time"], unit="ms")
    df = df.drop(columns=["open_time"])

    numeric_cols = ["open", "high", "low", "close", "volume"]
    df[numeric_cols] = df[numeric_cols].astype(float)

    df = df.sort_values("time").reset_index(drop=True)

    return df
