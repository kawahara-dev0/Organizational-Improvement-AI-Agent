"""LLM instance factory.

Returns LangChain chat model instances for Gemini and Claude.
Actual API calls only happen when the models are invoked; instantiation
itself does not require network access.
"""

from functools import lru_cache

from langchain_anthropic import ChatAnthropic
from langchain_google_genai import ChatGoogleGenerativeAI

from app.settings import settings

# Model identifiers
GEMINI_MODEL = "gemini-2.5-flash-lite"
CLAUDE_MODEL = "claude-sonnet-4-5"


@lru_cache(maxsize=1)
def get_gemini() -> ChatGoogleGenerativeAI:
    return ChatGoogleGenerativeAI(
        model=GEMINI_MODEL,
        google_api_key=settings.gemini_api_key,
        temperature=0.3,
    )


@lru_cache(maxsize=1)
def get_claude() -> ChatAnthropic:
    return ChatAnthropic(
        model=CLAUDE_MODEL,
        api_key=settings.anthropic_api_key,
        temperature=0.3,
        max_tokens=4096,
    )
