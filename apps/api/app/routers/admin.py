"""Admin-only management endpoints.

Endpoints:
  GET  /admin/proposals    — list all submitted consultations
  GET  /admin/trends       — category × department aggregation
  POST /admin/departments  — add a new department
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.auth.deps import require_admin
from app.db.session import get_conn

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)


# ── Proposals ──────────────────────────────────────────────────────────────


@router.get("/proposals")
async def list_proposals(conn=Depends(get_conn)) -> list[dict]:
    """Return all submitted consultations ordered by creation date (desc)."""
    rows = await conn.fetch(
        """
        SELECT
            id::text,
            department,
            category,
            COALESCE(severity, 0) AS severity,
            summary,
            user_name,
            user_email,
            admin_status,
            is_submitted,
            created_at
        FROM consultations
        WHERE is_submitted = TRUE
        ORDER BY created_at DESC
        """
    )
    return [dict(r) for r in rows]


# ── Trends ─────────────────────────────────────────────────────────────────


@router.get("/trends")
async def get_trends(conn=Depends(get_conn)) -> list[dict]:
    """Aggregate submitted consultations by category and department."""
    rows = await conn.fetch(
        """
        SELECT
            category,
            department,
            COUNT(*)::int AS count,
            ROUND(AVG(COALESCE(severity, 0))::numeric, 2)::float AS avg_severity
        FROM consultations
        WHERE is_submitted = TRUE
        GROUP BY category, department
        ORDER BY count DESC, avg_severity DESC
        """
    )
    return [dict(r) for r in rows]


# ── Departments ────────────────────────────────────────────────────────────


class DepartmentCreate(BaseModel):
    name: str


@router.post("/departments", status_code=201)
async def create_department(
    body: DepartmentCreate,
    conn=Depends(get_conn),
) -> dict:
    """Add a new department."""
    row = await conn.fetchrow(
        "INSERT INTO departments (name) VALUES ($1) RETURNING id::text, name",
        body.name,
    )
    return dict(row)
