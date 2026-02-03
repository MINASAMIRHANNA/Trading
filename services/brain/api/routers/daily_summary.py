from fastapi import APIRouter
from api.deps import get_dataset
from learning.daily_summary import build_daily_summary

router = APIRouter()

@router.get("/")
def daily_summary(symbol: str | None = None):
    df = get_dataset(symbol)
    return build_daily_summary(df)
