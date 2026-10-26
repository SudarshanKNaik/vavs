-- ============================================================
-- Migration 031: SMS + email messages for blood requests
-- ============================================================
-- One row per message sent for a blood request, alongside the calls:
-- donor/organization confirmations, appeals to donors who missed the
-- call, updates to the request's contact person and a summary email to
-- the requesting doctor. dedupe_key makes each message send at most once.
-- Additive only. Safe to re-run.
-- ============================================================

CREATE TABLE IF NOT EXISTS blood_campaign_messages (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    campaign_id  UUID NOT NULL REFERENCES blood_campaigns(id) ON DELETE CASCADE,
    attempt_id   UUID REFERENCES blood_campaign_donor_attempts(id) ON DELETE CASCADE,
    kind         TEXT NOT NULL CHECK (kind IN (
                     'donor_accepted', 'org_accepted', 'donor_missed',
                     'contact_update', 'contact_summary', 'doctor_summary')),
    channel      TEXT NOT NULL CHECK (channel IN ('sms', 'email')),
    recipient    TEXT NOT NULL,              -- masked phone or email
    status       TEXT NOT NULL DEFAULT 'pending'
                 CHECK (status IN ('pending', 'sent', 'failed', 'skipped')),
    detail       TEXT,
    dedupe_key   TEXT NOT NULL UNIQUE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_blood_campaign_messages_campaign
    ON blood_campaign_messages (campaign_id, created_at);
