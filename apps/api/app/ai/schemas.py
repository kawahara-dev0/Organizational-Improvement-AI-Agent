from pydantic import BaseModel, Field

from app.ai.enums import ModelProvider, RouterTask


class RouterContext(BaseModel):
    """Input context used by the model router to select a provider."""

    task: RouterTask
    severity: int = Field(default=0, ge=0, le=5)
    is_submitted: bool = False
    is_analytical: bool = False


class RouterDecision(BaseModel):
    """Output of the model router."""

    provider: ModelProvider
    reason: str


class ChatMessage(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class InvokeRequest(BaseModel):
    messages: list[ChatMessage]
    context: RouterContext
    system_prompt: str = ""


class InvokeResponse(BaseModel):
    content: str
    provider_used: ModelProvider
