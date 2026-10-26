-- ============================================================
-- Migration 029: Outbreak Watch (symptom surveillance)
-- ============================================================
-- Symptoms patients mention on AI calls are stored per call,
-- tagged with the patient's locality, and grouped into syndromes
-- (dengue-like, respiratory, gastro). The Outbreak Watch page
-- compares each area's last 7 days against its own baseline.
-- Additive only. Safe to re-run.
-- ============================================================

-- Neighbourhood / area the patient lives in, e.g. 'Old Hubli'.
ALTER TABLE patients
    ADD COLUMN IF NOT EXISTS locality TEXT;

CREATE TABLE IF NOT EXISTS symptom_reports (
    id           UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    doctor_id    TEXT NOT NULL,
    patient_id   UUID REFERENCES patients(id) ON DELETE SET NULL,
    call_log_id  UUID REFERENCES call_logs(id) ON DELETE CASCADE,
    -- 'ai_call' (from a real call) or 'demo' (sample data, removable)
    source       TEXT NOT NULL DEFAULT 'ai_call',
    locality     TEXT,
    latitude     NUMERIC(10, 7),
    longitude    NUMERIC(10, 7),
    symptoms     TEXT[] NOT NULL DEFAULT '{}',
    -- dengue_like | respiratory | gastro | fever
    syndrome     TEXT NOT NULL,
    reported_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- The webhook and the poller can both process the same call.
CREATE UNIQUE INDEX IF NOT EXISTS uq_symptom_reports_call_log
    ON symptom_reports (call_log_id)
    WHERE call_log_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_symptom_reports_doctor_time
    ON symptom_reports (doctor_id, reported_at DESC);
