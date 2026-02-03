from fastapi import APIRouter
from api.deps import get_dataset
from learning.daily_aggregates import build_daily_aggregates

router = APIRouter()


@router.get("/")
def overview(symbol: str | None = None):
    # Use keyword arg to avoid positional signature drift.
    df = get_dataset(symbol=symbol)
    overall = build_daily_aggregates(df)["overall"]

    return {
        "trades": int(overall["trades"]),
        "win_rate": float(overall["win_rate"]),
        "avg_pnl": float(overall["avg_pnl"]),
        "expectancy": float(overall["expectancy"]),
    }
