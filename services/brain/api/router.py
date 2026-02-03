"""Central API router that aggregates all endpoint routers."""
from fastapi import APIRouter

from api.routers import (
    ai_chat,
    ai_coach,
    daily_education,
    daily_summary,
    decision,
    demo,
    events,
    execution_status,
    ml,
    overview,
    performance,
    simulate,
    strategy_compare,
    strategy_ranking,
    sync,
)

api_router = APIRouter()

# Include all routers
api_router.include_router(sync.router, prefix="/sync", tags=["sync"])
api_router.include_router(overview.router, prefix="/overview", tags=["overview"])
api_router.include_router(performance.router, prefix="/performance", tags=["performance"])
api_router.include_router(ml.router, prefix="/ml", tags=["ml"])
api_router.include_router(decision.router, prefix="/decision", tags=["decision"])
api_router.include_router(simulate.router, prefix="/simulate", tags=["simulate"])
api_router.include_router(strategy_ranking.router, prefix="/strategy-ranking", tags=["strategy-ranking"])
api_router.include_router(strategy_compare.router, prefix="/strategy-compare", tags=["strategy-compare"])
api_router.include_router(execution_status.router, prefix="/execution-status", tags=["execution-status"])
api_router.include_router(events.router, prefix="/events", tags=["events"])
api_router.include_router(daily_summary.router, prefix="/daily-summary", tags=["daily-summary"])
api_router.include_router(daily_education.router, prefix="/daily-education", tags=["daily-education"])
api_router.include_router(ai_coach.router, prefix="/ai-coach", tags=["ai-coach"])
api_router.include_router(ai_chat.router, prefix="/ai-chat", tags=["ai-chat"])
api_router.include_router(demo.router, prefix="/demo", tags=["demo"])
