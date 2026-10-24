-- =========================================================================
-- Seed data: Hubli, Karnataka doctors
-- =========================================================================
-- Note: The current doctors table has no dedicated location column.
-- To preserve location context, "(Hubli, Karnataka)" is included in doctor names.

-- -------------------------------------------------------------------------
-- 1) Migrate existing lab technician users to doctors
-- Source assumed: Supabase auth.users metadata role fields.
-- -------------------------------------------------------------------------

WITH lab_tech_users AS (
    SELECT
        u.id::text AS auth_user_id,
        COALESCE(
            NULLIF(u.raw_user_meta_data->>'full_name', ''),
            NULLIF(u.raw_user_meta_data->>'name', ''),
            split_part(u.email, '@', 1)
        ) AS base_name,
        COALESCE(u.email, '') AS email,
        lower(COALESCE(u.raw_user_meta_data->>'role', u.raw_app_meta_data->>'role', '')) AS role_value
    FROM auth.users u
    WHERE lower(COALESCE(u.raw_user_meta_data->>'role', u.raw_app_meta_data->>'role', ''))
          IN ('lab_technician', 'lab technician', 'lab-tech', 'labtech')
)
INSERT INTO doctors (
    auth_user_id,
    name,
    specialty,
    language,
    consultation_type,
    fee,
    rating_avg,
    rating_count,
    active
)
SELECT
    l.auth_user_id,
    CASE
        WHEN l.base_name ILIKE 'dr.%' THEN l.base_name || ' (Hubli, Karnataka)'
        ELSE 'Dr. ' || initcap(replace(l.base_name, '.', ' ')) || ' (Hubli, Karnataka)'
    END,
    'General Physician',
    'Kannada, English, Hindi',
    'hybrid',
    500,
    4.5,
    0,
    true
FROM lab_tech_users l
WHERE NOT EXISTS (
    SELECT 1
    FROM doctors d
    WHERE d.auth_user_id = l.auth_user_id
);

-- Keep already-migrated rows aligned as doctors
UPDATE doctors d
SET
    specialty = COALESCE(NULLIF(d.specialty, ''), 'General Physician'),
    language = COALESCE(NULLIF(d.language, ''), 'Kannada, English, Hindi'),
    consultation_type = COALESCE(NULLIF(d.consultation_type, ''), 'hybrid'),
    active = true,
    name = CASE
        WHEN d.name ILIKE '%(Hubli, Karnataka)%' THEN d.name
        WHEN d.name ILIKE 'Dr.%' THEN d.name || ' (Hubli, Karnataka)'
        ELSE 'Dr. ' || d.name || ' (Hubli, Karnataka)'
    END
WHERE EXISTS (
    SELECT 1
    FROM auth.users u
    WHERE u.id::text = d.auth_user_id
      AND lower(COALESCE(u.raw_user_meta_data->>'role', u.raw_app_meta_data->>'role', ''))
          IN ('lab_technician', 'lab technician', 'lab-tech', 'labtech')
);

WITH seed_doctors(name, specialty, language, consultation_type, fee, rating_avg, rating_count) AS (
    VALUES
        ('Dr. Ananya Kulkarni (Hubli, Karnataka)', 'General Physician', 'Kannada, English, Hindi', 'hybrid', 500, 4.8, 128),
        ('Dr. Raghavendra Deshpande (Hubli, Karnataka)', 'Cardiology', 'Kannada, English, Hindi', 'video', 900, 4.7, 96),
        ('Dr. Priya Patil (Hubli, Karnataka)', 'Dermatology', 'Kannada, English, Hindi', 'chat', 650, 4.6, 82),
        ('Dr. Suresh Hegde (Hubli, Karnataka)', 'Orthopedics', 'Kannada, English, Hindi', 'hybrid', 800, 4.7, 101),
        ('Dr. Meera Joshi (Hubli, Karnataka)', 'Pediatrics', 'Kannada, English, Hindi', 'video', 700, 4.9, 147),
        ('Dr. Vivek Bhat (Hubli, Karnataka)', 'Neurology', 'Kannada, English, Hindi', 'video', 1100, 4.7, 75),
        ('Dr. Shruti Rao (Hubli, Karnataka)', 'Gynecology', 'Kannada, English, Hindi', 'hybrid', 850, 4.8, 119),
        ('Dr. Kiran Naik (Hubli, Karnataka)', 'ENT', 'Kannada, English, Hindi', 'chat', 600, 4.5, 64),
        ('Dr. Nidhi Shetty (Hubli, Karnataka)', 'Endocrinology', 'Kannada, English, Hindi', 'video', 950, 4.7, 88),
        ('Dr. Prakash Kulkarni (Hubli, Karnataka)', 'Pulmonology', 'Kannada, English, Hindi', 'hybrid', 900, 4.6, 70),
        ('Dr. Kavya Hiremath (Hubli, Karnataka)', 'Psychiatry', 'Kannada, English, Hindi', 'chat', 750, 4.8, 92),
        ('Dr. Aditya Mestri (Hubli, Karnataka)', 'Urology', 'Kannada, English, Hindi', 'video', 950, 4.6, 67)
)
INSERT INTO doctors (
    auth_user_id,
    name,
    specialty,
    language,
    consultation_type,
    fee,
    rating_avg,
    rating_count,
    active
)
SELECT
    'seed-hubli-' || lower(replace(split_part(name, ' ', 2), '.', '')),
    name,
    specialty,
    language,
    consultation_type,
    fee,
    rating_avg,
    rating_count,
    true
FROM seed_doctors d
WHERE NOT EXISTS (
    SELECT 1
    FROM doctors existing
    WHERE existing.name = d.name
);
