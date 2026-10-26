-- ============================================================
-- Migration 023: NGO Portal
-- ============================================================
-- Additive only. Existing patients, user_accounts rows and
-- doctor/patient behaviour are untouched:
--   * user_accounts.role CHECK is widened to also allow 'ngo'
--   * NGO organizations, memberships and server-side sessions
--   * patient <-> NGO registration link (patients table unchanged)
--   * CSV import history + per-row results
--   * NGO audit events
-- Safe to re-run.
-- ============================================================

-- 1. Allow the 'ngo' role on user_accounts (drops only CHECK constraints
--    that reference the role column, then re-adds a widened one).
DO $$
DECLARE
    con RECORD;
BEGIN
    FOR con IN
        SELECT c.conname
        FROM pg_constraint c
        JOIN pg_class t ON t.oid = c.conrelid
        WHERE t.relname = 'user_accounts'
          AND c.contype = 'c'
          AND pg_get_constraintdef(c.oid) ILIKE '%role%'
    LOOP
        EXECUTE format('ALTER TABLE user_accounts DROP CONSTRAINT %I', con.conname);
    END LOOP;
END $$;

ALTER TABLE user_accounts
    ADD CONSTRAINT user_accounts_role_check
    CHECK (role IN ('doctor', 'patient', 'ngo'));

-- 2. NGO organizations
CREATE TABLE IF NOT EXISTS ngo_organizations (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name                TEXT NOT NULL,
    registration_number TEXT,
    contact_email       TEXT,
    contact_phone       TEXT,
    city                TEXT,
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_ngo_organizations_name
    ON ngo_organizations (lower(name));

-- 3. NGO memberships (one NGO per user account)
CREATE TABLE IF NOT EXISTS ngo_memberships (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ngo_id       UUID NOT NULL REFERENCES ngo_organizations(id) ON DELETE CASCADE,
    account_id   UUID NOT NULL REFERENCES user_accounts(id) ON DELETE CASCADE,
    member_role  TEXT NOT NULL DEFAULT 'staff' CHECK (member_role IN ('admin', 'staff')),
    is_active    BOOLEAN NOT NULL DEFAULT TRUE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_ngo_memberships_account UNIQUE (account_id)
);

CREATE INDEX IF NOT EXISTS idx_ngo_memberships_ngo ON ngo_memberships (ngo_id);

-- 4. Server-side NGO sessions (only a SHA-256 hash of the token is stored)
CREATE TABLE IF NOT EXISTS ngo_sessions (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    token_hash   TEXT NOT NULL UNIQUE,
    account_id   UUID NOT NULL REFERENCES user_accounts(id) ON DELETE CASCADE,
    ngo_id       UUID NOT NULL REFERENCES ngo_organizations(id) ON DELETE CASCADE,
    expires_at   TIMESTAMPTZ NOT NULL,
    revoked_at   TIMESTAMPTZ,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ngo_sessions_account ON ngo_sessions (account_id);

-- 5. CSV import batches
CREATE TABLE IF NOT EXISTS ngo_patient_imports (
    id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ngo_id                 UUID NOT NULL REFERENCES ngo_organizations(id) ON DELETE CASCADE,
    created_by_account_id  UUID REFERENCES user_accounts(id) ON DELETE SET NULL,
    file_name              TEXT,
    file_size_bytes        INTEGER NOT NULL DEFAULT 0,
    default_doctor_id      UUID REFERENCES doctors(id) ON DELETE SET NULL,
    column_mapping         JSONB NOT NULL DEFAULT '{}'::jsonb,
    status                 TEXT NOT NULL DEFAULT 'previewed'
                           CHECK (status IN ('previewed', 'processing', 'completed', 'failed')),
    total_rows             INTEGER NOT NULL DEFAULT 0,
    valid_rows             INTEGER NOT NULL DEFAULT 0,
    invalid_rows           INTEGER NOT NULL DEFAULT 0,
    duplicate_rows         INTEGER NOT NULL DEFAULT 0,
    review_rows            INTEGER NOT NULL DEFAULT 0,
    inserted_count         INTEGER NOT NULL DEFAULT 0,
    skipped_count          INTEGER NOT NULL DEFAULT 0,
    failed_count           INTEGER NOT NULL DEFAULT 0,
    confirmed_by_account_id UUID REFERENCES user_accounts(id) ON DELETE SET NULL,
    confirmed_at           TIMESTAMPTZ,
    completed_at           TIMESTAMPTZ,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ngo_patient_imports_ngo
    ON ngo_patient_imports (ngo_id, created_at DESC);

-- 6. Per-row preview/import results
CREATE TABLE IF NOT EXISTS ngo_patient_import_rows (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    import_id    UUID NOT NULL REFERENCES ngo_patient_imports(id) ON DELETE CASCADE,
    row_number   INTEGER NOT NULL,
    raw_data     JSONB NOT NULL DEFAULT '{}'::jsonb,
    normalized   JSONB,
    status       TEXT NOT NULL
                 CHECK (status IN ('valid', 'invalid', 'duplicate', 'review',
                                   'inserted', 'skipped', 'failed')),
    errors       JSONB NOT NULL DEFAULT '[]'::jsonb,
    patient_id   UUID REFERENCES patients(id) ON DELETE SET NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_ngo_patient_import_rows UNIQUE (import_id, row_number)
);

-- 7. Patient registration provenance (one row per NGO-registered patient)
CREATE TABLE IF NOT EXISTS ngo_patient_registrations (
    id                        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id                UUID NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    ngo_id                    UUID NOT NULL REFERENCES ngo_organizations(id) ON DELETE CASCADE,
    source                    TEXT NOT NULL CHECK (source IN ('manual', 'csv')),
    import_id                 UUID REFERENCES ngo_patient_imports(id) ON DELETE SET NULL,
    registered_by_account_id  UUID REFERENCES user_accounts(id) ON DELETE SET NULL,
    idempotency_key           TEXT,
    created_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_ngo_patient_registrations_patient UNIQUE (patient_id)
);

CREATE INDEX IF NOT EXISTS idx_ngo_patient_registrations_ngo
    ON ngo_patient_registrations (ngo_id, created_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS uq_ngo_patient_registrations_idempotency
    ON ngo_patient_registrations (ngo_id, idempotency_key)
    WHERE idempotency_key IS NOT NULL;

-- 8. NGO audit events (no passwords/tokens/clinical payloads)
CREATE TABLE IF NOT EXISTS ngo_audit_events (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ngo_id       UUID REFERENCES ngo_organizations(id) ON DELETE SET NULL,
    account_id   UUID REFERENCES user_accounts(id) ON DELETE SET NULL,
    action       TEXT NOT NULL,
    entity_type  TEXT,
    entity_id    TEXT,
    metadata     JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ngo_audit_events_ngo
    ON ngo_audit_events (ngo_id, created_at DESC);
