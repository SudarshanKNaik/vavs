# CareSync AI

CareSync AI is a clinical follow-up automation platform. Clinics build workflows that react to events such as a lab result arriving or a missed appointment, and the platform carries out the next steps: an AI voice call to the patient, booking a slot with the doctor, emailing the report, or alerting staff.

```
Trigger  →  Condition  →  Action  →  Output
lab result    value out     AI call +     transcript +
uploaded      of range      book slot     doctor summary
```

**Contents:** [Features](#features) · [How CareSync works](#how-caresync-works) · [Tech stack](#tech-stack) · [Project structure](#project-structure) · [Getting started](#getting-started) · [Known limitations](#known-limitations)

---

## Features

- **Visual workflow builder**: drag-and-drop nodes on a canvas (React Flow) to build trigger → condition → action pipelines. A workflow can also be drafted from a plain-English description with the AI builder.
- **AI voice calls**: outbound calls through ElevenLabs Conversational AI over Twilio. The agent receives patient, report and available-slot context, and the outcome is read back from the call.
- **Appointment scheduling**: doctor availability slots with atomic reserve/book, rescheduling, cancellation and optional Google Calendar events.
- **Lab report processing**: upload a PDF or a photo of a report, extract structured values, detect abnormal results and trigger workflows from them.
- **Automated follow-ups**: a background scheduler retries the workflow when a call ends without a booking.
- **Blood donation campaigns**: upload donor and NGO lists, match compatible and eligible donors, call them in batches, and view the results on a map.
- **Patient portal**: patients sign up, view their reports and appointments, book slots and join chat/video teleconsultations.
- **Doctor dashboard**: patients, call logs with transcripts, appointments, availability, follow-ups and an audit log.
- **Email**: OTP sign-up/login and report/notification delivery over SMTP.
- **Speech-to-text**: Deepgram transcription for voice input in the workflow builder.

### Workflow node catalogue

| Type | Nodes |
|---|---|
| Triggers | `lab_results_received`, `bloodwork_received`, `imaging_results_ready`, `abnormal_result_detected`, `appointment_missed`, `patient_due_for_labs`, `prescription_expiring`, `new_patient_registered`, `follow_up_due`, `blood_gathering_trigger` |
| Conditions | `check_result_values`, `check_patient_age`, `check_insurance`, `check_appointment_history`, `check_medication_list` |
| Actions | `call_patient`, `send_sms`, `schedule_appointment`, `create_lab_order`, `create_referral`, `send_notification`, `update_patient_record`, `assign_to_staff`, `start_blood_campaign` |
| Outputs | `log_completion`, `generate_transcript`, `create_report`, `send_summary_to_doctor` |

---

## How CareSync works

The big picture: a **clinical event** (a lab report, a missed appointment) starts a **workflow**. The workflow engine walks the doctor's node graph, and its actions reach the patient by **AI phone call**, SMS or email. The patient's answer on the call turns into a **booked appointment**. If no booking happens, the **follow-up scheduler** tries again later.

```mermaid
flowchart LR
    subgraph Inputs
        A[Lab report<br/>PDF / photo]
        B[Lab event<br/>API]
        C[Manual run<br/>from dashboard]
    end
    A --> E
    B --> E
    C --> E
    E[Workflow engine] --> F{Conditions}
    F -->|true| G[Actions]
    F -->|false| H[Other branch]
    G --> I[AI voice call<br/>ElevenLabs + Twilio]
    G --> J[Records<br/>lab order, referral,<br/>notification, report]
    I --> K[Call result<br/>poller / webhook]
    K -->|patient confirmed| L[Appointment booked]
    K -->|no booking| M[Follow-up scheduler<br/>retries later]
    M --> E
```

The sections below follow each flow in the order a clinic uses them.

### 1. Sign-up and login

Doctors and patients have separate accounts. Sign-up is protected by a 6-digit email OTP.

```mermaid
sequenceDiagram
    actor U as Doctor / Patient
    participant FE as Frontend
    participant API as Backend
    participant M as Gmail SMTP
    U->>FE: Enter email, name, mobile, password
    FE->>API: POST /api/auth/otp/send
    API->>M: Email 6-digit code (valid 10 min)
    U->>FE: Enter code
    FE->>API: POST /api/auth/register (with otp_code)
    API-->>FE: Account created
    FE->>API: POST /api/auth/login
    API-->>FE: Token + user (doctor_id or patient profile)
```

- Doctor pages: `/signUp`, `/signIn`. Patient pages: `/patient-signUp`, `/patient-signIn`.
- Registering a doctor also creates their `doctors` row (General Physician, unavailable until they switch availability on).
- A patient's portal profile is linked to a doctor through `POST /api/patient-portal/register`.

### 2. Doctor setup: availability and slots

1. On **Availability** (`/availability`), the doctor switches availability on (`PUT /api/doctors/{id}/availability/settings`). Switching it off can reschedule today's pending appointments if the doctor confirms.
2. The doctor adds, edits or removes slots (`/api/doctors/{id}/slots`). The backend also keeps a rolling set of upcoming slots for each doctor, so the AI agent always has times to offer.
3. Each slot is `available`, `reserved` (held for a few minutes during booking) or `booked`.

### 3. Getting patients into the system

| Route | What happens |
|---|---|
| **Manual** (`/patients`) | Doctor enters name, phone, DOB, insurance and risk level; conditions (ICD-10) and medications are added on the patient page. |
| **PDF intake** (`POST /api/pdf/intake`) | Doctor drops in a medical record PDF. The backend extracts demographics, medications and lab results and creates the patient and medication records. |
| **Import into existing patient** (`POST /api/patients/{id}/import-pdf`) | Adds a new report's data to a patient who already exists. |
| **Patient self sign-up** | The patient registers on the portal and is linked to a doctor. |

**How a report is read.** Text PDFs go through a built-in parser (pdfplumber + pattern matching). If that finds little or no data (scanned PDFs), or the upload is a JPG/PNG photo, the backend asks **Google Gemini** to extract `patient_info`, `lab_results` (test, value, unit, reference range, high/low/normal flag) and `medications`.

### 4. Building a workflow

A doctor can create a workflow in three ways, all on the **Triggers** pages (`/triggers`, `/triggers/new`) and the canvas (`/workflow`):

1. **From a template**: `GET /api/workflows/templates`, then `POST /api/workflows/templates/{id}/create`. Templates include *Lab Call to Appointment*, *Abnormal Lab Follow-Up*, *Missed Appointment Recovery*, *Prescription Renewal Reminder*, *New Patient Onboarding* and *Blood Campaign Launch*.
2. **By hand**: drag nodes onto the canvas and connect them. Condition nodes have a **true** and a **false** output.
3. **With the AI builder**: describe it in plain English, optionally by voice (Deepgram transcribes it). `POST /api/workflows/ai/generate` sends the description to OpenRouter and returns nodes and edges to review. If the model call fails, a simple fallback workflow is returned with a warning.

A workflow is saved as `DRAFT` or `ENABLED`. Only **enabled** workflows run automatically from lab events.

### 5. Triggering a workflow

```mermaid
flowchart TD
    A["Report upload<br/>POST /api/pdf/extract-and-execute"] --> X["Extract lab values<br/>(parser, then Gemini if needed)"]
    X --> P["Email patient a report summary<br/>+ open slots (if patient has an email)"]
    X --> R
    B["Lab event<br/>POST /api/lab-event"] --> Q["Find ENABLED workflows whose<br/>trigger matches trigger_type"]
    Q --> R["Run workflow for the patient"]
    C["Manual run<br/>POST /api/workflows/{id}/execute"] --> R
    D["Follow-up scheduler"] --> R
    R --> S["call_logs row created<br/>(status: running)"]
```

Each run creates a **call log** that stores every step's result. It finishes as `completed`, `failed`, or stays `running` while a phone call is in progress.

### 6. Inside the workflow engine

`backend/app/services/workflow_engine.py` runs the graph breadth-first from the trigger node:

1. **Trigger**: marks the start of the run.
2. **Conditions** decide the branch. For example, `check_result_values` compares a lab value (`greater_than`, `less_than`, `in_range`, `out_of_range`) against thresholds, and only the matching **true**/**false** edge is followed.
3. **Actions** do the work:
   - `call_patient`: starts an AI call (see the next section).
   - `send_sms`: Twilio SMS.
   - `create_lab_order`, `create_referral`, `send_notification`, `assign_to_staff`: create records in the database.
   - `update_patient_record`: updates fields such as `risk_level`.
   - `schedule_appointment`: books once a date is confirmed. During a call this happens after the call ends.
   - `start_blood_campaign`: launches a donor campaign.
4. **Outputs** wrap up the run: `create_report` stores a structured execution report, `send_summary_to_doctor` leaves a summary notification for the doctor, `generate_transcript` fetches the call transcript and `log_completion` closes the run.

Every step is logged as `ok`, `skipped` or `error` and shown on `/triggers/{id}/logs` and `/calls`.

### 7. AI call to booked appointment

This is the core flow.

```mermaid
sequenceDiagram
    participant WF as Workflow engine
    participant DB as PostgreSQL
    participant EL as ElevenLabs agent
    participant TW as Twilio
    actor P as Patient
    WF->>DB: Fetch doctor's next 3 open slots
    WF->>EL: POST /convai/twilio/outbound-call<br/>(patient, doctor, report, slots)
    EL->>TW: Place call from clinic number
    TW->>P: Phone rings
    P->>EL: Talks to agent, picks a date and time
    EL-->>EL: Fill data fields<br/>call_outcome, patient_confirmed,<br/>confirmed_date, confirmed_time
    loop every 30 s (up to 40 times)
        WF->>EL: GET conversation
    end
    alt patient confirmed
        WF->>DB: Create appointment, book the slot
    else no booking
        WF->>DB: Queue follow-up job
    end
```

1. **Context.** `call_patient` sends the agent these values: patient name, doctor name and specialty, call reason, report title/date, a lab summary, facility details and a spoken list of open slots (for example "Monday October 26 at 2:30 PM, or …").
2. **The call.** ElevenLabs dials through the Twilio number imported into ElevenLabs. The agent asks which date suits the patient, offers the matching times and confirms once.
3. **Reading the result.** The backend checks the conversation every 30 seconds after the call starts. It reads these fields:

   | Field | Meaning |
   |---|---|
   | `call_outcome` | `appointment_booked`, `callback_requested`, `declined`, `reschedule_needed`, `no_answer`, `voicemail` |
   | `patient_confirmed` | `true` only when the patient confirmed a slot |
   | `confirmed_date` / `confirmed_time` | `YYYY-MM-DD` / `HH:MM` (24-hour) |
   | `patient_availability_notes` | Preferred times or reason, if not booked |

   If the fields are missing, it falls back to the call summary and then the transcript to detect a confirmation and the date and time.
4. **Booking.** When confirmed, the appointment is created against the matching slot (or a new slot at that time), linked to the call log and report, and shown on `/appointments` and in the patient portal.
5. **Other ways in.** ElevenLabs can also post the result to `POST /api/elevenlabs/webhook` (signature-checked with `ELEVENLABS_WEBHOOK_SECRET`; needs a public `APP_BASE_URL`). Staff can force a check with `POST /api/call-logs/{id}/check`.

### 8. Follow-up retries

When a call ends **without a booking** (declined, no answer, voicemail, or confirmed without a date):

1. A follow-up job is queued for `FOLLOW_UP_CRON_DELAY_MINUTES` later, unless the patient already has an active appointment with that doctor.
2. The scheduler wakes every `FOLLOW_UP_CRON_POLL_INTERVAL_SECONDS`, picks up to `FOLLOW_UP_CRON_BATCH_SIZE` due jobs and re-runs the workflow.
3. Jobs stop after `FOLLOW_UP_CRON_MAX_ATTEMPTS`, or as soon as an appointment exists.

Jobs and their logs are on `/follow-ups` (`GET /api/follow-up-cron/jobs`). A job can be run immediately with `POST /api/follow-up-cron/jobs/{id}/run`.

### 9. Patient portal and teleconsultation

```mermaid
flowchart LR
    A[Patient signs in] --> B["See doctors and<br/>open slots"]
    B --> C["Book slot<br/>(held, then booked)"]
    C --> D[Appointment]
    D --> E[Reschedule to<br/>another slot]
    D --> F[Cancel]
    D --> G["Consultation room<br/>/consultation/{appointmentId}"]
    G --> H[Chat + video link]
```

- `/patient` shows the patient's reports, upcoming appointments and doctors. `/patient/booking` books a slot (`POST /api/patient-portal/slots/{id}/book`).
- Rescheduling moves the booking to a new slot and frees the old one, and cancelling frees the slot. Both are under `/api/patient-portal/appointments/{id}/…`.
- Each appointment has a consultation room with chat and, when a video room is set, a video link.
- Patients can leave feedback for a doctor (`POST /api/doctors/{id}/feedback`), which updates the doctor's rating.

### 10. Blood donation campaigns

```mermaid
flowchart TD
    A["Upload Excel<br/>sheets: donors, ngos"] --> B["Validate rows, normalise phone/blood type,<br/>geocode locations"]
    B --> C["Start campaign<br/>blood type, recipient, location, batch size"]
    C --> D["Pick next batch of eligible donors"]
    D --> E["Call batch in parallel<br/>(blood donor agent)"]
    E --> F{"Any donor<br/>said yes?"}
    F -->|yes| G["Campaign stopped,<br/>accepted donor recorded"]
    F -->|no| D
    D -->|no donors left| H[Campaign finished]
    G --> I["Map of donors and NGOs<br/>/triggers/blood"]
```

1. **Upload** (`POST /api/blood-campaigns/upload`): an `.xlsx` with a `donors` sheet and an `ngos` sheet. Invalid rows are reported back, and locations are geocoded for the map.
2. **Start** (`POST /api/blood-campaigns/start`, or the `start_blood_campaign` workflow action): choose the blood type, recipient, reason, location and batch size (1–10).
3. **Eligibility**: a donor must belong to the same doctor, have a compatible blood type, not have been called in this campaign, and be past the donation cooldown (90 days since their last donation for men, 120 for women).
4. **Calls**: each batch is called at once, using the blood donor agent (`ELEVENLABS_BLOOD_AGENT_ID`, falling back to `ELEVENLABS_AGENT_ID`). The agent records `donor_consent` and `call_outcome`.
5. **Stop rule**: the first donor who agrees ends the campaign. Otherwise the next batch is called until no eligible donors remain.
6. **Results**: progress and the donor/NGO map are at `/triggers/blood` (`GET /api/blood-campaigns/{id}` and `/map`).

### 11. Where the results show up

| Page | Shows |
|---|---|
| `/dashboard` | Overview of patients, calls and upcoming appointments |
| `/patients`, `/patients/{id}` | Records, conditions, medications, reports, lab orders, referrals |
| `/calls` | Every workflow run with steps, transcript and outcome |
| `/appointments` | Booked appointments, including ones booked by AI calls |
| `/follow-ups` | Queued and finished follow-up jobs |
| `/triggers` | Workflows, their run logs and blood campaigns |
| `/audit-log` | History of actions |
| `/settings` | Profile and notification preferences |

### Which service each flow needs

| Flow | Service | Without a key |
|---|---|---|
| Everything | PostgreSQL | The app doesn't start |
| OTP sign-up, report emails | Gmail SMTP | Sign-up OTP can't be sent |
| AI calls, blood campaigns | ElevenLabs + Twilio | `call_patient` step fails with "not configured" |
| SMS | Twilio | `send_sms` step fails |
| Scanned PDF / photo extraction | Google Gemini | Only text PDFs are read |
| AI workflow builder | OpenRouter | A basic fallback workflow is returned |
| Voice input in the builder | Deepgram | Voice input is unavailable |
| Calendar events | Google Calendar | Appointments are still stored, but no calendar event is created |

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
│   │   └── services/
│   │       ├── workflow_engine.py          # Runs workflow graphs
│   │       ├── elevenlabs_service.py       # Outbound calls, conversations
│   │       ├── blood_campaign_service.py   # Donor upload, matching, dispatch
│   │       ├── pdf_service.py              # PDF parsing + Gemini extraction
│   │       ├── workflow_ai_builder_service.py  # OpenRouter workflow drafts
│   │       ├── workflow_templates_service.py   # Prebuilt templates
│   │       ├── postgres_service.py         # Database access
│   │       ├── smtp_service.py             # OTP and notification email
│   │       └── google_calendar_service.py  # Calendar events
│   ├── migrations/             # Ordered SQL migrations (schema + seed data)
│   └── scripts/                # Bootstrap, migrate and reset helpers
└── frontend/
    ├── app/
    │   ├── (marketing)/        # Landing, features, pricing, about, contact, doctors
    │   ├── (auth)/             # Doctor and patient sign-in / sign-up
    │   ├── (app)/              # Doctor dashboard, patients, calls, triggers, …
    │   ├── (workflow)/         # Workflow builder canvas
    │   ├── (patient)/          # Patient portal and booking
    │   └── consultation/       # Teleconsultation room
    ├── components/             # UI and workflow builder components
    ├── services/api.ts         # Typed client for the backend API
    └── types/
```

---

## Getting started

Full step-by-step instructions, demo logins and troubleshooting are in [step.md](step.md). The short version:

### Prerequisites

- Docker (for PostgreSQL)
- Python 3.11
- Node.js 20+

### 1. Configure the backend

```bash
cp backend/.env.example backend/.env
```

The app starts with blank keys, and each feature reports "not configured" until its key is added. See [Which service each flow needs](#which-service-each-flow-needs).

| Variable | Needed for |
|---|---|
| `DATABASE_URL` | Database (default: `postgresql://postgres:postgres@localhost:5433/caresync_local`) |
| `ELEVENLABS_API_KEY`, `ELEVENLABS_AGENT_ID`, `ELEVENLABS_PHONE_NUMBER_ID` | AI voice calls |
| `ELEVENLABS_BLOOD_AGENT_ID` | Optional separate agent for blood donor calls |
| `ELEVENLABS_WEBHOOK_SECRET` | Verifying ElevenLabs webhook calls |
| `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_PHONE_NUMBER` | Telephony and SMS |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM_EMAIL` | OTP and email delivery |
| `GOOGLE_CALENDAR_ACCESS_TOKEN` | Calendar events for bookings |
| `GOOGLE_GEMINI_API_KEY`, `GOOGLE_GEMINI_MODEL` | Document extraction (default model `gemini-2.5-flash`) |
| `OPENROUTER_API_KEY`, `OPENROUTER_MODEL` | AI workflow builder |
| `DEEPGRAM_API_KEY` | Speech-to-text |
| `APP_BASE_URL` | Public URL used for webhook callbacks |
| `FOLLOW_UP_CRON_*` | Follow-up retry delay, polling interval, attempts and batch size |

**Setting up voice calls:**
1. Create an agent in ElevenLabs. Add the data collection fields from [section 7](#7-ai-call-to-booked-appointment) so results can be read back.
2. Import your Twilio number under **Phone Numbers → Import from Twilio** and assign it to the agent.
3. Put the agent ID and phone number ID in `backend/.env`.

### 2. Start the database and backend

```bash
backend/scripts/bootstrap_local_backend.sh
```

This starts PostgreSQL in Docker (container `caresync-vavs-postgres`, port **5433**), applies all migrations, creates `backend/.venv`, installs the dependencies, and runs the API at **http://localhost:8000**. Interactive API docs are at **http://localhost:8000/docs**, and the health check is at `/health`.

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

## Known limitations

- **Twilio trial accounts** can only call verified numbers and play a "press any key" message before each call. If the patient doesn't press a key, the call ends before the AI agent speaks.
- **Webhooks need a public URL.** On `localhost`, call results arrive through the 30-second poller instead of `/api/elevenlabs/webhook`.
- **Calendar events** are only created by the `schedule_appointment` node when a confirmed date is already known. Bookings made from a call are stored as appointments in CareSync.
- **Text PDFs use the built-in parser first**, which can misread multi-line names or test names that contain digits (for example "HbA1c"). Gemini is used only when that parser finds little data, or for photos.
- **Passwords are stored in plain text** in this version (see [PRODUCT_DIRECTION.md](PRODUCT_DIRECTION.md)). Use test credentials only.
