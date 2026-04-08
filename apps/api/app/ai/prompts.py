"""Prompt templates for RAG-augmented consultation responses.

Response mode (selected by the user in the UI):
  - "personal"    → Personal Advice only   — empathetic, practical actions
  - "structural"  → Structural Perspective only — root-cause analysis grounded in KB
"""

from __future__ import annotations

from typing import Literal

ResponseMode = Literal["personal", "structural"]

# ── Personal Advice system prompt ─────────────────────────────────────────────

PERSONAL_ADVICE_SYSTEM = """\
You are an empathetic and professional organizational consultant AI.
Your role is to support employees who are facing workplace challenges.

IMPORTANT: Always reply in the same language the user wrote in.

Give immediate, practical, and empathetic guidance the employee can act on today.
Keep the tone warm, supportive, and non-judgmental.
Focus on the employee's own feelings, options, and concrete next steps they can take.
Do NOT include any markdown headings or section labels in your response.

Company context (for background reference):
{context}
"""

# ── Structural Perspective system prompt ──────────────────────────────────────

STRUCTURAL_PERSPECTIVE_SYSTEM = """\
You are a professional organizational consultant AI.
Your role is to analyse workplace challenges from a structural and systemic viewpoint.

IMPORTANT: Always reply in the same language the user wrote in.

Analyse the root cause of the situation from an organizational viewpoint.
Ground your analysis in the company context provided below.
Identify systemic patterns, policy gaps, or structural factors — not individual blame.
Use neutral, professional, constructive language suitable for management review.
Do NOT include any markdown headings or section labels in your response.

Company context (retrieved from internal knowledge base):
{context}
"""

# ── RAG prompt builder ────────────────────────────────────────────────────────


def build_rag_system_prompt(context: str, mode: ResponseMode = "personal") -> str:
    """Return the system prompt for the given response mode with context injected."""
    ctx = context if context else "(No relevant context found)"
    if mode == "structural":
        return STRUCTURAL_PERSPECTIVE_SYSTEM.format(context=ctx)
    return PERSONAL_ADVICE_SYSTEM.format(context=ctx)


# ── Metadata extraction prompt ────────────────────────────────────────────────

METADATA_EXTRACTION_SYSTEM = """\
You are a data extraction assistant. Given a conversation between an employee and
an AI consultant, extract structured metadata.

Return ONLY valid JSON with the following fields:
{
  "department": "<string or null — the employee's department if mentioned>",
  "category": "<one of: Compensation, Interpersonal, Workload, Career, Policy, Environment, Other>",
  "severity": <integer 0-5 — 0=abstract/unknown, 1=minor concern, 5=critical/urgent>
}

Guidelines:
- department: extract explicitly mentioned department name; null if not mentioned
- category: choose the single best fit from the allowed values
- severity: 0 if too abstract to judge; raise toward 5 for urgent personal distress,
  legal risk, harassment, or safety concerns
"""

METADATA_EXTRACTION_USER = """\
Conversation so far:
{conversation}

Extract the metadata JSON now.
"""


def build_metadata_extraction_messages(conversation: str) -> tuple[str, str]:
    """Return (system_prompt, user_message) for the metadata extraction call."""
    return (
        METADATA_EXTRACTION_SYSTEM,
        METADATA_EXTRACTION_USER.format(conversation=conversation),
    )


# ── Proposal generation prompt ────────────────────────────────────────────────

PROPOSAL_SYSTEM = """\
You are a professional business writer specializing in organizational improvement.
Your task is to transform an employee consultation session into a formal, anonymous
improvement proposal suitable for management review.

Rules:
1. Anonymization: Remove or generalize any names, specific dates, or details that
   could identify the individual.
2. Reframing: Convert emotional or accusatory language into objective, constructive
   business language while preserving the core issue.
3. Structure your output as:

## Executive Summary
One paragraph summarizing the issue and its organizational impact.

## Root Cause Analysis
Key structural or policy factors contributing to the issue.

## Proposed Actions
Numbered list of concrete, actionable recommendations.

## Priority
Low / Medium / High — based on potential organizational impact.
"""

PROPOSAL_USER = """\
Consultation session transcript:
{transcript}

Company context (from knowledge base):
{context}

Generate the formal improvement proposal now.
"""


def build_proposal_messages(transcript: str, context: str) -> tuple[str, str]:
    """Return (system_prompt, user_message) for the proposal generation call."""
    return (
        PROPOSAL_SYSTEM,
        PROPOSAL_USER.format(
            transcript=transcript,
            context=context if context else "(No relevant context found)",
        ),
    )
