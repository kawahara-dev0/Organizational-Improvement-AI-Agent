"""RAG retrieval — vector similarity search over knowledge_base.

Usage:
    chunks = await retrieve_hybrid(conn, query="...", top_k=5)

``retrieve_hybrid`` is the recommended entry point.  It:
  1. Embeds the query once.
  2. Finds the top-N most similar category names via ``kb_category_vectors``.
  3. Runs a small chunk search for each shortlisted category.
  4. Runs a small unfiltered fallback search to guard against category
     mis-selection.
  5. Deduplicates and re-ranks all candidates by cosine similarity, returning
     the final ``top_k`` results.

The lower-level ``retrieve`` function (single embedding, optional filters) is
kept for backward-compatibility and testing.
"""

from __future__ import annotations

import json
import logging

from asyncpg import Connection

from app.kb.embedder import embed_query

logger = logging.getLogger(__name__)

# ── Hybrid search tuning constants ────────────────────────────────────────────
HYBRID_TOP_N_CATEGORIES = 2  # how many category buckets to search
HYBRID_TOP_K_PER_CATEGORY = 2  # chunks retrieved per category
HYBRID_TOP_K_FALLBACK = 1  # chunks from unfiltered fallback
HYBRID_MIN_SIMILARITY = 0.45  # drop weak matches before they reach the prompt


# ── Internal helpers ──────────────────────────────────────────────────────────


async def _retrieve_by_vector(
    conn: Connection,
    vector: list[float],
    top_k: int,
    source_file: str | None = None,
    category: str | None = None,
) -> list[dict]:
    """Run a chunk similarity search with a pre-computed query vector.

    Avoids re-embedding when the same vector is used for multiple searches
    (e.g. in hybrid retrieval).
    """
    vector_str = "[" + ",".join(str(v) for v in vector) + "]"

    # Only return chunks from active document versions.
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

    await conn.execute("SET ivfflat.probes = 10")
    rows = await conn.fetch(sql, *params)
    return [
        {
            "id": str(row["id"]),
            "content": row["content"],
            "metadata": json.loads(row["metadata"]) if row["metadata"] else {},
            "similarity": float(row["similarity"]),
            "document_title": row["document_title"],
        }
        for row in rows
        if float(row["similarity"]) >= HYBRID_MIN_SIMILARITY
    ]


# ── Public API ─────────────────────────────────────────────────────────────────


async def retrieve(
    conn: Connection,
    query: str,
    top_k: int = 5,
    source_file: str | None = None,
    category: str | None = None,
) -> list[dict]:
    """Return the top-k most similar chunks for the given query.

    Simple single-pass search (embeds query, optional metadata filters).
    Prefer ``retrieve_hybrid`` for better precision in production.

    Each result dict contains:
        id, content, metadata (parsed JSONB), similarity (0-1 cosine),
        document_title
    """
    vector = await embed_query(query)
    results = await _retrieve_by_vector(
        conn, vector, top_k, source_file=source_file, category=category
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


async def retrieve_hybrid(
    conn: Connection,
    query: str,
    top_k: int = 4,
    source_file: str | None = None,
) -> list[dict]:
    """Hybrid RAG retrieval combining category-filtered and unfiltered searches.

    Algorithm
    ---------
    1. Embed the query once.
    2. Find the top-N most similar category names from ``kb_category_vectors``
       (only active versions are considered).
    3. For each shortlisted category run a small chunk search
       (HYBRID_TOP_K_PER_CATEGORY results each).
    4. Run one unfiltered fallback search (HYBRID_TOP_K_FALLBACK results)
       to guard against category mis-selection.
    5. Deduplicate by chunk id, re-rank by cosine similarity, return top_k.
    """
    from app.kb.category_repository import find_similar_categories

    vector = await embed_query(query)

    # ── 2. Find top-N categories ──────────────────────────────────────────────
    categories = await find_similar_categories(conn, vector, top_n=HYBRID_TOP_N_CATEGORIES)
    logger.debug(
        "retrieve_hybrid: query=%r top_categories=%r",
        query[:60],
        categories,
    )

    # ── 3. Category-filtered searches ─────────────────────────────────────────
    all_chunks: list[dict] = []
    for cat in categories:
        chunks = await _retrieve_by_vector(
            conn,
            vector,
            top_k=HYBRID_TOP_K_PER_CATEGORY,
            source_file=source_file,
            category=cat,
        )
        all_chunks.extend(chunks)

    # ── 4. Unfiltered fallback ────────────────────────────────────────────────
    fallback = await _retrieve_by_vector(
        conn,
        vector,
        top_k=HYBRID_TOP_K_FALLBACK,
        source_file=source_file,
        category=None,
    )
    all_chunks.extend(fallback)

    # ── 5. Deduplicate + re-rank ──────────────────────────────────────────────
    seen: set[str] = set()
    unique: list[dict] = []
    for chunk in sorted(all_chunks, key=lambda c: c["similarity"], reverse=True):
        if chunk["id"] not in seen:
            seen.add(chunk["id"])
            unique.append(chunk)
        if len(unique) >= top_k:
            break

    logger.debug(
        "retrieve_hybrid query=%r top_k=%d categories=%r → %d results",
        query[:60],
        top_k,
        categories,
        len(unique),
    )
    return unique


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
