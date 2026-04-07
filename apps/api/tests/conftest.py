"""Shared pytest fixtures for the API test suite."""

from __future__ import annotations

import asyncpg
import pytest_asyncio

from app.settings import settings


@pytest_asyncio.fixture
async def db_conn():
    """Provide a raw asyncpg connection to the test database.

    Each test gets a transaction that is rolled back after the test,
    so tests do not pollute each other and the DB remains clean.
    """
    conn = await asyncpg.connect(settings.database_url)
    transaction = conn.transaction()
    await transaction.start()

    yield conn

    await transaction.rollback()
    await conn.close()
