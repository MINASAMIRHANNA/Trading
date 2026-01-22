from datetime import datetime
from typing import List, Dict
from ingestion.binance.client import get_binance_client

def fetch_futures_trades(symbol: str | None = None) -> List[Dict]:
    """
    Fetch executed futures trades (READ-ONLY).
    """
    client = get_binance_client()

    raw_trades = client.futures_account_trades(symbol=symbol)
    trades = []

    for t in raw_trades:
        trades.append({
            "exchange_trade_id": int(t["id"]),
            "symbol": t["symbol"],
            "side": t["side"],
            "position_side": t.get("positionSide"),
            "price": float(t["price"]),
            "quantity": float(t["qty"]),
            "realized_pnl": float(t["realizedPnl"]),
            "commission": float(t["commission"]),
            "commission_asset": t["commissionAsset"],
            "order_id": int(t["orderId"]),
            "trade_time": datetime.fromtimestamp(t["time"] / 1000),
            "source": "binance"
        })

    return trades
