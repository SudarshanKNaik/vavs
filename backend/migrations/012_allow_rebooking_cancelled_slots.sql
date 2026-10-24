-- =========================================================================
-- Allow slot re-booking after cancellation
--
-- Problem:
-- A strict unique index on appointments(slot_id) prevents creating a new
-- appointment for the same slot when a previous appointment was cancelled.
-- The slot can be reserved, but final booking insert fails with duplicate key.
--
-- Fix:
-- Keep slot uniqueness only for non-cancelled appointments.
-- This preserves double-booking protection while allowing re-booking of
-- cancelled slots.
-- =========================================================================

DROP INDEX IF EXISTS uq_appointments_slot_id;

CREATE UNIQUE INDEX IF NOT EXISTS uq_appointments_slot_id
ON appointments(slot_id)
WHERE status <> 'cancelled';
