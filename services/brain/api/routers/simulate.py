from fastapi import APIRouter
from typing import List, Optional
from pydantic import BaseModel

from api.deps import get_dataset
from simulation.simulator import simulate_strategy

router = APIRouter()


class SimulationRequest(BaseModel):
    symbol: Optional[str] = None
    allowed_regimes: Optional[List[float]] = None
    allowed_alignment: Optional[List[float]] = None
    allowed_rsi_buckets: Optional[List[str]] = None
    max_atr_pct: Optional[float] = None


@router.post("/")
def simulate(req: SimulationRequest):
    df = get_dataset(req.symbol)

    result = simulate_strategy(
        df,
        allowed_regimes=req.allowed_regimes,
        allowed_alignment=req.allowed_alignment,
        allowed_rsi_buckets=req.allowed_rsi_buckets,
        max_atr_pct=req.max_atr_pct,
        symbol=req.symbol
    )

    # إزالة الـ DataFrame
    result.pop("simulated_df", None)

    # تأكيد تحويل كل القيم لأنواع Python native
    for section in ["actual", "simulated", "delta"]:
        for k, v in result[section].items():
            result[section][k] = float(v)

    return result
