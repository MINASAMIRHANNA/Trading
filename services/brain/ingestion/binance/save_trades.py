from typing import List, Dict
from database.session import get_session
from database.models.trades import Trade
from ingestion.binance.sync_validator import is_trade_valid, is_duplicate

def save_trades(trades: List[Dict]) -> int:
    saved = 0

    for session in get_session():
        for trade in trades:
            if not is_trade_valid(trade):
                continue

            if is_duplicate(session, trade["exchange_trade_id"]):
                continue

            session.add(Trade(**trade))
            saved += 1

    return saved
