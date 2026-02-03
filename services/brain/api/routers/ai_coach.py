from fastapi import APIRouter
from api.deps import get_dataset
from learning.daily_summary import build_daily_summary
from learning.ai_coach import generate_ai_coach

router = APIRouter()

@router.get("/")
def ai_coach(symbol: str | None = None):
    df = get_dataset(symbol)
    summary = build_daily_summary(df)
    return generate_ai_coach(summary)
