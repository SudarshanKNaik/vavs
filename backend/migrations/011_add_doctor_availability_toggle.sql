-- Add doctor-level availability toggle used by rolling slot generation logic.
ALTER TABLE doctors
ADD COLUMN IF NOT EXISTS is_available BOOLEAN NOT NULL DEFAULT TRUE;

CREATE INDEX IF NOT EXISTS idx_doctors_is_available ON doctors(is_available);
