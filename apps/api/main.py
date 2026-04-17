import asyncio
import logging
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.db.session import close_pool, get_pool
from app.routers import admin, admin_auth, consultations, departments, health, knowledge
from app.settings import settings

logging.basicConfig(
    level=settings.log_level.upper(),
    format="%(asctime)s [%(levelname)s] %(name)s req_id=%(req_id)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ── Rate limiter ──────────────────────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address, default_limits=[])

# ── FastAPI app ───────────────────────────────────────────────────────────────
app = FastAPI(
    title="OIAgent API",
    description="Organizational Improvement AI Agent — backend",
    version="0.1.0",
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ── CORS ──────────────────────────────────────────────────────────────────────
_cors_origins = [o.strip() for o in settings.cors_origins.split() if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request-ID middleware ─────────────────────────────────────────────────────
@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    """Attach a unique request ID to every request for tracing."""
    req_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
    request.state.req_id = req_id

    # Inject req_id into all log records emitted during this request.
    old_factory = logging.getLogRecordFactory()

    def record_factory(*args, **kwargs):
        record = old_factory(*args, **kwargs)
        record.req_id = req_id
        return record

    logging.setLogRecordFactory(record_factory)
    try:
        response = await call_next(request)
    finally:
        logging.setLogRecordFactory(old_factory)

    response.headers["X-Request-ID"] = req_id
    return response


# ── Retention background worker ───────────────────────────────────────────────
async def _retention_worker() -> None:
    """Background task: delete consultations older than CONSULTATION_RETENTION_DAYS.

    Runs once per day.  Errors are logged and retried on the next cycle.
    Only non-submitted consultations (abandoned sessions) are deleted;
    submitted proposals are retained for audit purposes.
    """
    days = settings.consultation_retention_days
    logger.info(
        "Retention worker started — non-submitted sessions older than %d days",
        days,
        extra={"req_id": "-"},
    )
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
                logger.info(
                    "Retention: deleted %d stale consultation(s)",
                    deleted,
                    extra={"req_id": "-"},
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Retention cleanup failed (will retry tomorrow): %s",
                exc,
                extra={"req_id": "-"},
            )


# ── Production secrets validation ─────────────────────────────────────────────
_INSECURE_DEFAULTS = {
    "admin_password": "changeme",
    "jwt_secret": "changeme-jwt-secret-replace-in-production",
}


def _check_production_secrets() -> None:
    """Raise RuntimeError if any secret is still at its insecure default value."""
    errors: list[str] = []
    for field, insecure in _INSECURE_DEFAULTS.items():
        if getattr(settings, field) == insecure:
            errors.append(f"{field.upper()} must be changed in production")
    if not settings.messages_encryption_key:
        errors.append(
            "MESSAGES_ENCRYPTION_KEY should be set in production "
            '(generate with: python -c "from cryptography.fernet import Fernet; '
            'print(Fernet.generate_key().decode())")'
        )
    if errors:
        msg = "Production security check failed:\n" + "\n".join(f"  • {e}" for e in errors)
        raise RuntimeError(msg)


# ── Lifecycle ─────────────────────────────────────────────────────────────────
@app.on_event("startup")
async def startup() -> None:
    if settings.app_env == "production":
        _check_production_secrets()
        logger.info("Production secrets validation passed", extra={"req_id": "-"})

    await get_pool()
    logger.info(
        "DB connection pool initialized (env=%s, cors=%s)",
        settings.app_env,
        _cors_origins,
        extra={"req_id": "-"},
    )
    if settings.consultation_retention_days > 0:
        asyncio.create_task(_retention_worker())
        logger.info(
            "Retention policy: non-submitted sessions deleted after %d days",
            settings.consultation_retention_days,
            extra={"req_id": "-"},
        )


@app.on_event("shutdown")
async def shutdown() -> None:
    await close_pool()
    logger.info("DB connection pool closed", extra={"req_id": "-"})


# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(health.router)
app.include_router(admin_auth.router)
app.include_router(admin.router)
app.include_router(departments.router)
app.include_router(knowledge.router)
app.include_router(consultations.router)
