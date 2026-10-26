-- ============================================================
-- Migration 021: Google Calendar connection per doctor
-- ============================================================
-- Each doctor connects their own Google Calendar with OAuth. The
-- refresh token lets the backend keep their calendar in sync with
-- bookings, cancellations and reschedules, and read busy times so
-- clashing slots aren't offered to patients.
-- Additive only. Safe to re-run.
-- ============================================================

CREATE TABLE IF NOT EXISTS doctor_google_calendar (
    doctor_id UUID PRIMARY KEY REFERENCES doctors(id) ON DELETE CASCADE,
    google_email TEXT,
    calendar_id TEXT NOT NULL DEFAULT 'primary',
    refresh_token TEXT NOT NULL,
    access_token TEXT,
    access_token_expires_at TIMESTAMPTZ,
    scopes TEXT,
    connected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_error TEXT
);

-- The Google event created for an appointment, so a cancel or reschedule
-- can delete it.
ALTER TABLE appointments
    ADD COLUMN IF NOT EXISTS google_event_id TEXT;
