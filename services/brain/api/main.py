from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routers import overview, performance, ml, simulate
from api.routers import daily_summary
from api.routers import ai_coach
from api.routers import ai_chat
from api.routers import strategy_compare
from api.routers import strategy_ranking
from api.routers import decision
from api.routers import daily_education
from api.routers import execution_status
app = FastAPI(title="Trading Intelligence Dashboard API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(overview.router, prefix="/api/overview")
app.include_router(performance.router, prefix="/api/performance")
app.include_router(ml.router, prefix="/api/ml")
app.include_router(simulate.router, prefix="/api/simulate")
app.include_router(daily_summary.router, prefix="/api/daily-summary")
app.include_router(ai_coach.router, prefix="/api/ai-coach")
app.include_router(ai_chat.router, prefix="/api/ai-chat")
app.include_router(strategy_compare.router, prefix="/api/strategy-compare")
app.include_router(strategy_ranking.router, prefix="/api/strategy-ranking")
app.include_router(decision.router, prefix="/api/decision")
app.include_router(daily_education.router,prefix="/api/daily-education")
app.include_router(execution_status.router,prefix="/api/execution")
