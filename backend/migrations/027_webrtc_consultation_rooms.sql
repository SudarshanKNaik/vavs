-- ============================================================
-- Migration 027: Own WebRTC video calls for consultations
-- ============================================================
-- Video consultations moved off the meet.jit.si embed (which makes
-- the first participant sign in) to a built-in 1:1 WebRTC call.
-- Allow the 'webrtc' provider and point existing Jitsi rooms at the
-- consultation page. Safe to re-run.
-- ============================================================

ALTER TABLE consultation_rooms DROP CONSTRAINT IF EXISTS consultation_rooms_provider_check;
ALTER TABLE consultation_rooms ADD CONSTRAINT consultation_rooms_provider_check
    CHECK (provider IN ('daily', '100ms', 'twilio', 'webrtc'));

UPDATE consultation_rooms
SET provider = 'webrtc',
    room_url = '/consultation/' || appointment_id::text
WHERE room_url LIKE 'https://meet.jit.si/%';
