from fastapi import APIRouter
from api.deps import get_dataset
from learning.daily_aggregates import build_daily_aggregates

router = APIRouter()


@router.get("/by-regime")
def by_regime(symbol: str | None = None):
    df = get_dataset(symbol)
    stats = build_daily_aggregates(df)["by_regime"]

    return [
        {
            "market_regime_encoded": float(row["market_regime_encoded"]),
            "trades": int(row["trades"]),
            "win_rate": float(row["win_rate"]),
            "avg_pnl": float(row["avg_pnl"]),
        }
        for _, row in stats.iterrows()
    ]


@router.get("/by-alignment")
def by_alignment(symbol: str | None = None):
    df = get_dataset(symbol)
    stats = build_daily_aggregates(df)["by_alignment"]

    return [
        {
            "directional_alignment": float(row["directional_alignment"]),
            "trades": int(row["trades"]),
            "win_rate": float(row["win_rate"]),
            "avg_pnl": float(row["avg_pnl"]),
        }
        for _, row in stats.iterrows()
    ]
