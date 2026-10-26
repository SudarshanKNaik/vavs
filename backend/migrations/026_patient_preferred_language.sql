-- ============================================================
-- Migration 026: Remember each patient's call language
-- ============================================================
-- Set from the AI call's preferred_language result, so the next
-- call starts in the patient's language instead of asking again.
-- ISO 639-1 code, e.g. 'kn' (Kannada), 'or' (Odia), 'hi' (Hindi).
-- Additive only. Safe to re-run.
-- ============================================================

ALTER TABLE patients
    ADD COLUMN IF NOT EXISTS preferred_language TEXT;
