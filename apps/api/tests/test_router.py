"""Unit tests for the model router.

All routing decisions are pure functions (no I/O), so no mocking of LLMs
is needed for the decide() tests.  The invoke_* tests mock the LLM to
avoid real API calls.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.ai.enums import ModelProvider, RouterTask
from app.ai.router import (
    decide,
    generate_proposal,
    invoke_analytical,
    invoke_chat,
    invoke_rag,
)
from app.ai.schemas import ChatMessage, InvokeRequest, RouterContext

# ── decide() — pure routing logic ────────────────────────────────────────────

class TestDecideWithFlagOff:
    """When ENABLE_CLAUDE_ROUTING=false, always return Gemini."""

    def setup_method(self):
        self._patch = patch("app.ai.router.settings")
        self.mock_settings = self._patch.start()
        self.mock_settings.enable_claude_routing = False

    def teardown_method(self):
        self._patch.stop()

    def test_chat_uses_gemini(self):
        ctx = RouterContext(task=RouterTask.CHAT)
        decision = decide(ctx)
        assert decision.provider == ModelProvider.GEMINI

    def test_proposal_still_uses_gemini_when_flag_off(self):
        ctx = RouterContext(task=RouterTask.PROPOSAL, is_submitted=True)
        decision = decide(ctx)
        assert decision.provider == ModelProvider.GEMINI

    def test_high_severity_uses_gemini_when_flag_off(self):
        ctx = RouterContext(task=RouterTask.CHAT, severity=5)
        decision = decide(ctx)
        assert decision.provider == ModelProvider.GEMINI


class TestDecideWithFlagOn:
    """When ENABLE_CLAUDE_ROUTING=true, apply routing rules."""

    def setup_method(self):
        self._patch = patch("app.ai.router.settings")
        self.mock_settings = self._patch.start()
        self.mock_settings.enable_claude_routing = True

    def teardown_method(self):
        self._patch.stop()

    def test_chat_low_severity_uses_gemini(self):
        ctx = RouterContext(task=RouterTask.CHAT, severity=2)
        decision = decide(ctx)
        assert decision.provider == ModelProvider.GEMINI

    def test_chat_severity_4_uses_claude(self):
        ctx = RouterContext(task=RouterTask.CHAT, severity=4)
        decision = decide(ctx)
        assert decision.provider == ModelProvider.CLAUDE

    def test_chat_severity_5_uses_claude(self):
        ctx = RouterContext(task=RouterTask.CHAT, severity=5)
        decision = decide(ctx)
        assert decision.provider == ModelProvider.CLAUDE

    def test_chat_severity_3_uses_gemini(self):
        ctx = RouterContext(task=RouterTask.CHAT, severity=3)
        decision = decide(ctx)
        assert decision.provider == ModelProvider.GEMINI

    def test_proposal_uses_claude(self):
        ctx = RouterContext(task=RouterTask.PROPOSAL, is_submitted=True)
        decision = decide(ctx)
        assert decision.provider == ModelProvider.CLAUDE

    def test_analytical_uses_claude(self):
        ctx = RouterContext(task=RouterTask.ANALYTICAL, is_analytical=True)
        decision = decide(ctx)
        assert decision.provider == ModelProvider.CLAUDE

    def test_rag_low_severity_uses_gemini(self):
        ctx = RouterContext(task=RouterTask.RAG, severity=1)
        decision = decide(ctx)
        assert decision.provider == ModelProvider.GEMINI


# ── invoke_* — mock LLM calls ────────────────────────────────────────────────

def _make_request(task: RouterTask, severity: int = 0) -> InvokeRequest:
    return InvokeRequest(
        messages=[ChatMessage(role="user", content="hello")],
        context=RouterContext(task=task, severity=severity),
        system_prompt="You are a helpful assistant.",
    )


def _mock_llm(response_text: str = "mocked response") -> MagicMock:
    mock = MagicMock()
    ai_message = MagicMock()
    ai_message.content = response_text
    mock.ainvoke = AsyncMock(return_value=ai_message)
    return mock


@pytest.mark.asyncio
async def test_invoke_chat_returns_response():
    with (
        patch("app.ai.router.settings") as mock_settings,
        patch("app.ai.router.get_gemini") as mock_get_gemini,
    ):
        mock_settings.enable_claude_routing = False
        mock_get_gemini.return_value = _mock_llm("chat reply")

        response = await invoke_chat(_make_request(RouterTask.CHAT))

    assert response.content == "chat reply"
    assert response.provider_used == ModelProvider.GEMINI


@pytest.mark.asyncio
async def test_invoke_rag_returns_response():
    with (
        patch("app.ai.router.settings") as mock_settings,
        patch("app.ai.router.get_gemini") as mock_get_gemini,
    ):
        mock_settings.enable_claude_routing = False
        mock_get_gemini.return_value = _mock_llm("rag reply")

        response = await invoke_rag(_make_request(RouterTask.RAG))

    assert response.content == "rag reply"
    assert response.provider_used == ModelProvider.GEMINI


@pytest.mark.asyncio
async def test_generate_proposal_uses_claude_when_flag_on():
    with (
        patch("app.ai.router.settings") as mock_settings,
        patch("app.ai.router.get_claude") as mock_get_claude,
    ):
        mock_settings.enable_claude_routing = True
        mock_get_claude.return_value = _mock_llm("proposal text")

        response = await generate_proposal(_make_request(RouterTask.PROPOSAL))

    assert response.content == "proposal text"
    assert response.provider_used == ModelProvider.CLAUDE


@pytest.mark.asyncio
async def test_invoke_analytical_uses_claude_when_flag_on():
    with (
        patch("app.ai.router.settings") as mock_settings,
        patch("app.ai.router.get_claude") as mock_get_claude,
    ):
        mock_settings.enable_claude_routing = True
        mock_get_claude.return_value = _mock_llm("analysis result")

        response = await invoke_analytical(_make_request(RouterTask.ANALYTICAL))

    assert response.content == "analysis result"
    assert response.provider_used == ModelProvider.CLAUDE
