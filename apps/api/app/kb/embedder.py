"""Embedding pipeline using Gemini gemini-embedding-001 (768 dimensions).

Matches the vector dimension defined in the DB migration (VECTOR(768)).

Free-tier rate limits for gemini-embedding-001:
  RPM : 100 requests / minute
  TPM : 30,000 tokens / minute

Strategy
--------
* Small batch size (EMBED_BATCH_SIZE = 5) to keep per-request token usage low.
* Minimum inter-batch gap of MIN_BATCH_INTERVAL seconds (≈ 0.65 s → ≤ 92 RPM).
* _TpmGuard tracks approximate token consumption in a sliding 60-second window
  and sleeps until the window resets when the TPM limit is approached.
* Token count is estimated as len(text) / CHARS_PER_TOKEN (conservative: 4
  chars/token for English; Japanese/CJK uses more tokens per char so the
  estimate may under-count slightly, hence a 20 % safety margin in the guard).
"""

from __future__ import annotations

import asyncio
import logging
import time

from google import genai
from google.genai import types as genai_types

from app.kb.parser import Chunk
from app.settings import settings

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = "gemini-embedding-001"

# ── Rate-limit parameters (tuned for free tier) ───────────────────────────────
EMBED_BATCH_SIZE = 3       # chunks per API call (smaller batch for CJK safety)
MIN_BATCH_INTERVAL = 1.0   # seconds between requests  → max 60 RPM  (limit 100)
TPM_LIMIT = 20_000         # conservative ceiling (actual 30 K, keeps headroom)
# Conservative estimate: 1 char ≈ 1 token for CJK-heavy documents.
CHARS_PER_TOKEN = 1


def _estimate_tokens(texts: list[str]) -> int:
    return max(1, sum(len(t) for t in texts) // CHARS_PER_TOKEN)


class _TpmGuard:
    """Sliding-window token-per-minute tracker.

    Sleeps until the current 60-second window resets when the budget would
    be exceeded. One instance is shared for the duration of a single upload.
    """

    def __init__(self, tpm_limit: int = TPM_LIMIT) -> None:
        self._limit = tpm_limit
        self._used = 0
        self._window_start = time.monotonic()

    async def acquire(self, tokens: int) -> None:
        now = time.monotonic()
        elapsed = now - self._window_start
        if elapsed >= 60.0:
            self._window_start = now
            self._used = 0

        if self._used + tokens > self._limit:
            remaining = 60.0 - (time.monotonic() - self._window_start) + 0.5
            if remaining > 0:
                logger.info(
                    "TPM budget (%d/%d) reached — sleeping %.1f s",
                    self._used,
                    self._limit,
                    remaining,
                )
                await asyncio.sleep(remaining)
            self._window_start = time.monotonic()
            self._used = 0

        self._used += tokens


def _get_client() -> genai.Client:
    return genai.Client(api_key=settings.gemini_api_key)


async def embed_chunks(chunks: list[Chunk]) -> list[list[float]]:
    """Return embedding vectors, one per chunk, respecting free-tier rate limits."""
    client = _get_client()
    vectors: list[list[float]] = []
    tpm_guard = _TpmGuard()

    for i in range(0, len(chunks), EMBED_BATCH_SIZE):
        batch = chunks[i : i + EMBED_BATCH_SIZE]
        texts = [c.content for c in batch]
        estimated_tokens = _estimate_tokens(texts)

        # ── TPM guard: sleep if budget would be exceeded ──────────────────
        await tpm_guard.acquire(estimated_tokens)

        logger.debug(
            "Embedding batch %d–%d (%d chunks, ~%d tokens)",
            i,
            i + len(batch) - 1,
            len(batch),
            estimated_tokens,
        )

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

        # ── RPM guard: enforce minimum inter-batch gap ────────────────────
        if i + EMBED_BATCH_SIZE < len(chunks):
            await asyncio.sleep(MIN_BATCH_INTERVAL)

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
