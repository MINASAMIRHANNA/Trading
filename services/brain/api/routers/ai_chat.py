from fastapi import APIRouter
from pydantic import BaseModel
from learning.ai_chat import ask_ai_coach
from learning.llm_context import build_llm_context
from learning.datasets import load_feature_dataset
from learning.daily_summary import build_daily_summary

router = APIRouter()

class ChatRequest(BaseModel):
    question: str
    symbol: str | None = None

@router.post("/")
def ai_chat(req: ChatRequest):
    df = load_feature_dataset(req.symbol)
    summary = build_daily_summary(df)

    regime_stats = df.groupby("market_regime")["pnl_pct"].mean()
    feature_importance = "market_regime > alignment > entry quality"

    context = build_llm_context(
        df=df,
        daily_summary=summary,
        regime_stats=regime_stats,
        feature_importance=feature_importance,
    )

    answer = ask_ai_coach(req.question, context)
    return {"answer": answer}
