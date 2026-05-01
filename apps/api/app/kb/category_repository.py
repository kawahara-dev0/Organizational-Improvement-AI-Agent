"""CRUD for kb_category_vectors — per-document-version category embeddings."""

from __future__ import annotations

from asyncpg import Connection

from app.kb.parser import UNCATEGORIZED_CATEGORY

# Categories that should not participate in similarity-based selection.
_SKIP_CATEGORIES = {UNCATEGORIZED_CATEGORY}


async def upsert_category_vectors(
    conn: Connection,
    document_id: str,
    version_id: str,
    categories: list[str],
    vectors: list[list[float]],
) -> None:
    """Insert or replace category embedding rows for a document version.

    ``Uncategorized`` is excluded — it has no meaningful semantic content
    to compare against query vectors.
    """
    for category, vector in zip(categories, vectors, strict=True):
        if category in _SKIP_CATEGORIES:
            continue
        vector_str = "[" + ",".join(str(v) for v in vector) + "]"
        await conn.execute(
            """
            INSERT INTO kb_category_vectors
                (document_id, version_id, category, embedding)
            VALUES ($1::uuid, $2::uuid, $3, $4::vector)
            ON CONFLICT (version_id, category)
            DO UPDATE SET embedding = EXCLUDED.embedding
            """,
            document_id,
            version_id,
            category,
            vector_str,
        )


async def find_similar_categories(
    conn: Connection,
    query_vector: list[float],
    top_n: int = 3,
) -> list[str]:
    """Return up to *top_n* category names from active versions ordered by
    cosine similarity to *query_vector*.

    Only categories from currently-active document versions are considered.
    """
    vector_str = "[" + ",".join(str(v) for v in query_vector) + "]"
    rows = await conn.fetch(
        """
        SELECT DISTINCT ON (kc.category) kc.category,
               1 - (kc.embedding <=> $1::vector) AS similarity
        FROM   kb_category_vectors kc
        JOIN   kb_document_versions v ON v.id = kc.version_id
        WHERE  v.is_active = TRUE
        ORDER  BY kc.category, kc.embedding <=> $1::vector
        LIMIT  $2
        """,
        vector_str,
        top_n,
    )
    # Re-sort the distinct rows by similarity descending (DISTINCT ON reorders)
    sorted_rows = sorted(rows, key=lambda r: r["similarity"], reverse=True)
    return [r["category"] for r in sorted_rows]
