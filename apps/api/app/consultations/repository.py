"""CRUD operations for the consultations table."""

from __future__ import annotations

import json
import secrets
import uuid

from asyncpg import Connection

from app.utils.crypto import decrypt_messages, encrypt_messages, is_encryption_enabled


async def create_consultation(
    conn: Connection,
    department: str | None = None,
) -> tuple[str, str]:
    """Insert a new consultation row and return (UUID, access token)."""
    row_id = str(uuid.uuid4())
    access_token = secrets.token_urlsafe(32)
    await conn.execute(
        """
        INSERT INTO consultations (id, access_token, department) VALUES ($1::uuid, $2, $3)
        """,
        row_id,
        access_token,
        department,
    )
    return row_id, access_token


async def verify_consultation_access(
    conn: Connection,
    consultation_id: str,
    access_token: str,
) -> bool:
    """Return True only when the opaque access token matches the session."""
    if not access_token:
        return False
    row = await conn.fetchrow(
        """
        SELECT 1
        FROM consultations
        WHERE id = $1::uuid AND access_token = $2
        """,
        consultation_id,
        access_token,
    )
    return row is not None


async def get_consultation(conn: Connection, consultation_id: str) -> dict | None:
    row = await conn.fetchrow(
        """
        SELECT id, department, category, severity, feedback,
               is_submitted, summary, proposal, messages,
               user_name, user_email, admin_status, created_at
        FROM consultations
        WHERE id = $1::uuid
        """,
        consultation_id,
    )
    if not row:
        return None
    data = dict(row)
    # messages is stored as JSONB; asyncpg returns it as a JSON string.
    # decrypt_messages handles encrypted ("enc:v1:…"), plain string, and
    # legacy list values transparently.
    raw = json.loads(data["messages"]) if data["messages"] else []
    data["messages"] = decrypt_messages(raw)
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

    When encryption is enabled, the whole messages array is re-encrypted
    on each write (read-modify-write).  Without encryption, the original
    fast JSONB concatenation is used.
    """
    msg: dict = {"role": role, "content": content}
    if mode is not None:
        msg["mode"] = mode

    if is_encryption_enabled():
        # Read current messages, append, encrypt, write back.
        session = await get_consultation(conn, consultation_id)
        messages = session["messages"] if session else []
        messages.append(msg)
        encrypted_str = encrypt_messages(messages)
        # Store as a JSONB string value: json.dumps wraps in double-quotes.
        await conn.execute(
            "UPDATE consultations SET messages = $1::jsonb WHERE id = $2::uuid",
            json.dumps(encrypted_str),
            consultation_id,
        )
    else:
        # Fast path: native JSONB concatenation.
        await conn.execute(
            """
            UPDATE consultations
            SET messages = messages || $1::jsonb
            WHERE id = $2::uuid
            """,
            f"[{json.dumps(msg)}]",
            consultation_id,
        )


async def update_metadata(
    conn: Connection,
    consultation_id: str,
    category: str | None,
    severity: int,
) -> None:
    """Overwrite extracted metadata fields managed by LLM analysis."""
    await conn.execute(
        """
        UPDATE consultations
        SET category = COALESCE($1, category),
            severity = $2
        WHERE id = $3::uuid
        """,
        category,
        severity,
        consultation_id,
    )


async def set_consultation_department(
    conn: Connection,
    consultation_id: str,
    department: str | None,
) -> None:
    """Set the user-selected department exactly, including clearing to NULL."""
    await conn.execute(
        """
        UPDATE consultations
        SET department = $1
        WHERE id = $2::uuid
        """,
        department,
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
        WHERE id = $5::uuid
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
        WHERE id = $2::uuid
        """,
        value,
        consultation_id,
    )
    return result == "UPDATE 1"
