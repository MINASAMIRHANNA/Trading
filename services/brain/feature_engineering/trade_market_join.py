import pandas as pd
from datetime import timedelta


def join_trade_with_market(
    trades_df: pd.DataFrame,
    market_df: pd.DataFrame,
    max_delay: timedelta = timedelta(minutes=10)
) -> pd.DataFrame:
    """
    Join each trade with the last available market candle BEFORE execution time.

    - trades_df must contain: trade_time
    - market_df must contain: time + indicators + market_regime
    - max_delay prevents bad joins if data is too far apart
    """

    # Safety copies
    trades = trades_df.copy()
    market = market_df.copy()

    # Ensure datetime & sorting
    trades["trade_time"] = pd.to_datetime(trades["trade_time"], utc=True)
    market["time"] = pd.to_datetime(market["time"], utc=True)

    trades = trades.sort_values("trade_time")
    market = market.sort_values("time")

    # Merge using backward asof (NO lookahead)
    merged = pd.merge_asof(
        trades,
        market,
        left_on="trade_time",
        right_on="time",
        direction="backward",
        tolerance=max_delay
    )

    # Mark invalid joins
    merged["market_join_valid"] = ~merged["time"].isna()

    return merged
