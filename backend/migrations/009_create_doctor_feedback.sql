-- Doctor feedback table
CREATE TABLE IF NOT EXISTS doctor_feedback (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    doctor_id UUID NOT NULL REFERENCES doctors(id) ON DELETE CASCADE,
    patient_id UUID REFERENCES patients(id) ON DELETE SET NULL,
    rating INT NOT NULL CHECK (rating >= 1 AND rating <= 5),
    comment TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_feedback_doctor ON doctor_feedback(doctor_id);
CREATE INDEX IF NOT EXISTS idx_feedback_patient ON doctor_feedback(patient_id);
