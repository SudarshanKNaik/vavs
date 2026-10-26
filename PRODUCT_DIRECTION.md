# CareSync AI: Product Direction

An assessment of the current platform against the mentor's feedback, with
what we should build next and what we should stop building.

---

## 1. What the mentor asked for

| # | Mentor's point | What it means for us |
|---|---|---|
| 1 | Build something the hospital industry uses directly and that **disrupts** it | Pick one painful, expensive, manual hospital process and replace it end to end. Avoid a general "platform with many features". |
| 2 | He liked **blood banks**, but asked **how we handle the data**. The doctor or hospital **shouldn't have to deal with it** | The hospital should never upload, clean or own donor spreadsheets. **We** own and maintain the donor network. The hospital only says "I need 2 units of B+ at this location". |
| 3 | **Just deliver it** and **cut manual and human cost** | No setup and no workflow building on the hospital's side. One request goes in and a confirmed donor or unit comes out. People step in only for exceptions. |

---

## 2. Assessment of what we have built

### Current feature set

| Area | What exists | Fit with the mentor's direction |
|---|---|---|
| Blood campaign | Excel upload of donors and NGOs, compatibility matching, cooldown check, AI calls in batches, live map | **Core: keep and rebuild** (see Section 3) |
| AI voice calls (ElevenLabs + Twilio) | Outbound calls with context, outcome from webhook or polling | **Core: keep.** This is the engine that replaces staff phone calls |
| Follow-up scheduler | Retries calls on a delay up to a limit | **Keep.** Reuse it for donor retries and reminders |
| Lab report PDF to abnormal result to call patient | PDF extraction, range check, call, book slot | **Park.** Useful, but it's a separate product. Keep the code; stop investing |
| Appointment slots and booking | Atomic reserve and book, rebooking | **Reuse** to book donation slots at blood centres |
| Drag-and-drop workflow builder + AI builder | React Flow canvas, around 28 node types | **Stop.** It asks hospital staff to design automation, which goes against "just deliver it" |
| Teleconsultation (chat and video) | Rooms, messages, feedback | **Drop from the pitch.** A crowded market with nothing that sets us apart |
| Patient portal | Sign-up, reports, appointments | **Park.** Not needed for blood |
| Marketing site (pricing, features, 3D) | Several pages | **Rewrite** around one value proposition |

**Summary:** we built a broad "clinic automation toolkit". The mentor is
asking for one **outcome-based service**. Blood is the strongest candidate
because:

- It is urgent, and the time to find a donor directly affects patient outcomes.
- Today's process is manual: staff and relatives phone people, post on WhatsApp groups and go through NGO contacts.
- Each request has a clear measurable outcome: a donor confirmed and arrived, or a unit issued.

### How blood data is handled today (the mentor's concern)

From [blood_campaign_service.py](backend/app/services/blood_campaign_service.py)
and [016_create_blood_campaign_tables.sql](backend/migrations/016_create_blood_campaign_tables.sql):

| Today | Problem |
|---|---|
| The **doctor uploads an Excel file** (`Donors` and `NGOs` sheets) | The hospital has to find, own, format and refresh donor data. This is exactly what the mentor said it shouldn't do. |
| Every donor row is tied to `doctor_id` | Each doctor gets their own small donor list. There is no shared network, so the system doesn't get better as more hospitals join. |
| No donor **consent** record and no opt-out | We call phone numbers from a spreadsheet. Under India's DPDP Act 2023 we need recorded consent for a stated purpose, and a way to withdraw it. |
| The doctor sees donor **names and phone numbers** in the UI and map | This exposes more donor data than needed. The hospital needs a confirmed donor, not the whole contact list. |
| `last_donated_date` comes from the spreadsheet and is never updated | Eligibility data goes stale, so we may call ineligible people or skip eligible ones. |
| Geocoding through public Nominatim, called row by row during upload | Slow, rate-limited under Nominatim's usage policy, and blocks the upload. |

### Automation quality today

| Behaviour | Where | Problem |
|---|---|---|
| Donors are picked by `ORDER BY created_at` | `list_campaign_eligible_donors` in [postgres_service.py](backend/app/services/postgres_service.py) | **Distance is ignored**, even though we geocode everyone. A donor 40 km away can be called before one 2 km away. |
| "Accepted" means the transcript contains `yes` **and** `donat` | `_is_positive_outcome` in [blood_campaign_service.py](backend/app/services/blood_campaign_service.py) | False positives. For example, "yes I know, but I can't donate" counts as accepted. |
| The campaign **stops at the first "yes"** | `run_blood_campaign_dispatch` | No confirmation that the donor actually showed up, no backup donor, and no support for needing more than one unit. |
| Eligibility is blood type plus a 90 or 120 day cooldown only | Same SQL | Age, weight, recent illness or medication, and hemoglobin are not screened. Donors may be turned away at the blood centre. |
| Campaigns run as an in-memory `asyncio.create_task` and poll for about 7 minutes per batch | `start_blood_campaign` | A backend restart (including `--reload` on every code change) silently kills running campaigns. |
| Plasma and platelet compatibility are not modelled | Compatibility table | The table is correct for red cells and whole blood but wrong for plasma, where compatibility is reversed. |

### Platform risks found during the assessment

These must be fixed before any real hospital uses the system:

1. **No authentication on the API.** No route checks a session. Any caller
   can pass any `doctor_id` and read or modify patients, donors, campaigns
   and call logs. See [endpoints.py](backend/app/api/endpoints.py).
2. **Passwords are stored in plain text.** See
   [007_plain_password_auth_adjustment.sql](backend/migrations/007_plain_password_auth_adjustment.sql)
   and `login_user_account`.
3. **The webhook signature check is optional.** If
   `ELEVENLABS_WEBHOOK_SECRET` is empty, anyone can post fake call outcomes
   to `/api/elevenlabs/webhook`.
4. **The session lives in `localStorage`**, which any XSS on the site can read.

---

## 3. What we should build: blood requisition on autopilot

### The pitch in one line

> The hospital raises a blood request. CareSync delivers a confirmed,
> pre-screened donor to a licensed blood centre, or finds stock nearby, with
> no staff phone calls.

### What the hospital does (the whole list)

1. Raises a request: blood group, component, units, urgency, location. This
   can come from a web form, a WhatsApp message, or later an integration with
   the hospital's HIS (hospital information system).
2. Watches one live status page: *searching → donor confirmed → donor
   en route → donated → closed*.

That's all. The hospital doesn't upload donors, configure workflows or
make calls.

### What the platform does automatically

```
Request received
   │
   ├─▶ 1. Check stock at nearby blood centres (partner feeds / e-RaktKosh where available)
   │       └─ stock found → reserve, notify hospital, done
   │
   ├─▶ 2. Pick donors from OUR network
   │       eligible (type/component, cooldown, age, consent active)
   │       ranked by distance + past response rate + time of day
   │
   ├─▶ 3. Contact donors in waves
   │       WhatsApp/SMS first (cheap) → AI voice call in local language (Kannada/Hindi/English)
   │       structured answers: consent yes/no, available when, quick pre-screen questions
   │
   ├─▶ 4. On "yes": book a slot at the nearest licensed blood centre,
   │       send directions + reminders, keep 1–2 backup donors warm
   │
   ├─▶ 5. Confirm arrival/donation (blood centre taps "donated" or donor replies)
   │       update donor's last_donated_date automatically
   │
   └─▶ 6. Escalate only if waves exhaust: NGO partners → human coordinator
```

### Data model: who owns what

| Data | Owner | Who can see it |
|---|---|---|
| Donor profile (name, phone, blood group, location, last donation, consent) | **CareSync network** | The donor (self-service) and the platform. **Not the hospital.** |
| Blood request (group, units, urgency, location) | Hospital | Hospital and platform |
| Match result | Platform | The hospital sees "Donor #A12, ETA 25 min, confirmed". Contact goes through **masked calling**, so the real number is never shown. |
| Donation event | Blood centre | Updates the donor's eligibility automatically |

**Where donors come from (so the hospital never supplies them):**

- Self-registration through a WhatsApp bot, a missed-call number or a QR code at camps, colleges and corporate drives. Consent is captured at registration.
- Partner NGOs and blood centres who onboard their donor lists **with donor consent**: each donor gets an opt-in SMS before being added.
- After each successful donation, the donor is invited to stay in the network.

**Data handling rules:**

- Consent is recorded per purpose and can be withdrawn by replying STOP or calling a number.
- The minimum data needed is stored. Medical pre-screen answers are kept only as long as needed.
- Phone numbers are encrypted at rest. Masked calling between donor and hospital.
- Every access is logged. We already have an audit-log page we can reuse.

### Why this cuts human cost

| Manual today | Automated |
|---|---|
| Staff or relatives phone donors one by one | AI and WhatsApp contact many donors in parallel |
| Donor lists kept in personal phones and WhatsApp groups | One shared, consented, always-updated network |
| No idea who's eligible | Eligibility is computed and updated after each donation |
| Follow-up "are you coming?" calls | Automatic reminders and arrival confirmation |
| Repeated for every request at every hospital | Each new hospital and donor makes the network better for everyone |

### How we deliver it ("just deliver it")

- **No setup for the hospital:** we onboard it in one call, give it a request link or WhatsApp number, and it's live.
- **Pricing per outcome** (per fulfilled request), not per seat. The hospital pays only when blood is arranged.
- We run the blood-centre and NGO partnerships, so the hospital doesn't have to.

---

## 4. What we should NOT do

| Don't | Why |
|---|---|
| Ask hospitals to upload donor Excel files | This is the mentor's direct objection. Donor data is our job. |
| Show donor phone numbers or names to hospitals | Privacy risk, DPDP exposure, and donors stop trusting us. Use masked calling. |
| Call people who never consented | Legal risk (DPDP Act, telecom rules on unsolicited calls) and damage to our reputation. |
| Build our own blood **inventory or blood bank management** software | Blood centres already use existing systems, and e-RaktKosh exists nationally. We integrate with them; we don't replace them. |
| Collect blood or route donors anywhere except a **licensed blood centre** | Blood collection is regulated in India. We coordinate; licensed centres collect. |
| Offer cash or anything that looks like payment to donors | Paid donation is prohibited under national blood policy. Recognition such as certificates and badges is fine. |
| Keep pitching the workflow builder, teleconsultation and patient portal | They dilute the story and none of them is the disruption. Park them. |
| Let the AI's "yes" be final | Confirm with structured answers plus a reminder and arrival check, and always keep backup donors. |
| Claim medical eligibility decisions | The pre-screen only filters. The blood centre's medical officer decides. |

> Note: the legal points above are a starting checklist, not legal advice.
> Before a pilot, confirm the current DPDP rules, telecom calling
> rules and Drugs & Cosmetics Act requirements for blood centres.

---

## 5. Changes needed in the code

### Must fix first (security)

- [ ] Add real authentication: hashed passwords (bcrypt or argon2), signed session tokens, and a FastAPI dependency that resolves the logged-in user and replaces the `doctor_id` query or form parameters.
- [ ] Make `ELEVENLABS_WEBHOOK_SECRET` mandatory outside local development.
- [ ] Move the session from `localStorage` to an httpOnly cookie.

### Blood product rebuild

- [ ] New `donors` table that is **not** tied to `doctor_id`, with `consent_status`, `consent_at`, `consent_source`, `opted_out_at`, date of birth or age band, and encrypted phone.
- [ ] Donor self-registration flow (start with a web form and SMS OTP, then add WhatsApp).
- [ ] `blood_requests` table (hospital, group, **component**, units, urgency, location) to replace `blood_campaigns`.
- [ ] Rank donors by **distance** (we already store latitude and longitude) and response history, not `created_at`.
- [ ] Replace the transcript keyword check with the structured `donor_consent` field only, followed by an SMS confirmation.
- [ ] Keep the campaign running until **N units** are confirmed and keep backup donors. Add an "arrived/donated" confirmation step.
- [ ] Update `last_donated_date` automatically after a confirmed donation.
- [ ] Move campaign dispatch into the persistent job table the follow-up scheduler already uses (`follow_up_jobs`), so a restart doesn't lose campaigns.
- [ ] Geocode once at registration, asynchronously, with caching. Don't geocode during upload.
- [ ] Separate compatibility tables for red cells, plasma and platelets.
- [ ] Hospital view: request status only, with masked contact.

### Park (keep the code, remove from navigation and pitch)

- Workflow builder and AI builder, teleconsultation, patient portal, lab-report workflow.

---

## 6. Roadmap

| Phase | Goal | Deliverable |
|---|---|---|
| **0. Hardening** (1–2 weeks) | Safe enough to demo with real people | Auth, hashed passwords, webhook secret, cookie sessions |
| **1. Donor network** (2–3 weeks) | Hospitals never touch donor data | Donor self-registration with consent, shared donor table, opt-out, distance ranking |
| **2. Request to donor** (2–3 weeks) | One request in, confirmed donor out | Request form, SMS then AI-call waves, structured consent, slot at blood centre, reminders, arrival confirmation |
| **3. Pilot** (4 weeks) | Proof with numbers | 1–2 hospitals and 1 blood centre in Hubli-Dharwad, 500+ registered donors |
| **4. Stock lookup and scale** | Use stock before calling donors | Partner blood centre stock feeds or e-RaktKosh integration, masked calling, more languages |

---

## 7. Numbers to show the mentor after the pilot

- **Time to confirmed donor** (median minutes from request to "yes"), compared with the hospital's current process.
- **Fulfilment rate:** requests where a donor actually donated.
- **Staff minutes per request:** target close to 0.
- **Cost per fulfilled request:** calls + SMS + platform cost, compared with staff time.
- **Donor network growth and response rate:** this is the moat.

---

## 8. Questions to validate with hospitals and blood centres

1. Who in the hospital handles a blood request today, and how long does it take?
2. How often do they need replacement or emergency donors, and for which groups and components?
3. Would a blood centre confirm "donated" in our app, or would an SMS reply from the donor be enough?
4. Would the hospital pay per fulfilled request? Is a patient's family a better payer, or a CSR or NGO sponsor?
5. Can partner blood centres share live stock with us, and in what format?
