# Implementation Roadmap — Organizational Improvement AI Agent

**Per-step verification:** Every step should end with a **short manual smoke check** (and automated tests where they already exist). Examples: run the dev server and load one screen; `curl` `/health`; run one migration against a local DB; hit a single API with a test JWT. Only **commit and push after** that check passes (or after filing a known limitation in the commit message). This keeps each pushed increment trustworthy without requiring full E2E on every step.

**Git & CI workflow:** After each step, **commit with a clear message and push** to the remote (feature branch or `main`, per your team policy). Treat every step as a mergeable increment. **Continuous Integration** must run **static analysis** on every push and pull request (and optionally on `main` after merge): e.g. Python with **Ruff** (and optionally **mypy** or **pyright**), frontend with **ESLint** plus **TypeScript** (`tsc --noEmit`). Fix or explicitly justify failures before merging; static-analysis green should be the default bar for each step once the relevant code exists.

---

## Step 1 — Repository and project layout

**Goal:** Establish a maintainable monorepo (or split repos) and shared conventions.

**Deliverables:**

- Root structure, e.g. `apps/web` (Next.js), `apps/api` (FastAPI), `packages/shared` (optional: types, OpenAPI client).
- `.gitignore`, editor config, and **Python 3.12** toolchain definition (`pyproject.toml` or `requirements.txt` + optional `uv`/`poetry`).
- Minimal `README` with local run pointers (can stay short until Step 2).
- CI pipeline definition that runs the **static-analysis** jobs described in **Git & CI workflow** (start with no-op or minimal checks, then add Ruff/ESLint/tsc as code appears).
- **Verify:** Package installs succeed; if a Next app exists, `pnpm dev` / `npm run dev` serves the starter page. Add API `/health` check from Step 3 onward.

---

## Step 2 — Supabase schema and local parity

**Goal:** Materialize the data model from the design doc.

**Deliverables:**

- SQL migrations (or Supabase migration files) for `knowledge_base` (with `vector` column dimension aligned to your embedding model, e.g. 768 for Gemini), `departments`, `consultations`.
- RLS policies: **public/employee** vs **admin** access boundaries defined (even if auth is placeholder IDs at first).
- Seed script for sample `departments` (optional).

---

## Step 3 — FastAPI foundation

**Goal:** Runnable API with configuration, logging, and health checks.

**Deliverables:**

- FastAPI app, `/health`, structured settings via environment variables (Supabase URL/keys, model API keys, **feature flag for Claude routing**).
- Database client (Supabase REST or `asyncpg`/SQLAlchemy — pick one pattern and stick to it).
- Dockerfile for API (optional but recommended early).

---

## Step 4 — Model router abstraction

**Goal:** Single place that chooses Gemini vs Claude per design rules.

**Deliverables:**

- Interface: `invoke_chat`, `invoke_rag`, `generate_proposal`, etc., backed by LangChain/LangGraph where appropriate.
- **Default:** all paths use Gemini 2.0 Flash-Lite.
- **Conditional Claude:** when `severity >= 4`, when generating formal `proposal` after submit, or Top-down analytical mode — **gated by env var** (e.g. `ENABLE_CLAUDE_ROUTING=true`) so dev/test stay on Gemini only.
- Unit tests for routing decisions (mock LLMs).

---

## Step 5 — Knowledge base ingestion (UC-Admin partial)

**Goal:** Upload → chunk → embed → upsert into `knowledge_base`.

**Deliverables:**

- File parsers (PDF/Excel/DOCX) and chunking strategy (with metadata: source file, page).
- Embedding pipeline using the same model as query-time RAG.
- Admin-only API routes: upload, list chunks, update, delete.

---

## Step 6 — RAG retrieval service

**Goal:** Reusable retrieval given a consultation message or session context.

**Deliverables:**

- Vector search over `knowledge_base` with metadata filters if needed.
- Prompt templates for “Personal Advice” vs “Structural Perspective” sections.
- Integration tests against a small fixture index.

---

## Step 7 — Consultation session API (UC-1 core)

**Goal:** Chat turn that persists/consults `consultations` and returns dual-perspective answers.

**Deliverables:**

- Create/update `consultations` row; store transcript or message history (design prefers updating `department`, `category`, `severity` as conversation evolves — define storage: JSONB column or separate `messages` table).
- After each assistant turn (or on a schedule): call **Gemini** metadata extractor to refresh `department`, `category`, `severity` (0–5).
- `feedback` endpoint for Like/Dislike.

---

## Step 8 — Next.js app shell and employee chat UI

**Goal:** Employee-facing App Router UI wired to the consultation API.

**Deliverables:**

- Department dropdown (from `departments` API).
- Chat UI, feedback buttons, “Submit to Manager” entry point.
- Env-based API base URL; basic error/loading states.

---

## Step 9 — Formal submission flow (UC-2)

**Goal:** Draft summary/proposal, user review, atomic submit.

**Deliverables:**

- Server action or API: generate draft `summary` + `proposal` with PII redaction and tone reframing (router uses Claude when flag on; else Gemini).
- UI: editable draft in chat; optional name/email.
- **Single transaction** on confirm: set `summary`, `proposal`, `user_name`, `user_email`, `is_submitted=true`, `admin_status='New'`.

---

## Step 10 — Admin authentication and dashboard shell

**Goal:** Restrict manager routes and deliver layout/navigation.

**Deliverables:**

- Admin login (Supabase Auth or your chosen IdP) and role check.
- Dashboard routes: Knowledge Base, Departments, Trends, Proposals.

---

## Step 11 — Admin: departments and knowledge management UI

**Goal:** Complete UC-Admin file management and department registry in the browser.

**Deliverables:**

- CRUD for departments.
- Upload/list/edit/delete knowledge chunks (calls Step 5 APIs).

---

## Step 12 — Admin: trends and proposal review

**Goal:** Heatmap, executive summary, proposal workflow.

**Deliverables:**

- Aggregations for `category` × `severity` heatmap (per department filters if required by product).
- Gemini-generated bullet summary from recent consultation metadata.
- Proposal list filter `is_submitted=true`; detail view; `admin_status` updates.
- Top-down “analytical” mode (multi-proposal / policy draft) behind same model router.

---

## Step 13 — Hardening and production readiness

**Goal:** Safe, observable deployment.

**Deliverables:**

- Rate limiting, input size limits, and secrets handling strict in production.
- Enable **Claude routing** only in production via env; document toggles.
- Logging/tracing (request IDs), basic monitoring hooks.
- Deployment manifests (e.g. Vercel + container host for API, or full container stack).

---

## Summary

| Step | Focus                         |
|------|-------------------------------|
| 1    | Repo layout, Python 3.12 pin  |
| 2    | DB schema + RLS               |
| 3    | FastAPI core                  |
| 4    | Model router + env flag       |
| 5    | KB ingestion                  |
| 6    | RAG retrieval                 |
| 7    | UC-1 consultation API         |
| 8    | Next.js employee UI           |
| 9    | UC-2 submission               |
| 10   | Admin auth + shell            |
| 11   | Admin KB + departments        |
| 12   | Trends + proposal review    |
| 13   | Security + deploy             |

You may merge adjacent steps for smaller teams (e.g. 5+6, 11+12) as long as each **push** remains a coherent, reviewable unit and **CI static analysis** still passes for the touched code.
