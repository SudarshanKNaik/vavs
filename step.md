# Running CareSync AI locally

Three things need to be running:

| Part | What it is | URL |
|---|---|---|
| Database | PostgreSQL 16 in Docker (container `caresync-vavs-postgres`) | `localhost:5433` |
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

> **Already have a `backend/.env` from before?** The database moved to port
> **5433**. Make sure the first line reads
> `DATABASE_URL=postgresql://postgres:postgres@localhost:5433/caresync_local`.
> An old `.env` with `5432` connects to a different Postgres (or none at all).

## Step 2: Start the database and backend

Run this from the project root in its own terminal:

```bash
backend/scripts/bootstrap_local_backend.sh
```

The script:

1. Starts the `caresync-vavs-postgres` container on port 5433, creating it on the first run. If it is already running, the script reuses it.
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
docker start caresync-vavs-postgres     # if the DB isn't running
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

## Demo logins

Signing up needs an email OTP, which only works once SMTP is configured. For
local testing, use these accounts (created directly in the database):

| | Doctor | Patient |
|---|---|---|
| Page | http://localhost:3000/signIn | http://localhost:3000/patient-signIn |
| Email | `doctor@caresync.local` | `patient@caresync.local` |
| Password | `Doctor@123` | `Patient@123` |
| Who | Dr. Ananya Kulkarni, General Physician | Rahul Patil (`+919000000002`) |

The patient is assigned to the demo doctor, so Rahul Patil appears in the
doctor's patient list, and bookings from the patient portal show up on the
doctor's side.

The doctor's ID is generated when the seed data runs, so it differs between
databases. Look it up with:

```bash
curl -s http://localhost:8000/api/doctors | grep -o '"id":"[^"]*","name":"Dr. Ananya[^"]*"'
```

The patient's phone number is a placeholder. Change it to your own number
before you test AI calls or SMS, or the call goes to a number that doesn't
exist.

These are local-only test accounts. Passwords are currently stored in plain
text (see `PRODUCT_DIRECTION.md`), so never reuse a real password here.

### Recreating the demo accounts

A new or reset database has no accounts. Create both with:

```bash
docker exec -i caresync-vavs-postgres psql -U postgres -d caresync_local <<'SQL'
WITH acct AS (
  INSERT INTO user_accounts (role, email, username, mobile, password)
  VALUES ('doctor', 'doctor@caresync.local', 'Dr. Ananya Kulkarni', '+919000000001', 'Doctor@123')
  RETURNING id
)
UPDATE doctors SET auth_user_id = (SELECT id::text FROM acct)
WHERE name LIKE 'Dr. Ananya Kulkarni%';

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
| Container `caresync-vavs-postgres` | Status **Running**, labelled **(healthy)** |
| Port | `5433:5432` (your machine's port 5433 → Postgres's 5432 inside the container) |
| Image | `postgres:16.6` |
| Volume | `vavs_postgres_data` holds the database files |

Useful commands:

```bash
docker ps --filter name=caresync-vavs-postgres     # is it running and healthy?
docker logs caresync-vavs-postgres --tail 50       # database logs
docker exec -it caresync-vavs-postgres psql -U postgres -d caresync_local   # SQL shell
```

Inside the SQL shell:

```sql
\dt                                    -- list tables (expect ~29)
SELECT * FROM schema_migrations;       -- migrations that have run
SELECT name, specialty FROM doctors;   -- seeded doctors
\q                                     -- quit
```

### Other `caresync-postgres` containers

Older versions of this project used a container named `caresync-postgres` on
port 5432. If another copy of the project on your machine still runs one, you'll see it in
Docker Desktop too. It doesn't affect this copy, which uses only
`caresync-vavs-postgres` on 5433. Leave it running if the other copy needs it.

### Resetting the database

```bash
backend/scripts/reset_local_db.sh --yes
```

This deletes all local data and rebuilds the schema and seed data. Afterwards,
[recreate the demo accounts](#recreating-the-demo-accounts).

## Adding API keys later

Add the keys to `backend/.env`, then restart the backend. Each feature needs
these keys:

| Feature | Keys in `backend/.env` |
|---|---|
| AI voice calls | `ELEVENLABS_API_KEY`, `ELEVENLABS_AGENT_ID`, `ELEVENLABS_PHONE_NUMBER_ID`, `ELEVENLABS_WEBHOOK_SECRET` |
| Blood campaign calls (optional separate agent) | `ELEVENLABS_BLOOD_AGENT_ID`. If blank, blood campaigns use `ELEVENLABS_AGENT_ID` |
| Telephony and SMS | `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_PHONE_NUMBER` |
| OTP login and emails | `SMTP_USERNAME`, `SMTP_PASSWORD` (Gmail app password), `SMTP_FROM_EMAIL` |
| Google Calendar sync and busy-time blocking | `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET` (see [Google Calendar](#google-calendar)) |
| Lab report extraction | `GOOGLE_GEMINI_API_KEY` |
| AI workflow builder | `OPENROUTER_API_KEY` |
| Voice input | `DEEPGRAM_API_KEY` |
| Webhooks (ElevenLabs callbacks) | `APP_BASE_URL`: must be a public URL (e.g. an ngrok tunnel to port 8000) |

Don't commit `backend/.env`. It is already listed in `backend/.gitignore`.

## Google Calendar

Each doctor connects their own Google Calendar in **Settings → Google Calendar
→ Connect**. After that:

- bookings appear as events, cancelled ones are deleted, and reschedules move;
- anything already in the doctor's calendar hides those slots from patients and
  the call agent.

One-time setup in [Google Cloud Console](https://console.cloud.google.com/):

1. **APIs & Services → Library:** enable the **Google Calendar API**.
2. **OAuth consent screen:** add the scopes `.../auth/calendar.events` and
   `.../auth/calendar.freebusy`. While the app is in "Testing", add each
   doctor's Google account under **Test users**.
3. **Credentials → your OAuth client (Web application):** add
   `http://localhost:8000/api/google/oauth/callback` under **Authorized
   redirect URIs**. Use your public backend URL in production.
4. Copy the **Client secret** into `backend/.env` as
   `GOOGLE_OAUTH_CLIENT_SECRET`, then restart the backend. The client ID is
   already set as `GOOGLE_OAUTH_CLIENT_ID`.

The old `GOOGLE_CALENDAR_ACCESS_TOKEN` is only a fallback for the workflow
"schedule appointment" node, and it must be an OAuth access token. An API
key (`AIza…`) can't write to calendars.

## Setting up the AI call agent (ElevenLabs dashboard)

The agent's prompt and tools live in the ElevenLabs dashboard, not in this
repo. For the agent to offer real times and handle several calls at once
without double-booking, set up the following.

### 1. Prompt

Add this to the agent's system prompt:

```
Today is {{current_date}}, {{current_time}} ({{clinic_timezone}}).
Days with open appointments: {{available_dates}}

Booking steps:
1. Offer only the DAYS above (the next few open days). Don't read out times
   yet. The patient may also ask for any other day in the next 30 days.
2. When the patient picks a day, call get_available_times with that date and
   read out the times it returns.
3. When the patient picks a time, call hold_slot. Only say the appointment is
   booked if it returns held = true. If not, offer the times it suggests.
Never invent a day or time. If the days say NO OPEN SLOTS, don't book;
say the clinic will call back.
```

### 2. Two server (webhook) tools

The backend must be reachable from the internet: set `APP_BASE_URL` to a
public URL, e.g. an ngrok tunnel to port 8000. For both tools:

- **Method:** `POST`, JSON body
- **Header:** `X-Tool-Secret` = the value of `ELEVENLABS_TOOL_SECRET` in
  `backend/.env` (generated for you; keep it secret)
- **Body parameter `call_log_id`:** filled from the dynamic variable
  `{{call_log_id}}` (the backend sends it with every call)

| Tool name | URL | Other body parameters (filled by the agent) |
|---|---|---|
| `get_available_times` | `<APP_BASE_URL>/api/elevenlabs/tools/available-times` | `date`: the day the patient chose, as YYYY-MM-DD |
| `hold_slot` | `<APP_BASE_URL>/api/elevenlabs/tools/hold-slot` | `date` (YYYY-MM-DD), `time` (e.g. `11:00 AM`) |

A held time is reserved for 30 minutes, and the post-call booking turns it
into an appointment. If the patient changes their mind, holding a new time
releases the old one.

### Languages (ask first, then switch)

For the agent to speak Kannada, Odia, Hindi and so on:

- **Agent tab → Voice / TTS model:** `Eleven v4 Turbo` (or v3). Flash v2 is
  English-only, and Flash v2.5 / Multilingual v2 don't support Kannada or Odia.
- **Agent tab → Additional languages:** add every language you need.
- **Tools tab → add the system tool "Detect language"** (`language_detection`).
  Without it the agent can't switch and stays in English.
- **First message:** ask the language first, e.g. *"Hello {{patient_name}}, this
  is CareSync calling on behalf of Dr. {{doctor_name}}. Which language would you
  like to talk in? English, ಕನ್ನಡ, हिंदी, ଓଡ଼ିଆ, or another language?"*
- **Prompt:** tell the agent to call `language_detection` as soon as the patient
  names or speaks a language, then use only that language, and to record it in a
  `preferred_language` data collection field.
- **Security → Overrides → Language:** keep enabled. The backend saves each
  patient's language after a call and starts their next call directly in it.

### 3. Data collection fields

Set the descriptions so the agent records exactly what was held:
`confirmed_date` as YYYY-MM-DD and `confirmed_time` as 24-hour HH:MM
(e.g. 14:30).

Without the tools, the agent still works from `{{available_slots}}` (the full
list at call start), but two simultaneous calls can then pick the same time.
The second patient's booking fails after the call, and they get an automatic
follow-up call.

## Troubleshooting

| Problem | Fix |
|---|---|
| `container name "/caresync-vavs-postgres" is already in use` | The container exists but wasn't created by `docker compose`. The bootstrap script reuses it. If you use `docker compose up` directly, run `docker start caresync-vavs-postgres` instead. |
| `port 5433 is already allocated` | Something else is using port 5433. Find it with `lsof -i :5433` |
| `/health` shows `"database":"unreachable"` | The DB container is stopped (`docker start caresync-vavs-postgres`), or `backend/.env` still points at port 5432 |
| Login says `Invalid email or password` for the demo accounts | The database is new or was reset. [Recreate the demo accounts](#recreating-the-demo-accounts) |
| `Address already in use` / `Port 8000 is already in use` | A backend is already running. Find it with `lsof -i :8000`, then `kill <PID>` |
| `Port 3000 is in use ... using 3001` followed by `Unable to acquire lock at .next/dev/lock` | Another `next dev` is already running for this folder. Find it with `lsof -i :3000`, `kill <PID>`, then run `npm run dev` again |
| Frontend loads but shows no data | The backend isn't running. Check http://localhost:8000/health |
