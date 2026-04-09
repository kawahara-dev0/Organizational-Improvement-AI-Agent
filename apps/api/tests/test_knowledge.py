"""Integration tests for knowledge-base version retention.

Covers:
  purge_old_versions()  — deletes versions + chunks beyond VERSION_RETENTION (3)
  upload_new_version    — POST /knowledge/documents/{id}/upload triggers purge

Run with:
    docker compose run --rm api uv run pytest tests/test_knowledge.py -v
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.auth.deps import create_admin_token
from app.db.session import get_conn as real_get_conn
from app.kb.doc_repository import VERSION_RETENTION, purge_old_versions
from main import app

# ── DB helpers ─────────────────────────────────────────────────────────────────


async def _create_document(conn, title: str = "Test Doc") -> str:
    """Insert a kb_documents row and return its id."""
    row = await conn.fetchrow(
        "INSERT INTO kb_documents (title, category) VALUES ($1, $2) RETURNING id::text",
        title,
        "",
    )
    return row["id"]


async def _create_version(
    conn, document_id: str, *, version_no: int, is_active: bool = False
) -> str:
    """Insert a kb_document_versions row and return its id."""
    row = await conn.fetchrow(
        """
        INSERT INTO kb_document_versions
            (document_id, version_no, source_file, is_active, chunk_count)
        VALUES ($1::uuid, $2, $3, $4, 0)
        RETURNING id::text
        """,
        document_id,
        version_no,
        f"file_v{version_no}.pdf",
        is_active,
    )
    return row["id"]


async def _create_chunk(conn, document_id: str, version_id: str) -> str:
    """Insert a dummy knowledge_base chunk and return its id."""
    dummy_vector = "[" + ",".join(["0.0"] * 768) + "]"
    row = await conn.fetchrow(
        """
        INSERT INTO knowledge_base (content, embedding, metadata, document_id, version_id)
        VALUES ($1, $2::vector, $3::jsonb, $4::uuid, $5::uuid)
        RETURNING id::text
        """,
        "dummy content",
        dummy_vector,
        "{}",
        document_id,
        version_id,
    )
    return row["id"]


def _auth() -> dict:
    return {"Authorization": f"Bearer {create_admin_token()}"}


# ── purge_old_versions unit tests ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_purge_does_nothing_when_within_retention(db_conn) -> None:
    """purge_old_versions returns 0 when version count <= VERSION_RETENTION."""
    doc_id = await _create_document(db_conn)
    for i in range(1, VERSION_RETENTION + 1):
        await _create_version(db_conn, doc_id, version_no=i, is_active=(i == VERSION_RETENTION))

    deleted = await purge_old_versions(db_conn, doc_id)

    assert deleted == 0
    count = await db_conn.fetchval(
        "SELECT COUNT(*) FROM kb_document_versions WHERE document_id = $1::uuid", doc_id
    )
    assert count == VERSION_RETENTION


@pytest.mark.asyncio
async def test_purge_removes_oldest_versions_beyond_retention(db_conn) -> None:
    """purge_old_versions deletes versions older than VERSION_RETENTION newest."""
    doc_id = await _create_document(db_conn)
    total = VERSION_RETENTION + 2  # e.g., 5 versions
    for i in range(1, total + 1):
        await _create_version(db_conn, doc_id, version_no=i, is_active=(i == total))

    deleted = await purge_old_versions(db_conn, doc_id)

    assert deleted == 2
    remaining = await db_conn.fetch(
        """
        SELECT version_no FROM kb_document_versions
        WHERE document_id = $1::uuid ORDER BY version_no
        """,
        doc_id,
    )
    remaining_nos = [r["version_no"] for r in remaining]
    # Only the newest 3 versions should remain
    assert remaining_nos == [total - 2, total - 1, total]


@pytest.mark.asyncio
async def test_purge_deletes_chunks_of_removed_versions(db_conn) -> None:
    """purge_old_versions removes knowledge_base chunks for deleted versions."""
    doc_id = await _create_document(db_conn)
    # Create 4 versions with chunks
    version_ids = []
    for i in range(1, 5):
        vid = await _create_version(db_conn, doc_id, version_no=i, is_active=(i == 4))
        version_ids.append(vid)
        await _create_chunk(db_conn, doc_id, vid)

    old_version_id = version_ids[0]  # v1 — should be purged
    kept_version_id = version_ids[3]  # v4 — should be kept

    await purge_old_versions(db_conn, doc_id)

    # Chunk for v1 must be gone
    old_chunk_count = await db_conn.fetchval(
        "SELECT COUNT(*) FROM knowledge_base WHERE version_id = $1::uuid", old_version_id
    )
    assert old_chunk_count == 0

    # Chunk for v4 must remain
    kept_chunk_count = await db_conn.fetchval(
        "SELECT COUNT(*) FROM knowledge_base WHERE version_id = $1::uuid", kept_version_id
    )
    assert kept_chunk_count == 1


@pytest.mark.asyncio
async def test_purge_does_not_create_orphan_chunks(db_conn) -> None:
    """Chunks of purged versions must not become orphan rows (version_id NULL)."""
    doc_id = await _create_document(db_conn)
    version_ids = []
    for i in range(1, VERSION_RETENTION + 3):
        vid = await _create_version(db_conn, doc_id, version_no=i)
        version_ids.append(vid)
        await _create_chunk(db_conn, doc_id, vid)

    await purge_old_versions(db_conn, doc_id)

    orphan_count = await db_conn.fetchval(
        "SELECT COUNT(*) FROM knowledge_base WHERE document_id = $1::uuid AND version_id IS NULL",
        doc_id,
    )
    assert orphan_count == 0


@pytest.mark.asyncio
async def test_purge_does_not_affect_other_documents(db_conn) -> None:
    """purge_old_versions must not delete versions/chunks of other documents."""
    doc_a = await _create_document(db_conn, title="Doc A")
    doc_b = await _create_document(db_conn, title="Doc B")

    # Doc A gets 4 versions (1 over retention)
    for i in range(1, 5):
        await _create_version(db_conn, doc_a, version_no=i, is_active=(i == 4))

    # Doc B gets 1 version
    vid_b = await _create_version(db_conn, doc_b, version_no=1, is_active=True)
    await _create_chunk(db_conn, doc_b, vid_b)

    await purge_old_versions(db_conn, doc_a)

    # Doc B's version and chunk must be intact
    b_version_count = await db_conn.fetchval(
        "SELECT COUNT(*) FROM kb_document_versions WHERE document_id = $1::uuid", doc_b
    )
    assert b_version_count == 1

    b_chunk_count = await db_conn.fetchval(
        "SELECT COUNT(*) FROM knowledge_base WHERE version_id = $1::uuid", vid_b
    )
    assert b_chunk_count == 1


@pytest.mark.asyncio
async def test_purge_custom_keep_value(db_conn) -> None:
    """purge_old_versions respects the `keep` parameter."""
    doc_id = await _create_document(db_conn)
    for i in range(1, 7):  # 6 versions
        await _create_version(db_conn, doc_id, version_no=i, is_active=(i == 6))

    deleted = await purge_old_versions(db_conn, doc_id, keep=2)

    assert deleted == 4
    remaining = await db_conn.fetchval(
        "SELECT COUNT(*) FROM kb_document_versions WHERE document_id = $1::uuid", doc_id
    )
    assert remaining == 2


# ── upload_new_version endpoint integration ───────────────────────────────────


@pytest.mark.asyncio
async def test_upload_triggers_purge_via_endpoint(db_conn) -> None:
    """POST /knowledge/documents/{id}/upload auto-purges old versions after upload."""
    # Pre-insert a document with VERSION_RETENTION existing versions
    doc_id = await _create_document(db_conn, title="Auto Purge Doc")
    for i in range(1, VERSION_RETENTION + 1):
        is_last = i == VERSION_RETENTION
        vid = await _create_version(db_conn, doc_id, version_no=i, is_active=is_last)
        await db_conn.execute(
            "UPDATE kb_documents SET current_version_id = $1::uuid WHERE id = $2::uuid",
            vid,
            doc_id,
        )

    mock_llm = MagicMock()
    mock_llm.ainvoke = AsyncMock(return_value=MagicMock(content="chunk text"))

    dummy_pdf = b"%PDF-1.4 1 0 obj<</Type/Catalog>>endobj"

    async def _override():
        yield db_conn

    app.dependency_overrides[real_get_conn] = _override
    try:
        with patch(
            "app.routers.knowledge._parse_embed_store",
            new_callable=AsyncMock,
            return_value=5,  # simulate 5 chunks created
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    f"/knowledge/documents/{doc_id}/upload",
                    headers=_auth(),
                    files={"file": ("new.pdf", dummy_pdf, "application/pdf")},
                )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 201
    # After upload we should have at most VERSION_RETENTION versions
    count = await db_conn.fetchval(
        "SELECT COUNT(*) FROM kb_document_versions WHERE document_id = $1::uuid", doc_id
    )
    assert count <= VERSION_RETENTION
