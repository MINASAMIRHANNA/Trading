from pydantic import BaseModel
from typing import Dict, Any, List

class Metrics(BaseModel):
    trades: int
    win_rate: float
    avg_pnl: float
    expectancy: float

class SimulationResponse(BaseModel):
    actual: Metrics
    simulated: Metrics
    delta: Metrics
