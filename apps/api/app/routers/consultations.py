"""Consultation session endpoints (UC-1 & UC-2).

Endpoints:
    POST   /consultations              — create a new session
    GET    /consultations/{id}         — retrieve session details
    POST   /consultations/{id}/chat    — send a chat message, get dual-perspective reply
    POST   /consultations/{id}/draft   — generate proposal preview (no DB write)
    POST   /consultations/{id}/submit  — atomically persist the confirmed submission
    POST   /consultations/{id}/feedback — record like/dislike

Free-tier API usage controls (configurable via .env):
    RAG_ENABLED=false              — skip vector search (saves 1 embed call/turn)
    METADATA_EXTRACTION_INTERVAL=3 — run metadata extraction every N assistant turns
                                     (0 = disabled entirely)
"""

from __future__ import annotations

import json
import logging
import re
from typing import Literal

from asyncpg import Connection
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.ai.enums import RouterTask
from app.ai.prompts import (
    ResponseMode,
    build_metadata_extraction_messages,
    build_proposal_messages,
    build_rag_system_prompt,
)
from app.ai.router import generate_proposal, invoke_chat, invoke_rag
from app.ai.schemas import ChatMessage, InvokeRequest, RouterContext
from app.consultations.repository import (
    append_message,
    create_consultation,
    get_consultation,
    submit_consultation,
    update_feedback,
    update_metadata,
)
from app.db.session import get_conn
from app.kb.retriever import build_sources, format_context, retrieve
from app.settings import settings
from app.utils.pii import mask_pii

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/consultations", tags=["consultations"])

_limiter = Limiter(key_func=get_remote_address)

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


class SourceRef(BaseModel):
    index: int
    title: str
    primary_page: int | None = None
    supplementary_pages: list[int] = []


class ChatResponse(BaseModel):
    consultation_id: str
    reply: str
    provider_used: str
    mode: ResponseMode
    sources: list[SourceRef] = []


class FeedbackRequest(BaseModel):
    value: int = Field(..., ge=-1, le=1, description="-1=dislike, 0=neutral, 1=like")


class FeedbackResponse(BaseModel):
    consultation_id: str
    feedback: int


class CreateRequest(BaseModel):
    department: str | None = None


class CreateResponse(BaseModel):
    consultation_id: str


class UpdateDepartmentRequest(BaseModel):
    department: str | None = None


class SubmitRequest(BaseModel):
    user_name: str | None = Field(None, max_length=200)
    user_email: str | None = Field(None, max_length=200)
    summary: str = Field(..., description="Summary text from draft preview")
    proposal: str = Field(..., description="Proposal text from draft preview")


class DraftRequest(BaseModel):
    language: Literal["auto", "ja", "en"] = Field(
        default="auto",
        description='Proposal output language: "auto" matches transcript, "ja" or "en" forces.',
    )


class DraftResponse(BaseModel):
    summary: str
    proposal: str


class SubmitResponse(BaseModel):
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
    conversation_text = "\n".join(f"{m['role'].capitalize()}: {m['content']}" for m in messages)
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
    body: CreateRequest = CreateRequest(),
    conn: Connection = Depends(get_conn),
) -> CreateResponse:
    """Create a new consultation session and return its ID."""
    consultation_id = await create_consultation(conn, department=body.department)
    return CreateResponse(consultation_id=consultation_id)


@router.patch("/{consultation_id}/department", status_code=204)
async def update_department(
    consultation_id: str,
    body: UpdateDepartmentRequest,
    conn: Connection = Depends(get_conn),
) -> None:
    """Update the department field of an existing consultation."""
    session = await get_consultation(conn, consultation_id)
    if not session:
        raise HTTPException(status_code=404, detail="Consultation not found")
    await update_metadata(
        conn,
        consultation_id,
        department=body.department,
        category=session.get("category"),
        severity=session.get("severity") or 0,
    )


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
@_limiter.limit(lambda: settings.chat_rate_limit)
async def chat(
    request: Request,
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
    retrieved_chunks: list[dict] = []
    if settings.rag_enabled:
        try:
            retrieved_chunks = await retrieve(conn, query=body.content, top_k=5)
            context_text = format_context(retrieved_chunks)
        except Exception as exc:  # noqa: BLE001
            if _is_quota_error(exc):
                logger.warning("RAG embed quota exceeded — proceeding without context")
            else:
                logger.warning("RAG retrieval failed — proceeding without context: %s", exc)

    # 3. Build LLM request with history + RAG context.
    # PII is masked in the copy sent to the external LLM; the DB retains the
    # original text (which is encrypted at rest when MESSAGES_ENCRYPTION_KEY
    # is configured).
    def _masked(msg: dict) -> dict:
        return {**msg, "content": mask_pii(msg["content"])}

    existing_messages = _messages_to_lc([_masked(m) for m in session["messages"]])
    existing_messages.append(ChatMessage(role="user", content=mask_pii(body.content)))

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
                    "The AI service rate limit has been reached. "
                    "Please wait a moment and try again."
                ),
            ) from exc
        raise

    # 4. Persist assistant reply (with mode so UI can restore badges on reload)
    await append_message(conn, consultation_id, "assistant", response.content, mode=body.mode)

    # 5. Metadata extraction — only every N assistant turns (best-effort, non-blocking)
    updated_session = await get_consultation(conn, consultation_id)
    if updated_session and _should_extract_metadata(updated_session["messages"]):
        await _extract_and_persist_metadata(conn, consultation_id, updated_session["messages"])

    sources = [SourceRef(**s) for s in build_sources(retrieved_chunks)]

    return ChatResponse(
        consultation_id=consultation_id,
        reply=response.content,
        provider_used=response.provider_used.value,
        mode=body.mode,
        sources=sources,
    )


# Proposal draft: model may use ### headings or plain "Executive Summary" / etc. lines.
_SECTION_BOUNDARY = re.compile(
    r"(?m)^(?:#{1,4}\s+.+|Executive Summary\s*:?\s*|Root Cause Analysis\s*:?\s*"
    r"|Proposed Actions\s*:?\s*|Recommended Actions\s*:?\s*"
    r"|エグゼクティブサマリー\s*:?\s*|概要\s*:?\s*|原因分析\s*:?\s*|提案事項\s*:?\s*"
    r"|提案(?:される)?(?:行動|アクション)\s*:?\s*)\s*$",
    re.IGNORECASE,
)


def _norm_section_heading(heading: str) -> str:
    h = heading.strip()
    h = re.sub(r"^#+\s*", "", h).strip().lower()
    return h


def _is_executive_heading(norm: str) -> bool:
    return ("executive" in norm and "summary" in norm) or "エグゼクティブ" in norm or norm == "概要"


def _is_rca_heading(norm: str) -> bool:
    return ("root" in norm and "cause" in norm) or "原因分析" in norm


def _is_actions_heading(norm: str) -> bool:
    return (
        ("proposed" in norm and "action" in norm)
        or ("recommended" in norm and "action" in norm)
        or norm == "提案事項"
        or "推奨" in norm
        or ("提案" in norm and "行動" in norm)
    )


def _derive_summary_and_proposal(raw: str) -> tuple[str, str]:
    """Split model output into executive summary (short) and full proposal body (rest)."""
    text = raw.strip()
    if not text:
        return "", ""

    matches = list(_SECTION_BOUNDARY.finditer(text))
    if not matches:
        return text[:500].strip(), text

    sections: list[tuple[str, str]] = []
    if matches[0].start() > 0:
        pre = text[: matches[0].start()].strip()
        if pre:
            sections.append(("", pre))

    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        block = text[start:end].strip()
        first_nl = block.find("\n")
        if first_nl == -1:
            heading, body = block, ""
        else:
            heading, body = block[:first_nl].strip(), block[first_nl + 1 :].strip()
        sections.append((heading, body))

    exec_body = ""
    proposal_blocks: list[str] = []

    for heading, body in sections:
        if not heading.strip():
            if body and not exec_body:
                exec_body = body
            elif body:
                proposal_blocks.append(body)
            continue
        nh = _norm_section_heading(heading)
        if _is_executive_heading(nh):
            exec_body = body or exec_body
        elif _is_rca_heading(nh) or _is_actions_heading(nh) or nh:
            proposal_blocks.append(f"{heading}\n\n{body}".strip())

    summary = exec_body.strip() or text[:500].strip()
    proposal = "\n\n".join(b for b in proposal_blocks if b).strip()
    if not proposal:
        proposal = text
    return summary, proposal


async def _build_proposal_draft(
    conn: Connection,
    session: dict,
    *,
    language: Literal["auto", "ja", "en"] = "auto",
) -> tuple[str, str]:
    """Generate (summary, proposal) text from the consultation session.

    Does NOT write anything to the DB — caller decides whether to persist.
    """
    messages = session.get("messages") or []
    # Mask PII before sending the transcript to the external LLM.
    transcript = "\n".join(f"{m['role'].capitalize()}: {mask_pii(m['content'])}" for m in messages)

    context_text = ""
    if settings.rag_enabled:
        try:
            last_user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
            retrieved = await retrieve(conn, query=last_user, top_k=5)
            context_text = format_context(retrieved)
        except Exception as exc:  # noqa: BLE001
            logger.warning("RAG retrieval failed for proposal — proceeding: %s", exc)

    system_prompt, user_message = build_proposal_messages(
        transcript=transcript, context=context_text, language=language
    )
    req = InvokeRequest(
        messages=[ChatMessage(role="user", content=user_message)],
        context=RouterContext(
            task=RouterTask.PROPOSAL,
            severity=session.get("severity") or 0,
            is_submitted=True,
        ),
        system_prompt=system_prompt,
    )

    try:
        response = await generate_proposal(req)
    except Exception as exc:
        if _is_quota_error(exc):
            raise HTTPException(
                status_code=503,
                detail=(
                    "The AI service rate limit has been reached. "
                    "Please wait a moment and try again."
                ),
            ) from exc
        raise

    raw = response.content.strip()
    summary, proposal = _derive_summary_and_proposal(raw)
    return summary, proposal


@router.post("/{consultation_id}/draft", response_model=DraftResponse)
async def draft_proposal(
    consultation_id: str,
    body: DraftRequest | None = None,
    conn: Connection = Depends(get_conn),
) -> DraftResponse:
    """Generate a proposal preview for user review.

    Does NOT write to the DB. The user reviews the draft and then calls
    POST /{id}/submit to confirm and persist.
    """
    session = await get_consultation(conn, consultation_id)
    if not session:
        raise HTTPException(status_code=404, detail="Consultation not found")
    if session.get("is_submitted"):
        raise HTTPException(status_code=409, detail="Already submitted")
    if not session.get("messages"):
        raise HTTPException(status_code=422, detail="No conversation to submit")

    lang: Literal["auto", "ja", "en"] = body.language if body else "auto"
    summary, proposal = await _build_proposal_draft(conn, session, language=lang)
    return DraftResponse(summary=summary, proposal=proposal)


@router.post("/{consultation_id}/submit", response_model=SubmitResponse)
async def submit(
    consultation_id: str,
    body: SubmitRequest,
    conn: Connection = Depends(get_conn),
) -> SubmitResponse:
    """Atomically persist the confirmed submission (UC-2 final step).

    The client passes the summary and proposal text from the draft preview,
    plus optional contact info. A single UPDATE sets is_submitted=true.
    """
    session = await get_consultation(conn, consultation_id)
    if not session:
        raise HTTPException(status_code=404, detail="Consultation not found")
    if session.get("is_submitted"):
        raise HTTPException(status_code=409, detail="Already submitted")

    updated = await submit_consultation(
        conn,
        consultation_id,
        summary=body.summary,
        proposal=body.proposal,
        user_name=body.user_name,
        user_email=body.user_email,
    )
    if not updated:
        raise HTTPException(status_code=409, detail="Already submitted")

    logger.info("consultation submitted consultation_id=%s", consultation_id)
    return SubmitResponse(consultation_id=consultation_id)


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
