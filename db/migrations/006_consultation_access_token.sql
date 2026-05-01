-- ============================================================
-- Migration 006 — Consultation access tokens
--
-- A consultation UUID is an identifier, not an authorization secret.
-- This adds a separate opaque token required by the API for session reads
-- and mutations.
-- ============================================================

CREATE EXTENSION IF NOT EXISTS pgcrypto;

ALTER TABLE consultations
    ADD COLUMN IF NOT EXISTS access_token TEXT;

UPDATE consultations
SET access_token = encode(gen_random_bytes(32), 'base64')
WHERE access_token IS NULL;

ALTER TABLE consultations
    ALTER COLUMN access_token SET NOT NULL;

CREATE INDEX IF NOT EXISTS consultations_access_token_idx
    ON consultations (id, access_token);
