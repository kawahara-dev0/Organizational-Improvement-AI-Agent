FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN pip install --no-cache-dir uv

# ── dev stage (hot-reload) ────────────────────────────────────
FROM base AS dev
COPY pyproject.toml .
RUN uv sync --no-install-project
COPY . .
CMD ["uv", "run", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# ── production stage ──────────────────────────────────────────
FROM base AS prod

# Create a non-root user for running the application
RUN addgroup --system --gid 1001 appgroup && \
    adduser --system --uid 1001 --ingroup appgroup appuser

COPY pyproject.toml .
RUN uv sync --no-dev --no-install-project

COPY . .

# Ensure appuser owns the app directory
RUN chown -R appuser:appgroup /app

USER appuser

CMD ["uv", "run", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
