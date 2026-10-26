"""
Google Calendar Service
-----------------------
Each doctor connects their own Google Calendar with OAuth (Settings page).
The stored refresh token lets the backend:

* keep the calendar in sync: an event is created when an appointment is
  booked and deleted when it is cancelled or rescheduled;
* read the doctor's busy times, so slots that clash with something already
  in their calendar aren't offered to patients or the call agent.

Calendar calls never block or fail a booking: syncs run in a background
thread, and busy-time lookups fail open (slots stay offered) if Google is
unreachable.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

GCAL_BASE = "https://www.googleapis.com/calendar/v3"
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"

OAUTH_SCOPES = [
    "openid",
    "email",
    # Create / delete the appointment events this app owns.
    "https://www.googleapis.com/auth/calendar.events",
    # Read busy times only (not event details) to block clashing slots.
    "https://www.googleapis.com/auth/calendar.freebusy",
]
STATE_MAX_AGE_SECONDS = 600
BUSY_CACHE_SECONDS = 120

# One worker: syncs run in order, so two syncs of one appointment can't both
# see "no event yet" and create duplicates.
_sync_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="gcal-sync")
_busy_cache: dict[tuple[str, str, str], tuple[float, list[tuple[datetime, datetime]]]] = {}


# ---------------------------------------------------------------------------
# OAuth connect flow
# ---------------------------------------------------------------------------


def oauth_configured() -> bool:
    return bool(settings.google_oauth_client_id.strip() and settings.google_oauth_client_secret.strip())


def _sign(payload: str) -> str:
    key = settings.google_oauth_client_secret.encode()
    digest = hmac.new(key, payload.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def build_authorization_url(doctor_id: str) -> str:
    """Google consent URL. ``state`` is signed so the callback can trust the doctor id."""
    if not oauth_configured():
        raise RuntimeError(
            "Google OAuth is not configured: set GOOGLE_OAUTH_CLIENT_ID and "
            "GOOGLE_OAUTH_CLIENT_SECRET in backend/.env"
        )
    payload = f"{doctor_id}.{int(time.time())}"
    params = {
        "client_id": settings.google_oauth_client_id.strip(),
        "redirect_uri": settings.google_oauth_redirect_uri,
        "response_type": "code",
        "scope": " ".join(OAUTH_SCOPES),
        # offline + consent => Google returns a refresh token every time.
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": f"{payload}.{_sign(payload)}",
    }
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


def verify_state(state: str) -> str:
    """Return the doctor id from a signed state, or raise if forged/expired."""
    try:
        doctor_id, issued, signature = state.rsplit(".", 2)
        issued_at = int(issued)
    except ValueError as exc:
        raise RuntimeError("Invalid OAuth state") from exc
    if not hmac.compare_digest(signature, _sign(f"{doctor_id}.{issued}")):
        raise RuntimeError("Invalid OAuth state")
    if time.time() - issued_at > STATE_MAX_AGE_SECONDS:
        raise RuntimeError("The Google sign-in took too long; please try again")
    return doctor_id


def complete_oauth(doctor_id: str, code: str) -> dict[str, Any]:
    """Exchange the authorization code and store the doctor's connection."""
    with httpx.Client(timeout=15) as client:
        resp = client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.google_oauth_client_id.strip(),
                "client_secret": settings.google_oauth_client_secret.strip(),
                "redirect_uri": settings.google_oauth_redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        if resp.status_code >= 400:
            raise RuntimeError(f"Google token exchange failed: {resp.text}")
        tokens = resp.json()

        refresh_token = tokens.get("refresh_token")
        if not refresh_token:
            raise RuntimeError("Google did not return a refresh token; please connect again")

        email = None
        info = client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
        )
        if info.status_code < 400:
            email = info.json().get("email")

    expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(tokens.get("expires_in", 3600)))
    from app.services.postgres_service import _cursor

    with _cursor() as cur:
        cur.execute(
            """
            INSERT INTO doctor_google_calendar (
                doctor_id, google_email, refresh_token, access_token,
                access_token_expires_at, scopes, connected_at, updated_at, last_error
            )
            VALUES (%s, %s, %s, %s, %s, %s, now(), now(), NULL)
            ON CONFLICT (doctor_id) DO UPDATE SET
                google_email = EXCLUDED.google_email,
                refresh_token = EXCLUDED.refresh_token,
                access_token = EXCLUDED.access_token,
                access_token_expires_at = EXCLUDED.access_token_expires_at,
                scopes = EXCLUDED.scopes,
                connected_at = now(),
                updated_at = now(),
                last_error = NULL
            """,
            (doctor_id, email, refresh_token, tokens["access_token"], expires_at, tokens.get("scope")),
        )
    _clear_busy_cache(doctor_id)
    return get_connection_status(doctor_id)


def get_connection_status(doctor_id: str) -> dict[str, Any]:
    from app.services.postgres_service import _cursor

    with _cursor() as cur:
        cur.execute(
            """
            SELECT google_email, calendar_id, connected_at, last_error
            FROM doctor_google_calendar WHERE doctor_id = %s
            """,
            (doctor_id,),
        )
        row = cur.fetchone()
    if not row:
        return {"connected": False, "oauth_configured": oauth_configured()}
    return {
        "connected": True,
        "oauth_configured": oauth_configured(),
        "google_email": row["google_email"],
        "calendar_id": row["calendar_id"],
        "connected_at": row["connected_at"].isoformat() if row["connected_at"] else None,
        "last_error": row["last_error"],
    }


def disconnect(doctor_id: str) -> None:
    from app.services.postgres_service import _cursor

    with _cursor() as cur:
        cur.execute(
            "DELETE FROM doctor_google_calendar WHERE doctor_id = %s RETURNING refresh_token",
            (doctor_id,),
        )
        row = cur.fetchone()
    _clear_busy_cache(doctor_id)
    if row:
        try:
            httpx.post(GOOGLE_REVOKE_URL, data={"token": row["refresh_token"]}, timeout=10)
        except httpx.HTTPError as exc:
            logger.warning("Google token revoke failed for doctor %s: %s", doctor_id, exc)


# ---------------------------------------------------------------------------
# Access tokens
# ---------------------------------------------------------------------------


def _record_error(doctor_id: str, message: str | None) -> None:
    from app.services.postgres_service import _cursor

    with _cursor() as cur:
        cur.execute(
            "UPDATE doctor_google_calendar SET last_error = %s, updated_at = now() WHERE doctor_id = %s",
            (message, doctor_id),
        )


def _access_token(doctor_id: str) -> tuple[str, str] | None:
    """(access_token, calendar_id) for a connected doctor, refreshing if needed."""
    from app.services.postgres_service import _cursor

    with _cursor() as cur:
        cur.execute("SELECT * FROM doctor_google_calendar WHERE doctor_id = %s", (doctor_id,))
        row = cur.fetchone()
    if not row:
        return None

    expires_at = row.get("access_token_expires_at")
    if row.get("access_token") and expires_at and expires_at > datetime.now(timezone.utc) + timedelta(seconds=60):
        return row["access_token"], row["calendar_id"]

    resp = httpx.post(
        GOOGLE_TOKEN_URL,
        data={
            "client_id": settings.google_oauth_client_id.strip(),
            "client_secret": settings.google_oauth_client_secret.strip(),
            "refresh_token": row["refresh_token"],
            "grant_type": "refresh_token",
        },
        timeout=15,
    )
    if resp.status_code >= 400:
        # invalid_grant = the doctor revoked access or the token expired.
        _record_error(doctor_id, f"Token refresh failed: {resp.text[:300]}")
        raise RuntimeError("Google Calendar access expired; reconnect it in Settings")

    tokens = resp.json()
    new_expiry = datetime.now(timezone.utc) + timedelta(seconds=int(tokens.get("expires_in", 3600)))
    with _cursor() as cur:
        cur.execute(
            """
            UPDATE doctor_google_calendar
            SET access_token = %s, access_token_expires_at = %s, updated_at = now(), last_error = NULL
            WHERE doctor_id = %s
            """,
            (tokens["access_token"], new_expiry, doctor_id),
        )
    return tokens["access_token"], row["calendar_id"]


# ---------------------------------------------------------------------------
# Appointment sync
# ---------------------------------------------------------------------------


def sync_appointment(appointment_id: str) -> None:
    """Make the doctor's calendar match one appointment.

    Active (booked/confirmed) and no event yet -> create one.
    Cancelled (incl. the old half of a reschedule) with an event -> delete it.
    """
    from app.services.postgres_service import CLINIC_TZ, _cursor

    with _cursor() as cur:
        cur.execute(
            """
            SELECT a.id, a.doctor_id, a.status, a.consultation_type, a.google_event_id,
                   s.slot_start, s.slot_end, p.name AS patient_name, p.phone AS patient_phone
            FROM appointments a
            JOIN availability_slots s ON s.id = a.slot_id
            LEFT JOIN patients p ON p.id = a.patient_id
            WHERE a.id = %s
            """,
            (appointment_id,),
        )
        appt = cur.fetchone()
    if not appt:
        return

    doctor_id = str(appt["doctor_id"])
    auth = _access_token(doctor_id)
    if not auth:
        return  # doctor hasn't connected Google Calendar
    token, calendar_id = auth
    headers = {"Authorization": f"Bearer {token}"}
    events_url = f"{GCAL_BASE}/calendars/{calendar_id}/events"
    active = appt["status"] in {"booked", "confirmed"}
    tz = str(CLINIC_TZ)
    times = {
        "start": {"dateTime": appt["slot_start"].astimezone(CLINIC_TZ).isoformat(), "timeZone": tz},
        "end": {"dateTime": appt["slot_end"].astimezone(CLINIC_TZ).isoformat(), "timeZone": tz},
    }

    if active and appt["google_event_id"]:
        # The appointment kept its id but may have moved to another slot (the
        # "Set Not Available" toggle does this), so keep the event's time current.
        resp = httpx.patch(f"{events_url}/{appt['google_event_id']}", json=times, headers=headers, timeout=15)
        if resp.status_code in {404, 410}:
            # Deleted in Google by the doctor; recreate it below on the next sync.
            with _cursor() as cur:
                cur.execute("UPDATE appointments SET google_event_id = NULL WHERE id = %s", (appt["id"],))
        elif resp.status_code >= 400:
            _record_error(doctor_id, f"Update event failed: {resp.text[:300]}")
            raise RuntimeError(f"Google Calendar update failed {resp.status_code}")
    elif active:
        body = {
            "summary": f"Appointment: {appt['patient_name'] or 'Patient'}",
            "description": (
                f"{(appt['consultation_type'] or '').replace('_', ' ').title()} consultation booked via CareSync AI.\n"
                f"Patient phone: {appt['patient_phone'] or '-'}"
            ),
            **times,
            "reminders": {"useDefault": True},
        }
        resp = httpx.post(events_url, json=body, headers=headers, timeout=15)
        if resp.status_code >= 400:
            _record_error(doctor_id, f"Create event failed: {resp.text[:300]}")
            raise RuntimeError(f"Google Calendar create failed {resp.status_code}")
        with _cursor() as cur:
            cur.execute(
                "UPDATE appointments SET google_event_id = %s WHERE id = %s",
                (resp.json()["id"], appt["id"]),
            )
    elif not active and appt["google_event_id"]:
        resp = httpx.delete(f"{events_url}/{appt['google_event_id']}", headers=headers, timeout=15)
        # 404/410: already gone (deleted by the doctor in Google) — fine.
        if resp.status_code >= 400 and resp.status_code not in {404, 410}:
            _record_error(doctor_id, f"Delete event failed: {resp.text[:300]}")
            raise RuntimeError(f"Google Calendar delete failed {resp.status_code}")
        with _cursor() as cur:
            cur.execute("UPDATE appointments SET google_event_id = NULL WHERE id = %s", (appt["id"],))
    else:
        return

    _clear_busy_cache(doctor_id)


def _sync_safely(appointment_id: str) -> None:
    try:
        sync_appointment(appointment_id)
    except Exception:
        logger.exception("Google Calendar sync failed for appointment %s", appointment_id)


def queue_appointment_sync(*appointment_ids: Any) -> None:
    """Sync appointments in the background; never blocks or fails the caller."""
    for appointment_id in appointment_ids:
        if appointment_id:
            _sync_executor.submit(_sync_safely, str(appointment_id))


# ---------------------------------------------------------------------------
# Busy times (block clashing slots)
# ---------------------------------------------------------------------------


def _clear_busy_cache(doctor_id: str) -> None:
    for key in [k for k in _busy_cache if k[0] == doctor_id]:
        _busy_cache.pop(key, None)


def busy_intervals(doctor_id: str, start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
    """Busy periods in the doctor's Google Calendar (cached briefly).

    Returns [] if the doctor isn't connected or Google can't be reached, so
    slots are never hidden because of a Google outage.
    """
    # Cache per doctor and day range; the window start moves with "now".
    key = (doctor_id, start.date().isoformat(), end.date().isoformat())
    cached = _busy_cache.get(key)
    if cached and time.time() - cached[0] < BUSY_CACHE_SECONDS:
        return cached[1]

    try:
        auth = _access_token(doctor_id)
        if not auth:
            return []
        token, calendar_id = auth
        resp = httpx.post(
            f"{GCAL_BASE}/freeBusy",
            json={
                "timeMin": start.astimezone(timezone.utc).isoformat(),
                "timeMax": end.astimezone(timezone.utc).isoformat(),
                "items": [{"id": calendar_id}],
            },
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        resp.raise_for_status()
        periods = resp.json().get("calendars", {}).get(calendar_id, {}).get("busy", [])
        busy = [
            (
                datetime.fromisoformat(p["start"].replace("Z", "+00:00")),
                datetime.fromisoformat(p["end"].replace("Z", "+00:00")),
            )
            for p in periods
        ]
    except Exception as exc:
        logger.warning("Google free/busy lookup failed for doctor %s: %s", doctor_id, exc)
        return []

    _busy_cache[key] = (time.time(), busy)
    return busy


def drop_busy_slots(doctor_id: str, slots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove open slots that overlap something in the doctor's Google Calendar."""
    if not slots:
        return slots

    def _dt(value: Any) -> datetime | None:
        if isinstance(value, datetime):
            return value
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None

    starts = [d for d in (_dt(s.get("slot_start")) for s in slots) if d]
    ends = [d for d in (_dt(s.get("slot_end")) for s in slots) if d]
    if not starts or not ends:
        return slots
    busy = busy_intervals(doctor_id, min(starts), max(ends))
    if not busy:
        return slots

    kept = []
    for slot in slots:
        s_start, s_end = _dt(slot.get("slot_start")), _dt(slot.get("slot_end"))
        if s_start and s_end and any(b_start < s_end and s_start < b_end for b_start, b_end in busy):
            continue
        kept.append(slot)
    return kept


# ---------------------------------------------------------------------------
# Workflow "schedule appointment" node
# ---------------------------------------------------------------------------


def _legacy_token() -> str:
    token = settings.google_calendar_access_token.strip()
    if not token:
        raise RuntimeError(
            "Google Calendar is not connected. Connect it in Settings "
            "(or set GOOGLE_CALENDAR_ACCESS_TOKEN)."
        )
    return token


async def create_calendar_event(
    doctor_identifier: str,
    summary: str,
    start_iso: str,
    end_iso: str | None = None,
    description: str | None = None,
    timezone: str | None = None,
    attendee_email: str | None = None,
) -> dict[str, Any]:
    """
    Create an event on the doctor's Google Calendar.

    Uses the doctor's OAuth connection when they've connected in Settings,
    otherwise the legacy GOOGLE_CALENDAR_ACCESS_TOKEN.

    Args:
        doctor_identifier: The doctor's id (also used for logging).
        summary: Event title (e.g. "Follow-up: John Doe").
        start_iso: ISO-8601 datetime for the event start.
        end_iso: ISO-8601 datetime for event end (defaults to start + 30 min).
        description: Optional event body text.
        timezone: IANA timezone string (defaults to CLINIC_TIMEZONE).
        attendee_email: Optional patient email to invite.

    Returns:
        The Google Calendar event resource (includes ``id``, ``htmlLink``).
    """
    import asyncio

    calendar_id = "primary"
    try:
        auth = await asyncio.to_thread(_access_token, doctor_identifier)
    except Exception:
        auth = None
    if auth:
        google_token, calendar_id = auth
    else:
        google_token = _legacy_token()
    # Naive start times are clinic-local, so the event must use the clinic's zone.
    timezone = timezone or settings.clinic_timezone

    if not end_iso:
        end_iso = (datetime.fromisoformat(start_iso) + timedelta(minutes=30)).isoformat()

    event_body: dict[str, Any] = {
        "summary": summary,
        "start": {"dateTime": start_iso, "timeZone": timezone},
        "end": {"dateTime": end_iso, "timeZone": timezone},
    }
    if description:
        event_body["description"] = description
    if attendee_email:
        event_body["attendees"] = [{"email": attendee_email}]

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{GCAL_BASE}/calendars/{calendar_id}/events",
            json=event_body,
            headers={"Authorization": f"Bearer {google_token}", "Content-Type": "application/json"},
        )

    if resp.status_code >= 400:
        logger.error("Google Calendar error %s: %s", resp.status_code, resp.text)
        raise RuntimeError(f"Google Calendar API error {resp.status_code}: {resp.text}")

    event = resp.json()
    logger.info(
        "Google Calendar event created for doctor=%s — id=%s link=%s",
        doctor_identifier,
        event.get("id"),
        event.get("htmlLink"),
    )
    return event
