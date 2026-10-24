-- ============================================================
-- Migration 015: Report-Aware Call Linkage
-- ============================================================
-- Adds report/doctor context columns to call_logs and
-- appointment linkage columns to appointments so that the
-- "Report-Aware Call-to-Booking Bot" can trace each call back
-- to the triggering report and forward to the resulting
-- appointment.
-- Safe to re-run: all statements use IF NOT EXISTS.
-- ============================================================

-- ------------------------------------------------------------
-- call_logs – new columns
-- ------------------------------------------------------------

-- Link a call_log to the report that triggered the workflow
ALTER TABLE call_logs
    ADD COLUMN IF NOT EXISTS report_id UUID REFERENCES reports(id) ON DELETE SET NULL;

-- Doctor identifier stored as TEXT to avoid FK type-mismatch
-- issues (workflow engine stores doctor_id as text strings).
ALTER TABLE call_logs
    ADD COLUMN IF NOT EXISTS doctor_id TEXT;

-- Serialised list of slot-option dicts offered to the patient
-- during the call (populated by _handle_call_patient).
ALTER TABLE call_logs
    ADD COLUMN IF NOT EXISTS slot_options JSONB DEFAULT '[]'::jsonb;

-- Reference to the ElevenLabs conversation_id / callSid so we
-- can fetch the full transcript later without re-scanning
-- execution_log JSON.
ALTER TABLE call_logs
    ADD COLUMN IF NOT EXISTS transcript_ref TEXT;

-- Ordered list of status-change events for this call,
-- e.g. [{"status":"initiated","timestamp":"..."},
--        {"status":"completed","timestamp":"..."}]
ALTER TABLE call_logs
    ADD COLUMN IF NOT EXISTS status_timeline JSONB DEFAULT '[]'::jsonb;

-- ------------------------------------------------------------
-- appointments – new columns
-- ------------------------------------------------------------

-- Link an appointment back to the report that prompted the call
ALTER TABLE appointments
    ADD COLUMN IF NOT EXISTS report_id UUID REFERENCES reports(id) ON DELETE SET NULL;

-- Link an appointment to the call_log that produced it
ALTER TABLE appointments
    ADD COLUMN IF NOT EXISTS call_log_id UUID REFERENCES call_logs(id) ON DELETE SET NULL;

-- Freeform metadata about how / where the booking originated
-- e.g. {"source":"elevenlabs_webhook","conversation_id":"..."}
ALTER TABLE appointments
    ADD COLUMN IF NOT EXISTS call_origin JSONB;

-- ------------------------------------------------------------
-- Indexes
-- ------------------------------------------------------------

-- call_logs
CREATE INDEX IF NOT EXISTS idx_call_logs_report_id
    ON call_logs (report_id)
    WHERE report_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_call_logs_doctor_id
    ON call_logs (doctor_id)
    WHERE doctor_id IS NOT NULL;

-- appointments
CREATE INDEX IF NOT EXISTS idx_appointments_report_id
    ON appointments (report_id)
    WHERE report_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_appointments_call_log_id
    ON appointments (call_log_id)
    WHERE call_log_id IS NOT NULL;

-- Composite: look up all call-originated appointments quickly
CREATE INDEX IF NOT EXISTS idx_appointments_call_origin_not_null
    ON appointments (doctor_id, patient_id)
    WHERE call_origin IS NOT NULL;
