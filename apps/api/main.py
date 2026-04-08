import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.db.session import close_pool, get_pool
from app.routers import consultations, departments, health, knowledge
from app.settings import settings

logging.basicConfig(
    level=settings.log_level.upper(),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="OIAgent API",
    description="Organizational Improvement AI Agent — backend",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup() -> None:
    await get_pool()
    logger.info("DB connection pool initialized (env=%s)", settings.app_env)


@app.on_event("shutdown")
async def shutdown() -> None:
    await close_pool()
    logger.info("DB connection pool closed")


app.include_router(health.router)
app.include_router(departments.router)
app.include_router(knowledge.router)
app.include_router(consultations.router)
