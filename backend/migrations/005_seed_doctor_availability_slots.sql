-- =========================================================================
-- Seed data: Availability slots for active doctors
-- =========================================================================
-- Creates future slots for all active doctors so patient booking works out of the box.
-- Safe to re-run: avoids duplicates using doctor_id + slot_start + slot_end check.

WITH day_offsets AS (
    SELECT generate_series(0, 6) AS day_offset
),
time_templates AS (
    -- slot_start_time, slot_end_time
    SELECT time '09:00' AS start_time, time '09:30' AS end_time
    UNION ALL SELECT time '11:30' AS start_time, time '12:00' AS end_time
    UNION ALL SELECT time '15:00' AS start_time, time '15:30' AS end_time
),
seed_slots AS (
    SELECT
        d.id AS doctor_id,
        ((CURRENT_DATE + o.day_offset) + t.start_time)::timestamptz AS slot_start,
        ((CURRENT_DATE + o.day_offset) + t.end_time)::timestamptz AS slot_end
    FROM doctors d
    CROSS JOIN day_offsets o
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
WHERE NOT EXISTS (
    SELECT 1
    FROM availability_slots a
    WHERE a.doctor_id = s.doctor_id
      AND a.slot_start = s.slot_start
      AND a.slot_end = s.slot_end
);
