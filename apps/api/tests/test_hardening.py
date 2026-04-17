"""Tests for Step 13 — hardening features.

Covers:
  Request-ID middleware — auto-generation and client passthrough
  Rate limiting (slowapi) — 429 when threshold exceeded
  Production secrets validation — RuntimeError on insecure defaults

Run with:
    docker compose run --rm api uv run pytest tests/test_hardening.py -v
"""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.db.session import get_conn as real_get_conn
from main import _check_production_secrets, app

# ── helpers ────────────────────────────────────────────────────────────────────


@contextmanager
def _settings_patch(**kwargs):
    """Temporarily override settings fields for the duration of the with-block."""
    patches = [patch(f"main.settings.{k}", v) for k, v in kwargs.items()]
    for p in patches:
        p.start()
    try:
        yield
    finally:
        for p in patches:
            p.stop()


@contextmanager
def _mock_db():
    """Override get_conn with a mock connection that satisfies SELECT 1 checks."""

    async def _override():
        mock_conn = AsyncMock()
        mock_conn.fetchval = AsyncMock(return_value=1)
        yield mock_conn

    app.dependency_overrides[real_get_conn] = _override
    try:
        yield
    finally:
        app.dependency_overrides.pop(real_get_conn, None)


# ── Request-ID middleware ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_request_id_auto_generated() -> None:
    """When no X-Request-ID header is sent, the API generates one and echoes it."""
    with _mock_db():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/health")

    assert resp.status_code == 200
    req_id = resp.headers.get("x-request-id")
    assert req_id is not None
    assert len(req_id) > 0


@pytest.mark.asyncio
async def test_request_id_passthrough() -> None:
    """When X-Request-ID is provided by the client, the same value is echoed back."""
    custom_id = "my-trace-abc123"
    with _mock_db():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/health", headers={"X-Request-ID": custom_id})

    assert resp.status_code == 200
    assert resp.headers.get("x-request-id") == custom_id


@pytest.mark.asyncio
async def test_request_id_unique_across_requests() -> None:
    """Two requests without X-Request-ID receive distinct IDs."""
    with _mock_db():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r1 = await client.get("/health")
            r2 = await client.get("/health")

    id1 = r1.headers.get("x-request-id")
    id2 = r2.headers.get("x-request-id")
    assert id1 is not None
    assert id2 is not None
    assert id1 != id2


# ── Rate limiting ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_chat_rate_limit_returns_429_when_exceeded(db_conn) -> None:
    """POST /consultations/{id}/chat returns 429 after exceeding the rate limit.

    The limit is temporarily set to 1/minute so the second request trips it.
    The consultation row is created inside the test transaction so it exists
    during the requests.
    """
    from app.consultations.repository import create_consultation
    from app.db.session import get_conn as real_get_conn

    cid = await create_consultation(db_conn)

    async def _override():
        yield db_conn

    app.dependency_overrides[real_get_conn] = _override
    try:
        with patch("app.routers.consultations.settings.chat_rate_limit", "1/minute"):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                # First request — should succeed (or fail for a business reason, not rate-limit)
                r1 = await client.post(
                    f"/consultations/{cid}/chat",
                    json={"content": "hello", "mode": "personal"},
                )
                assert r1.status_code != 429, "First request must not be rate-limited"

                # Second request — must be rejected with 429
                r2 = await client.post(
                    f"/consultations/{cid}/chat",
                    json={"content": "hello again", "mode": "personal"},
                )
                assert r2.status_code == 429
    finally:
        app.dependency_overrides.clear()


# ── Production secrets validation ─────────────────────────────────────────────


def test_check_production_secrets_raises_on_default_password() -> None:
    """RuntimeError raised when admin_password is the insecure default."""
    with (
        _settings_patch(
            admin_password="changeme",
            jwt_secret="secure-random-jwt-secret-value",
            messages_encryption_key="some-fernet-key",
        ),
        pytest.raises(RuntimeError, match="ADMIN_PASSWORD"),
    ):
        _check_production_secrets()


def test_check_production_secrets_raises_on_default_jwt_secret() -> None:
    """RuntimeError raised when jwt_secret is the insecure default."""
    with (
        _settings_patch(
            admin_password="secure-admin-password",
            jwt_secret="changeme-jwt-secret-replace-in-production",
            messages_encryption_key="some-fernet-key",
        ),
        pytest.raises(RuntimeError, match="JWT_SECRET"),
    ):
        _check_production_secrets()


def test_check_production_secrets_raises_when_encryption_key_missing() -> None:
    """RuntimeError raised when MESSAGES_ENCRYPTION_KEY is empty."""
    with (
        _settings_patch(
            admin_password="secure-admin-password",
            jwt_secret="secure-random-jwt-secret-value",
            messages_encryption_key="",
        ),
        pytest.raises(RuntimeError, match="MESSAGES_ENCRYPTION_KEY"),
    ):
        _check_production_secrets()


def test_check_production_secrets_raises_with_multiple_errors() -> None:
    """RuntimeError message lists ALL failed checks, not just the first."""
    with (
        _settings_patch(
            admin_password="changeme",
            jwt_secret="changeme-jwt-secret-replace-in-production",
            messages_encryption_key="",
        ),
        pytest.raises(RuntimeError) as exc_info,
    ):
        _check_production_secrets()

    msg = str(exc_info.value)
    assert "ADMIN_PASSWORD" in msg
    assert "JWT_SECRET" in msg
    assert "MESSAGES_ENCRYPTION_KEY" in msg


def test_check_production_secrets_passes_when_all_set() -> None:
    """No exception when all required secrets are set to non-default values."""
    with _settings_patch(
        admin_password="secure-admin-password",
        jwt_secret="secure-random-jwt-secret-value",
        messages_encryption_key="some-fernet-key",
    ):
        _check_production_secrets()  # must not raise
