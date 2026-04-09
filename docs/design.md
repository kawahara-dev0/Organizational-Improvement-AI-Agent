# Technical Design Document: Organizational Improvement AI Agent

## 1. Overview
**Purpose**: A professional platform that bridges the gap between employee frustrations and organizational strategy. It uses RAG to analyze subjective feedback against objective corporate data (policies, financials) to propose structural improvements.

**Core Value**: 
- **Anonymity First**: Protects employees while extracting structural insights through non-PII metadata collection.
- **Data handling**: Chat text sent to the LLM is passed through **PII masking** (e.g. email / phone patterns → placeholders) to reduce accidental leakage. Optional **Fernet encryption at rest** for `consultations.messages` (`MESSAGES_ENCRYPTION_KEY`) so DB inspection does not expose plaintext transcripts; optional **retention deletion** for non-submitted sessions (`CONSULTATION_RETENTION_DAYS`). Third-party model providers’ training / logging policies are outside this app — configure keys and vendor terms accordingly.
- **AI Reasoning**: Uses a "Model Router" to switch between logical analysis (Claude) and fast processing (Gemini) based on task complexity.
- **Actionable Output**: Reframes emotional complaints into professional management proposals with priority scores.

## 2. Architecture & Technology Stack

- **Frontend**: Next.js 15 (App Router), Tailwind CSS — pin versions in `package.json` + lockfile for reproducible builds
- **Backend**: Python 3.12, FastAPI
- **Database**: Supabase (PostgreSQL + pgvector)
- **Orchestration**: LangChain / LangGraph
- **AI Models**: Claude 4.6 Sonnet, Gemini 2.5 Flash-Lite (Sonnet for deep reasoning; Flash for routing and RAG.)

## 3. Actor Definitions
- **User**: Seeking help for personal issues or suggesting organizational changes.
- **Manager (Admin)**: Oversees organizational health, reviews proposals, and updates organizational context (Policies/Structure).

## 4. Core Use Cases (The Sequential Flows)

### UC-1: AI-Powered Employee Consultation
Actor: Everyone
Goal: Provide immediate value to the employee while capturing anonymized data for organizational health mapping.

1. Entry & Context Selection:
- Employee selects a `#department` (optional) and describes their situation.
  Note: '#department' is dynamic and managed via the Manager Dashboard (UC-Admin).
- Employee describes their situation in the chat interface.

2. AI Routing & Real-time Logging (Gemini 2.5 Flash-Lite):
- AI analyzes the input to extract:
  * `#consultations.department`
  * `#consultations.category` (e.g., Compensation, Interpersonal)
  * `#consultations.severity` (Scale: 0-5. Set to 0 if abstract/pending).
- Dynamic Updates: As the conversation progresses, the AI periodically refreshes these fields (every N assistant turns, configurable via `METADATA_EXTRACTION_INTERVAL`).

3. Contextual Analysis (LLM + RAG):
- RAG Search: AI searches `#knowledge_base` for relevant company policies and strategy documents (can be disabled per turn via `RAG_ENABLED=false` to stay within API free-tier limits). Retrieval uses only chunks tied to an **active document version** (`kb_document_versions.is_active = TRUE`); legacy rows without a version are excluded from search.
- **Source citations**: The API returns a structured `sources` list (document title, primary page from highest similarity, optional “Also referenced” supplementary pages) so the UI can show references alongside inline `[1]`, `[2]` markers in the assistant reply.
- Response Mode Selection: The employee selects one of two response modes per message via the UI:
  * **Personal Advice**: Practical, empathetic immediate actions for the employee. Responds in the same language as the employee's message.
  * **Structural Perspective**: Root cause analysis based on `#knowledge_base` and organizational frameworks. Responds in the same language as the employee's message.
- The selected mode is sent to the API as `mode: "personal" | "structural"` and persisted per message in `#consultations.messages`.
- **PII masking** is applied to message content **before** it is sent to the LLM for chat and proposal-draft generation (not a substitute for user discipline; names/addresses in free text may still require broader patterns or manual review).

- Model Routing: The system routes tasks based on Risk (Severity) and Complexity (Intent) to optimize for both accuracy and API budget. By default, Gemini 2.5 Flash-Lite is used for all operations. The system switches to Claude 4.6 Sonnet only when the following specific conditions are met:
  * High-Risk Analysis: When `#consultations.severity` is identified as 4 or higher.
  * Proposal Generation: When `#consultations.is_submitted` is True and the system generates the formal `#consultations.proposal`.
  * Advanced Strategic Analysis: During Top-down mode for complex hypothesis testing or policy drafting (Analytical Queries).

  To minimize API overhead during building and testing, Gemini 2.5 Flash-Lite shall be used for ALL features. The routing logic to Claude should be implemented but toggled via environment variables only for the final deployment.

4. Feedback:
- Employee clicks "Like/Dislike" on the advice (Stored in `#consultations.feedback`).

### UC-2: Formal Proposal Escalation (The Submission Phase)
Prerequisite: Triggered following UC-1 to convert private chat context into a formal record.

1. Initiation:
- User clicks "Create proposal draft" (in the header bar) to generate a proposal preview.
- User may select the draft output language beforehand: **Auto** (match conversation), **日本語**, or **English**.

2. Interactive Review & Professional Reframing:
- AI (Claude 4.6 Sonnet) synthesizes the session into a formal draft (Summary & Structural Proposal).
- **Contact fields** (`user_name`, `user_email`) are collected only for submission and manager follow-up; they are **not** included in the LLM prompt for draft generation.
- Anonymization: AI automatically detects and redacts/generalizes specific names or PII within the text; the transcript passed to the model is also **PII-masked** at the API layer where patterns apply.
- Reframing: AI converts emotional/accusatory language into objective, professional business language.
- The draft is displayed in a **dedicated right panel** (always visible alongside the chat). The panel
  shows a placeholder message until a draft is generated.
- Draft output uses fixed section headings to enable reliable parsing:
  * Japanese: `### 概要` / `### 原因分析` / `### 提案事項`
  * English: `### Executive Summary` / `### Root Cause Analysis` / `### Proposed Actions`
- The "Executive Summary" / `概要` section body is surfaced separately at the top of the panel.
- This step does **not** write to the DB (`POST /consultations/{id}/draft`).

3. Identity Option:
- The right panel's fixed footer provides optional "Name" and "Email" fields (always accessible,
  independent of proposal text scroll position).
- Contact information is optional. If provided, managers may contact the submitter for follow-up.

4. Final Persistence (Atomic Update):
- Upon clicking "Send to Manager", the UI sends the reviewed draft content together with optional
  contact info to `POST /consultations/{id}/submit`, and a single DB update occurs:
  * Populate `#consultations.summary` and `#consultations.proposal`.
  * Set `#consultations.user_name` and `#consultations.user_email`.
  * Set `#consultations.is_submitted` to True.
  * Set `#consultations.admin_status` to "New".
- After submission, the right panel shows a thank-you message in place of the form. The chat input
  and mode selector are disabled (not hidden).

### UC-Admin: Managerial Dashboard & Strategic Control
Actor: Manager (Admin)
Goal: Manage organizational context and translate employee feedback into strategic action.

1. Knowledge Base Management (RAG Context)
- Upload & Sync: Manager uploads files (PDF/Excel/Docx) such as Employee Handbooks, Internal Policies, or Quarterly Goals.
- **Document-centric model**: Each logical document lives in `#kb_documents` with one or more file versions in `#kb_document_versions`; chunks in `#knowledge_base` reference `document_id` and `version_id`. Only the **active** version is used for retrieval; uploading a new version supersedes the previous one for search.
- Processing: The system chunks text and writes embeddings into `#knowledge_base` linked to the active version.
- **Version retention**: A maximum of **3 versions** (newest-first) are kept per document. When a new version is finalized, versions beyond the 3rd oldest are automatically deleted together with their `#knowledge_base` chunks. Chunks are deleted explicitly before the version row to prevent them from becoming orphan/legacy rows (the FK is `ON DELETE SET NULL`, not `CASCADE`).
- **No direct chunk editing** in the admin UI; accuracy is maintained by uploading a corrected file version. An admin tool may report and delete **legacy/orphan chunks** (`version_id` NULL) left from older ingestion paths.

2. Department Structure Management
- Registry: Manager defines the list of valid `#department` (e.g., Sales, Engineering, HR). These values populate the dropdown in UC-1.

3. Trend Dashboard
- Heatmap Visualization: A 2D matrix crossing `#consultations.category` and `#consultations.severity`. To detect departments or topics with rising tension (e.g., a spike in "High Severity" + "Interpersonal" in a specific team). Optional filters: **department**, **date range** (`date_from` / `date_to`).
- AI-Driven Executive Summary: Gemini 2.5 Flash-Lite scans aggregated trend rows (respecting the same filters) to generate a management brief; output language can be selected.

4. Proposal Review:
- Filter: Manager views only records where `#consultations.is_submitted` is True.
- Strategic Analysis (Top-down Mode): Manager uses Claude 4.6 Sonnet (during building and testing, Gemini 2.5 Flash-Lite shall be used.) to analyze specific proposals or cross-reference multiple submissions to draft new company-wide policies.
- Response & Status: Manager can mark `#consultations.admin_status`.

## 5. Database Schema
knowledge_base {
    UUID    id            Primary Key.
    text    content       Chunked text content from uploaded documents.
    VECTOR  embedding     Vector data (e.g., 768 dimensions for Gemini Embedding).
    JSONB   metadata	    Source file name, page numbers, category, chunk_index, etc.
    UUID    document_id   Optional FK → kb_documents (set for versioned uploads).
    UUID    version_id    Optional FK → kb_document_versions (retrieval requires active version).
}

kb_documents {
    UUID    id                  Primary Key.
    text    title               Logical document title (shown in citations).
    text    category            Optional grouping.
    UUID    current_version_id  FK → kb_document_versions (active file version).
    timestamp created_at, updated_at
}

kb_document_versions {
    UUID    id           Primary Key.
    UUID    document_id  FK → kb_documents.
    int     version_no   1-based per document.
    text    source_file  Original filename.
    bool    is_active    Only active version’s chunks participate in RAG.
    int     chunk_count  Filled after embedding pipeline.
    timestamp created_at
}

departments {
    UUID    id            Primary Key.
    text    name
    timestamp created_at
}

consultations {
    UUID    id            Primary Key.
    text    department
    text    category      Auto-extracted by AI.
    int     severity      Scale 0-5. (0 = Pending/Abstract). Auto-extracted by AI.
    int     feedback      1 (Like), -1 (Dislike), 0 (Default/Unanswered).
    bool    is_submitted  Default False. Set to True upon user's explicit submission.
    text    summary       Auto-generated by AI on submission.
    text    proposal      Auto-generated by AI on submission.
    text    user_name     Optional.
    text    user_email    Optional.
    text    admin_status  "New" (Default), "In Progress", "Resolved", or "Archived".
    JSONB   messages      Conversation transcript. Application layer: normally a JSON array of
                          {role, content, mode?} (role: "user" | "assistant"; mode on assistant
                          when set). When encryption is enabled, stored value may be a JSON string
                          containing ciphertext (prefix `enc:v1:`) — decrypted on read by the API.
    timestamp created_at
}