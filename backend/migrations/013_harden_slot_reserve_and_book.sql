-- =========================================================================
-- Harden slot reserve/book flow for patient portal
--
-- Fixes:
-- 1) Allow reserve refresh when the slot is already reserved by the same
--    patient (idempotent reserve).
-- 2) Clear reserved_by when converting reserved -> booked.
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
           OR (
               status = 'reserved'
               AND (
                   reserved_by = p_patient_id
                   OR (reserved_until IS NOT NULL AND reserved_until < now())
               )
           )
       )
    RETURNING *;
END;
$$;


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
           reserved_by = NULL,
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
