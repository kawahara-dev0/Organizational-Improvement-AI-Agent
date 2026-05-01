from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.db.session import get_conn as real_get_conn
from main import app


@pytest.mark.asyncio
async def test_health_ok() -> None:
    mock_conn = AsyncMock()
    mock_conn.fetchval = AsyncMock(return_value=1)

    async def override_get_conn():
        yield mock_conn

    app.dependency_overrides[real_get_conn] = override_get_conn
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/health")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
