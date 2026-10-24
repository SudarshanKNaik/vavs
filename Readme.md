# CareSync AI

CareSync AI is a clinical follow-up automation platform. Clinics build workflows that react to events such as a lab result arriving or a missed appointment, and the platform carries out the next steps: an AI voice call to the patient, booking a slot with the doctor, emailing the report, or alerting staff.

```
Trigger  →  Condition  →  Action  →  Output
lab result    value out     AI call +     transcript +
uploaded      of range      book slot     doctor summary
```

---

## Features

- **Visual workflow builder**: drag-and-drop nodes on a canvas (React Flow) to build trigger → condition → action pipelines. A workflow can also be drafted from a plain-English description using the AI builder.
- **AI voice calls**: outbound calls through ElevenLabs Conversational AI over Twilio. The agent receives patient, report and available-slot context, and the outcome is captured through webhooks.
- **Appointment scheduling**: doctor availability slots with atomic reserve/book, rebooking of cancelled slots, and optional Google Calendar events.
- **Lab report processing**: upload a PDF, extract structured values, detect abnormal results and trigger workflows from them.
- **Automated follow-ups**: a background scheduler retries follow-up calls on a configurable delay and attempt limit.
- **Blood donation campaigns**: upload donor and NGO lists, geocode them, match compatible donors near a request, call them, and view the results on a map.
- **Patient portal**: patients sign up, view their reports and appointments, and join chat/video teleconsultations.
- **Doctor dashboard**: patients, call logs with transcripts, appointments, availability, follow-ups and an audit log.
- **Email**: OTP login and report/notification delivery over SMTP.
- **Speech-to-text**: Deepgram transcription for voice input in the workflow builder.

### Workflow node catalogue

| Type | Nodes |
|---|---|
| Triggers | `lab_results_received`, `bloodwork_received`, `imaging_results_ready`, `abnormal_result_detected`, `appointment_missed`, `patient_due_for_labs`, `prescription_expiring`, `new_patient_registered`, `follow_up_due`, `blood_gathering_trigger` |
| Conditions | `check_result_values`, `check_patient_age`, `check_insurance`, `check_appointment_history`, `check_medication_list` |
| Actions | `call_patient`, `send_sms`, `schedule_appointment`, `create_lab_order`, `create_referral`, `send_notification`, `update_patient_record`, `assign_to_staff`, `start_blood_campaign` |
| Outputs | `log_completion`, `generate_transcript`, `create_report`, `send_summary_to_doctor` |

---

## Tech stack

| Layer | Technology |
|---|---|
| Frontend | Next.js 16, React 19, TypeScript, Tailwind CSS 4, React Flow (`@xyflow/react`), Leaflet, Three.js |
| Backend | Python 3.11, FastAPI, Uvicorn, Pydantic Settings, psycopg 3 |
| Database | PostgreSQL 16 (Docker) |
| Voice & telephony | ElevenLabs Conversational AI, Twilio |
| AI | OpenRouter (workflow builder), Google Gemini (document extraction), Deepgram (speech-to-text) |
| Other | pdfplumber (PDF parsing), openpyxl (donor spreadsheets), Gmail SMTP, Google Calendar API |

---

## Project structure

```
.
├── docker-compose.yml          # PostgreSQL 16 for local development
├── backend/
│   ├── main.py                 # FastAPI app, CORS, startup scheduler, /health
│   ├── requirements.txt
│   ├── .env.example
│   ├── app/
│   │   ├── api/endpoints.py    # All REST routes (mounted under /api)
│   │   ├── core/config.py      # Environment-based settings
│   │   └── services/           # Workflow engine, ElevenLabs, PDF, SMTP,
│   │                           # Google Calendar, blood campaigns, AI builder
│   ├── migrations/             # Ordered SQL migrations (schema + seed data)
│   └── scripts/                # Bootstrap, migrate and reset helpers
└── frontend/
    ├── app/
    │   ├── (marketing)/        # Landing, features, pricing, about, contact
    │   ├── (auth)/             # Doctor and patient sign-in / sign-up
    │   ├── (app)/              # Doctor dashboard, patients, calls, triggers, …
    │   ├── (workflow)/         # Workflow builder canvas
    │   ├── (patient)/          # Patient portal
    │   └── consultation/       # Teleconsultation room
    ├── components/             # UI and workflow builder components
    ├── services/api.ts         # Typed client for the backend API
    └── types/
```

---

## Getting started

### Prerequisites

- Docker (for PostgreSQL)
- Python 3.11
- Node.js 20+

### 1. Configure the backend

```bash
cp backend/.env.example backend/.env
```

The app starts with the defaults. Fill in the keys below to turn on the matching features.

| Variable | Needed for |
|---|---|
| `DATABASE_URL` | Database (default: `postgresql://postgres:postgres@localhost:5432/caresync_local`) |
| `ELEVENLABS_API_KEY`, `ELEVENLABS_AGENT_ID`, `ELEVENLABS_PHONE_NUMBER_ID` | AI voice calls |
| `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_PHONE_NUMBER` | Telephony and SMS |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM_EMAIL` | OTP and email delivery |
| `GOOGLE_CALENDAR_ACCESS_TOKEN` | Calendar events for bookings |
| `GOOGLE_GEMINI_API_KEY` | Document extraction |
| `OPENROUTER_API_KEY` | AI workflow builder |
| `DEEPGRAM_API_KEY` | Speech-to-text |
| `APP_BASE_URL` | Public URL used in webhook callbacks |

### 2. Start the database and backend

```bash
backend/scripts/bootstrap_local_backend.sh
```

This starts PostgreSQL in Docker, applies all migrations, creates `backend/.venv`, installs the dependencies, and runs the API at **http://localhost:8000**. Interactive API docs are at **http://localhost:8000/docs**, and the health check is at `/health`.

### 3. Start the frontend

```bash
cd frontend
npm install
npm run dev
```

Open **http://localhost:3000**. To point the frontend at another backend, set `NEXT_PUBLIC_API_URL`.

### Useful scripts

| Command | Purpose |
|---|---|
| `backend/scripts/migrate_local_postgres.sh` | Apply any pending migrations |
| `backend/scripts/reset_local_db.sh --yes` | Delete local data and rebuild the schema |
| `npm run build` (frontend) | Production build |
| `npm run lint` (frontend) | Lint the frontend |

---

## Example workflow

1. A lab report PDF is uploaded for a patient.
2. The extracted values are checked against reference ranges, and one is out of range.
3. The doctor's open slots are fetched.
4. The AI agent calls the patient, explains the result and offers the slots.
5. The patient picks a time, and the slot is booked and added to the calendar.
6. The call transcript and outcome are logged, and a summary is sent to the doctor.
7. If the patient doesn't answer, the follow-up scheduler retries the call.
