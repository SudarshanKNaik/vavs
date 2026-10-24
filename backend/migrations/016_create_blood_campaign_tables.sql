-- ============================================================
-- Migration 016: Blood Campaign Feature Tables
-- ============================================================
-- Additive schema for donor/NGO uploads, campaign orchestration,
-- and donor call attempt tracking.
-- Safe to re-run using IF NOT EXISTS semantics.
-- ============================================================

CREATE TABLE IF NOT EXISTS call_worker_pools (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    doctor_id TEXT NOT NULL,
    worker_name TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    phone_number_id TEXT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (doctor_id, worker_name)
);

CREATE TABLE IF NOT EXISTS blood_donors (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    doctor_id TEXT NOT NULL,
    name TEXT NOT NULL,
    gender TEXT NOT NULL,
    phone_number TEXT NOT NULL,
    location TEXT NOT NULL,
    latitude NUMERIC(10, 7),
    longitude NUMERIC(10, 7),
    last_donated_date DATE NOT NULL,
    blood_type TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (doctor_id, phone_number)
);

CREATE TABLE IF NOT EXISTS blood_ngos (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    doctor_id TEXT NOT NULL,
    ngo_name TEXT NOT NULL,
    phone_number TEXT NOT NULL,
    location TEXT NOT NULL,
    latitude NUMERIC(10, 7),
    longitude NUMERIC(10, 7),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (doctor_id, phone_number, ngo_name)
);

CREATE TABLE IF NOT EXISTS blood_campaigns (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    doctor_id TEXT NOT NULL,
    blood_type TEXT NOT NULL,
    recipient_name TEXT NOT NULL,
    reason TEXT,
    patient_location TEXT,
    patient_latitude NUMERIC(10, 7),
    patient_longitude NUMERIC(10, 7),
    batch_size INTEGER NOT NULL DEFAULT 3,
    status TEXT NOT NULL DEFAULT 'draft',
    accepted_donor_id UUID REFERENCES blood_donors(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS blood_campaign_donor_attempts (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    campaign_id UUID NOT NULL REFERENCES blood_campaigns(id) ON DELETE CASCADE,
    donor_id UUID NOT NULL REFERENCES blood_donors(id) ON DELETE CASCADE,
    worker_pool_id UUID REFERENCES call_worker_pools(id) ON DELETE SET NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    eligibility_reason TEXT,
    call_sid TEXT,
    conversation_id TEXT,
    outcome TEXT,
    message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    UNIQUE (campaign_id, donor_id)
);

CREATE INDEX IF NOT EXISTS idx_blood_donors_doctor_id
    ON blood_donors(doctor_id);

CREATE INDEX IF NOT EXISTS idx_blood_donors_blood_type
    ON blood_donors(blood_type);

CREATE INDEX IF NOT EXISTS idx_blood_campaigns_doctor_status
    ON blood_campaigns(doctor_id, status);

CREATE INDEX IF NOT EXISTS idx_blood_attempts_campaign_status
    ON blood_campaign_donor_attempts(campaign_id, status);

CREATE INDEX IF NOT EXISTS idx_worker_pools_doctor_active
    ON call_worker_pools(doctor_id, is_active);
