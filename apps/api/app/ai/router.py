"""Model router.

Routing rules (applied only when ENABLE_CLAUDE_ROUTING=true):
  - PROPOSAL task           → Claude  (formal proposal generation)
  - ANALYTICAL task         → Claude  (top-down strategic analysis)
  - severity >= 4           → Claude  (high-risk consultation)

All other cases, or when the flag is off, use Gemini 2.0 Flash-Lite.
"""

import logging

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.ai.enums import ModelProvider, RouterTask
from app.ai.llm import get_claude, get_gemini
from app.ai.schemas import (
    ChatMessage,
    InvokeRequest,
    InvokeResponse,
    RouterContext,
    RouterDecision,
)
from app.settings import settings

logger = logging.getLogger(__name__)

_CLAUDE_TASKS = {RouterTask.PROPOSAL, RouterTask.ANALYTICAL}


def decide(context: RouterContext) -> RouterDecision:
    """Pure routing logic — no I/O, easy to unit-test."""
    if not settings.enable_claude_routing:
        return RouterDecision(
            provider=ModelProvider.GEMINI,
            reason="Claude routing disabled (ENABLE_CLAUDE_ROUTING=false)",
        )

    if context.task in _CLAUDE_TASKS:
        return RouterDecision(
            provider=ModelProvider.CLAUDE,
            reason=f"Task '{context.task}' requires deep reasoning",
        )

    if context.severity >= 4:
        return RouterDecision(
            provider=ModelProvider.CLAUDE,
            reason=f"High-risk consultation (severity={context.severity})",
        )

    return RouterDecision(
        provider=ModelProvider.GEMINI,
        reason="Standard task — using fast model",
    )


def _build_lc_messages(
    messages: list[ChatMessage],
    system_prompt: str,
) -> list:
    lc_messages = []
    if system_prompt:
        lc_messages.append(SystemMessage(content=system_prompt))
    for m in messages:
        if m.role == "user":
            lc_messages.append(HumanMessage(content=m.content))
        else:
            lc_messages.append(AIMessage(content=m.content))
    return lc_messages


def _get_model(provider: ModelProvider) -> BaseChatModel:
    if provider == ModelProvider.CLAUDE:
        return get_claude()
    return get_gemini()


async def invoke_chat(request: InvokeRequest) -> InvokeResponse:
    """General consultation chat turn."""
    decision = decide(request.context)
    model = _get_model(decision.provider)
    lc_messages = _build_lc_messages(request.messages, request.system_prompt)
    logger.info("invoke_chat provider=%s reason=%s", decision.provider, decision.reason)
    result = await model.ainvoke(lc_messages)
    return InvokeResponse(content=result.content, provider_used=decision.provider)


async def invoke_rag(request: InvokeRequest) -> InvokeResponse:
    """RAG-augmented response (retrieved context already embedded in system_prompt)."""
    rag_context = RouterContext(
        task=RouterTask.RAG,
        severity=request.context.severity,
        is_submitted=request.context.is_submitted,
        is_analytical=request.context.is_analytical,
    )
    decision = decide(rag_context)
    model = _get_model(decision.provider)
    lc_messages = _build_lc_messages(request.messages, request.system_prompt)
    logger.info("invoke_rag provider=%s reason=%s", decision.provider, decision.reason)
    result = await model.ainvoke(lc_messages)
    return InvokeResponse(content=result.content, provider_used=decision.provider)


async def generate_proposal(request: InvokeRequest) -> InvokeResponse:
    """Formal proposal generation triggered on submission (UC-2)."""
    proposal_context = RouterContext(
        task=RouterTask.PROPOSAL,
        severity=request.context.severity,
        is_submitted=True,
        is_analytical=request.context.is_analytical,
    )
    decision = decide(proposal_context)
    model = _get_model(decision.provider)
    lc_messages = _build_lc_messages(request.messages, request.system_prompt)
    logger.info("generate_proposal provider=%s reason=%s", decision.provider, decision.reason)
    result = await model.ainvoke(lc_messages)
    return InvokeResponse(content=result.content, provider_used=decision.provider)


async def invoke_analytical(request: InvokeRequest) -> InvokeResponse:
    """Top-down strategic analysis for the admin dashboard."""
    analytical_context = RouterContext(
        task=RouterTask.ANALYTICAL,
        severity=request.context.severity,
        is_submitted=request.context.is_submitted,
        is_analytical=True,
    )
    decision = decide(analytical_context)
    model = _get_model(decision.provider)
    lc_messages = _build_lc_messages(request.messages, request.system_prompt)
    logger.info("invoke_analytical provider=%s reason=%s", decision.provider, decision.reason)
    result = await model.ainvoke(lc_messages)
    return InvokeResponse(content=result.content, provider_used=decision.provider)
