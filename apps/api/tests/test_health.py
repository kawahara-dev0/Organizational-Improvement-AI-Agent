from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from main import app


@pytest.mark.asyncio
async def test_health_ok() -> None:
    mock_conn = AsyncMock()
    mock_conn.fetchval = AsyncMock(return_value=1)

    with patch("app.routers.health.get_conn", return_value=mock_conn):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
