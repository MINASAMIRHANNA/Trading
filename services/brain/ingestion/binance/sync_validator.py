from typing import Dict
from database.models.trades import Trade

def is_trade_valid(trade: Dict) -> bool:
    """
    Validate trade integrity before saving.
    """
    required_fields = [
        "exchange_trade_id",
        "symbol",
        "price",
        "quantity",
        "trade_time"
    ]

    for field in required_fields:
        if trade.get(field) is None:
            return False

    if trade["quantity"] <= 0:
        return False

    if trade["price"] <= 0:
        return False

    return True

def is_duplicate(session, exchange_trade_id: int) -> bool:
    return (
        session.query(Trade)
        .filter(Trade.exchange_trade_id == exchange_trade_id)
        .first()
        is not None
    )
