-- ============================================================
-- Migration 030: Outbreak Watch places (any city)
-- ============================================================
-- Caches OpenStreetMap lookups so each locality or city is
-- geocoded once (Nominatim allows at most 1 request a second).
-- A row with NULL coordinates records a place that wasn't found.
-- Additive only. Safe to re-run.
-- ============================================================

CREATE TABLE IF NOT EXISTS place_geocodes (
    query       TEXT PRIMARY KEY,           -- normalised lookup text
    name        TEXT,
    latitude    NUMERIC(10, 7),
    longitude   NUMERIC(10, 7),
    -- Bounding box of a city, used to find its neighbourhoods.
    south       NUMERIC(10, 7),
    north       NUMERIC(10, 7),
    west        NUMERIC(10, 7),
    east        NUMERIC(10, 7),
    -- For cities: [{"name", "latitude", "longitude"}, ...] neighbourhoods.
    areas       JSONB,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- City the sample data was generated for, shown on the page.
ALTER TABLE symptom_reports
    ADD COLUMN IF NOT EXISTS region TEXT;
