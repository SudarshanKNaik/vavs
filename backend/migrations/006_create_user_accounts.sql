-- =========================================================================
-- Local auth accounts (email/password) for doctor and patient login
-- =========================================================================

CREATE TABLE IF NOT EXISTS user_accounts (
    id             UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    role           TEXT NOT NULL CHECK (role IN ('doctor', 'patient')),
    email          TEXT NOT NULL,
    username       TEXT NOT NULL,
    mobile         TEXT NOT NULL,
    password       TEXT NOT NULL,
    is_active      BOOLEAN NOT NULL DEFAULT true,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (role, email)
);

CREATE INDEX IF NOT EXISTS idx_user_accounts_email_role
ON user_accounts(email, role);
