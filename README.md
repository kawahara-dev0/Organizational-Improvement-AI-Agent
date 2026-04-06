# OIAgent — Organizational Improvement AI Agent

A professional platform that bridges employee feedback and organizational strategy via RAG and AI-powered analysis.

## Repository layout

```
OIAgent/
├── apps/
│   ├── api/        # Python 3.12, FastAPI backend
│   └── web/        # Next.js 15 (App Router) frontend
├── docs/           # Design documents and implementation roadmap
└── .github/
    └── workflows/  # CI: static analysis on every push / PR
```

## Prerequisites

| Tool | Version |
|------|---------|
| Node.js | 24.x |
| npm | bundled with Node |
| Python | 3.12 |
| uv | latest (`pip install uv` or [uv docs](https://docs.astral.sh/uv/)) |

## Local development

### Frontend (`apps/web`)

```bash
cd apps/web
npm install
npm run dev        # http://localhost:3000
```

### Backend (`apps/api`)

```bash
cd apps/api
uv sync            # creates .venv and installs all deps
uv run uvicorn main:app --reload   # http://localhost:8000
```

> **Note:** `main.py` will be added in Step 3 of the implementation roadmap.

## Environment variables

Copy `.env.example` (added in Step 3) to `.env` in each app directory and fill in:

| Variable | Description |
|----------|-------------|
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_ANON_KEY` | Supabase anonymous key |
| `SUPABASE_SERVICE_KEY` | Supabase service role key (backend only) |
| `GEMINI_API_KEY` | Google AI Studio API key |
| `ANTHROPIC_API_KEY` | Anthropic API key (production only) |
| `ENABLE_CLAUDE_ROUTING` | Set `true` to activate Claude model routing (production) |

## CI

Every push and pull request triggers `.github/workflows/ci.yml`:

- **Python**: Ruff lint + format check (mypy opt-in)
- **Frontend**: ESLint + TypeScript (`tsc --noEmit`)

## Implementation roadmap

See [`docs/implementation-roadmap.md`](docs/implementation-roadmap.md).
