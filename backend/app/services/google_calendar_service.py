"""
Google Calendar Service
-----------------------
Creates calendar events in Google Calendar using a pre-configured access token.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

def _get_google_token() -> str:
    token = settings.google_calendar_access_token.strip()
    if not token:
        raise RuntimeError(
            "GOOGLE_CALENDAR_ACCESS_TOKEN is not configured. "
            "Set it in backend/.env to enable calendar event creation."
        )
    return token


# ---------------------------------------------------------------------------
# Google Calendar API
# ---------------------------------------------------------------------------

GCAL_BASE = "https://www.googleapis.com/calendar/v3"


async def create_calendar_event(
    doctor_identifier: str,
    summary: str,
    start_iso: str,
    end_iso: str | None = None,
    description: str | None = None,
    timezone: str = "America/New_York",
    attendee_email: str | None = None,
) -> dict[str, Any]:
    """
    Create an event on the doctor's primary Google Calendar.

    Args:
        doctor_identifier: Identifier for logging/tracing the doctor context.
        summary: Event title (e.g. "Follow-up: John Doe").
        start_iso: ISO-8601 datetime for the event start.
        end_iso: ISO-8601 datetime for event end (defaults to start + 30 min).
        description: Optional event body text.
        timezone: IANA timezone string.
        attendee_email: Optional patient email to invite.

    Returns:
        The Google Calendar event resource (includes ``id``, ``htmlLink``).
    """
    google_token = _get_google_token()

    # Default to 30-minute appointment if no end time
    if not end_iso:
        start_dt = datetime.fromisoformat(start_iso)
        end_dt = start_dt + timedelta(minutes=30)
        end_iso = end_dt.isoformat()

    event_body: dict[str, Any] = {
        "summary": summary,
        "start": {"dateTime": start_iso, "timeZone": timezone},
        "end": {"dateTime": end_iso, "timeZone": timezone},
    }
    if description:
        event_body["description"] = description
    if attendee_email:
        event_body["attendees"] = [{"email": attendee_email}]

    url = f"{GCAL_BASE}/calendars/primary/events"
    headers = {
        "Authorization": f"Bearer {google_token}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(url, json=event_body, headers=headers)

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
