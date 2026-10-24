-- =========================================================================
-- Email OTP codes for local auth verification
-- =========================================================================

CREATE TABLE IF NOT EXISTS email_otp_codes (
    id           UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    role         TEXT NOT NULL CHECK (role IN ('doctor', 'patient')),
    email        TEXT NOT NULL,
    purpose      TEXT NOT NULL CHECK (purpose IN ('login', 'register', 'password_reset')),
    otp_code     TEXT NOT NULL,
    expires_at   TIMESTAMPTZ NOT NULL,
    used_at      TIMESTAMPTZ,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_email_otp_lookup
ON email_otp_codes(role, email, purpose, used_at, expires_at);
