"""Integration tests for admin endpoints.

Covers:
  POST /admin/login                         — auth
  GET  /admin/proposals                     — list submitted proposals
  GET  /admin/proposals/{id}                — proposal detail
  PATCH /admin/proposals/{id}/status        — status update
  POST /admin/analyze                       — LLM analytical draft (mocked)
  GET  /admin/trends                        — heatmap + by-department
  POST /admin/trends/summary                — LLM management brief (mocked)
  POST /admin/departments                   — create department
  PUT  /admin/departments/{id}              — rename department
  DELETE /admin/departments/{id}            — delete department
  Pure-function units: _parse_date, _build_trends_where

Run with:
    docker compose run --rm api uv run pytest tests/test_admin.py -v
"""

from __future__ import annotations

import uuid
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.auth.deps import create_admin_token
from app.db.session import get_conn as real_get_conn
from app.routers.admin import _build_trends_where, _parse_date
from main import app

# ── Helpers ────────────────────────────────────────────────────────────────


def _auth(token: str | None = None) -> dict:
    """Return Authorization header dict (uses a fresh valid token by default)."""
    t = token or create_admin_token()
    return {"Authorization": f"Bearer {t}"}


async def _insert_submitted(
    conn,
    *,
    summary: str = "Test summary",
    proposal: str = "Test proposal",
    department: str | None = None,
    category: str | None = None,
    severity: int = 2,
) -> str:
    """Insert a submitted consultation row and return its id."""
    row_id = str(uuid.uuid4())
    await conn.execute(
        """
        INSERT INTO consultations
            (id, department, category, severity, is_submitted,
             summary, proposal, admin_status)
        VALUES
            ($1, $2, $3, $4, TRUE, $5, $6, 'New')
        """,
        row_id,
        department,
        category,
        severity,
        summary,
        proposal,
    )
    return row_id


async def _insert_unsubmitted(conn) -> str:
    """Insert a non-submitted consultation row and return its id."""
    row_id = str(uuid.uuid4())
    await conn.execute(
        "INSERT INTO consultations (id) VALUES ($1)",
        row_id,
    )
    return row_id


# ── Admin login ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_admin_login_correct_password() -> None:
    """POST /admin/login with the correct password returns a JWT access_token."""
    from app.settings import settings

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/admin/login", json={"password": settings.admin_password})

    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_admin_login_wrong_password() -> None:
    """POST /admin/login with a wrong password returns 401."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/admin/login", json={"password": "wrong-password"})

    assert resp.status_code == 401


# ── Auth guard ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_admin_endpoints_require_token(db_conn) -> None:
    """Admin routes must return 401 when no Bearer token is provided."""
    app.dependency_overrides[real_get_conn] = lambda: db_conn

    async def _override():
        yield db_conn

    app.dependency_overrides[real_get_conn] = _override
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            assert (await c.get("/admin/proposals")).status_code == 401
            assert (await c.get("/admin/trends")).status_code == 401
            assert (await c.post("/admin/departments", json={"name": "X"})).status_code == 401
    finally:
        app.dependency_overrides.clear()


# ── Proposals ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_proposals_returns_only_submitted(db_conn) -> None:
    """GET /admin/proposals must include submitted rows and exclude non-submitted ones."""
    submitted_id = await _insert_submitted(db_conn, summary="Issue A")
    unsubmitted_id = await _insert_unsubmitted(db_conn)

    async def _override():
        yield db_conn

    app.dependency_overrides[real_get_conn] = _override
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/admin/proposals", headers=_auth())
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    ids = {p["id"] for p in resp.json()}
    assert submitted_id in ids
    assert unsubmitted_id not in ids


@pytest.mark.asyncio
async def test_get_proposal_detail(db_conn) -> None:
    """GET /admin/proposals/{id} returns summary and proposal text."""
    cid = await _insert_submitted(db_conn, summary="Hello summary", proposal="Hello proposal")

    async def _override():
        yield db_conn

    app.dependency_overrides[real_get_conn] = _override
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get(f"/admin/proposals/{cid}", headers=_auth())
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == cid
    assert data["summary"] == "Hello summary"
    assert data["proposal"] == "Hello proposal"


@pytest.mark.asyncio
async def test_get_proposal_detail_404_when_not_submitted(db_conn) -> None:
    """GET /admin/proposals/{id} returns 404 for a non-submitted consultation."""
    cid = await _insert_unsubmitted(db_conn)

    async def _override():
        yield db_conn

    app.dependency_overrides[real_get_conn] = _override
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get(f"/admin/proposals/{cid}", headers=_auth())
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_update_proposal_status_valid(db_conn) -> None:
    """PATCH .../status with a valid status persists and returns the new status."""
    cid = await _insert_submitted(db_conn)

    async def _override():
        yield db_conn

    app.dependency_overrides[real_get_conn] = _override
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.patch(
                f"/admin/proposals/{cid}/status",
                json={"admin_status": "In Progress"},
                headers=_auth(),
            )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    assert resp.json()["admin_status"] == "In Progress"

    row = await db_conn.fetchrow("SELECT admin_status FROM consultations WHERE id = $1", cid)
    assert row["admin_status"] == "In Progress"


@pytest.mark.asyncio
async def test_update_proposal_status_invalid_value(db_conn) -> None:
    """PATCH .../status with an invalid status returns 422."""
    cid = await _insert_submitted(db_conn)

    async def _override():
        yield db_conn

    app.dependency_overrides[real_get_conn] = _override
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.patch(
                f"/admin/proposals/{cid}/status",
                json={"admin_status": "InvalidStatus"},
                headers=_auth(),
            )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_update_proposal_status_404_for_unknown_id(db_conn) -> None:
    """PATCH .../status for a non-existent id returns 404."""
    fake_id = str(uuid.uuid4())

    async def _override():
        yield db_conn

    app.dependency_overrides[real_get_conn] = _override
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.patch(
                f"/admin/proposals/{fake_id}/status",
                json={"admin_status": "Resolved"},
                headers=_auth(),
            )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 404


# ── Analytical mode (LLM mocked) ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_analyze_proposals_returns_draft(db_conn) -> None:
    """POST /admin/analyze with valid ids returns a draft string."""
    cid = await _insert_submitted(db_conn, summary="S1", proposal="P1")

    mock_llm = MagicMock()
    mock_llm.ainvoke = AsyncMock(return_value=MagicMock(content="Policy draft text"))

    async def _override():
        yield db_conn

    app.dependency_overrides[real_get_conn] = _override
    try:
        with patch("app.routers.admin.get_gemini", return_value=mock_llm):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
                resp = await c.post(
                    "/admin/analyze",
                    json={"proposal_ids": [cid], "language": "en"},
                    headers=_auth(),
                )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    data = resp.json()
    assert "draft" in data
    assert data["proposal_count"] == 1


@pytest.mark.asyncio
async def test_analyze_proposals_empty_ids_returns_422(db_conn) -> None:
    """POST /admin/analyze with no ids returns 422."""

    async def _override():
        yield db_conn

    app.dependency_overrides[real_get_conn] = _override
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post(
                "/admin/analyze",
                json={"proposal_ids": []},
                headers=_auth(),
            )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_analyze_proposals_nonexistent_ids_returns_404(db_conn) -> None:
    """POST /admin/analyze with ids that don't exist returns 404."""
    fake_id = str(uuid.uuid4())

    async def _override():
        yield db_conn

    app.dependency_overrides[real_get_conn] = _override
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post(
                "/admin/analyze",
                json={"proposal_ids": [fake_id]},
                headers=_auth(),
            )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 404


# ── Trends ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_trends_returns_required_keys(db_conn) -> None:
    """GET /admin/trends must return heatmap and by_department keys."""

    async def _override():
        yield db_conn

    app.dependency_overrides[real_get_conn] = _override
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/admin/trends", headers=_auth())
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    data = resp.json()
    assert "heatmap" in data
    assert "by_department" in data


@pytest.mark.asyncio
async def test_get_trends_department_filter(db_conn) -> None:
    """GET /admin/trends?department=X should only aggregate rows for that department."""
    tag = uuid.uuid4().hex[:8]
    await _insert_submitted(
        db_conn, department=f"Engineering_{tag}", category="Workload", severity=3
    )
    await _insert_submitted(
        db_conn, department=f"Finance_{tag}", category="Compensation", severity=1
    )

    async def _override():
        yield db_conn

    app.dependency_overrides[real_get_conn] = _override
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get(f"/admin/trends?department=Engineering_{tag}", headers=_auth())
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    depts = {r["department"] for r in resp.json()["by_department"]}
    assert f"Engineering_{tag}" in depts
    assert f"Finance_{tag}" not in depts


@pytest.mark.asyncio
async def test_get_trends_date_filter(db_conn) -> None:
    """GET /admin/trends with date_from/date_to should not raise an error."""

    async def _override():
        yield db_conn

    app.dependency_overrides[real_get_conn] = _override
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get(
                "/admin/trends?date_from=2024-01-01&date_to=2099-12-31", headers=_auth()
            )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_trends_summary_returns_summary(db_conn) -> None:
    """POST /admin/trends/summary returns a summary when data exists (LLM mocked)."""
    await _insert_submitted(db_conn, category="Workload", department="HR", severity=2)

    mock_llm = MagicMock()
    mock_llm.ainvoke = AsyncMock(return_value=MagicMock(content="Management brief text"))

    async def _override():
        yield db_conn

    app.dependency_overrides[real_get_conn] = _override
    try:
        with patch("app.routers.admin.get_gemini", return_value=mock_llm):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
                resp = await c.post(
                    "/admin/trends/summary",
                    json={"language": "en"},
                    headers=_auth(),
                )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    assert "summary" in resp.json()


# ── Departments ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_department(db_conn) -> None:
    """POST /admin/departments creates a new department and returns id + name."""
    name = f"_test_dept_{uuid.uuid4().hex[:8]}"

    async def _override():
        yield db_conn

    app.dependency_overrides[real_get_conn] = _override
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/admin/departments", json={"name": name}, headers=_auth())
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == name
    assert "id" in data


@pytest.mark.asyncio
async def test_update_department(db_conn) -> None:
    """PUT /admin/departments/{id} renames an existing department."""
    row = await db_conn.fetchrow(
        "INSERT INTO departments (name) VALUES ($1) RETURNING id::text, name",
        f"_test_dept_{uuid.uuid4().hex[:8]}",
    )
    dept_id = row["id"]
    new_name = f"_renamed_{uuid.uuid4().hex[:8]}"

    async def _override():
        yield db_conn

    app.dependency_overrides[real_get_conn] = _override
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.put(
                f"/admin/departments/{dept_id}",
                json={"name": new_name},
                headers=_auth(),
            )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    assert resp.json()["name"] == new_name


@pytest.mark.asyncio
async def test_update_department_404_unknown_id(db_conn) -> None:
    """PUT /admin/departments/{id} returns 404 for an unknown id."""

    async def _override():
        yield db_conn

    app.dependency_overrides[real_get_conn] = _override
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.put(
                f"/admin/departments/{uuid.uuid4()}",
                json={"name": "X"},
                headers=_auth(),
            )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_department(db_conn) -> None:
    """DELETE /admin/departments/{id} removes the department (204 No Content)."""
    row = await db_conn.fetchrow(
        "INSERT INTO departments (name) VALUES ($1) RETURNING id::text",
        f"_test_dept_{uuid.uuid4().hex[:8]}",
    )
    dept_id = row["id"]

    async def _override():
        yield db_conn

    app.dependency_overrides[real_get_conn] = _override
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.delete(f"/admin/departments/{dept_id}", headers=_auth())
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 204
    row_after = await db_conn.fetchrow("SELECT id FROM departments WHERE id = $1::uuid", dept_id)
    assert row_after is None


@pytest.mark.asyncio
async def test_delete_department_404_unknown_id(db_conn) -> None:
    """DELETE /admin/departments/{id} returns 404 for an unknown id."""

    async def _override():
        yield db_conn

    app.dependency_overrides[real_get_conn] = _override
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.delete(f"/admin/departments/{uuid.uuid4()}", headers=_auth())
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 404


# ── Pure-function unit tests ────────────────────────────────────────────────


def test_parse_date_valid_iso() -> None:
    assert _parse_date("2026-01-15") == date(2026, 1, 15)


def test_parse_date_none_input() -> None:
    assert _parse_date(None) is None


def test_parse_date_empty_string() -> None:
    assert _parse_date("") is None


def test_parse_date_invalid_string() -> None:
    assert _parse_date("not-a-date") is None


def test_build_trends_where_no_filters() -> None:
    clause, params = _build_trends_where(None, None, None)
    assert clause == "WHERE TRUE"
    assert params == []


def test_build_trends_where_department_only() -> None:
    clause, params = _build_trends_where("Engineering", None, None)
    assert "department = $1" in clause
    assert params[0] == "Engineering"


def test_build_trends_where_date_range() -> None:
    clause, params = _build_trends_where(None, "2026-01-01", "2026-03-31")
    assert "created_at::date >=" in clause
    assert "created_at::date <" in clause
    # date_to is advanced by 1 day in the implementation
    assert date(2026, 4, 1) in params


def test_build_trends_where_all_filters() -> None:
    clause, params = _build_trends_where("HR", "2026-01-01", "2026-12-31")
    assert "department = $1" in clause
    assert "created_at::date >=" in clause
    assert "created_at::date <" in clause
    assert len(params) == 3
