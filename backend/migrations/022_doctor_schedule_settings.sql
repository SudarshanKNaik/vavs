-- ============================================================
-- Migration 022: Editable schedule rules per doctor
-- ============================================================
-- Replaces the fixed clinic rules (10:30 AM to 4:30 PM, 30-minute
-- slots, 1:30 to 2:30 PM break, Sundays closed, 30 days ahead).
-- A doctor without a row uses those values as defaults.
-- working_days uses ISO weekdays: 1 = Monday ... 7 = Sunday.
-- Additive only. Safe to re-run.
-- ============================================================

CREATE TABLE IF NOT EXISTS doctor_schedule_settings (
    doctor_id UUID PRIMARY KEY REFERENCES doctors(id) ON DELETE CASCADE,
    day_start TIME NOT NULL DEFAULT '10:30',
    day_end TIME NOT NULL DEFAULT '16:30',
    break_start TIME DEFAULT '13:30',
    break_end TIME DEFAULT '14:30',
    slot_minutes INTEGER NOT NULL DEFAULT 30,
    working_days SMALLINT[] NOT NULL DEFAULT '{1,2,3,4,5,6}',
    window_days INTEGER NOT NULL DEFAULT 30,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT doctor_schedule_hours_check CHECK (day_start < day_end),
    CONSTRAINT doctor_schedule_break_check CHECK (
        (break_start IS NULL AND break_end IS NULL)
        OR (break_start IS NOT NULL AND break_end IS NOT NULL
            AND break_start < break_end
            AND break_start >= day_start AND break_end <= day_end)
    ),
    CONSTRAINT doctor_schedule_slot_minutes_check CHECK (slot_minutes BETWEEN 10 AND 120),
    CONSTRAINT doctor_schedule_window_check CHECK (window_days BETWEEN 1 AND 90),
    CONSTRAINT doctor_schedule_days_check CHECK (
        cardinality(working_days) >= 1 AND working_days <@ ARRAY[1,2,3,4,5,6,7]::SMALLINT[]
    )
);
