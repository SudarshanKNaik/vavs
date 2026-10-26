# Running CareSync AI locally

Three things need to be running:

| Part | What it is | URL |
|---|---|---|
| Database | PostgreSQL 16 in Docker (container `caresync-postgres`) | `localhost:5432` |
| Backend | FastAPI (Python 3.11) | http://localhost:8000 |
| Frontend | Next.js | http://localhost:3000 |

## Prerequisites

- Docker Desktop (open and running)
- Python 3.11 (`python3 --version`)
- Node.js 20+ (`node --version`)

## Step 1: Configure the backend (first time only)

```bash
cp backend/.env.example backend/.env
```

You can leave every API key blank for now. The app starts without them, and
each feature that needs a key reports that it is "not configured" when used.
See [Adding API keys later](#adding-api-keys-later).

## Step 2: Start the database and backend

Run this from the project root in its own terminal:

```bash
backend/scripts/bootstrap_local_backend.sh
```

The script:

1. Starts the `caresync-postgres` container. If it is already running, the script reuses it.
2. Applies any pending SQL migrations from `backend/migrations/`. Migrations that already ran are skipped.
3. Creates `backend/.venv` and installs the Python packages (first run only).
4. Starts the API on port 8000 with auto-reload.

Leave this terminal open. Press `Ctrl+C` to stop the backend.

Check that it works:

```bash
curl http://localhost:8000/health
# {"status":"ok","database":"ok"}
```

API docs: http://localhost:8000/docs

### Starting the backend by hand (after the first run)

```bash
docker start caresync-postgres          # if the DB isn't running
cd backend
source .venv/bin/activate
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

## Step 3: Start the frontend

In a second terminal:

```bash
cd frontend
npm install        # first time only, or after package.json changes
npm run dev
```

Open http://localhost:3000.

The frontend connects to `http://localhost:8000` by default. To use a different
backend, create `frontend/.env.local` with:

```
NEXT_PUBLIC_API_URL=https://your-backend-url
```

## Demo doctor login

Signing up needs an email OTP, which only works once SMTP is configured. For
local testing, use this account (created directly in the database):

| Field | Value |
|---|---|
| Page | http://localhost:3000/signIn |
| Email | `doctor@caresync.local` |
| Password | `Doctor@123` |
| Linked doctor | Dr. Ananya Kulkarni, General Physician (`d63f7abf-4a70-49e4-b78b-5a79bb8f1f18`) |

This is a local-only test account. Passwords are currently stored in plain
text (see `PRODUCT_DIRECTION.md`), so never reuse a real password here. If you
reset the database, the account is deleted. Recreate it with:

```bash
docker exec -i caresync-postgres psql -U postgres -d caresync_local <<'SQL'
WITH acct AS (
  INSERT INTO user_accounts (role, email, username, mobile, password)
  VALUES ('doctor', 'doctor@caresync.local', 'Dr. Ananya Kulkarni', '+919000000001', 'Doctor@123')
  RETURNING id
)
UPDATE doctors SET auth_user_id = (SELECT id::text FROM acct)
WHERE name LIKE 'Dr. Ananya Kulkarni%';
SQL
```

## Demo patient login

| Field | Value |
|---|---|
| Page | http://localhost:3000/patient-signIn |
| Email | `patient@caresync.local` |
| Password | `Patient@123` |
| Patient | Rahul Patil (`+919000000002`), assigned to the demo doctor, Dr. Ananya Kulkarni |

Because the patient belongs to the demo doctor, you see Rahul Patil in the
doctor's patient list, and bookings from the patient portal show up on the
doctor's side.

The phone number is a placeholder. Change it to your own number before you
test AI calls or SMS, or the call goes to a number that doesn't exist.

To recreate the account after a database reset (run the doctor command first):

```bash
docker exec -i caresync-postgres psql -U postgres -d caresync_local <<'SQL'
WITH acct AS (
  INSERT INTO user_accounts (role, email, username, mobile, password)
  VALUES ('patient', 'patient@caresync.local', 'Rahul Patil', '+919000000002', 'Patient@123')
  RETURNING id, email
), pat AS (
  INSERT INTO patients (doctor_id, name, phone, notes)
  SELECT id::text, 'Rahul Patil', '+919000000002', 'Demo patient for local testing'
  FROM doctors WHERE name LIKE 'Dr. Ananya Kulkarni%'
  RETURNING id
)
INSERT INTO patient_accounts (auth_user_id, patient_id, email)
SELECT acct.id::text, pat.id, acct.email FROM acct, pat;
SQL
```

## What to check in Docker

Open Docker Desktop, then go to **Containers**. Check these:

| Check | Expected |
|---|---|
| Container `caresync-postgres` | Status **Running**, labelled **(healthy)** |
| Port | `5432:5432` |
| Image | `postgres:16.6` |
| Volume | `vavs_postgres_data` (or `<folder>_postgres_data`) holds the database files |

Useful commands:

```bash
docker ps --filter name=caresync-postgres     # is it running and healthy?
docker logs caresync-postgres --tail 50       # database logs
docker exec -it caresync-postgres psql -U postgres -d caresync_local   # SQL shell
```

Inside the SQL shell:

```sql
\dt                                    -- list tables (expect ~29)
SELECT * FROM schema_migrations;       -- migrations that have run
SELECT name, specialty FROM doctors;   -- seeded doctors
\q                                     -- quit
```

### Note: one container shared between project copies

The container name `caresync-postgres` and port `5432` are fixed in
`docker-compose.yml`. If another copy of this project on your machine already
created the container, both copies use the same database. The
bootstrap script detects that container and reuses it. If you want a fresh
database for this copy, delete the container from the other copy first, then
run the reset script below.

### Resetting the database

```bash
backend/scripts/reset_local_db.sh --yes
```

This deletes all local data and rebuilds the schema and seed data.

## Adding API keys later

Add the keys to `backend/.env`, then restart the backend. Each feature needs
these keys:

| Feature | Keys in `backend/.env` |
|---|---|
| AI voice calls | `ELEVENLABS_API_KEY`, `ELEVENLABS_AGENT_ID`, `ELEVENLABS_PHONE_NUMBER_ID`, `ELEVENLABS_WEBHOOK_SECRET` |
| Telephony and SMS | `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_PHONE_NUMBER` |
| OTP login and emails | `SMTP_USERNAME`, `SMTP_PASSWORD` (Gmail app password), `SMTP_FROM_EMAIL` |
| Calendar events | `GOOGLE_CALENDAR_ACCESS_TOKEN` |
| Lab report extraction | `GOOGLE_GEMINI_API_KEY` |
| AI workflow builder | `OPENROUTER_API_KEY` |
| Voice input | `DEEPGRAM_API_KEY` |
| Webhooks (ElevenLabs callbacks) | `APP_BASE_URL`: must be a public URL (e.g. an ngrok tunnel to port 8000) |

Don't commit `backend/.env`. It is already listed in `backend/.gitignore`.

## Troubleshooting

| Problem | Fix |
|---|---|
| `container name "/caresync-postgres" is already in use` | Another project copy owns the container. The bootstrap script now reuses it. If you use `docker compose up` directly, run `docker start caresync-postgres` instead. |
| `port 5432 is already allocated` | Another Postgres is running. Stop it, or check `lsof -i :5432` |
| `/health` shows `"database":"unreachable"` | The DB container is stopped. Run `docker start caresync-postgres` |
| `Address already in use` / `Port 8000 is already in use` | A backend is already running. Find it with `lsof -i :8000`, then `kill <PID>` |
| `Port 3000 is in use ... using 3001` followed by `Unable to acquire lock at .next/dev/lock` | Another `next dev` is already running for this folder. Find it with `lsof -i :3000`, `kill <PID>`, then run `npm run dev` again |
| Frontend loads but shows no data | The backend isn't running. Check http://localhost:8000/health |
