-- ============================================================
-- Migration 020: Track who cancelled / rescheduled appointments
-- ============================================================
-- A patient's cancel or reschedule used to leave only a free-text
-- note, so the doctor's dashboard couldn't tell a reschedule from
-- a cancellation, or show which time the patient moved to.
-- Additive only. Safe to re-run.
-- ============================================================

ALTER TABLE appointments
    ADD COLUMN IF NOT EXISTS cancelled_by TEXT,
    ADD COLUMN IF NOT EXISTS cancelled_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS rescheduled_to_appointment_id UUID
        REFERENCES appointments(id) ON DELETE SET NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'appointments_cancelled_by_check'
    ) THEN
        ALTER TABLE appointments ADD CONSTRAINT appointments_cancelled_by_check
            CHECK (cancelled_by IS NULL OR cancelled_by IN ('patient', 'doctor', 'system'));
    END IF;
END $$;

-- Backfill from the notes older rows were written with.
UPDATE appointments
SET cancelled_by = CASE
        WHEN notes ILIKE '%Cancelled by patient%' OR notes ILIKE '%Rescheduled to slot%' THEN 'patient'
        WHEN notes ILIKE '%Cancelled by doctor%' THEN 'doctor'
        ELSE 'system'
    END,
    cancelled_at = COALESCE(cancelled_at, updated_at)
WHERE status = 'cancelled' AND cancelled_by IS NULL;

CREATE INDEX IF NOT EXISTS idx_appointments_doctor_cancelled_at
    ON appointments(doctor_id, cancelled_at DESC)
    WHERE cancelled_at IS NOT NULL;
