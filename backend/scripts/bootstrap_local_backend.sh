#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BACKEND_DIR="${ROOT_DIR}/backend"

POSTGRES_CONTAINER="${POSTGRES_CONTAINER:-caresync-vavs-postgres}"

cd "${ROOT_DIR}"

# The container name is fixed in docker-compose.yml, so if a container with
# that name already exists (even one created outside this compose project),
# `docker compose up` would fail with a name conflict. Reuse it instead.
if docker ps --format '{{.Names}}' | grep -qx "${POSTGRES_CONTAINER}"; then
  echo "PostgreSQL container ${POSTGRES_CONTAINER} is already running; reusing it"
elif docker ps -a --format '{{.Names}}' | grep -qx "${POSTGRES_CONTAINER}"; then
  echo "Starting existing PostgreSQL container ${POSTGRES_CONTAINER}..."
  docker start "${POSTGRES_CONTAINER}"
else
  echo "Starting PostgreSQL container..."
  docker compose up -d postgres
fi

echo "Applying migrations..."
"${BACKEND_DIR}/scripts/migrate_local_postgres.sh"

cd "${BACKEND_DIR}"

if [[ ! -d ".venv" ]]; then
  echo "Creating backend virtual environment..."
  python3 -m venv .venv
fi

source .venv/bin/activate

if [[ ! -f ".deps_installed" ]] || [[ requirements.txt -nt .deps_installed ]]; then
  echo "Installing Python dependencies..."
  pip install -r requirements.txt
  touch .deps_installed
fi

if lsof -nP -iTCP:8000 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Port 8000 is already in use (is the backend already running?):" >&2
  lsof -nP -iTCP:8000 -sTCP:LISTEN >&2
  echo "Stop that process (kill <PID>) and run this script again." >&2
  exit 1
fi

echo "Starting FastAPI backend on http://0.0.0.0:8000"
exec uvicorn main:app --host 0.0.0.0 --port 8000 --reload
