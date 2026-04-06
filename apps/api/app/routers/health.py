from asyncpg import Connection
from fastapi import APIRouter, Depends

from app.db.session import get_conn

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(conn: Connection = Depends(get_conn)) -> dict:
    """Liveness + DB connectivity check."""
    await conn.fetchval("SELECT 1")
    return {"status": "ok"}
