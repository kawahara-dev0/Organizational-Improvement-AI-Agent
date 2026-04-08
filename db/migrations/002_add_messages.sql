-- ============================================================
-- Migration 002 — Add messages column to consultations
-- ============================================================

-- Store the full conversation transcript as a JSONB array
-- [{"role": "user"|"assistant", "content": "..."}]
ALTER TABLE consultations
    ADD COLUMN IF NOT EXISTS messages JSONB NOT NULL DEFAULT '[]';
