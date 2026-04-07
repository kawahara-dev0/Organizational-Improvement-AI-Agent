"""Integration tests for the RAG retrieval service.

Requires a running PostgreSQL container with the schema applied.
Run with:
    docker compose run --rm api pytest tests/test_rag.py -v

Test strategy:
- Insert fixture chunks with known hand-crafted 768-dim vectors directly into DB
  (bypassing the embedder to avoid real API calls and rate limits).
- Mock embed_query() to return a known vector.
- Assert that the closest chunk is ranked first.
- Assert metadata filters work correctly.
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.ai.prompts import (
    build_metadata_extraction_messages,
    build_proposal_messages,
    build_rag_system_prompt,
)
from app.kb.retriever import format_context, retrieve

DIMS = 768

# Unique prefix so test-inserted data never collides with pre-existing DB rows
_TEST_SRC = f"_test_{uuid.uuid4().hex[:8]}"


def _unit_vector(hot_dims: range) -> list[float]:
    """Return a normalised 768-dim vector with 1.0 at the specified dim indices."""
    v = [0.0] * DIMS
    for d in hot_dims:
        v[d] = 1.0
    norm = sum(x ** 2 for x in v) ** 0.5
    return [x / norm for x in v]


# Fixture chunk A: "hot" in dims 0-99   → queries in that region should prefer it
VECTOR_A = _unit_vector(range(100))
# Fixture chunk B: "hot" in dims 100-199
VECTOR_B = _unit_vector(range(100, 200))
# Query vector identical to A → should rank A > B
QUERY_LIKE_A = VECTOR_A[:]


async def _insert_chunk(
    conn,
    content: str,
    vector: list[float],
    metadata: dict,
) -> str:
    """Insert a single chunk row directly with a pre-computed vector."""
    row_id = str(uuid.uuid4())
    vector_str = "[" + ",".join(str(v) for v in vector) + "]"
    await conn.execute(
        """
        INSERT INTO knowledge_base (id, content, embedding, metadata)
        VALUES ($1, $2, $3::vector, $4::jsonb)
        """,
        row_id,
        content,
        vector_str,
        json.dumps(metadata),
    )
    return row_id


# ── Basic retrieval ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_retrieve_returns_closest_first(db_conn) -> None:
    """Chunk A should rank before chunk B when the query vector equals A."""
    src = f"{_TEST_SRC}_closest"
    id_a = await _insert_chunk(
        db_conn,
        content="Content about vacation policy.",
        vector=VECTOR_A,
        metadata={"source_file": src, "page_number": 1},
    )
    id_b = await _insert_chunk(
        db_conn,
        content="Content about salary review process.",
        vector=VECTOR_B,
        metadata={"source_file": src, "page_number": 2},
    )

    with patch("app.kb.retriever.embed_query", new=AsyncMock(return_value=QUERY_LIKE_A)):
        results = await retrieve(db_conn, query="vacation days", top_k=2, source_file=src)

    assert len(results) == 2
    assert results[0]["id"] == id_a, "Closest chunk (A) should be ranked first"
    assert results[1]["id"] == id_b
    assert results[0]["similarity"] > results[1]["similarity"]


@pytest.mark.asyncio
async def test_retrieve_top_k_limits_results(db_conn) -> None:
    """top_k should limit the number of returned results."""
    src = f"{_TEST_SRC}_topk"
    for i in range(5):
        await _insert_chunk(
            db_conn,
            content=f"Chunk {i}",
            vector=VECTOR_A,
            metadata={"source_file": src, "page_number": i},
        )

    with patch("app.kb.retriever.embed_query", new=AsyncMock(return_value=QUERY_LIKE_A)):
        results = await retrieve(db_conn, query="any", top_k=3, source_file=src)

    assert len(results) == 3


@pytest.mark.asyncio
async def test_retrieve_empty_db_returns_empty_list(db_conn) -> None:
    """retrieve() on an empty table should return an empty list, not raise."""
    with patch("app.kb.retriever.embed_query", new=AsyncMock(return_value=QUERY_LIKE_A)):
        results = await retrieve(db_conn, query="anything", top_k=5)

    assert results == []


# ── Metadata filters ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_retrieve_filter_by_source_file(db_conn) -> None:
    """source_file filter should exclude chunks from other documents."""
    src_alpha = f"{_TEST_SRC}_alpha"
    src_beta = f"{_TEST_SRC}_beta"
    await _insert_chunk(db_conn, "From doc-alpha", VECTOR_A, {"source_file": src_alpha})
    await _insert_chunk(db_conn, "From doc-beta", VECTOR_A, {"source_file": src_beta})

    with patch("app.kb.retriever.embed_query", new=AsyncMock(return_value=QUERY_LIKE_A)):
        results = await retrieve(db_conn, query="test", source_file=src_alpha)

    assert len(results) == 1
    assert results[0]["metadata"]["source_file"] == src_alpha


@pytest.mark.asyncio
async def test_retrieve_filter_by_category(db_conn) -> None:
    """category filter should exclude chunks with a different category."""
    src = f"{_TEST_SRC}_cat"
    await _insert_chunk(
        db_conn, "Policy text", VECTOR_A, {"source_file": src, "category": "policy"}
    )
    await _insert_chunk(
        db_conn, "Salary text", VECTOR_A, {"source_file": src, "category": "salary"}
    )

    with patch("app.kb.retriever.embed_query", new=AsyncMock(return_value=QUERY_LIKE_A)):
        # Filter by both source_file and category to isolate test data
        results = await retrieve(db_conn, query="rules", source_file=src, category="policy")

    assert len(results) == 1
    assert results[0]["metadata"]["category"] == "policy"


@pytest.mark.asyncio
async def test_retrieve_result_structure(db_conn) -> None:
    """Each result dict must contain the expected keys with correct types."""
    src = f"{_TEST_SRC}_struct"
    await _insert_chunk(
        db_conn, "Sample content.", VECTOR_A, {"source_file": src, "page_number": 1}
    )

    with patch("app.kb.retriever.embed_query", new=AsyncMock(return_value=QUERY_LIKE_A)):
        results = await retrieve(db_conn, query="sample", top_k=1, source_file=src)

    assert len(results) == 1
    r = results[0]
    assert isinstance(r["id"], str)
    assert isinstance(r["content"], str)
    assert isinstance(r["metadata"], dict)
    assert isinstance(r["similarity"], float)
    assert 0.0 <= r["similarity"] <= 1.0


# ── format_context helper ──────────────────────────────────────────────────────

def test_format_context_produces_numbered_list() -> None:
    chunks = [
        {"content": "First chunk.", "metadata": {"source_file": "a.pdf", "page_number": 1}},
        {"content": "Second chunk.", "metadata": {"source_file": "b.pdf", "page_number": 3}},
    ]
    result = format_context(chunks)
    assert "[1]" in result
    assert "[2]" in result
    assert "First chunk." in result
    assert "Second chunk." in result
    assert "source: a.pdf" in result


def test_format_context_empty_list() -> None:
    assert format_context([]) == ""


# ── Prompt builders ────────────────────────────────────────────────────────────

def test_build_rag_system_prompt_injects_context() -> None:
    prompt = build_rag_system_prompt("Some HR context here.")
    assert "Some HR context here." in prompt
    assert "Personal Advice" in prompt
    assert "Structural Perspective" in prompt


def test_build_rag_system_prompt_no_context() -> None:
    prompt = build_rag_system_prompt("")
    assert "No relevant context found" in prompt


def test_build_metadata_extraction_messages() -> None:
    system, user = build_metadata_extraction_messages("Employee: I am underpaid.")
    assert "JSON" in system
    assert "severity" in system
    assert "underpaid" in user


def test_build_proposal_messages() -> None:
    system, user = build_proposal_messages(
        transcript="Employee: My manager ignores my suggestions.",
        context="Company policy doc text.",
    )
    assert "Executive Summary" in system
    assert "anonymi" in system.lower()
    assert "manager ignores" in user
    assert "Company policy" in user
