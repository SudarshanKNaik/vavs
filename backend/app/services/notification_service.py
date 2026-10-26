from __future__ import annotations

"""
Patient notifications (SMS + email) for appointment changes.

Every booking, reschedule, cancellation and clinic-initiated move calls
``queue_appointment_notification``. Messages are sent in the background and
failures are only logged, so a notification can never delay or break the
change itself.

  event        SMS  email
  booked       yes  yes (smtp_service confirmation template)
  rescheduled  yes  yes (smtp_service confirmation template)
  moved        yes  yes   clinic moved it, e.g. doctor marked unavailable
  cancelled    yes  yes   by the patient, the doctor or the system

Email needs an address on file (patient portal account); SMS needs a mobile
number. NOTIFY_PATIENTS_SMS / NOTIFY_PATIENTS_EMAIL switch each channel off.
"""

import logging
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from html import escape
from typing import Any

from app.core.config import settings
from app.services import sms_service, smtp_service

logger = logging.getLogger(__name__)

EVENTS = {"booked", "rescheduled", "moved", "cancelled"}

# One worker keeps messages for the same appointment in order.
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="patient-notify")


def queue_appointment_notification(
    appointment_id: Any,
    event: str,
    *,
    rescheduled_from: Any = None,
    previous_start: datetime | str | None = None,
    cancelled_by: str | None = None,
    reason: str | None = None,
) -> None:
    """Notify the patient about an appointment change, in the background."""
    if not appointment_id or event not in EVENTS:
        return
    if not (settings.notify_patients_sms or settings.notify_patients_email):
        return
    _executor.submit(
        _notify_safely,
        str(appointment_id),
        event,
        str(rescheduled_from) if rescheduled_from else None,
        previous_start,
        cancelled_by,
        reason,
    )


def _notify_safely(*args: Any) -> None:
    try:
        notify_appointment_sync(*args)
    except Exception:
        logger.exception("Patient notification failed for appointment %s", args[0] if args else "?")


# ---------------------------------------------------------------------------
# Message building
# ---------------------------------------------------------------------------


def _appointment_context(appointment_id: str) -> dict[str, Any] | None:
    from app.services.postgres_service import _cursor

    with _cursor() as cur:
        cur.execute(
            """
            SELECT a.id, a.status, s.slot_start,
                   p.name AS patient_name, p.phone AS patient_phone,
                   pa.email AS patient_email,
                   d.name AS doctor_name
            FROM appointments a
            JOIN availability_slots s ON s.id = a.slot_id
            JOIN patients p ON p.id = a.patient_id
            LEFT JOIN patient_accounts pa ON pa.patient_id = a.patient_id
            LEFT JOIN doctors d ON d.id = a.doctor_id
            WHERE a.id = %s
            """,
            (appointment_id,),
        )
        return cur.fetchone()


def _slot_start_of(appointment_id: str | None) -> datetime | None:
    if not appointment_id:
        return None
    from app.services.postgres_service import _cursor

    with _cursor() as cur:
        cur.execute(
            "SELECT s.slot_start FROM appointments a JOIN availability_slots s ON s.id = a.slot_id WHERE a.id = %s",
            (appointment_id,),
        )
        row = cur.fetchone()
    return row["slot_start"] if row else None


def _when(value: datetime | str | None) -> str:
    """'Tue 27 Oct, 2:00 PM' in clinic time."""
    from app.services.postgres_service import CLINIC_TZ, _parse_iso_datetime

    dt = _parse_iso_datetime(value)
    if not dt:
        return "your scheduled time"
    local = dt.astimezone(CLINIC_TZ)
    return f"{local.strftime('%a')} {local.day} {local.strftime('%b')}, {local.hour % 12 or 12}:{local.strftime('%M %p')}"


def _doctor_label(name: str | None) -> str:
    """'Dr. Meera Joshi (Hubli, Karnataka)' -> 'Dr. Meera Joshi'."""
    clean = re.sub(r"\s*\([^)]*\)\s*$", "", (name or "").strip())
    if not clean:
        return "your doctor"
    return clean if clean.lower().startswith("dr") else f"Dr. {clean}"


def _portal_link() -> str:
    base = settings.frontend_base_url.rstrip("/")
    # A localhost link is useless on a patient's phone.
    if not base or "localhost" in base or "127.0.0.1" in base:
        return ""
    return f"{base}/patient"


def build_sms(
    event: str,
    ctx: dict[str, Any],
    *,
    previous_start: datetime | str | None = None,
    cancelled_by: str | None = None,
    reason: str | None = None,
) -> str:
    doctor = _doctor_label(ctx.get("doctor_name"))
    when = _when(ctx.get("slot_start"))
    link = _portal_link()
    reason_text = f" Reason: {reason.strip()[:80]}." if reason and reason.strip() else ""

    if event == "booked":
        text = f"CareSync: Your appointment with {doctor} is confirmed for {when}."
        if link:
            text += f" Manage: {link}"
    elif event == "rescheduled":
        text = f"CareSync: Your appointment with {doctor} is moved to {when}"
        text += f" (was {_when(previous_start)})." if previous_start else "."
    elif event == "moved":
        text = (
            f"CareSync: {doctor} is unavailable at your original time, so your appointment "
            f"is moved to {when}."
        )
        if previous_start:
            text = text[:-1] + f" (was {_when(previous_start)})."
        text += " Reply or call the clinic if this doesn't suit you."
    else:  # cancelled
        if cancelled_by == "patient":
            text = f"CareSync: Your appointment with {doctor} on {when} is cancelled."
        else:
            text = (
                f"CareSync: Sorry, your appointment with {doctor} on {when} was cancelled "
                f"by the clinic.{reason_text} Please book a new time"
            )
            text += f": {link}" if link else "."
    return text


def _cancel_or_move_email(
    event: str,
    ctx: dict[str, Any],
    *,
    previous_start: datetime | str | None,
    cancelled_by: str | None,
    reason: str | None,
) -> tuple[str, str, str]:
    doctor = _doctor_label(ctx.get("doctor_name"))
    when = _when(ctx.get("slot_start"))
    name = ctx.get("patient_name") or "there"
    link = f"{settings.frontend_base_url.rstrip('/')}/patient"

    if event == "moved":
        subject = f"Appointment moved: {when}"
        lines = [
            f"{doctor} is unavailable at your original time"
            + (f" ({_when(previous_start)})" if previous_start else "")
            + ", so your appointment has been moved.",
            f"New time: {when}.",
            "If the new time doesn't suit you, you can reschedule it in your patient portal.",
        ]
    elif cancelled_by == "patient":
        subject = f"Appointment cancelled: {when}"
        lines = [f"Your appointment with {doctor} on {when} has been cancelled as requested."]
    else:
        subject = f"Appointment cancelled by the clinic: {when}"
        lines = [f"We're sorry, your appointment with {doctor} on {when} had to be cancelled by the clinic."]
        if reason and reason.strip():
            lines.append(f"Reason: {reason.strip()}")
        lines.append("Please book a new time in your patient portal.")

    html = (
        "<div style='font-family:Arial,sans-serif;line-height:1.5;color:#2C2420;max-width:520px'>"
        "<h2 style='margin:0 0 12px'>CareSync AI</h2>"
        f"<p>Hello {escape(name)},</p>"
        + "".join(f"<p>{escape(line)}</p>" for line in lines)
        + f"<p><a href='{escape(link)}'>Open your patient portal</a></p>"
        "</div>"
    )
    text = f"Hello {name},\n\n" + "\n".join(lines) + f"\n\nPatient portal: {link}\n"
    return subject, html, text


# ---------------------------------------------------------------------------
# Sending
# ---------------------------------------------------------------------------


def notify_appointment_sync(
    appointment_id: str,
    event: str,
    rescheduled_from: str | None = None,
    previous_start: datetime | str | None = None,
    cancelled_by: str | None = None,
    reason: str | None = None,
) -> dict[str, str]:
    """Send the SMS and email for one appointment event. Returns per-channel status."""
    ctx = _appointment_context(appointment_id)
    if not ctx:
        return {"sms": "skipped: appointment not found", "email": "skipped: appointment not found"}
    if previous_start is None and rescheduled_from:
        previous_start = _slot_start_of(rescheduled_from)

    result: dict[str, str] = {}

    if not settings.notify_patients_sms:
        result["sms"] = "disabled"
    elif not sms_service.sms_configured():
        result["sms"] = "skipped: Twilio not configured"
    elif not sms_service.normalize_sms_number(ctx.get("patient_phone")):
        result["sms"] = "skipped: no valid mobile number"
    else:
        body = build_sms(event, ctx, previous_start=previous_start, cancelled_by=cancelled_by, reason=reason)
        try:
            sms_service.send_sms_sync(ctx["patient_phone"], body)
            result["sms"] = "sent"
        except Exception as exc:
            logger.warning(
                "Appointment SMS failed appointment=%s event=%s to=%s: %s",
                appointment_id, event, sms_service.mask_phone(ctx.get("patient_phone")), exc,
            )
            result["sms"] = "failed"

    if not settings.notify_patients_email:
        result["email"] = "disabled"
    elif event in {"booked", "rescheduled"}:
        try:
            sent = smtp_service.send_appointment_confirmation_sync(appointment_id, rescheduled_from)
            result["email"] = "sent" if sent else "skipped"
        except Exception as exc:
            logger.warning("Appointment email failed appointment=%s event=%s: %s", appointment_id, event, exc)
            result["email"] = "failed"
    elif not (settings.smtp_username.strip() and settings.smtp_password.strip()):
        result["email"] = "skipped: SMTP not configured"
    elif not ctx.get("patient_email"):
        result["email"] = "skipped: no email on file"
    else:
        subject, html, text = _cancel_or_move_email(
            event, ctx, previous_start=previous_start, cancelled_by=cancelled_by, reason=reason
        )
        try:
            smtp_service._send_email_sync(ctx["patient_email"], subject, html, text)
            result["email"] = "sent"
        except Exception as exc:
            logger.warning("Appointment email failed appointment=%s event=%s: %s", appointment_id, event, exc)
            result["email"] = "failed"

    logger.info("Patient notified appointment=%s event=%s %s", appointment_id, event, result)
    return result
