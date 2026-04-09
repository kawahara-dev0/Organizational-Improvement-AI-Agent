"""RAG retrieval — vector similarity search over knowledge_base.

Usage:
    chunks = await retrieve(conn, query="...", top_k=5)

Metadata filters (all optional):
    source_file  — limit to a specific uploaded document
    category     — limit to a category (e.g. "policy")
"""

from __future__ import annotations

import json
import logging

from asyncpg import Connection

from app.kb.embedder import embed_query

logger = logging.getLogger(__name__)


async def retrieve(
    conn: Connection,
    query: str,
    top_k: int = 5,
    source_file: str | None = None,
    category: str | None = None,
) -> list[dict]:
    """Return the top-k most similar chunks for the given query.

    Each result dict contains:
        id, content, metadata (parsed JSONB), similarity (0-1 cosine)
    """
    vector = await embed_query(query)
    vector_str = "[" + ",".join(str(v) for v in vector) + "]"

    # Build WHERE clauses.
    # Only return chunks from active document versions.
    # Chunks with version_id IS NULL (uploaded before the document management
    # system was introduced) are intentionally excluded — they should be
    # re-uploaded through the Knowledge Base admin UI.
    conditions: list[str] = ["v.is_active = TRUE"]
    params: list = [vector_str, top_k]

    if source_file is not None:
        params.append(source_file)
        conditions.append(f"kb.metadata->>'source_file' = ${len(params)}")

    if category is not None:
        params.append(category)
        conditions.append(f"kb.metadata->>'category' = ${len(params)}")

    where_clause = "WHERE " + " AND ".join(conditions)

    sql = f"""
        SELECT
            kb.id,
            kb.content,
            kb.metadata,
            1 - (kb.embedding <=> $1::vector) AS similarity,
            d.title AS document_title
        FROM knowledge_base kb
        LEFT JOIN kb_document_versions v ON v.id = kb.version_id
        LEFT JOIN kb_documents d ON d.id = v.document_id
        {where_clause}
        ORDER BY kb.embedding <=> $1::vector
        LIMIT $2
    """

    # Increase probes so the ivfflat index scans enough clusters.
    # This is a session-level hint and does not affect other queries.
    await conn.execute("SET ivfflat.probes = 10")

    rows = await conn.fetch(sql, *params)
    results = []
    for row in rows:
        results.append(
            {
                "id": str(row["id"]),
                "content": row["content"],
                "metadata": json.loads(row["metadata"]) if row["metadata"] else {},
                "similarity": float(row["similarity"]),
                "document_title": row["document_title"],
            }
        )

    logger.debug(
        "RAG retrieve query=%r top_k=%d filters={source_file=%r, category=%r} → %d results",
        query[:60],
        top_k,
        source_file,
        category,
        len(results),
    )
    return results


def format_context(chunks: list[dict]) -> str:
    """Concatenate retrieved chunks into a single context string for the LLM prompt."""
    parts = []
    for i, chunk in enumerate(chunks, start=1):
        meta = chunk.get("metadata", {})
        title = chunk.get("document_title") or meta.get("source_file", "unknown")
        page = meta.get("page_number", "?")
        parts.append(f"[{i}] (source: {title}, page: {page})\n{chunk['content']}")
    return "\n\n".join(parts)


def build_sources(chunks: list[dict]) -> list[dict]:
    """Return document-grouped source references for the UI footnotes.

    Chunks are already ordered by similarity (highest first from SQL).
    Within each document group the first-seen chunk becomes the primary
    reference (highest relevance); remaining pages are supplementary.

    Each item:
        {
            "index": N,
            "title": str,
            "primary_page": int | None,
            "supplementary_pages": [int, ...]   # sorted ascending
        }
    """
    # Ordered dict: title → {primary_page, all_pages}
    groups: dict[str, dict] = {}
    for chunk in chunks:
        meta = chunk.get("metadata", {})
        title = chunk.get("document_title") or meta.get("source_file", "unknown")
        page = meta.get("page_number")
        if title not in groups:
            groups[title] = {"primary_page": page, "all_pages": set()}
        if page is not None:
            groups[title]["all_pages"].add(page)

    sources: list[dict] = []
    for i, (title, info) in enumerate(groups.items(), start=1):
        primary = info["primary_page"]
        supp = sorted(p for p in info["all_pages"] if p != primary)
        sources.append(
            {
                "index": i,
                "title": title,
                "primary_page": primary,
                "supplementary_pages": supp,
            }
        )
    return sources
