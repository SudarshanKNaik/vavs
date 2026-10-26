-- ============================================================
-- Migration 024: NGO self-registration email OTPs
-- ============================================================
-- Kept separate from doctor/patient email_otp_codes so NGO sign-up
-- never touches the doctor/patient auth flow. Only a SHA-256 hash of
-- each code is stored. Safe to re-run.
-- ============================================================

CREATE TABLE IF NOT EXISTS ngo_email_otps (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email       TEXT NOT NULL,
    purpose     TEXT NOT NULL DEFAULT 'register' CHECK (purpose IN ('register')),
    code_hash   TEXT NOT NULL,
    attempts    INTEGER NOT NULL DEFAULT 0,
    expires_at  TIMESTAMPTZ NOT NULL,
    used_at     TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ngo_email_otps_lookup
    ON ngo_email_otps (email, purpose, created_at DESC);
