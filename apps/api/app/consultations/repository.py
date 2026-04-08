"""CRUD operations for the consultations table."""

from __future__ import annotations

import json
import uuid

from asyncpg import Connection


async def create_consultation(
    conn: Connection,
    department: str | None = None,
) -> str:
    """Insert a new consultation row and return its UUID."""
    row_id = str(uuid.uuid4())
    await conn.execute(
        """
        INSERT INTO consultations (id, department) VALUES ($1, $2)
        """,
        row_id,
        department,
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
    mode: str | None = None,
) -> None:
    """Append a single message object to the messages JSONB array.

    The mode field (personal | structural) is stored on assistant messages
    so the UI can restore mode badges when reloading the session.
    """
    msg: dict = {"role": role, "content": content}
    if mode is not None:
        msg["mode"] = mode
    message = json.dumps(msg)
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


async def submit_consultation(
    conn: Connection,
    consultation_id: str,
    summary: str,
    proposal: str,
    user_name: str | None = None,
    user_email: str | None = None,
) -> bool:
    """Atomically finalize a consultation as a formal submission.

    Sets summary, proposal, optional contact info, is_submitted=true,
    and admin_status='New' in a single UPDATE.
    Returns True if a row was updated.
    """
    result = await conn.execute(
        """
        UPDATE consultations
        SET summary      = $1,
            proposal     = $2,
            user_name    = $3,
            user_email   = $4,
            is_submitted = TRUE,
            admin_status = 'New'
        WHERE id = $5
          AND is_submitted = FALSE
        """,
        summary,
        proposal,
        user_name,
        user_email,
        consultation_id,
    )
    return result == "UPDATE 1"


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
