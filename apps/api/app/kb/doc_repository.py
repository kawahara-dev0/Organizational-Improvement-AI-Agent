"""CRUD for kb_documents and kb_document_versions.

Document lifecycle
------------------
1. create_document()               → kb_documents row (no version yet)
2. create_version()                → kb_document_versions row (version_no auto-incremented)
3. upsert_chunks() [existing]      → knowledge_base rows with document_id + version_id
4. finalize_version()              → sets chunk_count, activates new version,
                                     deactivates old ones, updates current_version_id
"""
from __future__ import annotations

from asyncpg import Connection

# ── Documents ─────────────────────────────────────────────────────────────────


async def list_documents(conn: Connection) -> list[dict]:
    """Return all documents with their active version info and chunk count."""
    rows = await conn.fetch(
        """
        SELECT
            d.id::text,
            d.title,
            d.category,
            d.created_at,
            d.updated_at,
            v.id::text          AS version_id,
            v.version_no,
            v.source_file,
            v.chunk_count,
            v.created_at        AS version_created_at
        FROM kb_documents d
        LEFT JOIN kb_document_versions v
               ON v.id = d.current_version_id
        ORDER BY d.updated_at DESC
        """
    )
    return [dict(r) for r in rows]


async def get_document(conn: Connection, document_id: str) -> dict | None:
    """Return a document with its full version history."""
    doc_row = await conn.fetchrow(
        """
        SELECT id::text, title, category, current_version_id::text,
               created_at, updated_at
        FROM kb_documents WHERE id = $1::uuid
        """,
        document_id,
    )
    if not doc_row:
        return None

    version_rows = await conn.fetch(
        """
        SELECT id::text, version_no, source_file, is_active,
               chunk_count, created_at
        FROM kb_document_versions
        WHERE document_id = $1::uuid
        ORDER BY version_no DESC
        """,
        document_id,
    )
    return {**dict(doc_row), "versions": [dict(v) for v in version_rows]}


async def create_document(
    conn: Connection, title: str, category: str
) -> str:
    """Insert a new kb_documents row and return its UUID string."""
    row = await conn.fetchrow(
        "INSERT INTO kb_documents (title, category) VALUES ($1, $2) RETURNING id::text",
        title,
        category,
    )
    return row["id"]  # type: ignore[index]


async def update_document_meta(
    conn: Connection, document_id: str, title: str, category: str
) -> bool:
    """Rename / recategorise a document. Returns False if not found."""
    result = await conn.execute(
        """
        UPDATE kb_documents
           SET title = $1, category = $2, updated_at = NOW()
         WHERE id = $3::uuid
        """,
        title,
        category,
        document_id,
    )
    return result == "UPDATE 1"


async def archive_document(conn: Connection, document_id: str) -> bool:
    """Delete a document and all its versions + chunks (CASCADE)."""
    result = await conn.execute(
        "DELETE FROM kb_documents WHERE id = $1::uuid",
        document_id,
    )
    return result == "DELETE 1"


# ── Versions ──────────────────────────────────────────────────────────────────


async def create_version(
    conn: Connection, document_id: str, source_file: str
) -> tuple[str, int]:
    """Insert a new kb_document_versions row.

    Returns (version_id, version_no). Does NOT activate yet; call
    finalize_version() after chunks are embedded and stored.
    """
    row = await conn.fetchrow(
        """
        INSERT INTO kb_document_versions (document_id, version_no, source_file, is_active)
        SELECT $1::uuid,
               COALESCE(MAX(version_no), 0) + 1,
               $2,
               FALSE          -- activated only after successful embed
        FROM kb_document_versions
        WHERE document_id = $1::uuid
        RETURNING id::text, version_no
        """,
        document_id,
        source_file,
    )
    return row["id"], row["version_no"]  # type: ignore[index]


async def finalize_version(
    conn: Connection, document_id: str, version_id: str, chunk_count: int
) -> None:
    """Activate the new version, deactivate all previous ones, update document."""
    async with conn.transaction():
        # Deactivate previous versions
        await conn.execute(
            """
            UPDATE kb_document_versions
               SET is_active = FALSE
             WHERE document_id = $1::uuid
               AND id <> $2::uuid
            """,
            document_id,
            version_id,
        )
        # Activate new version with chunk count
        await conn.execute(
            """
            UPDATE kb_document_versions
               SET is_active = TRUE, chunk_count = $1
             WHERE id = $2::uuid
            """,
            chunk_count,
            version_id,
        )
        # Update document pointer
        await conn.execute(
            """
            UPDATE kb_documents
               SET current_version_id = $1::uuid, updated_at = NOW()
             WHERE id = $2::uuid
            """,
            version_id,
            document_id,
        )


async def delete_version(conn: Connection, version_id: str) -> None:
    """Delete a version row (and its chunks if they reference this version)."""
    await conn.execute(
        "DELETE FROM kb_document_versions WHERE id = $1::uuid",
        version_id,
    )


async def list_chunks_for_version(
    conn: Connection, version_id: str
) -> list[dict]:
    """Return all chunks belonging to a specific version (view only)."""
    rows = await conn.fetch(
        """
        SELECT id::text,
               (metadata->>'chunk_index')::int AS chunk_index,
               content,
               metadata->>'page_number' AS page_number
        FROM knowledge_base
        WHERE version_id = $1::uuid
        ORDER BY (metadata->>'chunk_index')::int
        """,
        version_id,
    )
    return [dict(r) for r in rows]
