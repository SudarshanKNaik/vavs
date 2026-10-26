# CareSync AI: Tech Stack

The complete technology stack, with exact versions as installed. For how to
run the project, see [step.md](step.md).

---

## 1. Architecture at a glance

```
                    ┌─────────────────────────────────────────┐
  Doctor / Patient  │  Frontend: Next.js 16 + React 19 (TS)   │  :3000
  (browser)  ─────▶ │  marketing site, doctor app, patient    │
                    │  portal, workflow builder, blood pages   │
                    └────────────────────┬────────────────────┘
                                         │ REST (JSON) /api/*
                    ┌────────────────────▼────────────────────┐
                    │  Backend: FastAPI on Uvicorn (Py 3.11)  │  :8000
                    │  workflow engine, booking, follow-up    │
                    │  scheduler, blood campaigns, webhooks   │
                    └───┬──────────────┬──────────────────┬───┘
                        │ psycopg 3    │ httpx / SDKs     │ webhooks + live tools
              ┌─────────▼────┐   ┌─────▼───────────┐  ┌───▼──────────────────┐
              │ PostgreSQL 16│   │ ElevenLabs,     │  │ ElevenLabs calls back │
              │ (Docker)     │   │ Twilio, Gemini, │  │ during/after a call   │
              │ :5433        │   │ OpenRouter, ... │  │                       │
              └──────────────┘   └─────────────────┘  └───────────────────────┘
```

| Layer | Technology |
|---|---|
| Frontend | Next.js 16.1.6 (App Router, Turbopack), React 19.2.3, TypeScript 5.9.3 |
| Styling | Tailwind CSS 4.2.2, shadcn (base-nova style), Lucide icons |
| Backend | Python 3.11.9, FastAPI 0.135.1, Uvicorn 0.41.0, Pydantic 2.12.5 |
| Database | PostgreSQL 16.6 in Docker, accessed with psycopg 3.2.12 (raw SQL) |
| Voice AI | ElevenLabs Conversational AI, over Twilio telephony |
| Other AI | Google Gemini (document extraction), OpenRouter / DeepSeek (workflow builder), Deepgram (speech-to-text) |

---

## 2. Frontend

**Location:** `frontend/` · **Run:** `npm run dev` · **Port:** 3000

### Core

| Package | Version | Used for |
|---|---|---|
| `next` | 16.1.6 | Framework: App Router, route groups, `next/font`, `next/image`, Turbopack dev server |
| `react`, `react-dom` | 19.2.3 | UI |
| `typescript` | 5.9.3 | Types (`strict: false`, path alias `@/*`) |

### UI and styling

| Package | Version | Used for |
|---|---|---|
| `tailwindcss` + `@tailwindcss/postcss` | 4.2.2 | All styling. CSS-first config with `@theme` in `app/globals.css` |
| `shadcn` | 4.1.0 | Component scaffolding (`components.json`, style `base-nova`) |
| `@base-ui/react` | 1.3.0 | Primitive behind the `Button` component |
| `class-variance-authority` | 0.7.1 | Button variants |
| `clsx` + `tailwind-merge` | 2.1.1 / 3.5.0 | `cn()` class helper (`lib/utils`) |
| `tw-animate-css` | 1.4.0 | Animation utilities |
| `lucide-react` | 0.577.0 | All icons (including the workflow node icons) |
| Google Fonts via `next/font` | n/a | Jost (body), Cormorant Garamond (serif headings), JetBrains Mono (code) |

### Feature libraries

| Package | Version | Used for |
|---|---|---|
| `@xyflow/react` (React Flow) | 12.10.1 | Drag-and-drop workflow canvas and nodes (`components/workflow/`) |
| `dagre` (+ `@types/dagre`) | 0.8.5 | Auto-layout of workflow graphs |
| `leaflet` (+ `@types/leaflet`) | 1.9.4 | Blood campaign map, using OpenStreetMap tiles (`components/blood/BloodCampaignMap.tsx`) |
| `three` | 0.183.2 | 3D visuals on the marketing site |
| `@react-three/fiber` / `@react-three/drei` | 9.5.0 / 10.7.7 | React wrappers for the 3D sphere and particle effects |
| `ogl` | 1.0.11 | Lightweight WebGL particle background (`components/Particles.tsx`) |
| Browser `MediaRecorder` API | n/a | Voice input in the workflow builder (audio sent to Deepgram through the backend) |

### Frontend structure

| Route group | Contents |
|---|---|
| `app/(marketing)` | Landing, features, pricing, about, contact, doctors |
| `app/(auth)` | Doctor and patient sign-in / sign-up |
| `app/(app)` | Doctor app: dashboard, patients, blood requests, calls, follow-ups, availability, appointments, audit log, settings, triggers |
| `app/(workflow)` | Workflow builder canvas |
| `app/(patient)` | Patient portal and self-service booking |
| `app/consultation` | Teleconsultation room (Jitsi Meet link) |
| `app/pitch` | Pitch slides page |
| `services/api.ts` | Typed client for every backend endpoint (`NEXT_PUBLIC_API_URL`, default `http://localhost:8000`) |
| `lib/local-auth.tsx` | Auth context. Session stored in `localStorage` |

### Tooling

| Tool | Version | Used for |
|---|---|---|
| ESLint + `eslint-config-next` | 9.39.4 / 16.1.6 | Linting (`npm run lint`), including React hooks rules |
| `@types/node`, `@types/react`, `@types/react-dom`, `@types/three` | 20 / 19 / 19 / 0.183 | Type definitions |

---

## 3. Backend

**Location:** `backend/` · **Run:** `backend/scripts/bootstrap_local_backend.sh` · **Port:** 8000 · **Docs:** `/docs` (Swagger UI) · **Health:** `/health`

### Runtime and framework

| Package | Version | Used for |
|---|---|---|
| Python | 3.11.9 | Runtime (uses `zoneinfo`, `asyncio`) |
| `fastapi` | 0.135.1 | REST API. All routes in `app/api/endpoints.py`, mounted under `/api` |
| `starlette` | 0.52.1 | Underlying ASGI toolkit (CORS middleware, `run_in_threadpool`) |
| `uvicorn` | 0.41.0 | ASGI server (`--reload` in development) |
| `watchfiles` | 1.1.1 | File watching for `--reload` |
| `pydantic` | 2.12.5 | Request and response validation |
| `pydantic-settings` + `python-dotenv` | 2.13.1 / 1.2.2 | Settings loaded from `backend/.env` (`app/core/config.py`) |
| `python-multipart` | 0.0.20 | File uploads (PDFs, Excel) |

### Data and integrations

| Package | Version | Used for |
|---|---|---|
| `psycopg[binary]` | 3.2.12 | PostgreSQL driver. Raw SQL, no ORM (`app/services/postgres_service.py`) |
| `httpx` | 0.28.1 | Async HTTP to ElevenLabs, Gemini, OpenRouter, Deepgram, Google Calendar, Nominatim |
| `requests` | 2.32.5 | A few synchronous HTTP calls |
| `twilio` | 9.10.2 | SMS sending and TwiML voice fallback |
| `pdfplumber` (pdfminer.six, pypdfium2) | 0.11.9 | Lab report PDF text extraction |
| `openpyxl` | 3.1.5 | Donor / NGO Excel upload parsing |

### Backend modules

| File | Responsibility |
|---|---|
| `main.py` | App setup, CORS, startup of the follow-up scheduler, `/health` |
| `app/api/endpoints.py` | All REST routes: auth, doctors, slots, appointments, patients, workflows, PDFs, call logs, follow-ups, blood campaigns and requests, ElevenLabs webhook and live tools |
| `app/services/postgres_service.py` | All database access, slot scheduling rules, booking, cancellation |
| `app/services/workflow_engine.py` | Runs workflow graphs node by node (trigger → condition → action → output) |
| `app/services/elevenlabs_service.py` | Starts outbound AI calls, fetches conversations |
| `app/services/blood_campaign_service.py` | Donor matching, batched donor calling, Excel ingest, geocoding |
| `app/services/pdf_service.py` | Lab report parsing: pdfplumber text + regex, plus Gemini structured extraction (tries fallback Gemini models) |
| `app/services/workflow_ai_builder_service.py` | Plain-English → workflow graph with OpenRouter |
| `app/services/workflow_templates_service.py` | Built-in workflow templates |
| `app/services/smtp_service.py` | OTP and notification emails |
| `app/services/google_calendar_service.py` | Calendar events for bookings |

### Background work

| Mechanism | What runs |
|---|---|
| In-process asyncio loop, started at app startup | Follow-up scheduler: polls `follow_up_jobs` and claims due jobs with `FOR UPDATE SKIP LOCKED` |
| `asyncio.create_task` | Blood campaign dispatch; post-call result polling |

These run inside the API process, so a restart stops in-flight campaigns. See
[Known gaps](#9-known-gaps).

---

## 4. Database

| Item | Detail |
|---|---|
| Engine | PostgreSQL **16.6** (`postgres:16.6` Docker image) |
| Container | `caresync-vavs-postgres`, host port **5433** → 5432, volume `vavs_postgres_data` |
| Database | `caresync_local` (user/password `postgres` / `postgres`, local only) |
| Extensions | `pgcrypto` 1.3 (UUIDs via `gen_random_uuid()`), `plpgsql` |
| Migrations | Plain SQL files `backend/migrations/000`–`019`, applied in order by `scripts/migrate_local_postgres.sh`, tracked in `schema_migrations` |
| Stored functions | `reserve_availability_slot`, `book_reserved_slot`: atomic slot hold and booking |
| Timezone | Stored in UTC. Clinic time is `CLINIC_TIMEZONE` (default `Asia/Kolkata`) |

**Tables (29):** `appointments`, `availability_slots`, `blood_campaign_donor_attempts`,
`blood_campaigns`, `blood_donors`, `blood_ngos`, `call_logs`, `call_worker_pools`,
`consultation_feedback`, `consultation_messages`, `consultation_rooms`,
`doctor_feedback`, `doctors`, `email_otp_codes`, `follow_up_job_logs`,
`follow_up_jobs`, `lab_orders`, `notifications`, `patient_accounts`,
`patient_conditions`, `patient_medications`, `patients`, `pdf_documents`,
`referrals`, `reports`, `schema_migrations`, `staff_assignments`,
`user_accounts`, `workflows`.

---

## 5. External services

| Service | What it does here | Endpoint | Config (`backend/.env`) |
|---|---|---|---|
| **ElevenLabs Conversational AI** | AI voice agent for patient follow-up and donor calls. Outbound calls via its Twilio integration, a post-call webhook, and live mid-call slot tools | `api.elevenlabs.io/v1` (`/convai/twilio/outbound-call`, conversations) | `ELEVENLABS_API_KEY`, `ELEVENLABS_AGENT_ID`, `ELEVENLABS_PHONE_NUMBER_ID`, `ELEVENLABS_WEBHOOK_SECRET`, `ELEVENLABS_BLOOD_AGENT_ID`, `ELEVENLABS_TOOL_SECRET` |
| **Twilio** | Phone number behind the AI calls; SMS action; TwiML voice fallback | Twilio Python SDK | `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_PHONE_NUMBER` |
| **Google Gemini** | Structured extraction of lab values from PDFs and images | `generativelanguage.googleapis.com/v1beta` | `GOOGLE_GEMINI_API_KEY`, `GOOGLE_GEMINI_MODEL` (default `gemini-2.5-flash`) |
| **OpenRouter** | LLM for "describe a workflow in plain English" | `openrouter.ai/api/v1` | `OPENROUTER_API_KEY`, `OPENROUTER_MODEL` (default `deepseek/deepseek-v3.2`) |
| **Deepgram** | Speech-to-text for voice input in the workflow builder | `api.deepgram.com/v1/listen` | `DEEPGRAM_API_KEY`, `DEEPGRAM_MODEL` (default `nova-3`) |
| **Gmail SMTP** | OTP codes and email notifications | `smtp.gmail.com:587` (STARTTLS) | `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM_EMAIL` |
| **Google Calendar API + OAuth 2.0** | Per-doctor connection (Settings): events created, moved and deleted with bookings; free/busy hides clashing slots | `www.googleapis.com/calendar/v3`, `accounts.google.com`, `oauth2.googleapis.com` | `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`, `GOOGLE_OAUTH_REDIRECT_URI`, `FRONTEND_BASE_URL` |
| **OpenStreetMap Nominatim** | Geocoding donor, NGO and hospital addresses | `nominatim.openstreetmap.org/search` | none (public, rate-limited) |
| **OpenStreetMap tiles** | Map tiles for the blood campaign map | `tile.openstreetmap.org` | none |
| **Jitsi Meet** | Video room for teleconsultations | `meet.jit.si` | none |
| **Web3Forms** | Marketing contact form submissions | `api.web3forms.com/submit` | key in the frontend page |
| **Stripe Payment Links** | Pricing page "buy" buttons (currently test links) | `buy.stripe.com` | links in the frontend page |
| **Unsplash** | Marketing images | `images.unsplash.com` | none |

Every key is optional for local development. A feature whose key is missing
reports "not configured" instead of failing.

---

## 6. Authentication and security (current state)

| Area | Current implementation |
|---|---|
| Accounts | `user_accounts` table, email + password, roles `doctor` / `patient` |
| Sign-up | Email OTP (`email_otp_codes`, 10-minute expiry) via SMTP |
| Session | Random token returned at login, kept in browser `localStorage` |
| API authorization | **None yet:** routes trust the `doctor_id` / `auth_user_id` sent by the client |
| Passwords | **Stored in plain text** (migration 007) |
| ElevenLabs post-call webhook | HMAC signature check when `ELEVENLABS_WEBHOOK_SECRET` is set |
| ElevenLabs live tools | Require the `X-Tool-Secret` header (`ELEVENLABS_TOOL_SECRET`) |
| CORS | `localhost:3000/3001` and `*.vercel.app` |

The fixes for these are listed in [PRODUCT_DIRECTION.md](PRODUCT_DIRECTION.md)
under "Must fix first (security)".

---

## 7. Infrastructure and deployment

| Item | Detail |
|---|---|
| Local database | Docker Compose (`docker-compose.yml`), one `postgres` service |
| Backend deploy | `backend/Procfile` (`web: uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}`) for Procfile-based hosts (Heroku, Render, Railway) |
| Frontend deploy | Vercel (CORS allows `care-sync-ai-delta.vercel.app` and `*.vercel.app`) |
| Webhooks in development | Need a public URL (`APP_BASE_URL`), e.g. an ngrok tunnel to port 8000 |
| Scripts | `bootstrap_local_backend.sh` (DB + migrations + venv + API), `migrate_local_postgres.sh`, `reset_local_db.sh --yes` |
| CI | None configured |
| Tests | No automated test suite. The `backend/test_*.py` files are manual integration scripts |

---

## 8. Domain rules built into the code

| Rule | Where |
|---|---|
| Schedule rules per doctor, editable on Manage Availability: working days, hours, optional break, slot length (10–120 min), booking window (1–90 days). Default: Mon–Sat, 10:30 AM–4:30 PM, 30-min slots, 1:30–2:30 PM break, 30 days | `doctor_schedule_settings` table (migration 022), `DoctorSchedule` / `DEFAULT_SCHEDULE` in `postgres_service.py` |
| Saving a schedule rebuilds unbooked future slots; booked appointments are never changed (the doctor is told how many fall outside the new hours) | `save_doctor_schedule` |
| Rolling slot window, generated on demand in one batch insert, never overlapping existing slots | `_ensure_doctor_rolling_slots` |
| Who cancelled / rescheduled an appointment, and where it moved | `appointments.cancelled_by`, `cancelled_at`, `rescheduled_to_appointment_id` (migration 020) |
| Slot hold → booking (atomic, prevents double booking) | `reserve_availability_slot`, `book_reserved_slot` SQL functions |
| Blood compatibility: red-cell rules for whole blood, PRBC and platelets; reversed ABO rules for plasma | `compatible_donor_blood_types` |
| Donor cooldown: 90 days (male), 120 days (female) | `list_campaign_eligible_donors` |
| Donors called nearest first, in batches sized by urgency (6 / 4 / 2) | `blood_campaign_service.py` |
| Follow-up call retries: delay, attempt limit, batch size | `FOLLOW_UP_CRON_*` settings |

---

## 9. Known gaps

| Gap | Impact |
|---|---|
| No API auth; plain-text passwords | Not safe for real patient data until fixed |
| In-process background tasks | A restart drops running blood campaigns and pending polls |
| Unused dependencies | `react-leaflet` (frontend) and several Python packages in `requirements.txt` (`pyiceberg`, `PyJWT`, `aiohttp`, `cryptography`, `rich`, `websockets`, …) are installed but not imported by the app; candidates for removal |
| No automated tests or CI | Regressions are caught manually |
| Geocoding through public Nominatim | Rate-limited; fine for a pilot, not for scale |
