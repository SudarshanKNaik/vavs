-- ============================================================
-- Migration 019: Blood request details on blood campaigns
-- ============================================================
-- A doctor's blood request is stored as a blood_campaign so it
-- reuses the existing donor-calling engine. These columns hold
-- what the doctor fills in on the Blood Request form.
-- Additive only. Safe to re-run.
-- ============================================================

ALTER TABLE blood_campaigns
    ADD COLUMN IF NOT EXISTS component TEXT NOT NULL DEFAULT 'whole_blood',
    ADD COLUMN IF NOT EXISTS units_needed INTEGER NOT NULL DEFAULT 1,
    ADD COLUMN IF NOT EXISTS urgency TEXT NOT NULL DEFAULT 'urgent',
    ADD COLUMN IF NOT EXISTS required_by TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS hospital_name TEXT,
    ADD COLUMN IF NOT EXISTS ward TEXT,
    ADD COLUMN IF NOT EXISTS contact_name TEXT,
    ADD COLUMN IF NOT EXISTS contact_phone TEXT,
    ADD COLUMN IF NOT EXISTS patient_id UUID REFERENCES patients(id) ON DELETE SET NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'blood_campaigns_component_check'
    ) THEN
        ALTER TABLE blood_campaigns ADD CONSTRAINT blood_campaigns_component_check
            CHECK (component IN ('whole_blood', 'packed_rbc', 'platelets', 'plasma'));
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'blood_campaigns_urgency_check'
    ) THEN
        ALTER TABLE blood_campaigns ADD CONSTRAINT blood_campaigns_urgency_check
            CHECK (urgency IN ('emergency', 'urgent', 'planned'));
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'blood_campaigns_units_needed_check'
    ) THEN
        ALTER TABLE blood_campaigns ADD CONSTRAINT blood_campaigns_units_needed_check
            CHECK (units_needed BETWEEN 1 AND 20);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_blood_campaigns_doctor_created
    ON blood_campaigns(doctor_id, created_at DESC);
