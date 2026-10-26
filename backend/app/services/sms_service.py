from __future__ import annotations

"""
Outbound SMS through Twilio (TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN /
TWILIO_PHONE_NUMBER). Numbers are normalized the same way as AI calls:
Indian mobile numbers to +91XXXXXXXXXX.
"""

import logging
import re

from app.core.config import settings

logger = logging.getLogger(__name__)


def sms_configured() -> bool:
    return bool(
        settings.twilio_account_sid.strip()
        and settings.twilio_auth_token.strip()
        and settings.twilio_phone_number.strip()
    )


def normalize_sms_number(raw_phone: str | None) -> str | None:
    """+91 + the last 10 digits, or None when the number can't be a mobile."""
    digits = re.sub(r"\D", "", raw_phone or "")
    if len(digits) < 10:
        return None
    return f"+91{digits[-10:]}"


def mask_phone(phone: str | None) -> str:
    digits = re.sub(r"\D", "", phone or "")
    return f"***{digits[-4:]}" if len(digits) >= 4 else "***"


def send_sms_sync(to_phone: str | None, body: str) -> str:
    """Send one SMS and return the Twilio message SID. Raises on failure."""
    if not sms_configured():
        raise RuntimeError(
            "Twilio is not configured. Set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN "
            "and TWILIO_PHONE_NUMBER in backend/.env to enable SMS."
        )
    to_number = normalize_sms_number(to_phone)
    if not to_number:
        raise RuntimeError("Phone number is not a valid mobile number")

    from twilio.rest import Client as TwilioClient

    client = TwilioClient(settings.twilio_account_sid, settings.twilio_auth_token)
    message = client.messages.create(
        to=to_number, from_=settings.twilio_phone_number.strip(), body=body
    )
    logger.info("SMS sent to %s sid=%s", mask_phone(to_number), message.sid)
    return message.sid
