-- ============================================================
-- Migration 018: Remove off-schedule seed slots
-- ============================================================
-- Migration 005 seeds 09:00 / 11:30 / 15:00 slots in the
-- database's timezone (UTC) for 7 days, including Sundays.
-- In clinic time (Asia/Kolkata) that is 2:30 PM, 5:00 PM and
-- 8:30 PM, so most fall outside the clinic schedule
-- (10:30 AM to 4:30 PM, 1:30 to 2:30 PM break, Sundays closed).
-- The AI call agent and the patient portal offered these
-- times to patients.
--
-- Deletes only slots that are still 'available', are not
-- referenced by any appointment, and fall outside the schedule.
-- Booked, reserved and cancelled slots are never touched.
-- Safe to re-run.
-- ============================================================

DELETE FROM availability_slots s
WHERE s.status = 'available'
  AND NOT EXISTS (
        SELECT 1 FROM appointments a WHERE a.slot_id = s.id
  )
  AND (
        EXTRACT(DOW FROM (s.slot_start AT TIME ZONE 'Asia/Kolkata')) = 0
     OR (s.slot_start AT TIME ZONE 'Asia/Kolkata')::time < time '10:30'
     OR (s.slot_start AT TIME ZONE 'Asia/Kolkata')::time >= time '16:30'
     OR (
            (s.slot_start AT TIME ZONE 'Asia/Kolkata')::time >= time '13:30'
        AND (s.slot_start AT TIME ZONE 'Asia/Kolkata')::time <  time '14:30'
        )
  );
