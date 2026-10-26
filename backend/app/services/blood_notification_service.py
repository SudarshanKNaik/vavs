from __future__ import annotations

"""
SMS + email alongside blood request calls.

After each donor/organization call:
  * said yes (donor)     -> SMS the donor where to go and whom to ask
  * said yes (org)       -> SMS the organization the request + contact person
  * missed call (donor)  -> SMS appeal with the contact number, only for
                            emergency/urgent requests that still need blood
  * any yes              -> SMS the request's contact person who said yes
When the search ends:
  * email the requesting doctor a summary (who said yes, how many called)
  * if nobody said yes, SMS the contact person so they can arrange blood

Nobody who declined is messaged. The patient's name is never included,
matching the blood agent's rule. Messages go out in the background, each at
most once (blood_campaign_messages.dedupe_key); failures are only logged.
NOTIFY_BLOOD_SMS / NOTIFY_BLOOD_EMAIL switch each channel off.
"""

import logging
from concurrent.futures import ThreadPoolExecutor
from html import escape
from typing import Any

from app.core.config import settings
from app.services import sms_service, smtp_service

logger = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="blood-notify")

MISSED_OUTCOMES = {"no_answer", "timeout"}
APPEAL_URGENCIES = {"emergency", "urgent"}


def queue_attempt_messages(attempt_id: Any) -> None:
    """Message the right people about one finished call, in the background."""
    if attempt_id and (settings.notify_blood_sms or settings.notify_blood_email):
        _executor.submit(_safely, notify_attempt_sync, str(attempt_id))


def queue_campaign_summary(campaign_id: Any) -> None:
    """Summarize a finished blood request, in the background."""
    if campaign_id and (settings.notify_blood_sms or settings.notify_blood_email):
        _executor.submit(_safely, notify_campaign_summary_sync, str(campaign_id))


def _safely(fn, *args: Any) -> None:
    try:
        fn(*args)
    except Exception:
        logger.exception("Blood request notification failed (%s)", fn.__name__)


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------


def _attempt_context(attempt_id: str) -> dict[str, Any] | None:
    from app.services.postgres_service import _cursor

    with _cursor() as cur:
        cur.execute(
            """
            SELECT a.id, a.campaign_id, a.status, a.outcome, a.target_type, a.units_confirmed,
                   COALESCE(d.name, o.org_name) AS target_name,
                   COALESCE(d.phone_number, o.phone_number) AS target_phone,
                   d.blood_type AS donor_blood_type
            FROM blood_campaign_donor_attempts a
            LEFT JOIN blood_donors d ON d.id = a.donor_id
            LEFT JOIN blood_donor_org o ON o.id = a.org_id
            WHERE a.id = %s
            """,
            (attempt_id,),
        )
        return cur.fetchone()


def _campaign(campaign_id: str) -> dict[str, Any] | None:
    from app.services.postgres_service import get_blood_campaign

    return get_blood_campaign(campaign_id)


def _doctor_email(doctor_id: str) -> str | None:
    from app.services.postgres_service import _cursor

    with _cursor() as cur:
        cur.execute(
            """
            SELECT ua.email
            FROM doctors d
            JOIN user_accounts ua ON ua.id::text = d.auth_user_id AND ua.role = 'doctor'
            WHERE d.id::text = %s
            LIMIT 1
            """,
            (str(doctor_id),),
        )
        row = cur.fetchone()
    return row["email"] if row and row.get("email") else None


def _claim(campaign_id: str, attempt_id: str | None, kind: str, channel: str, recipient: str) -> str | None:
    """Reserve a message slot; returns its id, or None if it was already sent."""
    from app.services.postgres_service import _cursor

    key = f"{campaign_id}:{attempt_id or '-'}:{kind}:{channel}"
    with _cursor() as cur:
        cur.execute(
            """
            INSERT INTO blood_campaign_messages (campaign_id, attempt_id, kind, channel, recipient, dedupe_key)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (dedupe_key) DO NOTHING
            RETURNING id
            """,
            (campaign_id, attempt_id, kind, channel, recipient, key),
        )
        row = cur.fetchone()
    return str(row["id"]) if row else None


def _finish(message_id: str, status: str, detail: str | None = None) -> None:
    from app.services.postgres_service import _cursor

    with _cursor() as cur:
        cur.execute(
            "UPDATE blood_campaign_messages SET status = %s, detail = %s, updated_at = now() WHERE id = %s",
            (status, detail, message_id),
        )


def list_campaign_messages(campaign_id: str) -> list[dict[str, Any]]:
    from app.services.postgres_service import _cursor, _json_safe

    with _cursor() as cur:
        cur.execute(
            """
            SELECT id, attempt_id, kind, channel, recipient, status, detail, created_at
            FROM blood_campaign_messages
            WHERE campaign_id = %s
            ORDER BY created_at
            """,
            (campaign_id,),
        )
        return [_json_safe(r) for r in cur.fetchall()]


# ---------------------------------------------------------------------------
# Sending
# ---------------------------------------------------------------------------


def _send_sms(campaign_id: str, attempt_id: str | None, kind: str, phone: str | None, body: str) -> str:
    if not settings.notify_blood_sms:
        return "disabled"
    recipient = sms_service.mask_phone(phone)
    message_id = _claim(campaign_id, attempt_id, kind, "sms", recipient)
    if not message_id:
        return "duplicate"
    if not sms_service.sms_configured():
        _finish(message_id, "skipped", "Twilio not configured")
        return "skipped"
    if not sms_service.normalize_sms_number(phone):
        _finish(message_id, "skipped", "No valid mobile number")
        return "skipped"
    try:
        sms_service.send_sms_sync(phone, body)
    except Exception as exc:
        logger.warning("Blood request SMS failed kind=%s to=%s: %s", kind, recipient, exc)
        _finish(message_id, "failed", str(exc)[:300])
        return "failed"
    _finish(message_id, "sent")
    return "sent"


def _send_email(campaign_id: str, kind: str, to_email: str | None, subject: str, html: str, text: str) -> str:
    if not settings.notify_blood_email:
        return "disabled"
    if not to_email:
        return "skipped"
    message_id = _claim(campaign_id, None, kind, "email", to_email)
    if not message_id:
        return "duplicate"
    if not (settings.smtp_username.strip() and settings.smtp_password.strip()):
        _finish(message_id, "skipped", "SMTP not configured")
        return "skipped"
    try:
        smtp_service._send_email_sync(to_email, subject, html, text)
    except Exception as exc:
        logger.warning("Blood request email failed kind=%s: %s", kind, exc)
        _finish(message_id, "failed", str(exc)[:300])
        return "failed"
    _finish(message_id, "sent")
    return "sent"


def _labels(campaign: dict[str, Any]) -> dict[str, str]:
    from app.services.blood_campaign_service import COMPONENT_LABELS

    hospital = campaign.get("hospital_name") or "the hospital"
    ward = campaign.get("ward")
    return {
        "blood": f"{campaign.get('blood_type')} {COMPONENT_LABELS.get(campaign.get('component') or 'whole_blood', 'blood')}",
        "blood_type": str(campaign.get("blood_type") or ""),
        "hospital": f"{hospital}, {ward}" if ward else hospital,
        "location": (campaign.get("patient_location") or "").strip(),
        "contact": " ".join(
            part for part in [campaign.get("contact_name") or "", campaign.get("contact_phone") or ""] if part
        ) or "the hospital",
    }


def notify_attempt_sync(attempt_id: str) -> dict[str, str]:
    attempt = _attempt_context(attempt_id)
    if not attempt:
        return {}
    campaign = _campaign(str(attempt["campaign_id"]))
    if not campaign:
        return {}
    cid = str(campaign["id"])
    labels = _labels(campaign)
    is_org = attempt.get("target_type") == "org"
    accepted = attempt.get("status") == "accepted"
    result: dict[str, str] = {}

    if accepted and is_org:
        units = attempt.get("units_confirmed")
        units_text = f"{units} unit(s) of " if units else ""
        result["target"] = _send_sms(
            cid, attempt_id, "org_accepted", attempt.get("target_phone"),
            f"CareSync BloodConnect: Thank you for confirming {units_text}{labels['blood']} for "
            f"{labels['hospital']}. Please coordinate with {labels['contact']}.",
        )
        result["contact"] = _send_sms(
            cid, attempt_id, "contact_update", campaign.get("contact_phone"),
            f"CareSync: {attempt.get('target_name')} confirmed {units_text}{labels['blood']} for your "
            f"request. Phone: {attempt.get('target_phone')}.",
        )
    elif accepted:
        where = f"{labels['hospital']} ({labels['location']})" if labels["location"] else labels["hospital"]
        result["target"] = _send_sms(
            cid, attempt_id, "donor_accepted", attempt.get("target_phone"),
            f"CareSync BloodConnect: Thank you for agreeing to donate {labels['blood_type']} blood. "
            f"Please go to {where} and ask for {labels['contact']}.",
        )
        result["contact"] = _send_sms(
            cid, attempt_id, "contact_update", campaign.get("contact_phone"),
            f"CareSync: Donor {attempt.get('target_name')} ({attempt.get('donor_blood_type') or labels['blood_type']}, "
            f"{attempt.get('target_phone')}) agreed to donate for your {labels['blood']} request.",
        )
    elif (
        not is_org
        and (attempt.get("outcome") or "") in MISSED_OUTCOMES
        and (campaign.get("urgency") or "urgent") in APPEAL_URGENCIES
        and campaign.get("status") in {"draft", "running"}
    ):
        result["target"] = _send_sms(
            cid, attempt_id, "donor_missed", attempt.get("target_phone"),
            f"CareSync BloodConnect: We tried to call you. A patient at {labels['hospital']} urgently "
            f"needs {labels['blood']} and your blood group matches. If you can donate, please call "
            f"{labels['contact']}. Thank you.",
        )
    return result


def notify_campaign_summary_sync(campaign_id: str) -> dict[str, str]:
    campaign = _campaign(campaign_id)
    if not campaign:
        return {}
    from app.services.postgres_service import list_campaign_attempts

    attempts = list_campaign_attempts(campaign_id)
    labels = _labels(campaign)
    yes = [a for a in attempts if a.get("status") == "accepted"]
    called = len({str(a.get("donor_id") or a.get("org_id")) for a in attempts})
    result: dict[str, str] = {}

    if not yes:
        result["contact"] = _send_sms(
            campaign_id, None, "contact_summary", campaign.get("contact_phone"),
            f"CareSync: No donor or blood bank has confirmed your {labels['blood']} request yet "
            f"({called} contacted). Please arrange blood through your blood bank.",
        )

    lines = [
        f"{a.get('donor_name') or 'Unknown'} ({'organization' if a.get('target_type') == 'org' else 'donor'}), "
        f"{a.get('donor_phone_number') or ''}"
        + (f", {a['units_confirmed']} unit(s)" if a.get("units_confirmed") else "")
        for a in yes
    ]
    outcome = f"{len(yes)} confirmed" if yes else "nobody confirmed"
    subject = f"Blood request {labels['blood']}: {outcome}"
    intro = (
        f"Your request for {campaign.get('units_needed') or 1} unit(s) of {labels['blood']} at "
        f"{labels['hospital']} has finished. {called} donor(s)/organization(s) were contacted."
    )
    html = (
        "<div style='font-family:Arial,sans-serif;line-height:1.5;color:#2C2420;max-width:560px'>"
        "<h2 style='margin:0 0 12px'>CareSync BloodConnect</h2>"
        f"<p>{escape(intro)}</p>"
        + (
            "<p><strong>Confirmed:</strong></p><ul>" + "".join(f"<li>{escape(line)}</li>" for line in lines) + "</ul>"
            if lines
            else "<p><strong>Nobody confirmed.</strong> Please arrange blood through your blood bank.</p>"
        )
        + "</div>"
    )
    text = intro + "\n\n" + ("Confirmed:\n" + "\n".join(f"- {line}" for line in lines) if lines else "Nobody confirmed.")
    result["doctor"] = _send_email(
        campaign_id, "doctor_summary", _doctor_email(str(campaign["doctor_id"])), subject, html, text
    )
    return result
