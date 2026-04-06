# Implementation Roadmap — Organizational Improvement AI Agent

**Per-step verification:** Every step should end with a **short manual smoke check** (and automated tests where they already exist). All services run inside **Docker / Docker Compose** — see the Docker section below for the canonical run commands per layer. This keeps each increment testable in an isolated, reproducible environment before it is committed.

**Git & CI workflow:** After each step, stage and **commit** locally with a clear message. **Push to the remote only when explicitly instructed.** Treat every step as a self-contained, reviewable commit. **Continuous Integration** runs **static analysis** on every push and pull request (and optionally on `main` after merge): Python with **Ruff** (and optionally **mypy**), frontend with **ESLint** + **TypeScript** (`tsc --noEmit`). Static-analysis green is the default bar for each step once the relevant code exists.

**Docker:** All runtime environments are containerized. The project provides:
- `apps/api/Dockerfile` — Python 3.12 FastAPI image
- `apps/web/Dockerfile` — Node 24 Next.js image
- `docker-compose.yml` at repo root — orchestrates `api`, `web`, and (from Step 2) a local Supabase-compatible Postgres+pgvector instance
- Each container is started with `docker compose up` for local dev; CI may run lint/type-check steps directly on the host (no Docker needed for static analysis only)

---

## Step 1 — Repository and project layout

**Goal:** Establish a maintainable monorepo and Docker-based local environment.

**Deliverables:**

- Root structure: `apps/web` (Next.js), `apps/api` (FastAPI), docs.
- `.gitignore`, **Python 3.12** toolchain definition (`pyproject.toml` + `.python-version`).
- `apps/api/Dockerfile` — Python 3.12 slim image for FastAPI (app entry point added in Step 3).
- `apps/web/Dockerfile` — Node 24 multi-stage image for Next.js.
- `docker-compose.yml` at repo root — wires `api` and `web` services; `db` service placeholder added in Step 2.
- Minimal `README` with `docker compose up` as the primary run instruction.
- CI pipeline (`.github/workflows/ci.yml`) for static analysis (Ruff + ESLint + tsc).
- **Verify:** `docker compose build` completes without errors; `docker compose up web` serves the Next.js starter page at `http://localhost:3000`.

---

## Step 2 — Supabase schema and local parity

**Goal:** Materialize the data model from the design doc with a local DB container.

**Deliverables:**

- Add `db` service to `docker-compose.yml`: `postgres:16` with the `pgvector` extension (using `pgvector/pgvector:pg16` image).
- SQL migrations for `knowledge_base` (768-dim vector), `departments`, `consultations`; applied via `docker compose exec db psql ...` or a migration tool container.
- RLS policies: **public/employee** vs **admin** access boundaries (placeholder until auth is wired in Step 10).
- Seed script for sample `departments`.
- **Verify:** `docker compose up db` starts cleanly; running the migrations populates all three tables.

---

## Step 3 — FastAPI foundation

**Goal:** Runnable API container with configuration, logging, and health checks.

**Deliverables:**

- FastAPI app entry point (`main.py`), `/health` endpoint, structured settings via `pydantic-settings` (reads from environment / `.env` file mounted by Compose).
- Database client (`asyncpg` or Supabase Python SDK — pick one pattern and stick to it).
- `.env.example` at repo root documenting all required variables (Supabase URL/keys, model API keys, `ENABLE_CLAUDE_ROUTING`).
- `apps/api/Dockerfile` finalized (was scaffolded in Step 1).
- **Verify:** `docker compose up api` starts; `curl http://localhost:8000/health` returns `{"status":"ok"}`.

---

## Step 4 — Model router abstraction

**Goal:** Single place that chooses Gemini vs Claude per design rules.

**Deliverables:**

- Interface: `invoke_chat`, `invoke_rag`, `generate_proposal`, etc., backed by LangChain/LangGraph where appropriate.
- **Default:** all paths use Gemini 2.0 Flash-Lite.
- **Conditional Claude:** when `severity >= 4`, when generating formal `proposal` after submit, or Top-down analytical mode — **gated by env var** (`ENABLE_CLAUDE_ROUTING=true`) so dev/test stay on Gemini only.
- Unit tests for routing decisions (mock LLMs).
- **Verify:** `docker compose run --rm api pytest tests/test_router.py` passes.

---

## Step 5 — Knowledge base ingestion (UC-Admin partial)

**Goal:** Upload → chunk → embed → upsert into `knowledge_base`.

**Deliverables:**

- File parsers (PDF/Excel/DOCX) and chunking strategy (with metadata: source file, page).
- Embedding pipeline using the same model as query-time RAG.
- Admin-only API routes: upload, list chunks, update, delete.
- **Verify:** Upload a sample PDF via `curl` against the running `api` container; confirm the chunk and vector appear in the `db` container.

---

## Step 6 — RAG retrieval service

**Goal:** Reusable retrieval given a consultation message or session context.

**Deliverables:**

- Vector search over `knowledge_base` with metadata filters if needed.
- Prompt templates for “Personal Advice” vs “Structural Perspective” sections.
- Integration tests against a small fixture index.
- **Verify:** `docker compose run --rm api pytest tests/test_rag.py` passes against the local `db` container.

---

## Step 7 — Consultation session API (UC-1 core)

**Goal:** Chat turn that persists/consults `consultations` and returns dual-perspective answers.

**Deliverables:**

- Create/update `consultations` row; store transcript or message history (design prefers updating `department`, `category`, `severity` as conversation evolves — define storage: JSONB column or separate `messages` table).
- After each assistant turn (or on a schedule): call **Gemini** metadata extractor to refresh `department`, `category`, `severity` (0–5).
- `feedback` endpoint for Like/Dislike.
- **Verify:** `docker compose up` and send a test chat message via `curl`; confirm `consultations` row is created in the `db` container with AI-extracted metadata.

---

## Step 8 — Next.js app shell and employee chat UI

**Goal:** Employee-facing App Router UI wired to the consultation API.

**Deliverables:**

- Department dropdown (from `departments` API).
- Chat UI, feedback buttons, “Submit to Manager” entry point.
- Env-based API base URL; basic error/loading states.
- **Verify:** `docker compose up` and open `http://localhost:3000`; department dropdown populates from the API container.

---

## Step 9 — Formal submission flow (UC-2)

**Goal:** Draft summary/proposal, user review, atomic submit.

**Deliverables:**

- Server action or API: generate draft `summary` + `proposal` with PII redaction and tone reframing (router uses Claude when flag on; else Gemini).
- UI: editable draft in chat; optional name/email.
- **Single transaction** on confirm: set `summary`, `proposal`, `user_name`, `user_email`, `is_submitted=true`, `admin_status='New'`.
- **Verify:** Submit a test consultation end-to-end via the browser; confirm the `consultations` row in the DB has all fields populated atomically.

---

## Step 10 — Admin authentication and dashboard shell

**Goal:** Restrict manager routes and deliver layout/navigation.

**Deliverables:**

- Admin login (Supabase Auth or your chosen IdP) and role check.
- Dashboard routes: Knowledge Base, Departments, Trends, Proposals.
- **Verify:** Admin login succeeds in browser; non-admin routes are blocked.

---

## Step 11 — Admin: departments and knowledge management UI

**Goal:** Complete UC-Admin file management and department registry in the browser.

**Deliverables:**

- CRUD for departments.
- Upload/list/edit/delete knowledge chunks (calls Step 5 APIs).
- **Verify:** Upload and delete a document from the admin UI; confirm DB state.

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
- Production Docker image optimizations (multi-stage builds, non-root user, minimal base images).
- Deployment manifests (e.g. Vercel for `web` + container registry + host for `api`, or full container stack).
- **Verify:** Production image builds cleanly; `docker compose -f docker-compose.prod.yml up` runs all services without errors.

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
