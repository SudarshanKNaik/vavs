-- =========================================================================
-- CareSync AIw / MedTrigger — Doctor Availability + Teleconsultation schema
-- Phase 0 foundation for directory, booking, consultation, reminders, feedback
-- Run after:
--   000_create_base_tables.sql
--   001_create_new_tables.sql
-- =========================================================================

-- 1) Doctor profile model
CREATE TABLE IF NOT EXISTS doctors (
    id                 UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    auth_user_id       TEXT,
    name               TEXT NOT NULL,
    specialty          TEXT NOT NULL,
    language           TEXT NOT NULL,
    consultation_type  TEXT NOT NULL CHECK (consultation_type IN ('video', 'chat', 'in_person', 'hybrid')),
    fee                NUMERIC(10,2) NOT NULL DEFAULT 0,
    rating_avg         NUMERIC(3,2) NOT NULL DEFAULT 0,
    rating_count       INTEGER NOT NULL DEFAULT 0,
    active             BOOLEAN NOT NULL DEFAULT true,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 2) Availability slots model
CREATE TABLE IF NOT EXISTS availability_slots (
    id                 UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    doctor_id          UUID NOT NULL REFERENCES doctors(id) ON DELETE CASCADE,
    slot_start         TIMESTAMPTZ NOT NULL,
    slot_end           TIMESTAMPTZ NOT NULL,
    status             TEXT NOT NULL DEFAULT 'available' CHECK (status IN ('available', 'reserved', 'booked', 'cancelled')),
    reserved_until     TIMESTAMPTZ,
    reserved_by        UUID REFERENCES patients(id) ON DELETE SET NULL,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (slot_end > slot_start)
);

-- Prevent duplicate slot creation for same doctor/time window
CREATE UNIQUE INDEX IF NOT EXISTS uq_availability_slot_doctor_time
ON availability_slots(doctor_id, slot_start, slot_end);

-- 3) Appointment model
CREATE TABLE IF NOT EXISTS appointments (
    id                 UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    doctor_id          UUID NOT NULL REFERENCES doctors(id) ON DELETE CASCADE,
    patient_id         UUID NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    slot_id            UUID NOT NULL REFERENCES availability_slots(id) ON DELETE RESTRICT,
    status             TEXT NOT NULL DEFAULT 'booked' CHECK (status IN ('booked', 'confirmed', 'in_progress', 'completed', 'cancelled', 'no_show')),
    consultation_type  TEXT NOT NULL CHECK (consultation_type IN ('video', 'chat', 'in_person')),
    notes              TEXT,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Booking safety: one slot can map to only one appointment
CREATE UNIQUE INDEX IF NOT EXISTS uq_appointments_slot_id
ON appointments(slot_id);

-- 4) Consultation room model (one room per appointment)
CREATE TABLE IF NOT EXISTS consultation_rooms (
    id                 UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    appointment_id     UUID NOT NULL REFERENCES appointments(id) ON DELETE CASCADE,
    provider           TEXT NOT NULL CHECK (provider IN ('daily', '100ms', 'twilio')),
    room_name          TEXT NOT NULL,
    room_url           TEXT,
    room_token         TEXT,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_consultation_room_appointment
ON consultation_rooms(appointment_id);

-- 5) Consultation chat messages
CREATE TABLE IF NOT EXISTS consultation_messages (
    id                 UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    appointment_id     UUID NOT NULL REFERENCES appointments(id) ON DELETE CASCADE,
    room_id            UUID REFERENCES consultation_rooms(id) ON DELETE SET NULL,
    sender_type        TEXT NOT NULL CHECK (sender_type IN ('doctor', 'patient', 'system')),
    sender_id          TEXT,
    message            TEXT NOT NULL,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 6) Post-consult feedback
CREATE TABLE IF NOT EXISTS consultation_feedback (
    id                 UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    appointment_id     UUID NOT NULL REFERENCES appointments(id) ON DELETE CASCADE,
    doctor_id          UUID NOT NULL REFERENCES doctors(id) ON DELETE CASCADE,
    patient_id         UUID NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    rating             INTEGER NOT NULL CHECK (rating >= 1 AND rating <= 5),
    comment            TEXT,
    tags               TEXT[] NOT NULL DEFAULT '{}',
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One feedback per appointment
CREATE UNIQUE INDEX IF NOT EXISTS uq_feedback_appointment
ON consultation_feedback(appointment_id);

-- Required indexes from checklist
CREATE INDEX IF NOT EXISTS idx_availability_slots_doctor_id ON availability_slots(doctor_id);
CREATE INDEX IF NOT EXISTS idx_availability_slots_slot_start ON availability_slots(slot_start);
CREATE INDEX IF NOT EXISTS idx_appointments_appointment_id ON appointments(id);

-- Additional useful indexes
CREATE INDEX IF NOT EXISTS idx_appointments_doctor_id ON appointments(doctor_id);
CREATE INDEX IF NOT EXISTS idx_appointments_patient_id ON appointments(patient_id);
CREATE INDEX IF NOT EXISTS idx_consultation_messages_appointment_id ON consultation_messages(appointment_id);
CREATE INDEX IF NOT EXISTS idx_feedback_doctor_id ON consultation_feedback(doctor_id);

-- =========================================================================
-- Atomic slot reservation helper
-- - Returns the reserved slot row if lock succeeded.
-- - Returns no rows if slot was not reservable.
-- =========================================================================
CREATE OR REPLACE FUNCTION reserve_availability_slot(
    p_slot_id UUID,
    p_patient_id UUID,
    p_hold_minutes INTEGER DEFAULT 10
)
RETURNS SETOF availability_slots
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    UPDATE availability_slots
       SET status = 'reserved',
           reserved_by = p_patient_id,
           reserved_until = now() + make_interval(mins => p_hold_minutes),
           updated_at = now()
     WHERE id = p_slot_id
       AND (
           status = 'available'
           OR (status = 'reserved' AND reserved_until IS NOT NULL AND reserved_until < now())
       )
    RETURNING *;
END;
$$;

-- =========================================================================
-- Atomic booking helper
-- - Converts a valid reserved slot into a booked appointment.
-- - Ensures the same slot cannot be double-booked.
-- =========================================================================
CREATE OR REPLACE FUNCTION book_reserved_slot(
    p_slot_id UUID,
    p_patient_id UUID,
    p_consultation_type TEXT DEFAULT 'video',
    p_notes TEXT DEFAULT NULL
)
RETURNS appointments
LANGUAGE plpgsql
AS $$
DECLARE
    v_slot availability_slots;
    v_appointment appointments;
BEGIN
    SELECT *
      INTO v_slot
      FROM availability_slots
     WHERE id = p_slot_id
       AND status = 'reserved'
       AND reserved_by = p_patient_id
       AND reserved_until IS NOT NULL
       AND reserved_until >= now()
     FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Slot is not reserved for this patient or reservation expired';
    END IF;

    UPDATE availability_slots
       SET status = 'booked',
           reserved_until = NULL,
           updated_at = now()
     WHERE id = p_slot_id;

    INSERT INTO appointments (
        doctor_id,
        patient_id,
        slot_id,
        status,
        consultation_type,
        notes
    ) VALUES (
        v_slot.doctor_id,
        p_patient_id,
        p_slot_id,
        'booked',
        p_consultation_type,
        p_notes
    )
    RETURNING * INTO v_appointment;

    RETURN v_appointment;
END;
$$;
