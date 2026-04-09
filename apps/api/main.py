import asyncio
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.db.session import close_pool, get_pool
from app.routers import admin, admin_auth, consultations, departments, health, knowledge
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


async def _retention_worker() -> None:
    """Background task: delete consultations older than CONSULTATION_RETENTION_DAYS.

    Runs once per day.  Errors are logged and retried on the next cycle.
    Only non-submitted consultations (abandoned sessions) are deleted;
    submitted proposals are retained for audit purposes.
    """
    days = settings.consultation_retention_days
    logger.info("Retention worker started — non-submitted sessions older than %d days", days)
    while True:
        await asyncio.sleep(24 * 60 * 60)
        try:
            pool = await get_pool()
            async with pool.acquire() as conn:
                result = await conn.execute(
                    """
                    DELETE FROM consultations
                    WHERE is_submitted = FALSE
                      AND created_at < NOW() - ($1 * INTERVAL '1 day')
                    """,
                    days,
                )
            deleted = int(result.split()[-1])
            if deleted:
                logger.info("Retention: deleted %d stale consultation(s)", deleted)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Retention cleanup failed (will retry tomorrow): %s", exc)


@app.on_event("startup")
async def startup() -> None:
    await get_pool()
    logger.info("DB connection pool initialized (env=%s)", settings.app_env)
    if settings.consultation_retention_days > 0:
        asyncio.create_task(_retention_worker())
        logger.info(
            "Retention policy: non-submitted sessions deleted after %d days",
            settings.consultation_retention_days,
        )


@app.on_event("shutdown")
async def shutdown() -> None:
    await close_pool()
    logger.info("DB connection pool closed")


app.include_router(health.router)
app.include_router(admin_auth.router)
app.include_router(admin.router)
app.include_router(departments.router)
app.include_router(knowledge.router)
app.include_router(consultations.router)
