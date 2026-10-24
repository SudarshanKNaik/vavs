#!/usr/bin/env bash
set -euo pipefail

# Resets local Docker Postgres data and rebuilds schema from migrations.
# Usage:
#   ./scripts/reset_local_db.sh --yes
# Optional:
#   POSTGRES_SERVICE=postgres ./scripts/reset_local_db.sh --yes

if [[ "${1:-}" != "--yes" ]]; then
  echo "This will permanently delete local database data (Docker volume)."
  echo "Re-run with: $0 --yes"
  exit 1
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BACKEND_DIR="${ROOT_DIR}/backend"
POSTGRES_SERVICE="${POSTGRES_SERVICE:-postgres}"

cd "${ROOT_DIR}"

echo "[1/4] Stopping containers and removing volumes..."
docker compose down -v --remove-orphans

echo "[2/4] Starting fresh Postgres container..."
docker compose up -d "${POSTGRES_SERVICE}"

echo "[3/4] Applying all migrations from scratch..."
"${BACKEND_DIR}/scripts/migrate_local_postgres.sh"

echo "[4/4] Reset complete. Local DB is fresh."
