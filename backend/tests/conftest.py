"""
Test fixtures for the backend.

Tests run against a throwaway PostgreSQL database (never the dev database).
Default: the docker-compose Postgres on localhost:5433. Override with
TEST_DATABASE_URL; the database name must end with "_test" because it is
dropped and recreated from all migrations at the start of each session.
"""

import os
import sys
import uuid
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import psycopg
import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = BACKEND_ROOT / "migrations"
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://postgres:postgres@localhost:5433/caresync_ngo_test"
)

# Must be set before the app (and its Settings) is imported.
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["FOLLOW_UP_CRON_ENABLED"] = "false"
# Never send real patient SMS/email from tests; notification tests opt in with fakes.
os.environ["NOTIFY_PATIENTS_SMS"] = "false"
os.environ["NOTIFY_PATIENTS_EMAIL"] = "false"
os.environ["NOTIFY_BLOOD_SMS"] = "false"
os.environ["NOTIFY_BLOOD_EMAIL"] = "false"
sys.path.insert(0, str(BACKEND_ROOT))


def _admin_url(url: str) -> tuple[str, str]:
    parsed = urlparse(url)
    db_name = parsed.path.lstrip("/")
    return urlunparse(parsed._replace(path="/postgres")), db_name


def _create_test_database() -> None:
    admin_url, db_name = _admin_url(TEST_DATABASE_URL)
    if not db_name.endswith("_test"):
        raise RuntimeError("TEST_DATABASE_URL database name must end with '_test'")
    try:
        admin = psycopg.connect(admin_url, autocommit=True, connect_timeout=5)
    except psycopg.OperationalError as exc:
        pytest.exit(f"Test PostgreSQL is not reachable ({exc}). Start it with docker compose up -d.", 2)
    with admin:
        admin.execute(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)')
        admin.execute(f'CREATE DATABASE "{db_name}"')

    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as conn:
        # Same preamble as scripts/migrate_local_postgres.sh
        conn.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
        conn.execute("CREATE SCHEMA IF NOT EXISTS auth")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS auth.users (
              id uuid PRIMARY KEY,
              email text,
              raw_user_meta_data jsonb DEFAULT '{}'::jsonb,
              raw_app_meta_data jsonb DEFAULT '{}'::jsonb
            )
            """
        )
        for path in sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9]_*.sql")):
            conn.execute(path.read_text(encoding="utf-8"))
        # Make sure at least one active doctor exists regardless of seed data.
        conn.execute(
            """
            INSERT INTO doctors (name, specialty, language, consultation_type, fee, active)
            VALUES ('Dr. Test Physician', 'General Physician', 'English', 'video', 500, TRUE)
            """
        )


@pytest.fixture(scope="session", autouse=True)
def test_database():
    _create_test_database()
    yield


@pytest.fixture(scope="session")
def client(test_database):
    from fastapi.testclient import TestClient

    import main

    with TestClient(main.app) as c:
        yield c


@pytest.fixture(scope="session")
def doctor_id(test_database):
    with psycopg.connect(TEST_DATABASE_URL) as conn:
        row = conn.execute("SELECT id FROM doctors WHERE active = TRUE ORDER BY created_at LIMIT 1").fetchone()
    return str(row[0])


def _make_ngo(client, label: str) -> dict:
    from app.services import ngo_service

    suffix = uuid.uuid4().hex[:8]
    org = ngo_service.create_ngo_organization(f"{label} {suffix}", city="Hubli")
    email = f"{label.lower().replace(' ', '')}-{suffix}@example.org"
    password = "correct-horse-battery"
    ngo_service.create_ngo_user(str(org["id"]), email=email, password=password, username=f"{label} Staff")
    resp = client.post("/api/ngo/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    token = resp.json()["token"]
    return {
        "ngo_id": str(org["id"]),
        "email": email,
        "password": password,
        "token": token,
        "headers": {"Authorization": f"Bearer {token}"},
    }


@pytest.fixture()
def ngo_a(client):
    return _make_ngo(client, "NGO A")


@pytest.fixture()
def ngo_b(client):
    return _make_ngo(client, "NGO B")


@pytest.fixture()
def db_conn(test_database):
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as conn:
        yield conn
