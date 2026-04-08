"""Department list endpoint."""

from __future__ import annotations

from asyncpg import Connection
from fastapi import APIRouter, Depends

from app.db.session import get_conn

router = APIRouter(prefix="/departments", tags=["departments"])


@router.get("")
async def list_departments(
    conn: Connection = Depends(get_conn),
) -> list[dict]:
    """Return all departments ordered by name."""
    rows = await conn.fetch("SELECT id, name FROM departments ORDER BY name")
    return [{"id": str(r["id"]), "name": r["name"]} for r in rows]
