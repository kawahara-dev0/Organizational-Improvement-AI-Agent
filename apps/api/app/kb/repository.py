"""knowledge_base table CRUD using asyncpg."""

from __future__ import annotations

import json
import uuid

from asyncpg import Connection

from app.kb.parser import Chunk

# ── Write ─────────────────────────────────────────────────────────────────────


async def upsert_chunks(
    conn: Connection,
    chunks: list[Chunk],
    vectors: list[list[float]],
) -> list[str]:
    """Insert chunk rows and return the list of new UUIDs."""
    ids: list[str] = []
    for chunk, vector in zip(chunks, vectors, strict=True):
        row_id = str(uuid.uuid4())
        vector_str = "[" + ",".join(str(v) for v in vector) + "]"
        await conn.execute(
            """
            INSERT INTO knowledge_base (id, content, embedding, metadata)
            VALUES ($1, $2, $3::vector, $4::jsonb)
            """,
            row_id,
            chunk.content,
            vector_str,
            json.dumps(chunk.metadata),
        )
        ids.append(row_id)
    return ids


# ── Read ──────────────────────────────────────────────────────────────────────


async def list_chunks(
    conn: Connection,
    source_file: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    if source_file:
        rows = await conn.fetch(
            """
            SELECT id, content, metadata, created_at
            FROM knowledge_base
            WHERE metadata->>'source_file' = $1
            ORDER BY created_at DESC
            LIMIT $2 OFFSET $3
            """,
            source_file,
            limit,
            offset,
        )
    else:
        rows = await conn.fetch(
            """
            SELECT id, content, metadata, created_at
            FROM knowledge_base
            ORDER BY created_at DESC
            LIMIT $1 OFFSET $2
            """,
            limit,
            offset,
        )
    return [dict(r) for r in rows]


async def get_chunk(conn: Connection, chunk_id: str) -> dict | None:
    row = await conn.fetchrow(
        "SELECT id, content, metadata, created_at FROM knowledge_base WHERE id = $1",
        chunk_id,
    )
    return dict(row) if row else None


# ── Update ────────────────────────────────────────────────────────────────────


async def update_chunk_content(
    conn: Connection,
    chunk_id: str,
    content: str,
    vector: list[float],
) -> bool:
    vector_str = "[" + ",".join(str(v) for v in vector) + "]"
    result = await conn.execute(
        """
        UPDATE knowledge_base
        SET content = $1, embedding = $2::vector
        WHERE id = $3
        """,
        content,
        vector_str,
        chunk_id,
    )
    return result == "UPDATE 1"


# ── Delete ────────────────────────────────────────────────────────────────────


async def delete_chunk(conn: Connection, chunk_id: str) -> bool:
    result = await conn.execute(
        "DELETE FROM knowledge_base WHERE id = $1",
        chunk_id,
    )
    return result == "DELETE 1"


async def delete_by_source(conn: Connection, source_file: str) -> int:
    """Delete all chunks belonging to a source file. Returns deleted count."""
    result = await conn.execute(
        "DELETE FROM knowledge_base WHERE metadata->>'source_file' = $1",
        source_file,
    )
    return int(result.split()[-1])
