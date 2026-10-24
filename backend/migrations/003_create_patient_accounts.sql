-- =========================================================================
-- Patient portal account mapping
-- =========================================================================

CREATE TABLE IF NOT EXISTS patient_accounts (
    id            UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    auth_user_id  TEXT NOT NULL UNIQUE,
    patient_id    UUID NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    email         TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_patient_accounts_patient_id
ON patient_accounts(patient_id);

CREATE INDEX IF NOT EXISTS idx_patient_accounts_auth_user_id
ON patient_accounts(auth_user_id);
