-- =========================================================================
-- Fix false negatives in book_reserved_slot reservation check
--
-- Replaces SELECT ... FOR UPDATE + FOUND check with a single UPDATE ...
-- RETURNING path, then inserts appointment from that returned row.
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
    v_doctor_id UUID;
    v_appointment appointments;
BEGIN
    UPDATE availability_slots
       SET status = 'booked',
           reserved_by = NULL,
           reserved_until = NULL,
           updated_at = now()
     WHERE id = p_slot_id
       AND status = 'reserved'
       AND reserved_by = p_patient_id
       AND reserved_until IS NOT NULL
       AND reserved_until >= now()
    RETURNING doctor_id INTO v_doctor_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Slot is not reserved for this patient or reservation expired';
    END IF;

    INSERT INTO appointments (
        doctor_id,
        patient_id,
        slot_id,
        status,
        consultation_type,
        notes
    ) VALUES (
        v_doctor_id,
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
