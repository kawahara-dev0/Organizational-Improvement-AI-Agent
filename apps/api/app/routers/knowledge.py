"""Admin-only knowledge base API routes (document-centric).

Documents are the primary management unit.  Chunks are derived data that
the admin can *view* but never edit directly — to change content, upload a
new version of the source file.

Endpoints:
  GET    /knowledge/documents              — list all documents
  POST   /knowledge/documents              — create document + upload first version
  GET    /knowledge/documents/{id}         — document detail (versions + chunks)
  PATCH  /knowledge/documents/{id}         — update title / category
  POST   /knowledge/documents/{id}/upload  — upload a new version
  DELETE /knowledge/documents/{id}         — delete document (cascades to chunks)
"""

from __future__ import annotations

import logging

from asyncpg import Connection
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from google.genai.errors import ClientError
from pydantic import BaseModel

from app.auth.deps import require_admin
from app.db.session import get_conn
from app.kb import doc_repository as doc_repo
from app.kb import embedder, parser
from app.kb import repository as chunk_repo

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/knowledge",
    tags=["knowledge"],
    dependencies=[Depends(require_admin)],
)

ALLOWED_EXTENSIONS = {"pdf", "docx", "xlsx", "xls"}
MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 MB


def _check_extension(filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type '.{ext}'. Allowed: {ALLOWED_EXTENSIONS}",
        )
    return ext


async def _parse_embed_store(
    file_data: bytes,
    filename: str,
    category: str,
    conn: Connection,
    document_id: str,
    version_id: str,
) -> int:
    """Parse → embed → store chunks. Returns chunk count."""
    pages = parser.parse(file_data, filename)
    if not pages:
        raise HTTPException(status_code=422, detail="No text content found in file.")

    chunks = parser.chunk_pages(pages, source_file=filename, category=category)
    vectors = await embedder.embed_chunks(chunks)
    ids = await chunk_repo.upsert_chunks(
        conn,
        chunks,
        vectors,
        document_id=document_id,
        version_id=version_id,
    )
    return len(ids)


# ── List ──────────────────────────────────────────────────────────────────────


@router.get("/documents")
async def list_documents(conn: Connection = Depends(get_conn)) -> list[dict]:
    """Return all documents with active version summary."""
    return await doc_repo.list_documents(conn)


# ── Create (document + first version) ────────────────────────────────────────


@router.post("/documents", status_code=201)
async def create_document(
    title: str = Form(...),
    category: str = Form(default=""),
    file: UploadFile = File(...),
    conn: Connection = Depends(get_conn),
) -> dict:
    """Create a new document and upload its first version."""
    _check_extension(file.filename or "")
    file_data = await file.read()
    if len(file_data) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="File too large (max 20 MB).")

    filename = file.filename or "unknown"

    document_id = await doc_repo.create_document(conn, title=title, category=category)
    version_id, version_no = await doc_repo.create_version(
        conn, document_id=document_id, source_file=filename
    )

    try:
        chunk_count = await _parse_embed_store(
            file_data, filename, category, conn, document_id, version_id
        )
    except ClientError as exc:
        # Roll back provisional document/version rows.
        await doc_repo.archive_document(conn, document_id)
        if exc.code == 429:
            raise HTTPException(
                status_code=503,
                detail=(
                    "Embedding quota limit reached. Please wait about 60 seconds "
                    "and try uploading again."
                ),
            ) from exc
        raise
    except Exception:
        await doc_repo.archive_document(conn, document_id)
        raise

    await doc_repo.finalize_version(conn, document_id, version_id, chunk_count)

    logger.info(
        "Created document %r (id=%s) v%d — %d chunks",
        title,
        document_id,
        version_no,
        chunk_count,
    )
    return {
        "document_id": document_id,
        "version_id": version_id,
        "version_no": version_no,
        "chunks_created": chunk_count,
    }


# ── Detail ────────────────────────────────────────────────────────────────────


@router.get("/documents/{document_id}")
async def get_document(
    document_id: str,
    conn: Connection = Depends(get_conn),
) -> dict:
    """Return document metadata, version history, and active-version chunks."""
    doc = await doc_repo.get_document(conn, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")

    # Attach chunks for the currently active version (view only)
    active_version_id = next(
        (v["id"] for v in doc.get("versions", []) if v["is_active"]),
        None,
    )
    chunks: list[dict] = []
    if active_version_id:
        chunks = await doc_repo.list_chunks_for_version(conn, active_version_id)

    return {**doc, "chunks": chunks}


# ── Update metadata ───────────────────────────────────────────────────────────


class DocumentUpdate(BaseModel):
    title: str
    category: str = ""


@router.patch("/documents/{document_id}")
async def update_document(
    document_id: str,
    body: DocumentUpdate,
    conn: Connection = Depends(get_conn),
) -> dict:
    """Update document title and/or category (does not affect chunks)."""
    updated = await doc_repo.update_document_meta(
        conn, document_id, title=body.title, category=body.category
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Document not found.")
    return {"document_id": document_id, "title": body.title, "category": body.category}


# ── Upload new version ────────────────────────────────────────────────────────


@router.post("/documents/{document_id}/upload", status_code=201)
async def upload_new_version(
    document_id: str,
    file: UploadFile = File(...),
    conn: Connection = Depends(get_conn),
) -> dict:
    """Upload a new version of an existing document.

    The new version becomes active immediately; previous version chunks are
    retained in DB but excluded from RAG retrieval (is_active = FALSE).
    """
    doc = await doc_repo.get_document(conn, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")

    _check_extension(file.filename or "")
    file_data = await file.read()
    if len(file_data) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="File too large (max 20 MB).")

    filename = file.filename or "unknown"
    category = doc.get("category", "")

    version_id, version_no = await doc_repo.create_version(
        conn, document_id=document_id, source_file=filename
    )

    try:
        chunk_count = await _parse_embed_store(
            file_data, filename, category, conn, document_id, version_id
        )
    except ClientError as exc:
        await doc_repo.delete_version(conn, version_id)
        if exc.code == 429:
            raise HTTPException(
                status_code=503,
                detail=(
                    "Embedding quota limit reached. Please wait about 60 seconds "
                    "and try uploading again."
                ),
            ) from exc
        raise
    except Exception:
        await doc_repo.delete_version(conn, version_id)
        raise

    await doc_repo.finalize_version(conn, document_id, version_id, chunk_count)

    purged = await doc_repo.purge_old_versions(conn, document_id)
    if purged:
        logger.info(
            "Purged %d old version(s) for document %s (keeping %d)",
            purged,
            document_id,
            doc_repo.VERSION_RETENTION,
        )

    logger.info("New version v%d for document %s — %d chunks", version_no, document_id, chunk_count)
    return {
        "document_id": document_id,
        "version_id": version_id,
        "version_no": version_no,
        "chunks_created": chunk_count,
    }


# ── Delete ────────────────────────────────────────────────────────────────────


@router.delete("/documents/{document_id}", status_code=204)
async def delete_document(
    document_id: str,
    conn: Connection = Depends(get_conn),
) -> None:
    """Delete a document and all its versions and chunks (irreversible)."""
    deleted = await doc_repo.archive_document(conn, document_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Document not found.")


# ── Orphan / legacy chunks ─────────────────────────────────────────────────


@router.get("/orphan-chunks")
async def get_orphan_chunks(conn: Connection = Depends(get_conn)) -> dict:
    """Return count of legacy chunks (version_id IS NULL) that are excluded from RAG.

    These were uploaded before the document management system was introduced.
    They are no longer used for retrieval and can be safely deleted.
    """
    row = await conn.fetchrow("SELECT COUNT(*) AS cnt FROM knowledge_base WHERE version_id IS NULL")
    return {"count": row["cnt"]}


@router.delete("/orphan-chunks", status_code=200)
async def delete_orphan_chunks(conn: Connection = Depends(get_conn)) -> dict:
    """Delete all legacy chunks (version_id IS NULL).

    These chunks are not used for RAG retrieval.  Deleting them frees storage
    and avoids confusion.  Re-upload the source documents through the
    Knowledge Base admin UI to restore their content.
    """
    result = await conn.execute("DELETE FROM knowledge_base WHERE version_id IS NULL")
    deleted = int(result.split()[-1])
    logger.info("Deleted %d orphan/legacy chunks", deleted)
    return {"deleted": deleted}
