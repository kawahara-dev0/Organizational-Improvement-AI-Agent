-- ============================================================
-- Migration 005 — knowledge_base FK: SET NULL → CASCADE
--
-- Previously document_id / version_id used ON DELETE SET NULL.
-- Deleting kb_documents or kb_document_versions left knowledge_base rows
-- with version_id NULL ("legacy chunks" in the admin UI).
-- CASCADE removes chunk rows when their document or version is deleted.
-- ============================================================

ALTER TABLE knowledge_base DROP CONSTRAINT IF EXISTS knowledge_base_document_id_fkey;
ALTER TABLE knowledge_base DROP CONSTRAINT IF EXISTS knowledge_base_version_id_fkey;

ALTER TABLE knowledge_base
    ADD CONSTRAINT knowledge_base_document_id_fkey
    FOREIGN KEY (document_id)
    REFERENCES kb_documents(id)
    ON DELETE CASCADE;

ALTER TABLE knowledge_base
    ADD CONSTRAINT knowledge_base_version_id_fkey
    FOREIGN KEY (version_id)
    REFERENCES kb_document_versions(id)
    ON DELETE CASCADE;
