from enum import StrEnum


class ModelProvider(StrEnum):
    GEMINI = "gemini"
    CLAUDE = "claude"


class RouterTask(StrEnum):
    """Task types that may trigger Claude routing when the feature flag is on."""

    CHAT = "chat"          # General consultation chat turn
    RAG = "rag"            # RAG retrieval + response
    PROPOSAL = "proposal"  # Formal proposal generation (UC-2)
    ANALYTICAL = "analytical"  # Top-down strategic analysis (UC-Admin)
