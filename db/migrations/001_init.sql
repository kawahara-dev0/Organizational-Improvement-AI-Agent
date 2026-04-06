-- ============================================================
-- Migration 001 — Initial schema
-- ============================================================

-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- ── knowledge_base ───────────────────────────────────────────
CREATE TABLE IF NOT EXISTS knowledge_base (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    content     TEXT        NOT NULL,
    embedding   VECTOR(768) NOT NULL,
    metadata    JSONB       NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ANN index for fast similarity search (cosine distance)
CREATE INDEX IF NOT EXISTS knowledge_base_embedding_idx
    ON knowledge_base
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

-- ── departments ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS departments (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT        NOT NULL UNIQUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── consultations ────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS consultations (
    id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    department   TEXT,
    category     TEXT,
    severity     SMALLINT    NOT NULL DEFAULT 0
                             CHECK (severity BETWEEN 0 AND 5),
    feedback     SMALLINT    NOT NULL DEFAULT 0
                             CHECK (feedback IN (-1, 0, 1)),
    is_submitted BOOLEAN     NOT NULL DEFAULT FALSE,
    summary      TEXT,
    proposal     TEXT,
    user_name    TEXT,
    user_email   TEXT,
    admin_status TEXT        NOT NULL DEFAULT 'New'
                             CHECK (admin_status IN ('New', 'In Progress', 'Resolved', 'Archived')),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Index for manager dashboard queries
CREATE INDEX IF NOT EXISTS consultations_is_submitted_idx
    ON consultations (is_submitted);

CREATE INDEX IF NOT EXISTS consultations_department_severity_idx
    ON consultations (department, severity);

-- ── Row-Level Security ────────────────────────────────────────
-- NOTE: RLS is enabled as a placeholder.
-- Actual role-based policies are wired in Step 10 (auth).

ALTER TABLE knowledge_base    ENABLE ROW LEVEL SECURITY;
ALTER TABLE departments       ENABLE ROW LEVEL SECURITY;
ALTER TABLE consultations     ENABLE ROW LEVEL SECURITY;

-- Temporary open policies for local development (overridden in Step 10)
CREATE POLICY "dev_allow_all_knowledge_base"
    ON knowledge_base FOR ALL USING (true) WITH CHECK (true);

CREATE POLICY "dev_allow_all_departments"
    ON departments FOR ALL USING (true) WITH CHECK (true);

CREATE POLICY "dev_allow_all_consultations"
    ON consultations FOR ALL USING (true) WITH CHECK (true);
