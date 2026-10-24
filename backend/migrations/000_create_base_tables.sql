-- =========================================================================
-- CareSync AI / MedTrigger — BASE schema
-- Run this FIRST in the Supabase SQL Editor BEFORE running 001_create_new_tables.sql
-- Dashboard → SQL Editor → New Query → paste → Run
-- =========================================================================

-- 1. Workflows
CREATE TABLE IF NOT EXISTS workflows (
    id          UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    doctor_id   TEXT NOT NULL,
    name        TEXT NOT NULL,
    description TEXT,
    category    TEXT NOT NULL DEFAULT 'Ungrouped',
    status      TEXT NOT NULL DEFAULT 'DRAFT',
    nodes       JSONB NOT NULL DEFAULT '[]'::JSONB,
    edges       JSONB NOT NULL DEFAULT '[]'::JSONB,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 2. Patients
CREATE TABLE IF NOT EXISTS patients (
    id                UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    doctor_id         TEXT NOT NULL,
    name              TEXT NOT NULL,
    phone             TEXT NOT NULL,
    dob               TEXT,
    mrn               TEXT,
    insurance         TEXT,
    primary_physician TEXT,
    last_visit        TEXT,
    risk_level        TEXT NOT NULL DEFAULT 'low',
    notes             TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 3. Call logs
CREATE TABLE IF NOT EXISTS call_logs (
    id             UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    workflow_id    UUID REFERENCES workflows(id) ON DELETE SET NULL,
    patient_id     UUID REFERENCES patients(id) ON DELETE SET NULL,
    trigger_node   TEXT,
    status         TEXT NOT NULL DEFAULT 'running',
    outcome        TEXT,
    execution_log  JSONB NOT NULL DEFAULT '[]'::JSONB,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 4. Patient conditions
CREATE TABLE IF NOT EXISTS patient_conditions (
    id           UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    patient_id   UUID NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    icd10_code   TEXT NOT NULL,
    description  TEXT NOT NULL,
    hcc_category TEXT,
    raf_impact   NUMERIC NOT NULL DEFAULT 0,
    status       TEXT NOT NULL DEFAULT 'documented',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 5. Patient medications
CREATE TABLE IF NOT EXISTS patient_medications (
    id           UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    patient_id   UUID NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    name         TEXT NOT NULL,
    dosage       TEXT,
    frequency    TEXT,
    route        TEXT,
    prescriber   TEXT,
    start_date   TEXT,
    end_date     TEXT,
    status       TEXT NOT NULL DEFAULT 'active',
    notes        TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_workflows_doctor     ON workflows(doctor_id);
CREATE INDEX IF NOT EXISTS idx_patients_doctor      ON patients(doctor_id);
CREATE INDEX IF NOT EXISTS idx_call_logs_workflow   ON call_logs(workflow_id);
CREATE INDEX IF NOT EXISTS idx_call_logs_patient    ON call_logs(patient_id);
CREATE INDEX IF NOT EXISTS idx_conditions_patient   ON patient_conditions(patient_id);
CREATE INDEX IF NOT EXISTS idx_medications_patient  ON patient_medications(patient_id);
