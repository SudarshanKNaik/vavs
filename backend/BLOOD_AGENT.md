# ElevenLabs blood agent setup

One agent (`ELEVENLABS_BLOOD_AGENT_ID`) handles both donor and organization
calls. The backend sends these dynamic variables on every call:

`call_type` (`donor` or `org`), `patient_name` (the person or organization
being called), `blood_type`, `blood_component`, `units_needed`,
`recipient_name`, `hospital_name`, `contact_name`, `contact_phone`,
`call_reason`, `facility_name`.

## System prompt

Paste the contents of `blood_agent_prompt.txt` as the agent's system prompt.
Do NOT paste this file: it is setup documentation, not a prompt.

Set the first message to something neutral that fits both call types:

> Hello {{patient_name}}, this is BloodConnect calling from CareSync on behalf of {{hospital_name}}. We have an urgent blood request. Do you have a moment?

## Data collection fields (Analysis tab)

| Identifier | Type | Description |
|---|---|---|
| `availability` | string | `yes` if the organization has the blood, `no` if not. Leave empty if the call ended before an answer. |
| `units_available` | string | Number of units they can release. |
| `donor_consent` | string | Existing field for donors (`yes`/`no`). |
| `call_outcome` | string | Existing field (optional fallback for orgs). |

An empty `availability` is treated as a hang-up: the organization is retried
once in the next batch, then dropped for that request.
