-- ============================================================
-- Migration 025: NGO Darpan ID
-- ============================================================
-- NGOs register with a 5-digit Darpan ID; one NGO per Darpan ID.
-- Nullable so organizations created before this migration (or by
-- operators via scripts/create_ngo_account.py) remain valid.
-- Safe to re-run.
-- ============================================================

ALTER TABLE ngo_organizations
    ADD COLUMN IF NOT EXISTS darpan_id TEXT;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'ngo_organizations_darpan_id_format'
    ) THEN
        ALTER TABLE ngo_organizations
            ADD CONSTRAINT ngo_organizations_darpan_id_format
            CHECK (darpan_id IS NULL OR darpan_id ~ '^[0-9]{5}$');
    END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_ngo_organizations_darpan_id
    ON ngo_organizations (darpan_id)
    WHERE darpan_id IS NOT NULL;
