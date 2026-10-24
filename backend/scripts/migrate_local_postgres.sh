#!/usr/bin/env bash
set -euo pipefail

DB_URL="${DATABASE_URL:-postgresql://postgres:postgres@localhost:5432/caresync_local}"
MIGRATIONS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../migrations" && pwd)"
POSTGRES_CONTAINER="${POSTGRES_CONTAINER:-caresync-postgres}"
POSTGRES_USER="${POSTGRES_USER:-postgres}"
POSTGRES_DB="${POSTGRES_DB:-caresync_local}"

echo "Using database: ${DB_URL}"

if command -v psql >/dev/null 2>&1; then
  echo "Using local psql client"
  run_psql() {
    psql "${DB_URL}" "$@"
  }
  run_psql_file() {
    local file_path="$1"
    psql "${DB_URL}" -v ON_ERROR_STOP=1 -f "${file_path}"
  }
else
  echo "Local psql not found; using Docker container ${POSTGRES_CONTAINER}"
  run_psql() {
    docker exec -i "${POSTGRES_CONTAINER}" psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" "$@"
  }
  run_psql_file() {
    local file_path="$1"
    docker exec -i "${POSTGRES_CONTAINER}" psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -v ON_ERROR_STOP=1 < "${file_path}"
  }
fi

echo "Waiting for PostgreSQL to become ready..."
for attempt in {1..30}; do
  if run_psql -tAc 'SELECT 1' >/dev/null 2>&1; then
    echo "PostgreSQL is ready"
    break
  fi

  if [[ "${attempt}" -eq 30 ]]; then
    echo "PostgreSQL did not become ready in time" >&2
    exit 1
  fi

  sleep 1
done

echo "Ensuring pgcrypto extension exists"
run_psql -v ON_ERROR_STOP=1 -c 'CREATE EXTENSION IF NOT EXISTS pgcrypto;'

echo "Ensuring auth.users compatibility table exists for local Postgres"
run_psql -v ON_ERROR_STOP=1 -c "CREATE SCHEMA IF NOT EXISTS auth;"
run_psql -v ON_ERROR_STOP=1 -c "
CREATE TABLE IF NOT EXISTS auth.users (
  id uuid PRIMARY KEY,
  email text,
  raw_user_meta_data jsonb DEFAULT '{}'::jsonb,
  raw_app_meta_data jsonb DEFAULT '{}'::jsonb
);
"

echo "Ensuring schema_migrations tracking table exists"
run_psql -v ON_ERROR_STOP=1 -c "
CREATE TABLE IF NOT EXISTS schema_migrations (
  file_name text PRIMARY KEY,
  applied_at timestamptz NOT NULL DEFAULT now()
);
"

migration_files=(
  000_create_base_tables.sql
  001_create_new_tables.sql
  002_create_doctor_teleconsultation_tables.sql
  003_create_patient_accounts.sql
  004_seed_hubli_doctors.sql
  005_seed_doctor_availability_slots.sql
  006_create_user_accounts.sql
  007_plain_password_auth_adjustment.sql
  008_seed_slots_2026_03_25_26.sql
  009_create_doctor_feedback.sql
  010_create_email_otp_codes.sql
  011_add_doctor_availability_toggle.sql
  012_allow_rebooking_cancelled_slots.sql
  013_harden_slot_reserve_and_book.sql
  014_fix_book_reserved_slot_atomic_update.sql
  015_report_aware_call_linkage.sql
  016_create_blood_campaign_tables.sql
  017_create_follow_up_cron_tables.sql
)

existing_markers="$(run_psql -tAc 'SELECT COUNT(*) FROM schema_migrations;' | tr -d '[:space:]')"
has_final_table="$(run_psql -tAc "SELECT to_regclass('public.doctor_feedback') IS NOT NULL;" | tr -d '[:space:]')"

if [[ "${existing_markers}" == "0" && "${has_final_table}" == "t" ]]; then
  echo "Existing schema detected; backfilling migration markers"
  for file in "${migration_files[@]}"; do
    run_psql -v ON_ERROR_STOP=1 -c "INSERT INTO schema_migrations(file_name) VALUES ('${file}') ON CONFLICT DO NOTHING;"
  done
fi

for file in "${migration_files[@]}"
do
  already_applied="$(run_psql -tAc "SELECT 1 FROM schema_migrations WHERE file_name = '${file}' LIMIT 1;" | tr -d '[:space:]')"
  if [[ "${already_applied}" == "1" ]]; then
    echo "Skipping ${file} (already applied)"
    continue
  fi

  echo "Applying ${file}"
  run_psql_file "${MIGRATIONS_DIR}/${file}"
  run_psql -v ON_ERROR_STOP=1 -c "INSERT INTO schema_migrations(file_name) VALUES ('${file}') ON CONFLICT DO NOTHING;"
done

echo "Migrations completed successfully."
