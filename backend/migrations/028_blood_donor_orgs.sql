-- ============================================================
-- Migration 028: Blood donor organizations + multi-target attempts
-- ============================================================
-- blood_donor_org holds organizations that store blood (blood banks,
-- hospitals, NGOs). It replaces blood_ngos as the list shown on the map and
-- as a call target for blood requests whose source is 'orgs' or 'any'.
-- blood_ngos is left in place, unused; its rows are copied across once.
--
-- Call attempts can now target a donor OR an organization, an organization
-- can be retried once after a hang-up (attempt_number), and units_confirmed
-- records what an organization promised, for later supplier-trust analysis.
-- Additive and safe to re-run.
-- ============================================================

CREATE TABLE IF NOT EXISTS blood_donor_org (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    doctor_id TEXT NOT NULL,
    org_name TEXT NOT NULL,
    phone_number TEXT NOT NULL,
    location TEXT NOT NULL,
    latitude NUMERIC(10, 7),
    longitude NUMERIC(10, 7),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (doctor_id, phone_number, org_name)
);

CREATE INDEX IF NOT EXISTS idx_blood_donor_org_doctor_id
    ON blood_donor_org(doctor_id);

INSERT INTO blood_donor_org (
    doctor_id, org_name, phone_number, location, latitude, longitude, created_at, updated_at
)
SELECT doctor_id, ngo_name, phone_number, location, latitude, longitude, created_at, updated_at
FROM blood_ngos
ON CONFLICT (doctor_id, phone_number, org_name) DO NOTHING;

-- Where a blood request may be fulfilled from, and how far to look.
ALTER TABLE blood_campaigns
    ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'donors',
    ADD COLUMN IF NOT EXISTS radius_km NUMERIC(6, 2) NOT NULL DEFAULT 20;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'blood_campaigns_source_check'
    ) THEN
        ALTER TABLE blood_campaigns ADD CONSTRAINT blood_campaigns_source_check
            CHECK (source IN ('donors', 'orgs', 'any'));
    END IF;
END $$;

-- Attempts: donor OR org, several attempts per target.
ALTER TABLE blood_campaign_donor_attempts
    ADD COLUMN IF NOT EXISTS org_id UUID REFERENCES blood_donor_org(id) ON DELETE CASCADE,
    ADD COLUMN IF NOT EXISTS target_type TEXT NOT NULL DEFAULT 'donor',
    ADD COLUMN IF NOT EXISTS attempt_number INTEGER NOT NULL DEFAULT 1,
    ADD COLUMN IF NOT EXISTS units_confirmed INTEGER;

ALTER TABLE blood_campaign_donor_attempts
    ALTER COLUMN donor_id DROP NOT NULL;

ALTER TABLE blood_campaign_donor_attempts
    DROP CONSTRAINT IF EXISTS blood_campaign_donor_attempts_campaign_id_donor_id_key;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'blood_attempts_target_check'
    ) THEN
        ALTER TABLE blood_campaign_donor_attempts ADD CONSTRAINT blood_attempts_target_check
            CHECK (
                (target_type = 'donor' AND donor_id IS NOT NULL AND org_id IS NULL)
                OR (target_type = 'org' AND org_id IS NOT NULL AND donor_id IS NULL)
            );
    END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_blood_attempts_donor
    ON blood_campaign_donor_attempts(campaign_id, donor_id, attempt_number)
    WHERE donor_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_blood_attempts_org
    ON blood_campaign_donor_attempts(campaign_id, org_id, attempt_number)
    WHERE org_id IS NOT NULL;

-- Supplier history: how often has each organization said yes?
CREATE INDEX IF NOT EXISTS idx_blood_attempts_org
    ON blood_campaign_donor_attempts(org_id, status)
    WHERE org_id IS NOT NULL;
