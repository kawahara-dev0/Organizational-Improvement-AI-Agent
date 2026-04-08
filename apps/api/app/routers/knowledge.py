"""Admin-only knowledge base API routes.

Endpoints:
  POST   /knowledge/upload         — parse, embed, upsert a document
  GET    /knowledge/chunks          — list chunks (filterable by source_file)
  GET    /knowledge/chunks/{id}     — get a single chunk
  PUT    /knowledge/chunks/{id}     — update chunk content (re-embeds)
  DELETE /knowledge/chunks/{id}     — delete a single chunk
  DELETE /knowledge/source          — delete all chunks for a source file
"""

from __future__ import annotations

import logging

from asyncpg import Connection
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel

from app.db.session import get_conn
from app.kb import embedder, parser, repository

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/knowledge", tags=["knowledge"])

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


# ── Upload ────────────────────────────────────────────────────────────────────


class UploadResponse(BaseModel):
    source_file: str
    chunks_created: int
    chunk_ids: list[str]


@router.post("/upload", response_model=UploadResponse)
async def upload_document(
    file: UploadFile = File(...),
    category: str = Form(default=""),
    conn: Connection = Depends(get_conn),
) -> UploadResponse:
    """Parse a document, embed its chunks, and upsert into knowledge_base."""
    _check_extension(file.filename or "")

    data = await file.read()
    if len(data) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="File too large (max 20 MB)")

    filename = file.filename or "unknown"

    pages = parser.parse(data, filename)
    if not pages:
        raise HTTPException(status_code=422, detail="No text content found in file")

    chunks = parser.chunk_pages(pages, source_file=filename, category=category)
    vectors = await embedder.embed_chunks(chunks)
    ids = await repository.upsert_chunks(conn, chunks, vectors)

    logger.info("Uploaded %s → %d chunks", filename, len(ids))
    return UploadResponse(source_file=filename, chunks_created=len(ids), chunk_ids=ids)


# ── List / Get ────────────────────────────────────────────────────────────────


@router.get("/chunks")
async def list_chunks(
    source_file: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    conn: Connection = Depends(get_conn),
) -> list[dict]:
    return await repository.list_chunks(conn, source_file=source_file, limit=limit, offset=offset)


@router.get("/chunks/{chunk_id}")
async def get_chunk(
    chunk_id: str,
    conn: Connection = Depends(get_conn),
) -> dict:
    chunk = await repository.get_chunk(conn, chunk_id)
    if not chunk:
        raise HTTPException(status_code=404, detail="Chunk not found")
    return chunk


# ── Update ────────────────────────────────────────────────────────────────────


class UpdateChunkRequest(BaseModel):
    content: str


@router.put("/chunks/{chunk_id}")
async def update_chunk(
    chunk_id: str,
    body: UpdateChunkRequest,
    conn: Connection = Depends(get_conn),
) -> dict:
    """Update chunk content and re-embed."""
    dummy_chunk = parser.Chunk(content=body.content)
    vectors = await embedder.embed_chunks([dummy_chunk])
    updated = await repository.update_chunk_content(conn, chunk_id, body.content, vectors[0])
    if not updated:
        raise HTTPException(status_code=404, detail="Chunk not found")
    return {"id": chunk_id, "content": body.content, "updated": True}


# ── Delete ────────────────────────────────────────────────────────────────────


@router.delete("/chunks/{chunk_id}")
async def delete_chunk(
    chunk_id: str,
    conn: Connection = Depends(get_conn),
) -> dict:
    deleted = await repository.delete_chunk(conn, chunk_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Chunk not found")
    return {"id": chunk_id, "deleted": True}


class DeleteSourceRequest(BaseModel):
    source_file: str


@router.delete("/source")
async def delete_source(
    body: DeleteSourceRequest,
    conn: Connection = Depends(get_conn),
) -> dict:
    """Delete all chunks for a given source file."""
    count = await repository.delete_by_source(conn, body.source_file)
    return {"source_file": body.source_file, "deleted_chunks": count}
