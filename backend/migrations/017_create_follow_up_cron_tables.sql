-- ============================================================
-- Migration 017: Follow-up Cron Queue and Logs
-- ============================================================
-- Tracks delayed follow-up workflow triggers when appointment
-- booking did not complete during or immediately after a call.
-- Safe to re-run.
-- ============================================================

CREATE TABLE IF NOT EXISTS follow_up_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    call_log_id UUID NOT NULL REFERENCES call_logs(id) ON DELETE CASCADE,
    workflow_id UUID REFERENCES workflows(id) ON DELETE SET NULL,
    doctor_id TEXT,
    patient_id UUID REFERENCES patients(id) ON DELETE SET NULL,
    reason TEXT,
    status TEXT NOT NULL DEFAULT 'queued',
    scheduled_for TIMESTAMPTZ NOT NULL,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    last_run_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    last_error TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_follow_up_jobs_call_log UNIQUE (call_log_id)
);

CREATE TABLE IF NOT EXISTS follow_up_job_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id UUID NOT NULL REFERENCES follow_up_jobs(id) ON DELETE CASCADE,
    level TEXT NOT NULL DEFAULT 'info',
    message TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_follow_up_jobs_doctor
    ON follow_up_jobs (doctor_id, status, scheduled_for);

CREATE INDEX IF NOT EXISTS idx_follow_up_jobs_due
    ON follow_up_jobs (status, scheduled_for);

CREATE INDEX IF NOT EXISTS idx_follow_up_job_logs_job
    ON follow_up_job_logs (job_id, created_at DESC);
