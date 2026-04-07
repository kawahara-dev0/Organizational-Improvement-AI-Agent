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

    # Build optional WHERE clauses
    conditions: list[str] = []
    params: list = [vector_str, top_k]

    if source_file is not None:
        params.append(source_file)
        conditions.append(f"metadata->>'source_file' = ${len(params)}")

    if category is not None:
        params.append(category)
        conditions.append(f"metadata->>'category' = ${len(params)}")

    where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    sql = f"""
        SELECT
            id,
            content,
            metadata,
            1 - (embedding <=> $1::vector) AS similarity
        FROM knowledge_base
        {where_clause}
        ORDER BY embedding <=> $1::vector
        LIMIT $2
    """

    # Increase probes so the ivfflat index scans enough clusters.
    # This is a session-level hint and does not affect other queries.
    await conn.execute("SET ivfflat.probes = 10")

    rows = await conn.fetch(sql, *params)
    results = []
    for row in rows:
        results.append({
            "id": str(row["id"]),
            "content": row["content"],
            "metadata": json.loads(row["metadata"]) if row["metadata"] else {},
            "similarity": float(row["similarity"]),
        })

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
        source = meta.get("source_file", "unknown")
        page = meta.get("page_number", "?")
        parts.append(f"[{i}] (source: {source}, page: {page})\n{chunk['content']}")
    return "\n\n".join(parts)
