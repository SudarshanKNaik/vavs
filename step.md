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
| `Address already in use` on port 8000 or 3000 | A server is already running. Find it with `lsof -i :8000` and stop it |
| Frontend loads but shows no data | The backend isn't running. Check http://localhost:8000/health |
