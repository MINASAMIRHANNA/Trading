import pandas as pd
from datetime import datetime, timezone, timedelta

from database.session import get_session
from database.models.trades import Trade

from market_data.candles import fetch_klines
from market_data.indicators import add_basic_indicators
from market_data.regime_detector import build_market_regime
from feature_engineering.trade_market_join import join_trade_with_market


def load_trades_df(limit=20, symbol="BTCUSDT"):
    rows = []
    for session in get_session():
        trades = (
            session.query(Trade)
            .filter(Trade.symbol == symbol)
            .order_by(Trade.trade_time.desc())
            .limit(limit)
            .all()
        )
        for t in trades:
            rows.append({
                "trade_time": t.trade_time,
                "symbol": t.symbol,
                "price": t.price,
                "realized_pnl": t.realized_pnl
            })
    return pd.DataFrame(rows)



def run():
    trades_df = load_trades_df(symbol="BTCUSDT")

    market_df = fetch_klines(
        symbol="BTCUSDT",
        interval="5m",
        start_time=datetime.now(timezone.utc) - timedelta(days=2)
    )

    market_df = add_basic_indicators(market_df)
    market_df = build_market_regime(market_df)

    joined = join_trade_with_market(trades_df, market_df)

    print(joined[[
        "trade_time",
        "price",
        "close",
        "rsi_14",
        "market_regime",
        "market_join_valid"
    ]].head())


if __name__ == "__main__":
    run()
