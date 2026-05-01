-- ============================================================
-- Migration 004 — Category vectors for hybrid RAG retrieval
--
-- kb_category_vectors stores one embedding per unique category
-- name per document version.  At query time the query vector is
-- compared against these embeddings to select the top-N most
-- relevant categories; chunks are then retrieved with SQL
-- category filters on those shortlisted names.
-- ============================================================

CREATE TABLE IF NOT EXISTS kb_category_vectors (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID        NOT NULL REFERENCES kb_documents(id)         ON DELETE CASCADE,
    version_id  UUID        NOT NULL REFERENCES kb_document_versions(id) ON DELETE CASCADE,
    category    TEXT        NOT NULL,
    embedding   VECTOR(768) NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (version_id, category)
);

-- ANN index for fast similarity search against category embeddings
CREATE INDEX IF NOT EXISTS kb_category_vectors_embedding_idx
    ON kb_category_vectors
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 10);

CREATE INDEX IF NOT EXISTS kb_category_vectors_version_id_idx
    ON kb_category_vectors (version_id);

-- ── RLS ───────────────────────────────────────────────────────
ALTER TABLE kb_category_vectors ENABLE ROW LEVEL SECURITY;

CREATE POLICY "dev_allow_all_kb_category_vectors"
    ON kb_category_vectors FOR ALL USING (true) WITH CHECK (true);
