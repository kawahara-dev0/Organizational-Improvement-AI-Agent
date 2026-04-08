-- ============================================================
-- Migration 003 — Knowledge Base document management
--
-- Introduces two tables to manage documents as first-class
-- entities, with full version history.
--
-- kb_documents        — one row per logical document (e.g. "就業規則")
-- kb_document_versions — one row per uploaded file version
--
-- knowledge_base is extended with document_id and version_id so
-- that chunks can be associated with the document/version they
-- came from. Chunks from inactive versions are excluded by the
-- retrieval query (version.is_active = TRUE).
-- ============================================================

-- ── kb_documents ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS kb_documents (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    title               TEXT        NOT NULL,
    category            TEXT        NOT NULL DEFAULT '',
    current_version_id  UUID,           -- FK set after first version insert
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── kb_document_versions ─────────────────────────────────────
CREATE TABLE IF NOT EXISTS kb_document_versions (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id     UUID        NOT NULL REFERENCES kb_documents(id) ON DELETE CASCADE,
    version_no      INT         NOT NULL,                -- 1-based, auto-incremented per document
    source_file     TEXT        NOT NULL,                -- original filename
    is_active       BOOLEAN     NOT NULL DEFAULT TRUE,   -- only one version active at a time
    chunk_count     INT         NOT NULL DEFAULT 0,      -- updated after embedding
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (document_id, version_no)
);

-- FK from kb_documents back to the active version
ALTER TABLE kb_documents
    ADD CONSTRAINT fk_current_version
    FOREIGN KEY (current_version_id)
    REFERENCES kb_document_versions(id)
    DEFERRABLE INITIALLY DEFERRED;

-- ── Extend knowledge_base ─────────────────────────────────────
ALTER TABLE knowledge_base
    ADD COLUMN IF NOT EXISTS document_id UUID REFERENCES kb_documents(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS version_id  UUID REFERENCES kb_document_versions(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS knowledge_base_document_id_idx
    ON knowledge_base (document_id);

CREATE INDEX IF NOT EXISTS knowledge_base_version_id_idx
    ON knowledge_base (version_id);

-- ── RLS policies ──────────────────────────────────────────────
ALTER TABLE kb_documents         ENABLE ROW LEVEL SECURITY;
ALTER TABLE kb_document_versions ENABLE ROW LEVEL SECURITY;

CREATE POLICY "dev_allow_all_kb_documents"
    ON kb_documents FOR ALL USING (true) WITH CHECK (true);

CREATE POLICY "dev_allow_all_kb_document_versions"
    ON kb_document_versions FOR ALL USING (true) WITH CHECK (true);
