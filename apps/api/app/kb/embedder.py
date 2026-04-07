"""Embedding pipeline using Gemini gemini-embedding-001 (768 dimensions).

Matches the vector dimension defined in the DB migration (VECTOR(768)).
Batches are capped to avoid API rate limits.
"""

from __future__ import annotations

import asyncio
import logging

from google import genai
from google.genai import types as genai_types

from app.kb.parser import Chunk
from app.settings import settings

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = "gemini-embedding-001"
EMBED_BATCH_SIZE = 20  # chunks per API call


def _get_client() -> genai.Client:
    return genai.Client(api_key=settings.gemini_api_key)


async def embed_chunks(chunks: list[Chunk]) -> list[list[float]]:
    """Return a list of embedding vectors, one per chunk (same order)."""
    client = _get_client()
    vectors: list[list[float]] = []

    for i in range(0, len(chunks), EMBED_BATCH_SIZE):
        batch = chunks[i : i + EMBED_BATCH_SIZE]
        texts = [c.content for c in batch]
        logger.debug("Embedding batch %d-%d (%d texts)", i, i + len(batch), len(texts))

        response = await asyncio.to_thread(
            client.models.embed_content,
            model=EMBEDDING_MODEL,
            contents=texts,
            config=genai_types.EmbedContentConfig(
                task_type="RETRIEVAL_DOCUMENT",
                # Must match DB column VECTOR(768); API default can be up to 3072.
                output_dimensionality=768,
            ),
        )
        for emb in response.embeddings:
            vectors.append(emb.values)

    return vectors


async def embed_query(text: str) -> list[float]:
    """Embed a single query string for similarity search."""
    client = _get_client()
    response = await asyncio.to_thread(
        client.models.embed_content,
        model=EMBEDDING_MODEL,
        contents=[text],
        config=genai_types.EmbedContentConfig(
            task_type="RETRIEVAL_QUERY",
            output_dimensionality=768,
        ),
    )
    return response.embeddings[0].values
