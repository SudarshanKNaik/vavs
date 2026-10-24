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
