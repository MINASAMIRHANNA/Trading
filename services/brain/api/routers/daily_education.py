from fastapi import APIRouter
from learning.datasets import load_feature_dataset
from learning.daily_education import build_daily_lesson
from api.routers.decision import decision as decision_endpoint

router = APIRouter()

@router.get("/")
def daily_education(symbol: str | None = None):
    """
    Return today's educational lesson based on decision context.
    """

    # Get decision output
    decision_output = decision_endpoint(symbol)

    # Load data for context
    df = load_feature_dataset(symbol=symbol)

    current_regime = None
    if not df.empty and "market_regime_encoded" in df.columns:
        current_regime = df.iloc[-1]["market_regime_encoded"]

    lesson = build_daily_lesson(
        decision=decision_output,
        strategy_stats=decision_output.get("details", {}),
        current_regime=current_regime,
    )

    return lesson
