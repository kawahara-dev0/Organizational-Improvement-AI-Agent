# OIAgent — Organizational Improvement AI Agent

A professional platform that bridges employee feedback and organizational strategy via RAG and AI-powered analysis.

## Repository layout

```
OIAgent/
├── apps/
│   ├── api/        # Python 3.12, FastAPI backend
│   └── web/        # Next.js 15 (App Router) frontend
├── db/
│   └── migrations/ # PostgreSQL + pgvector schema (apply in order)
├── docs/           # Design, roadmap, security notes
└── .github/
    └── workflows/  # CI on every push / PR
```

## Prerequisites

| Tool | Version |
|------|---------|
| Docker Desktop | latest |
| Docker Compose | v2 (bundled with Docker Desktop) |

Node.js and Python do **not** need to be installed locally — all runtimes run inside containers.

## Local development

```bash
# 1. Copy env template and fill in your API keys
cp .env.example .env

# 2. Build and start all services
docker compose up --build

# Services:
#   http://localhost:3000  — Next.js frontend
#   http://localhost:8000  — FastAPI backend  (entry point added in Step 3)
#   localhost:5432         — PostgreSQL + pgvector
```

To start only a single service (e.g. during Step 1 verification):

```bash
docker compose up web          # frontend only
docker compose build api       # build API image
```

## Environment variables

Copy `.env.example` to `.env` at the repo root and fill in:

| Variable | Description |
|----------|-------------|
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_ANON_KEY` | Supabase anonymous key |
| `SUPABASE_SERVICE_KEY` | Supabase service role key (backend only) |
| `GEMINI_API_KEY` | Google AI Studio API key |
| `ANTHROPIC_API_KEY` | Anthropic API key (production only) |
| `ENABLE_CLAUDE_ROUTING` | Set `true` to activate Claude model routing (production) |

See [`.env.example`](.env.example) for the full list (admin JWT, CORS, rate limits, message encryption, RAG flags, and local Postgres settings).

## CI

Every push and pull request triggers [`.github/workflows/ci.yml`](.github/workflows/ci.yml):

- **Python — static analysis**: Ruff lint + format check (mypy opt-in)
- **Python — tests**: Apply `db/migrations/*.sql` to a temporary PostgreSQL **pgvector** service, then `pytest`
- **Frontend**: ESLint + TypeScript (`tsc --noEmit`)

## Documentation

| Doc | Contents |
|-----|----------|
| [`docs/implementation-roadmap.md`](docs/implementation-roadmap.md) | Setup steps and verification checklist |
| [`docs/design.md`](docs/design.md) | Architecture and feature design |
| [`docs/security.md`](docs/security.md) | Threat model, hardening, and remaining risks |

Start with the implementation roadmap for step-by-step setup and verification.
