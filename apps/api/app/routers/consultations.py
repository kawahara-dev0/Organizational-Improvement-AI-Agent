"""Consultation session endpoints (UC-1 core).

Endpoints:
    POST   /consultations              — create a new session
    GET    /consultations/{id}         — retrieve session details
    POST   /consultations/{id}/chat    — send a chat message, get dual-perspective reply
    POST   /consultations/{id}/feedback — record like/dislike

Free-tier API usage controls (configurable via .env):
    RAG_ENABLED=false              — skip vector search (saves 1 embed call/turn)
    METADATA_EXTRACTION_INTERVAL=3 — run metadata extraction every N assistant turns
                                     (0 = disabled entirely)
"""

from __future__ import annotations

import json
import logging

from asyncpg import Connection
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.ai.enums import RouterTask
from app.ai.prompts import ResponseMode, build_metadata_extraction_messages, build_rag_system_prompt
from app.ai.router import invoke_chat, invoke_rag
from app.ai.schemas import ChatMessage, InvokeRequest, RouterContext
from app.consultations.repository import (
    append_message,
    create_consultation,
    get_consultation,
    update_feedback,
    update_metadata,
)
from app.db.session import get_conn
from app.kb.retriever import format_context, retrieve
from app.settings import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/consultations", tags=["consultations"])

# 429 error class from langchain_google_genai (imported lazily to avoid hard dep)
_QUOTA_ERROR_NAMES = {"ChatGoogleGenerativeAIError", "RateLimitError"}


def _is_quota_error(exc: Exception) -> bool:
    """Return True when the exception looks like a 429 / quota-exceeded error."""
    name = type(exc).__name__
    msg = str(exc)
    return name in _QUOTA_ERROR_NAMES or "429" in msg or "RESOURCE_EXHAUSTED" in msg


# ── Request / Response schemas ────────────────────────────────────────────────

class ChatRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=4000)
    mode: ResponseMode = "personal"


class ChatResponse(BaseModel):
    consultation_id: str
    reply: str
    provider_used: str
    mode: ResponseMode


class FeedbackRequest(BaseModel):
    value: int = Field(..., ge=-1, le=1, description="-1=dislike, 0=neutral, 1=like")


class FeedbackResponse(BaseModel):
    consultation_id: str
    feedback: int


class CreateResponse(BaseModel):
    consultation_id: str


# ── Helpers ───────────────────────────────────────────────────────────────────

def _messages_to_lc(messages: list[dict]) -> list[ChatMessage]:
    """Convert stored message dicts to ChatMessage objects."""
    return [ChatMessage(role=m["role"], content=m["content"]) for m in messages]


def _should_extract_metadata(messages: list[dict]) -> bool:
    """Return True on the 1st assistant turn, then every N turns thereafter.

    Trigger pattern (interval=3): 1, 4, 7, 10, ...
    Formula: (assistant_count - 1) % interval == 0
    """
    interval = settings.metadata_extraction_interval
    if interval <= 0:
        return False
    assistant_count = sum(1 for m in messages if m["role"] == "assistant")
    return assistant_count > 0 and (assistant_count - 1) % interval == 0


async def _extract_and_persist_metadata(
    conn: Connection,
    consultation_id: str,
    messages: list[dict],
) -> None:
    """Call Gemini to extract department/category/severity and persist them.

    Failures are silently swallowed — metadata extraction is best-effort and
    must never block the main chat response.
    """
    conversation_text = "\n".join(
        f"{m['role'].capitalize()}: {m['content']}" for m in messages
    )
    system_prompt, user_message = build_metadata_extraction_messages(conversation_text)

    try:
        req = InvokeRequest(
            messages=[ChatMessage(role="user", content=user_message)],
            context=RouterContext(task=RouterTask.CHAT, severity=0),
            system_prompt=system_prompt,
        )
        result = await invoke_chat(req)
        raw = result.content.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        extracted = json.loads(raw)
        await update_metadata(
            conn,
            consultation_id,
            department=extracted.get("department"),
            category=extracted.get("category"),
            severity=int(extracted.get("severity", 0)),
        )
        logger.info(
            "metadata extracted consultation_id=%s department=%s category=%s severity=%s",
            consultation_id,
            extracted.get("department"),
            extracted.get("category"),
            extracted.get("severity"),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "metadata extraction failed consultation_id=%s error=%s",
            consultation_id,
            exc,
        )


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("", response_model=CreateResponse, status_code=201)
async def create_session(
    conn: Connection = Depends(get_conn),
) -> CreateResponse:
    """Create a new consultation session and return its ID."""
    consultation_id = await create_consultation(conn)
    return CreateResponse(consultation_id=consultation_id)


@router.get("/{consultation_id}")
async def get_session(
    consultation_id: str,
    conn: Connection = Depends(get_conn),
) -> dict:
    """Retrieve full consultation details including message history."""
    session = await get_consultation(conn, consultation_id)
    if not session:
        raise HTTPException(status_code=404, detail="Consultation not found")
    return session


@router.post("/{consultation_id}/chat", response_model=ChatResponse)
async def chat(
    consultation_id: str,
    body: ChatRequest,
    conn: Connection = Depends(get_conn),
) -> ChatResponse:
    """Process a chat turn.

    API call budget per turn (free-tier optimised):
        - embed_query (RAG)     : 1 call  — skipped when RAG_ENABLED=false
        - invoke_rag            : 1 call  — always required (main response)
        - metadata extraction   : 1 call  — only every METADATA_EXTRACTION_INTERVAL turns
    """
    session = await get_consultation(conn, consultation_id)
    if not session:
        raise HTTPException(status_code=404, detail="Consultation not found")

    # 1. Persist user message
    await append_message(conn, consultation_id, "user", body.content)

    # 2. RAG retrieval (optional — skip to save 1 embed call/turn)
    context_text = ""
    if settings.rag_enabled:
        try:
            retrieved = await retrieve(conn, query=body.content, top_k=5)
            context_text = format_context(retrieved)
        except Exception as exc:  # noqa: BLE001
            if _is_quota_error(exc):
                logger.warning("RAG embed quota exceeded — proceeding without context")
            else:
                logger.warning("RAG retrieval failed — proceeding without context: %s", exc)

    # 3. Build LLM request with history + RAG context
    existing_messages = _messages_to_lc(session["messages"])
    existing_messages.append(ChatMessage(role="user", content=body.content))

    system_prompt = build_rag_system_prompt(context_text, mode=body.mode)
    severity = session.get("severity") or 0

    req = InvokeRequest(
        messages=existing_messages,
        context=RouterContext(task=RouterTask.RAG, severity=severity),
        system_prompt=system_prompt,
    )

    try:
        response = await invoke_rag(req)
    except Exception as exc:
        if _is_quota_error(exc):
            logger.warning("LLM quota exceeded consultation_id=%s", consultation_id)
            raise HTTPException(
                status_code=503,
                detail=(
                    "AI サービスのリクエスト上限に達しました。"
                    "しばらく待ってから再送信してください。"
                ),
            ) from exc
        raise

    # 4. Persist assistant reply
    await append_message(conn, consultation_id, "assistant", response.content)

    # 5. Metadata extraction — only every N assistant turns (best-effort, non-blocking)
    updated_session = await get_consultation(conn, consultation_id)
    if updated_session and _should_extract_metadata(updated_session["messages"]):
        await _extract_and_persist_metadata(
            conn, consultation_id, updated_session["messages"]
        )

    return ChatResponse(
        consultation_id=consultation_id,
        reply=response.content,
        provider_used=response.provider_used.value,
        mode=body.mode,
    )


@router.post("/{consultation_id}/feedback", response_model=FeedbackResponse)
async def feedback(
    consultation_id: str,
    body: FeedbackRequest,
    conn: Connection = Depends(get_conn),
) -> FeedbackResponse:
    """Record a like (1), neutral (0), or dislike (-1) for a consultation."""
    session = await get_consultation(conn, consultation_id)
    if not session:
        raise HTTPException(status_code=404, detail="Consultation not found")

    updated = await update_feedback(conn, consultation_id, body.value)
    if not updated:
        raise HTTPException(status_code=500, detail="Failed to update feedback")

    return FeedbackResponse(consultation_id=consultation_id, feedback=body.value)
