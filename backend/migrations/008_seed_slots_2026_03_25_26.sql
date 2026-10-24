-- =========================================================================
-- Seed data: Availability slots for all active doctors on 25-26 March 2026
-- =========================================================================
-- Safe to re-run: prevents duplicates through unique (doctor_id, slot_start, slot_end).

WITH target_days AS (
    SELECT DATE '2026-03-25' AS day_value
    UNION ALL
    SELECT DATE '2026-03-26' AS day_value
),
time_templates AS (
    -- slot_start_time, slot_end_time
    SELECT time '09:00' AS start_time, time '09:30' AS end_time
    UNION ALL SELECT time '10:30' AS start_time, time '11:00' AS end_time
    UNION ALL SELECT time '14:00' AS start_time, time '14:30' AS end_time
    UNION ALL SELECT time '16:00' AS start_time, time '16:30' AS end_time
),
seed_slots AS (
    SELECT
        d.id AS doctor_id,
        ((day_value + t.start_time)::timestamp AT TIME ZONE 'Asia/Kolkata') AS slot_start,
        ((day_value + t.end_time)::timestamp AT TIME ZONE 'Asia/Kolkata') AS slot_end
    FROM doctors d
    CROSS JOIN target_days
    CROSS JOIN time_templates t
    WHERE d.active = true
)
INSERT INTO availability_slots (
    doctor_id,
    slot_start,
    slot_end,
    status,
    created_at,
    updated_at
)
SELECT
    s.doctor_id,
    s.slot_start,
    s.slot_end,
    'available',
    now(),
    now()
FROM seed_slots s
ON CONFLICT (doctor_id, slot_start, slot_end) DO NOTHING;
