from __future__ import annotations

import asyncio
import logging
import smtplib
from email.message import EmailMessage
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)


def _smtp_settings() -> tuple[str, int, str, str, str]:
    host = settings.smtp_host.strip() or "smtp.gmail.com"
    port = int(settings.smtp_port or 587)
    username = settings.smtp_username.strip()
    password = settings.smtp_password.strip()
    from_email = settings.smtp_from_email.strip() or username

    if not username:
        raise RuntimeError("SMTP_USERNAME must be configured in backend/.env")
    if not password:
        raise RuntimeError("SMTP_PASSWORD must be configured in backend/.env")
    if not from_email:
        raise RuntimeError("SMTP_FROM_EMAIL must be configured in backend/.env")

    return host, port, username, password, from_email


def _send_email_sync(to_email: str, subject: str, html: str, text: str | None = None) -> dict[str, Any]:
    host, port, username, password, from_email = _smtp_settings()

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_email
    msg["To"] = to_email

    plain_text = text or ""
    if not plain_text:
        plain_text = "Please view this email in an HTML-compatible client."

    msg.set_content(plain_text)
    msg.add_alternative(html, subtype="html")

    with smtplib.SMTP(host, port, timeout=20) as server:
        server.starttls()
        server.login(username, password)
        server.send_message(msg)

    return {"id": f"smtp:{to_email}:{subject}"}


async def send_email(
    to_email: str,
    subject: str,
    html: str,
    text: str | None = None,
) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(_send_email_sync, to_email, subject, html, text)
    except smtplib.SMTPException as exc:
        logger.error("SMTP error while sending email: %s", exc)
        raise RuntimeError(f"SMTP error: {exc}") from exc


async def send_otp_email(to_email: str, otp_code: str, purpose: str) -> dict[str, Any]:
    subject = f"Your CareSync {purpose.replace('_', ' ').title()} OTP"
    html = (
        "<div style='font-family: Arial, sans-serif; line-height: 1.4;'>"
        "<h2>CareSync Verification Code</h2>"
        f"<p>Your one-time password is <strong>{otp_code}</strong>.</p>"
        "<p>This code expires in 10 minutes.</p>"
        "<p>If you did not request this, you can ignore this email.</p>"
        "</div>"
    )
    text = (
        f"CareSync OTP for {purpose}: {otp_code}. "
        "This code expires in 10 minutes."
    )
    return await send_email(to_email=to_email, subject=subject, html=html, text=text)


async def send_notification_email(to_email: str, subject: str, message: str) -> dict[str, Any]:
    html = (
        "<div style='font-family: Arial, sans-serif; line-height: 1.4;'>"
        "<h2>CareSync Notification</h2>"
        f"<p>{message}</p>"
        "</div>"
    )
    return await send_email(to_email=to_email, subject=subject, html=html, text=message)


# ---------------------------------------------------------------------------
# Appointment confirmation emails (sent via notification_service)
# ---------------------------------------------------------------------------


def _appointment_email_context(appointment_id: str) -> dict[str, Any] | None:
    from app.services.postgres_service import CLINIC_TZ, _cursor

    with _cursor() as cur:
        cur.execute(
            """
            SELECT a.id, a.status, a.consultation_type,
                   s.slot_start, s.slot_end,
                   p.name AS patient_name,
                   pa.email AS patient_email,
                   d.name AS doctor_name, d.specialty AS doctor_specialty
            FROM appointments a
            JOIN availability_slots s ON s.id = a.slot_id
            JOIN patients p ON p.id = a.patient_id
            LEFT JOIN patient_accounts pa ON pa.patient_id = a.patient_id
            LEFT JOIN doctors d ON d.id = a.doctor_id
            WHERE a.id = %s
            """,
            (appointment_id,),
        )
        row = cur.fetchone()
    if not row:
        return None
    start = row["slot_start"].astimezone(CLINIC_TZ)
    end = row["slot_end"].astimezone(CLINIC_TZ)
    row["when"] = f"{start.strftime('%A')}, {start.day} {start.strftime('%B %Y')}"
    row["time"] = f"{start.hour % 12 or 12}:{start.strftime('%M %p')} to {end.hour % 12 or 12}:{end.strftime('%M %p')}"
    return row


def send_appointment_confirmation_sync(appointment_id: str, rescheduled_from: str | None = None) -> bool:
    """Email the patient their booking (or new time, after a reschedule).

    Returns False without error when there's nothing to send: SMTP isn't
    configured, the patient has no email on file, or the booking is gone.
    """
    from html import escape

    if not (settings.smtp_username.strip() and settings.smtp_password.strip()):
        logger.info("Booking email skipped: SMTP not configured")
        return False
    ctx = _appointment_email_context(appointment_id)
    if not ctx or ctx["status"] not in {"booked", "confirmed"}:
        return False
    if not ctx["patient_email"]:
        logger.info("Booking email skipped: no email on file for appointment %s", appointment_id)
        return False

    doctor = ctx["doctor_name"] or "your doctor"
    specialty = f" ({ctx['doctor_specialty']})" if ctx["doctor_specialty"] else ""
    consult = {"video": "Video consultation", "chat": "Chat consultation", "in_person": "In-person visit"}.get(
        ctx["consultation_type"], "Consultation"
    )
    portal = f"{settings.frontend_base_url.rstrip('/')}/patient"

    if rescheduled_from:
        from app.services.postgres_service import CLINIC_TZ, _cursor

        with _cursor() as cur:
            cur.execute(
                "SELECT s.slot_start FROM appointments a JOIN availability_slots s ON s.id = a.slot_id WHERE a.id = %s",
                (rescheduled_from,),
            )
            old = cur.fetchone()
        old_when = (
            old["slot_start"].astimezone(CLINIC_TZ).strftime("%A %d %B at %I:%M %p") if old else "your previous time"
        )
        subject = f"Appointment rescheduled: {ctx['when']}"
        intro = f"Your appointment has been moved from {old_when} to the new time below."
    else:
        subject = f"Appointment confirmed: {ctx['when']}"
        intro = "Your appointment is confirmed. Here are the details."

    rows = [
        ("Doctor", f"{doctor}{specialty}"),
        ("Date", ctx["when"]),
        ("Time", ctx["time"]),
        ("Type", consult),
    ]
    rows_html = "".join(
        f"<tr><td style='padding:6px 16px 6px 0;color:#6E6057'>{escape(k)}</td>"
        f"<td style='padding:6px 0;font-weight:600;color:#2C2420'>{escape(v)}</td></tr>"
        for k, v in rows
    )
    html = (
        "<div style='font-family:Arial,sans-serif;line-height:1.5;color:#2C2420;max-width:520px'>"
        "<h2 style='margin:0 0 12px'>CareSync AI</h2>"
        f"<p>Hello {escape(ctx['patient_name'] or 'there')},</p>"
        f"<p>{escape(intro)}</p>"
        f"<table style='border-collapse:collapse;margin:12px 0'>{rows_html}</table>"
        f"<p>You can view, reschedule or cancel it in your <a href='{escape(portal)}'>patient portal</a>.</p>"
        "<p style='color:#6E6057;font-size:13px'>If you didn't book this appointment, please contact the clinic.</p>"
        "</div>"
    )
    text = (
        f"Hello {ctx['patient_name'] or 'there'},\n\n{intro}\n\n"
        + "\n".join(f"{k}: {v}" for k, v in rows)
        + f"\n\nView, reschedule or cancel: {portal}\n"
    )
    _send_email_sync(ctx["patient_email"], subject, html, text)
    logger.info("Booking email sent for appointment %s", appointment_id)
    return True
