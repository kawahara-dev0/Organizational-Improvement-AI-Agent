from collections.abc import AsyncGenerator

import asyncpg
from asyncpg import Connection, Pool

from app.settings import settings

_pool: Pool | None = None


async def get_pool() -> Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            dsn=settings.database_url,
            min_size=2,
            max_size=10,
        )
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def get_conn() -> AsyncGenerator[Connection, None]:
    """FastAPI dependency that yields a single connection from the pool."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        yield conn
