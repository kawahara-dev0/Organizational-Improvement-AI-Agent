"""Integration tests for the consultation repository and related endpoints.

Covers:
- create_consultation: department is persisted (or null) correctly
- append_message: mode field is stored in the JSONB messages array
- update_metadata via PATCH /consultations/{id}/department
- GET /departments endpoint

Run with:
    docker compose run --rm api uv run pytest tests/test_consultations.py -v
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.consultations.repository import (
    append_message,
    create_consultation,
    get_consultation,
    update_metadata,
)
from main import app

# ── create_consultation ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_consultation_no_department(db_conn) -> None:
    """A consultation created without a department should have department=None."""
    cid = await create_consultation(db_conn)
    row = await db_conn.fetchrow("SELECT department FROM consultations WHERE id = $1", cid)
    assert row is not None
    assert row["department"] is None


@pytest.mark.asyncio
async def test_create_consultation_with_department(db_conn) -> None:
    """The department passed to create_consultation should be saved to the DB."""
    cid = await create_consultation(db_conn, department="Engineering")
    row = await db_conn.fetchrow("SELECT department FROM consultations WHERE id = $1", cid)
    assert row is not None
    assert row["department"] == "Engineering"


# ── append_message ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_append_message_without_mode(db_conn) -> None:
    """A message appended without mode should have no 'mode' key in JSONB."""
    cid = await create_consultation(db_conn)
    await append_message(db_conn, cid, "user", "Hello")

    session = await get_consultation(db_conn, cid)
    assert session is not None
    msgs = session["messages"]
    assert len(msgs) == 1
    assert msgs[0]["role"] == "user"
    assert msgs[0]["content"] == "Hello"
    assert "mode" not in msgs[0]


@pytest.mark.asyncio
async def test_append_message_with_mode(db_conn) -> None:
    """An assistant message appended with mode should store the mode in JSONB."""
    cid = await create_consultation(db_conn)
    await append_message(db_conn, cid, "user", "My question")
    await append_message(db_conn, cid, "assistant", "My answer", mode="personal")

    session = await get_consultation(db_conn, cid)
    assert session is not None
    msgs = session["messages"]
    assert len(msgs) == 2
    assistant_msg = msgs[1]
    assert assistant_msg["role"] == "assistant"
    assert assistant_msg["mode"] == "personal"


@pytest.mark.asyncio
async def test_append_message_structural_mode(db_conn) -> None:
    """mode='structural' should be stored correctly."""
    cid = await create_consultation(db_conn)
    await append_message(db_conn, cid, "assistant", "Analysis", mode="structural")

    session = await get_consultation(db_conn, cid)
    assert session is not None
    assert session["messages"][0]["mode"] == "structural"


# ── update_metadata / PATCH department ────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_metadata_sets_department(db_conn) -> None:
    """update_metadata should overwrite department when a new value is provided."""
    cid = await create_consultation(db_conn)
    await update_metadata(db_conn, cid, department="Sales", category=None, severity=0)

    row = await db_conn.fetchrow("SELECT department FROM consultations WHERE id = $1", cid)
    assert row is not None
    assert row["department"] == "Sales"


@pytest.mark.asyncio
async def test_update_metadata_preserves_existing_department_on_null(db_conn) -> None:
    """Passing department=None to update_metadata should not overwrite an existing value
    (COALESCE($1, department) semantics)."""
    cid = await create_consultation(db_conn, department="Finance")
    await update_metadata(db_conn, cid, department=None, category="Compensation", severity=2)

    row = await db_conn.fetchrow(
        "SELECT department, category FROM consultations WHERE id = $1", cid
    )
    assert row is not None
    assert row["department"] == "Finance"  # preserved
    assert row["category"] == "Compensation"


# ── GET /departments endpoint ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_departments_returns_list() -> None:
    """GET /departments should return a JSON array (may be empty if no seed data)."""
    mock_conn = AsyncMock()
    mock_conn.fetch = AsyncMock(return_value=[])

    with patch("app.routers.departments.get_conn", return_value=mock_conn):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/departments")

    assert response.status_code == 200
    assert isinstance(response.json(), list)


@pytest.mark.asyncio
async def test_get_departments_returns_id_and_name(db_conn) -> None:
    """Each department item must expose 'id' and 'name' fields.

    Inserts a unique test department directly and calls the router function
    to avoid event-loop conflicts from mixing asyncpg mocks with ASGITransport.
    """
    import uuid as _uuid

    dept_name = f"_test_dept_{_uuid.uuid4().hex[:8]}"
    await db_conn.execute(
        "INSERT INTO departments (name) VALUES ($1) ON CONFLICT (name) DO NOTHING",
        dept_name,
    )

    from app.routers.departments import list_departments

    result = await list_departments(conn=db_conn)

    test_item = next((d for d in result if d["name"] == dept_name), None)
    assert test_item is not None, "Inserted test department not found in result"
    assert isinstance(test_item["id"], str)
    assert test_item["name"] == dept_name


# ── POST /consultations with department ────────────────────────────────────────


@pytest.mark.asyncio
async def test_post_consultations_saves_department(db_conn) -> None:
    """POST /consultations with a department body should persist the value in DB.

    Uses FastAPI dependency_overrides to inject the test connection (which is
    already inside a rollback transaction) instead of the production pool.
    """
    from app.db.session import get_conn as real_get_conn

    async def override_get_conn():
        yield db_conn

    app.dependency_overrides[real_get_conn] = override_get_conn
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/consultations",
                json={"department": "Human Resources"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 201
    cid = response.json()["consultation_id"]

    row = await db_conn.fetchrow("SELECT department FROM consultations WHERE id = $1", cid)
    assert row is not None
    assert row["department"] == "Human Resources"


# ── proposal draft split (plain headings, no markdown) ───────────────────────────


def test_derive_summary_and_proposal_plain_section_headings() -> None:
    from app.routers.consultations import _derive_summary_and_proposal

    raw = """Executive Summary

First paragraph only.

Root Cause Analysis
Point one.
Point two.

Proposed Actions
1. Do A
2. Do B
"""
    summary, proposal = _derive_summary_and_proposal(raw)
    assert summary.strip() == "First paragraph only."
    assert "Executive Summary" not in proposal
    assert "Root Cause Analysis" in proposal
    assert "Proposed Actions" in proposal
    assert "First paragraph only." not in proposal


def test_derive_summary_and_proposal_markdown_headings() -> None:
    from app.routers.consultations import _derive_summary_and_proposal

    raw = """### Executive Summary

One para.

### Root Cause Analysis

Details here.

### Proposed Actions

1. X
"""
    summary, proposal = _derive_summary_and_proposal(raw)
    assert "One para." in summary
    assert "One para." not in proposal
    assert "Root Cause Analysis" in proposal
    assert "Details here." in proposal


def test_derive_summary_and_proposal_japanese_fixed_headings() -> None:
    from app.routers.consultations import _derive_summary_and_proposal

    raw = """### 概要

要約は1段落。

### 原因分析

原因の詳細。

### 提案事項

1. 改善A
"""
    summary, proposal = _derive_summary_and_proposal(raw)
    assert "要約は1段落。" in summary
    assert "概要" not in proposal
    assert "原因分析" in proposal
    assert "提案事項" in proposal
