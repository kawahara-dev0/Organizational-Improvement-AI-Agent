"""CRUD operations for the consultations table."""

from __future__ import annotations

import json
import uuid

from asyncpg import Connection


async def create_consultation(conn: Connection) -> str:
    """Insert a new empty consultation row and return its UUID."""
    row_id = str(uuid.uuid4())
    await conn.execute(
        """
        INSERT INTO consultations (id) VALUES ($1)
        """,
        row_id,
    )
    return row_id


async def get_consultation(conn: Connection, consultation_id: str) -> dict | None:
    row = await conn.fetchrow(
        """
        SELECT id, department, category, severity, feedback,
               is_submitted, summary, proposal, messages,
               user_name, user_email, admin_status, created_at
        FROM consultations
        WHERE id = $1
        """,
        consultation_id,
    )
    if not row:
        return None
    data = dict(row)
    data["messages"] = json.loads(data["messages"]) if data["messages"] else []
    data["id"] = str(data["id"])
    return data


async def append_message(
    conn: Connection,
    consultation_id: str,
    role: str,
    content: str,
) -> None:
    """Append a single message object to the messages JSONB array."""
    message = json.dumps({"role": role, "content": content})
    await conn.execute(
        """
        UPDATE consultations
        SET messages = messages || $1::jsonb
        WHERE id = $2
        """,
        f"[{message}]",
        consultation_id,
    )


async def update_metadata(
    conn: Connection,
    consultation_id: str,
    department: str | None,
    category: str | None,
    severity: int,
) -> None:
    """Overwrite extracted metadata fields (department, category, severity)."""
    await conn.execute(
        """
        UPDATE consultations
        SET department = COALESCE($1, department),
            category   = COALESCE($2, category),
            severity   = $3
        WHERE id = $4
        """,
        department,
        category,
        severity,
        consultation_id,
    )


async def update_feedback(
    conn: Connection,
    consultation_id: str,
    value: int,
) -> bool:
    """Set feedback to -1 (dislike), 0 (neutral), or 1 (like). Returns True if updated."""
    result = await conn.execute(
        """
        UPDATE consultations
        SET feedback = $1
        WHERE id = $2
        """,
        value,
        consultation_id,
    )
    return result == "UPDATE 1"
