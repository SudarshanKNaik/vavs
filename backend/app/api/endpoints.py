from __future__ import annotations

"""
FastAPI route endpoints for MedTrigger.
"""

import asyncio
import logging
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import requests
from fastapi import APIRouter, File, Form, HTTPException, Request, Response, UploadFile, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

import app.services.postgres_service as db
from app.core.config import settings
from app.services.blood_campaign_service import (
    URGENCY_BATCH_SIZES,
    get_blood_campaign_map_points,
    get_blood_campaign_snapshot,
    ingest_blood_excel,
    start_blood_campaign,
)
from app.services.workflow_engine import execute_workflow
from app.services.workflow_ai_builder_service import (
    WorkflowBuilderError,
    generate_workflow_from_natural_language,
)
from app.services.workflow_templates_service import (
    get_workflow_template,
    list_workflow_templates,
)

logger = logging.getLogger(__name__)

router = APIRouter()

ALLOWED_TRIGGER_UPLOAD_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png"}

FOLLOW_UP_TERMINAL_STATUSES = {"completed", "failed", "cancelled", "skipped"}
_follow_up_scheduler_task: asyncio.Task | None = None
_follow_up_scheduler_started_at: datetime | None = None
_follow_up_scheduler_last_tick_at: datetime | None = None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_now_iso() -> str:
    return _utc_now().isoformat()


def _is_follow_up_needed(
    *,
    patient_confirmed: bool,
    confirmed_date: str,
    call_outcome: str,
) -> bool:
    if patient_confirmed and confirmed_date:
        return False

    outcome = (call_outcome or "").strip().lower()
    negative_outcomes = {
        "rejected",
        "declined",
        "failed",
        "no_answer",
        "busy",
        "unreachable",
        "callback_requested",
        "interrupted",
    }
    if outcome in negative_outcomes:
        return True

    return True


def _follow_up_reason(
    *,
    patient_confirmed: bool,
    confirmed_date: str,
    call_outcome: str,
) -> str:
    if patient_confirmed and not confirmed_date:
        return "Patient confirmed but no appointment date captured"
    if patient_confirmed and confirmed_date:
        return (
            f"Patient chose {confirmed_date} but it could not be booked "
            "(taken by another caller or not on the schedule)"
        )
    if not patient_confirmed:
        return f"No booking confirmation. call_outcome={call_outcome or 'unknown'}"
    return "Call completed without successful booking"


def _append_follow_up_log(
    job_id: str,
    level: str,
    message: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    try:
        db.create_follow_up_job_log(
            {
                "job_id": job_id,
                "level": level,
                "message": message,
                "metadata": metadata or {},
            }
        )
    except Exception as exc:
        logger.warning("Could not write follow_up_job log for %s: %s", job_id, exc)


def _enqueue_follow_up_if_needed(
    *,
    call_log: dict[str, Any],
    patient_confirmed: bool,
    confirmed_date: str,
    call_outcome: str,
    source: str,
) -> dict[str, Any] | None:
    if not call_log:
        return None

    call_log_id = str(call_log.get("id") or "").strip()
    if not call_log_id:
        return None

    patient_id = str(call_log.get("patient_id") or "").strip()
    doctor_id = str(_resolve_doctor_id_for_call_log(call_log) or "").strip()

    if not _is_follow_up_needed(
        patient_confirmed=patient_confirmed,
        confirmed_date=confirmed_date,
        call_outcome=call_outcome,
    ):
        # The patient picked a time, but that only counts if it was booked:
        # with simultaneous calls another caller can win the same slot, and the
        # patient must not be left believing they have an appointment.
        try:
            booked = bool(
                patient_id
                and doctor_id
                and db.has_active_appointment_for_patient_doctor(patient_id, doctor_id)
            )
        except Exception as exc:
            logger.warning("Follow-up booking check failed: %s", exc)
            booked = True  # can't tell; don't risk a duplicate call
        if booked:
            return None

    if patient_id and doctor_id:
        try:
            if db.has_active_appointment_for_patient_doctor(patient_id, doctor_id):
                logger.info(
                    "Follow-up skipped: patient already has active appointment patient_id=%s doctor_id=%s",
                    patient_id,
                    doctor_id,
                )
                return None
        except Exception as exc:
            logger.warning("Follow-up appointment pre-check failed: %s", exc)

    delay = max(1, int(settings.follow_up_cron_delay_minutes))
    scheduled_for = _utc_now() + timedelta(minutes=delay)
    reason = _follow_up_reason(
        patient_confirmed=patient_confirmed,
        confirmed_date=confirmed_date,
        call_outcome=call_outcome,
    )
    max_attempts = max(1, int(settings.follow_up_cron_max_attempts))

    existing = db.get_follow_up_job_by_call_log(call_log_id)
    if existing:
        status = str(existing.get("status") or "").lower()
        if status in FOLLOW_UP_TERMINAL_STATUSES:
            return existing

        updated = db.update_follow_up_job(
            existing["id"],
            {
                "status": "queued",
                "reason": reason,
                "scheduled_for": scheduled_for,
                "last_error": None,
                "max_attempts": max_attempts,
                "metadata": {
                    **(existing.get("metadata") or {}),
                    "last_enqueued_source": source,
                    "last_call_outcome": call_outcome,
                },
            },
        )
        _append_follow_up_log(
            updated["id"],
            "info",
            f"Follow-up re-queued by {source}",
            {
                "call_log_id": call_log_id,
                "reason": reason,
                "scheduled_for": scheduled_for.isoformat(),
            },
        )
        return updated

    job = db.create_follow_up_job(
        {
            "call_log_id": call_log_id,
            "workflow_id": call_log.get("workflow_id"),
            "doctor_id": call_log.get("doctor_id"),
            "patient_id": call_log.get("patient_id"),
            "status": "queued",
            "reason": reason,
            "scheduled_for": scheduled_for,
            "max_attempts": max_attempts,
            "metadata": {
                "created_by_source": source,
                "call_outcome": call_outcome,
                "patient_confirmed": patient_confirmed,
                "confirmed_date": confirmed_date,
            },
        }
    )
    _append_follow_up_log(
        job["id"],
        "info",
        f"Follow-up queued by {source}",
        {
            "call_log_id": call_log_id,
            "reason": reason,
            "scheduled_for": scheduled_for.isoformat(),
        },
    )
    logger.info(
        "Follow-up queued job_id=%s call_log_id=%s scheduled_for=%s",
        job["id"],
        call_log_id,
        scheduled_for.isoformat(),
    )
    return job


async def _run_db_call(func, *args, **kwargs):
    return await run_in_threadpool(lambda: func(*args, **kwargs))


async def _resolve_doctor_or_404_async(doctor_identifier: str) -> dict:
    doctor = await _run_db_call(db.resolve_doctor, doctor_identifier)
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found")
    return doctor


def _resolve_doctor_or_404(doctor_identifier: str) -> dict:
    doctor = db.resolve_doctor(doctor_identifier)
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found")
    return doctor


def _format_lab_results_summary(lab_results: list[dict[str, Any]], max_items: int = 6) -> str:
    if not lab_results:
        return "No specific lab values were extracted from your uploaded report."

    lines: list[str] = []
    for row in lab_results[:max_items]:
        test_name = str(row.get("test_name") or "Test").strip()
        value = str(row.get("value") or "-").strip()
        unit = str(row.get("unit") or "").strip()
        ref = str(row.get("reference_range") or "").strip()
        flag = str(row.get("flag") or "normal").strip().lower()

        suffix_parts: list[str] = []
        if unit:
            suffix_parts.append(unit)
        if ref:
            suffix_parts.append(f"ref: {ref}")
        if flag and flag != "normal":
            suffix_parts.append(f"flag: {flag}")

        suffix = f" ({', '.join(suffix_parts)})" if suffix_parts else ""
        lines.append(f"- {test_name}: {value}{suffix}")

    remaining = len(lab_results) - len(lines)
    if remaining > 0:
        lines.append(f"- +{remaining} more result(s)")

    return "\n".join(lines)


def _format_slot_options_for_email(slots: list[dict[str, Any]], max_items: int = 5) -> str:
    if not slots:
        return "No immediate slots are open right now. Please contact the clinic for scheduling support."

    lines: list[str] = []
    for slot in slots[:max_items]:
        start_dt = slot.get("slot_start")
        end_dt = slot.get("slot_end")

        if isinstance(start_dt, datetime):
            local_start = start_dt + timedelta(hours=5, minutes=30)
            day_part = local_start.strftime("%A, %d %b %Y")
            start_time = local_start.strftime("%I:%M %p")
        else:
            day_part = str(start_dt or "Upcoming")
            start_time = ""

        if isinstance(end_dt, datetime):
            local_end = end_dt + timedelta(hours=5, minutes=30)
            end_time = local_end.strftime("%I:%M %p")
        else:
            end_time = ""

        time_range = f"{start_time} - {end_time}" if start_time and end_time else start_time
        label = f"- {day_part}"
        if time_range:
            label += f" at {time_range}"
        lines.append(label)

    return "\n".join(lines)


def _derive_report_summary_text(
    raw_text: str,
    patient_info: dict[str, Any] | None,
    lab_results: list[dict[str, Any]] | None,
) -> str:
    patient_info = patient_info or {}
    lab_results = lab_results or []

    if lab_results:
        abnormal = [r for r in lab_results if str(r.get("flag") or "").lower() in {"high", "low"}]
        top_tests = ", ".join(
            str(r.get("test_name") or "").strip()
            for r in lab_results[:4]
            if str(r.get("test_name") or "").strip()
        )
        if abnormal:
            return (
                f"Extracted {len(lab_results)} lab value(s). "
                f"{len(abnormal)} value(s) are flagged outside reference range. "
                f"Key tests: {top_tests or 'see details below'}."
            )
        return (
            f"Extracted {len(lab_results)} lab value(s). "
            f"No out-of-range flags detected in parsed values. "
            f"Key tests: {top_tests or 'see details below'}."
        )

    text = (raw_text or "").strip()
    if not text:
        return "We received your report, but detailed values could not be extracted automatically. Please review the attached details with your doctor."

    lines = [
        ln.strip()
        for ln in text.splitlines()
        if ln and len(ln.strip()) >= 12 and not ln.strip().isdigit()
    ]
    cleaned: list[str] = []
    for ln in lines:
        if ln.lower().startswith(("page ", "confidential", "printed on")):
            continue
        cleaned.append(ln)
        if len(cleaned) >= 3:
            break

    summary_body = " ".join(cleaned)
    summary_body = re.sub(r"\s+", " ", summary_body).strip()
    if len(summary_body) > 420:
        summary_body = summary_body[:417].rstrip() + "..."

    patient_name = str(patient_info.get("name") or "").strip()
    if patient_name:
        return f"Report summary for {patient_name}: {summary_body or 'Document text extracted successfully; key clinical values were not clearly structured.'}"
    return summary_body or "Document text extracted successfully; key clinical values were not clearly structured."


async def _send_patient_report_summary_email(
    *,
    patient: dict[str, Any],
    doctor: dict[str, Any] | None,
    lab_results: list[dict[str, Any]],
    report_summary_text: str,
    slot_options: list[dict[str, Any]],
    file_name: str,
) -> tuple[bool, str]:
    from app.services.smtp_service import send_email

    patient_id = patient.get("id")
    patient_email = ""
    if patient_id:
        patient_email = str(db.get_patient_account_email(patient_id) or "").strip()
    if not patient_email:
        patient_email = str(patient.get("email") or "").strip()
    if not patient_email:
        return False, "Patient email not found"

    doctor_name = str((doctor or {}).get("name") or "your doctor").strip() or "your doctor"
    lab_summary = _format_lab_results_summary(lab_results)
    slot_summary = _format_slot_options_for_email(slot_options)

    subject = "Lab Report Summary and Next Available Appointment Slots"
    message = (
        f"Hello {patient.get('name', 'Patient')},\n\n"
        f"Dr. {doctor_name} has reviewed the uploaded report ({file_name}).\n\n"
        "Clinical summary:\n"
        f"{report_summary_text}\n\n"
        "Report summary:\n"
        f"{lab_summary}\n\n"
        f"Next available appointment slots with Dr. {doctor_name}:\n"
        f"{slot_summary}\n\n"
        "If you would like to confirm a slot, please reply to this email or contact the clinic.\n\n"
        "Regards,\nCareSync"
    )

    lab_rows_html = "".join(
        (
            "<tr>"
            f"<td style='padding:8px;border-bottom:1px solid #eef2f7;color:#0f172a'>{str(r.get('test_name') or '-')}</td>"
            f"<td style='padding:8px;border-bottom:1px solid #eef2f7;color:#0f172a'>{str(r.get('value') or '-')}</td>"
            f"<td style='padding:8px;border-bottom:1px solid #eef2f7;color:#475569'>{str(r.get('unit') or '-')}</td>"
            f"<td style='padding:8px;border-bottom:1px solid #eef2f7;color:#475569'>{str(r.get('reference_range') or '-')}</td>"
            f"<td style='padding:8px;border-bottom:1px solid #eef2f7;color:#0f172a'>{str(r.get('flag') or 'normal')}</td>"
            "</tr>"
        )
        for r in (lab_results or [])[:8]
    )
    if not lab_rows_html:
        lab_rows_html = (
            "<tr><td colspan='5' style='padding:10px;color:#64748b'>"
            "No specific lab values were extracted from this report."
            "</td></tr>"
        )

    slot_rows_html = ""
    for s in (slot_options or [])[:5]:
        start_dt = s.get("slot_start")
        end_dt = s.get("slot_end")
        if isinstance(start_dt, datetime):
            local_start = start_dt + timedelta(hours=5, minutes=30)
            date_label = local_start.strftime("%A, %d %b %Y")
            time_start = local_start.strftime("%I:%M %p")
        else:
            date_label = str(start_dt or "Upcoming")
            time_start = ""
        if isinstance(end_dt, datetime):
            local_end = end_dt + timedelta(hours=5, minutes=30)
            time_end = local_end.strftime("%I:%M %p")
        else:
            time_end = ""
        timing = f"{time_start} - {time_end}" if time_start and time_end else time_start
        slot_rows_html += (
            "<tr>"
            f"<td style='padding:8px;border-bottom:1px solid #eef2f7;color:#0f172a'>{date_label}</td>"
            f"<td style='padding:8px;border-bottom:1px solid #eef2f7;color:#0f172a'>{timing or '-'}</td>"
            "</tr>"
        )
    if not slot_rows_html:
        slot_rows_html = (
            "<tr><td colspan='2' style='padding:10px;color:#64748b'>"
            "No immediate slots are open right now. Please contact the clinic for support."
            "</td></tr>"
        )

    html = (
        "<div style='font-family:Segoe UI,Arial,sans-serif;background:#f8fafc;padding:24px'>"
        "<div style='max-width:760px;margin:0 auto;background:#ffffff;border:1px solid #e2e8f0;border-radius:14px;overflow:hidden'>"
        "<div style='padding:20px 24px;background:linear-gradient(90deg,#0f172a,#1e293b);color:#ffffff'>"
        "<h2 style='margin:0;font-size:20px'>CareSync Clinical Summary</h2>"
        f"<p style='margin:8px 0 0;font-size:13px;opacity:0.9'>Uploaded report: {file_name}</p>"
        "</div>"
        "<div style='padding:20px 24px'>"
        f"<p style='margin:0 0 12px;color:#0f172a'>Hello {patient.get('name', 'Patient')},</p>"
        f"<p style='margin:0 0 18px;color:#334155'>Dr. {doctor_name} reviewed your latest uploaded report. Below is a professional summary and next available appointment timings.</p>"
        "<h3 style='margin:0 0 10px;color:#0f172a;font-size:16px'>Clinical Summary</h3>"
        f"<p style='margin:0 0 14px;color:#334155;line-height:1.5'>{report_summary_text}</p>"
        "<h3 style='margin:0 0 10px;color:#0f172a;font-size:16px'>Lab Report Summary</h3>"
        "<table style='width:100%;border-collapse:collapse;border:1px solid #e2e8f0;border-radius:10px;overflow:hidden'>"
        "<thead><tr style='background:#f1f5f9'>"
        "<th style='text-align:left;padding:8px;color:#334155'>Test</th>"
        "<th style='text-align:left;padding:8px;color:#334155'>Value</th>"
        "<th style='text-align:left;padding:8px;color:#334155'>Unit</th>"
        "<th style='text-align:left;padding:8px;color:#334155'>Reference</th>"
        "<th style='text-align:left;padding:8px;color:#334155'>Flag</th>"
        "</tr></thead>"
        f"<tbody>{lab_rows_html}</tbody>"
        "</table>"
        "<h3 style='margin:18px 0 10px;color:#0f172a;font-size:16px'>Next Appointment Timings</h3>"
        "<table style='width:100%;border-collapse:collapse;border:1px solid #e2e8f0;border-radius:10px;overflow:hidden'>"
        "<thead><tr style='background:#f1f5f9'>"
        "<th style='text-align:left;padding:8px;color:#334155'>Date</th>"
        "<th style='text-align:left;padding:8px;color:#334155'>Timing</th>"
        "</tr></thead>"
        f"<tbody>{slot_rows_html}</tbody>"
        "</table>"
        "<p style='margin:16px 0 0;color:#475569'>To confirm a slot, reply to this email or contact the clinic desk.</p>"
        "</div>"
        "</div>"
        "</div>"
    )

    await send_email(
        to_email=patient_email,
        subject=subject,
        html=html,
        text=message,
    )
    return True, "Summary email sent"


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class WorkflowCreate(BaseModel):
    doctor_id: str
    name: str
    description: str | None = None
    category: str = "Ungrouped"
    status: str = "DRAFT"
    nodes: list[dict[str, Any]] = Field(default_factory=list)
    edges: list[dict[str, Any]] = Field(default_factory=list)


class WorkflowUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    category: str | None = None
    status: str | None = None
    nodes: list[dict[str, Any]] | None = None
    edges: list[dict[str, Any]] | None = None


class WorkflowAIGenerateRequest(BaseModel):
    prompt: str = Field(min_length=10, max_length=5000)
    doctor_id: str | None = None


class WorkflowAIGenerateResponse(BaseModel):
    workflow_name: str
    workflow_description: str
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]
    notes: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class WorkflowTemplateSummary(BaseModel):
    id: str
    name: str
    description: str
    category: str
    use_case: str
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]


class WorkflowTemplateCreateRequest(BaseModel):
    doctor_id: str
    name: str | None = None
    description: str | None = None
    status: str = "DRAFT"
class SpeechTranscriptionResponse(BaseModel):
    transcript: str = ""
    model: str


class PatientCreate(BaseModel):
    name: str
    phone: str
    doctor_id: str
    dob: str | None = None
    mrn: str | None = None
    insurance: str | None = None
    primary_physician: str | None = None
    last_visit: str | None = None
    risk_level: str = "low"
    notes: str | None = None


class PatientUpdate(BaseModel):
    name: str | None = None
    phone: str | None = None
    dob: str | None = None
    mrn: str | None = None
    insurance: str | None = None
    primary_physician: str | None = None
    last_visit: str | None = None
    risk_level: str | None = None
    notes: str | None = None


class ConditionCreate(BaseModel):
    icd10_code: str
    description: str
    hcc_category: str | None = None
    raf_impact: float = 0
    status: str = "documented"


class ConditionUpdate(BaseModel):
    icd10_code: str | None = None
    description: str | None = None
    hcc_category: str | None = None
    raf_impact: float | None = None
    status: str | None = None


class MedicationCreate(BaseModel):
    name: str
    dosage: str | None = None
    frequency: str | None = None
    route: str | None = None
    prescriber: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    status: str = "active"
    notes: str | None = None


class MedicationUpdate(BaseModel):
    name: str | None = None
    dosage: str | None = None
    frequency: str | None = None
    route: str | None = None
    prescriber: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    status: str | None = None
    notes: str | None = None


class ExecuteRequest(BaseModel):
    patient_id: str
    trigger_node_type: str | None = None
    report_id: str | None = None
    doctor_id: str | None = None  # override workflow doctor_id


class AuthRegisterRequest(BaseModel):
    role: str = Field(pattern="^(doctor|patient)$")
    email: str
    password: str = Field(min_length=6)
    username: str
    mobile: str
    otp_code: str = Field(min_length=6, max_length=6)


class AuthLoginRequest(BaseModel):
    role: str = Field(pattern="^(doctor|patient)$")
    email: str
    password: str


class AuthOtpSendRequest(BaseModel):
    role: str = Field(pattern="^(doctor|patient)$")
    email: str
    purpose: str = Field(pattern="^(login|register|password_reset)$")


class AuthOtpVerifyRequest(BaseModel):
    role: str = Field(pattern="^(doctor|patient)$")
    email: str
    purpose: str = Field(pattern="^(login|register|password_reset)$")
    otp_code: str = Field(min_length=6, max_length=6)


class EmailNotificationRequest(BaseModel):
    to_email: str
    subject: str
    message: str


class LabEventRequest(BaseModel):
    trigger_type: str  # e.g. "lab_results_received"
    patient_id: str
    doctor_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class BloodCampaignStartRequest(BaseModel):
    doctor_id: str
    blood_type: str
    recipient_name: str
    reason: str | None = None
    patient_location: str | None = None
    batch_size: int = Field(default=3, ge=1, le=10)


class BloodRequestCreate(BaseModel):
    """What a doctor fills in on the Blood Request form."""

    doctor_id: str
    blood_type: str = Field(pattern=r"^(A|B|AB|O)[+-]$")
    component: str = Field(
        default="whole_blood", pattern="^(whole_blood|packed_rbc|platelets|plasma)$"
    )
    units_needed: int = Field(default=1, ge=1, le=20)
    urgency: str = Field(default="urgent", pattern="^(emergency|urgent|planned)$")
    required_by: datetime | None = None
    recipient_name: str = Field(min_length=1, max_length=200)
    patient_id: str | None = None
    reason: str | None = Field(default=None, max_length=1000)
    hospital_name: str = Field(min_length=1, max_length=200)
    ward: str | None = Field(default=None, max_length=200)
    hospital_location: str = Field(min_length=1, max_length=500)
    contact_name: str = Field(min_length=1, max_length=200)
    contact_phone: str = Field(min_length=6, max_length=20)


# ---------------------------------------------------------------------------
# Local auth APIs (doctor/patient email-password)
# ---------------------------------------------------------------------------


@router.post("/auth/register")
async def auth_register(body: AuthRegisterRequest):
    try:
        otp_ok = db.verify_email_otp(body.role, body.email, "register", body.otp_code)
        if not otp_ok:
            raise HTTPException(status_code=401, detail="Invalid or expired OTP")

        return db.register_user_account(
            role=body.role,
            email=body.email,
            password=body.password,
            username=body.username,
            mobile=body.mobile,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Registration failed role=%s email=%s", body.role, body.email)
        raise HTTPException(
            status_code=500, detail=f"Registration failed: {exc}"
        ) from exc


@router.post("/auth/login")
async def auth_login(body: AuthLoginRequest):
    try:
        return db.login_user_account(
            role=body.role,
            email=body.email,
            password=body.password,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Login failed role=%s email=%s", body.role, body.email)
        raise HTTPException(status_code=500, detail=f"Login failed: {exc}") from exc


@router.post("/auth/otp/send")
async def auth_send_otp(body: AuthOtpSendRequest):
    from app.services.smtp_service import send_otp_email

    otp_code = f"{secrets.randbelow(1_000_000):06d}"

    try:
        db.save_email_otp(body.role, body.email, body.purpose, otp_code)
        await send_otp_email(body.email, otp_code, body.purpose)
        return {
            "sent": True,
            "email": body.email,
            "purpose": body.purpose,
            "expires_in_minutes": 10,
        }
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception(
            "OTP send failed role=%s email=%s purpose=%s",
            body.role,
            body.email,
            body.purpose,
        )
        raise HTTPException(status_code=500, detail=f"OTP send failed: {exc}") from exc


@router.post("/auth/otp/verify")
async def auth_verify_otp(body: AuthOtpVerifyRequest):
    ok = db.verify_email_otp(body.role, body.email, body.purpose, body.otp_code)
    if not ok:
        raise HTTPException(status_code=401, detail="Invalid or expired OTP")
    return {"verified": True}


# ---------------------------------------------------------------------------
# Phase 0 API contracts (pre-implementation schemas)
# ---------------------------------------------------------------------------


class DoctorListQuery(BaseModel):
    specialty: str | None = None
    language: str | None = None
    consultation_type: str | None = None
    available_now: bool | None = None


class DoctorListItem(BaseModel):
    id: str
    name: str
    specialty: str
    language: str
    consultation_type: str
    fee: float
    rating_avg: float
    rating_count: int
    is_available: bool = True
    available_now: bool = False
    next_slot_start: str | None = None


class DoctorAvailabilitySlot(BaseModel):
    id: str
    doctor_id: str
    slot_start: str
    slot_end: str
    status: str


class DoctorAvailabilitySettingsResponse(BaseModel):
    doctor_id: str
    is_available: bool
    pending_today_appointments: int = 0
    rescheduled_appointments: int = 0


class DoctorAvailabilityToggleRequest(BaseModel):
    is_available: bool
    confirm_reschedule_today: bool = False


class ReserveSlotRequest(BaseModel):
    patient_id: str
    hold_minutes: int = Field(default=10, ge=1, le=30)


class ReserveSlotResponse(BaseModel):
    slot_id: str
    status: str
    reserved_until: str | None = None


class AvailabilitySlotCreateRequest(BaseModel):
    slot_start: str
    slot_end: str
    status: str = "available"


class AvailabilitySlotUpdateRequest(BaseModel):
    slot_start: str | None = None
    slot_end: str | None = None
    status: str | None = None


class AvailabilitySlotsCancelRequest(BaseModel):
    slot_ids: list[str] = Field(min_length=1, max_length=200)
    reason: str | None = Field(default=None, max_length=500)


class AvailabilitySlotsReopenRequest(BaseModel):
    slot_ids: list[str] = Field(min_length=1, max_length=200)


class DoctorScheduleRequest(BaseModel):
    """The doctor's editable schedule rules. Times are clinic-local HH:MM."""

    day_start: str = Field(pattern=r"^\d{2}:\d{2}$")
    day_end: str = Field(pattern=r"^\d{2}:\d{2}$")
    break_start: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    break_end: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    slot_minutes: int = Field(ge=10, le=120)
    working_days: list[int] = Field(min_length=1, max_length=7)  # ISO: 1 = Monday ... 7 = Sunday
    window_days: int = Field(ge=1, le=90)


class PatientPortalRegisterRequest(BaseModel):
    auth_user_id: str
    email: str
    name: str
    phone: str
    doctor_id: str


class PatientPortalBookRequest(BaseModel):
    auth_user_id: str
    consultation_type: str = "video"
    notes: str | None = None


class PatientPortalCancelAppointmentRequest(BaseModel):
    auth_user_id: str
    reason: str | None = None


class PatientPortalRescheduleAppointmentRequest(BaseModel):
    auth_user_id: str
    new_slot_id: str
    consultation_type: str | None = None
    notes: str | None = None


class AppointmentDoctorUpdateRequest(BaseModel):
    doctor_id: str
    status: str | None = None
    consultation_type: str | None = None
    notes: str | None = None


class CreateAppointmentRequest(BaseModel):
    slot_id: str
    patient_id: str
    consultation_type: str = "video"
    notes: str | None = None


class AppointmentResponse(BaseModel):
    id: str
    doctor_id: str
    patient_id: str
    slot_id: str
    status: str
    consultation_type: str
    created_at: str


class ConsultationRoomResponse(BaseModel):
    id: UUID
    appointment_id: UUID
    provider: str
    room_name: str
    room_url: str | None = None


class ConsultationRoomCreateRequest(BaseModel):
    actor_role: str = Field(pattern="^(doctor|patient)$")
    actor_id: str
    provider: str = "daily"


class ConsultationMessageCreateRequest(BaseModel):
    actor_role: str = Field(pattern="^(doctor|patient)$")
    actor_id: str
    message: str = Field(min_length=1, max_length=2000)


class ConsultationMessageResponse(BaseModel):
    id: UUID
    appointment_id: UUID
    room_id: UUID | None = None
    sender_type: str
    sender_id: str | None = None
    message: str
    created_at: datetime


class ReminderJobResponse(BaseModel):
    appointment_id: str
    reminder_type: str
    scheduled_for: str
    status: str


class FeedbackCreateRequest(BaseModel):
    rating: int = Field(ge=1, le=5)
    comment: str | None = None
    tags: list[str] = Field(default_factory=list)


class FeedbackResponse(BaseModel):
    id: str
    appointment_id: str
    doctor_id: str
    patient_id: str
    rating: int
    comment: str | None = None
    tags: list[str] = Field(default_factory=list)
    created_at: str


@router.post("/doctors/{doctor_id}/feedback", status_code=201)
async def submit_doctor_feedback(
    doctor_id: str, body: FeedbackCreateRequest, request: Request
):
    patient_id = request.query_params.get("patient_id")
    feedback = await _run_db_call(
        db.create_doctor_feedback,
        doctor_id,
        body.rating,
        body.comment,
        patient_id,
    )
    return feedback


@router.get("/doctors/{doctor_id}/feedback")
async def list_doctor_feedback(doctor_id: str, limit: int = 20):
    doctor = await _resolve_doctor_or_404_async(doctor_id)
    return await _run_db_call(db.list_doctor_feedback, doctor["id"], limit)


def _validate_consultation_access(
    appointment: dict, actor_role: str, actor_id: str
) -> tuple[str, str]:
    """
    Validate chat room access and return normalized (sender_type, sender_id).
    sender_id is persisted as the canonical doctor/patient entity id.
    """
    if actor_role not in {"doctor", "patient"}:
        raise HTTPException(
            status_code=400, detail="actor_role must be doctor or patient"
        )

    if actor_role == "doctor":
        doctor = _resolve_doctor_or_404(actor_id)
        if appointment.get("doctor_id") != doctor.get("id"):
            raise HTTPException(
                status_code=403,
                detail="This appointment is not assigned to this doctor",
            )
        return "doctor", doctor["id"]

    patient = db.get_patient_by_auth_user_id(actor_id)
    if not patient:
        raise HTTPException(
            status_code=404, detail="Patient profile not found for this auth user"
        )
    if appointment.get("patient_id") != patient.get("id"):
        raise HTTPException(
            status_code=403, detail="This appointment does not belong to this patient"
        )
    return "patient", patient["id"]


# ---------------------------------------------------------------------------
# Doctor directory + availability (Phase 1)
# ---------------------------------------------------------------------------


@router.get("/doctors", response_model=list[DoctorListItem])
async def list_doctors(
    specialty: str | None = None,
    language: str | None = None,
    consultation_type: str | None = None,
    available_now: bool | None = None,
):
    doctors = await _run_db_call(
        db.list_doctors,
        specialty=specialty,
        language=language,
        consultation_type=consultation_type,
        available_now=available_now,
    )
    return doctors


@router.get(
    "/doctors/{doctor_id}/availability/settings",
    response_model=DoctorAvailabilitySettingsResponse,
)
async def get_doctor_availability_settings(doctor_id: str):
    doctor = await _resolve_doctor_or_404_async(doctor_id)
    settings = await _run_db_call(db.get_doctor_availability_settings, doctor["id"])
    return settings


@router.put(
    "/doctors/{doctor_id}/availability/settings",
    response_model=DoctorAvailabilitySettingsResponse,
)
async def update_doctor_availability_settings(
    doctor_id: str, body: DoctorAvailabilityToggleRequest
):
    doctor = _resolve_doctor_or_404(doctor_id)
    try:
        result = db.set_doctor_availability(
            doctor["id"],
            is_available=body.is_available,
            confirm_reschedule_today=body.confirm_reschedule_today,
        )
        current = db.get_doctor_availability_settings(doctor["id"])
        return {
            **current,
            "rescheduled_appointments": result.get("rescheduled_appointments", 0),
        }
    except RuntimeError as exc:
        detail = str(exc)
        if detail.startswith("CONFIRM_REQUIRED:"):
            count = detail.split(":", 1)[1]
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "CONFIRM_REQUIRED",
                    "message": "Doctor confirmation required before moving today's appointments",
                    "pending_today_appointments": int(count.split()[0]) if count else 0,
                },
            ) from exc
        raise HTTPException(status_code=400, detail=detail) from exc
    except Exception as exc:
        logger.exception("Update availability settings failed doctor_id=%s", doctor_id)
        raise HTTPException(
            status_code=500, detail=f"Update availability settings failed: {exc}"
        ) from exc


@router.get(
    "/doctors/{doctor_id}/availability", response_model=list[DoctorAvailabilitySlot]
)
async def doctor_availability(doctor_id: str):
    doctor = await _resolve_doctor_or_404_async(doctor_id)
    return await _run_db_call(db.list_doctor_availability, doctor["id"])


@router.get("/doctors/{doctor_id}/slots")
async def doctor_slots(
    doctor_id: str,
    include_past: bool = False,
    status: str | None = None,
):
    doctor = await _resolve_doctor_or_404_async(doctor_id)
    return await _run_db_call(
        db.list_doctor_slots,
        doctor["id"],
        include_past=include_past,
        status=status,
    )


@router.post("/doctors/{doctor_id}/slots", status_code=201)
async def create_doctor_slot(doctor_id: str, body: AvailabilitySlotCreateRequest):
    doctor = _resolve_doctor_or_404(doctor_id)

    try:
        return db.create_doctor_slot(
            doctor_id=doctor["id"],
            slot_start=body.slot_start,
            slot_end=body.slot_end,
            status=body.status,
        )
    except Exception as exc:
        logger.exception("Create slot failed for doctor_id=%s", doctor_id)
        raise HTTPException(
            status_code=400, detail=f"Create slot failed: {exc}"
        ) from exc


@router.put("/doctors/{doctor_id}/slots/{slot_id}")
async def update_doctor_slot(
    doctor_id: str, slot_id: str, body: AvailabilitySlotUpdateRequest
):
    doctor = _resolve_doctor_or_404(doctor_id)
    resolved_doctor_id = doctor["id"]

    slot = db.get_availability_slot(slot_id)
    if not slot or slot.get("doctor_id") != resolved_doctor_id:
        raise HTTPException(status_code=404, detail="Slot not found")

    payload = {k: v for k, v in body.model_dump().items() if v is not None}
    if not payload:
        return slot

    if slot.get("status") == "booked" and any(
        k in payload for k in ("slot_start", "slot_end", "status")
    ):
        raise HTTPException(status_code=409, detail="Booked slots cannot be edited")

    try:
        return db.update_doctor_slot(resolved_doctor_id, slot_id, payload)
    except Exception as exc:
        logger.exception("Update slot failed slot_id=%s", slot_id)
        raise HTTPException(
            status_code=400, detail=f"Update slot failed: {exc}"
        ) from exc


@router.delete("/doctors/{doctor_id}/slots/{slot_id}", status_code=204)
async def delete_doctor_slot(doctor_id: str, slot_id: str):
    doctor = _resolve_doctor_or_404(doctor_id)
    resolved_doctor_id = doctor["id"]

    slot = db.get_availability_slot(slot_id)
    if not slot or slot.get("doctor_id") != resolved_doctor_id:
        raise HTTPException(status_code=404, detail="Slot not found")

    if slot.get("status") == "booked":
        raise HTTPException(status_code=409, detail="Booked slots cannot be deleted")

    try:
        db.delete_doctor_slot(resolved_doctor_id, slot_id)
    except Exception as exc:
        logger.exception("Delete slot failed slot_id=%s", slot_id)
        raise HTTPException(
            status_code=400, detail=f"Delete slot failed: {exc}"
        ) from exc


@router.get("/doctors/{doctor_id}/schedule")
async def get_doctor_schedule(doctor_id: str):
    doctor = _resolve_doctor_or_404(doctor_id)
    schedule = await _run_db_call(db.get_doctor_schedule, str(doctor["id"]))
    return {
        **schedule.to_dict(),
        "is_default": schedule == db.DEFAULT_SCHEDULE,
        "timezone": settings.clinic_timezone,
    }


@router.put("/doctors/{doctor_id}/schedule")
async def update_doctor_schedule(doctor_id: str, body: DoctorScheduleRequest):
    """Save the doctor's hours, break, slot length, working days and booking
    window, then rebuild their upcoming slots (booked appointments are kept)."""
    doctor = _resolve_doctor_or_404(doctor_id)
    if any(d < 1 or d > 7 for d in body.working_days):
        raise HTTPException(status_code=422, detail="working_days must be 1 (Monday) to 7 (Sunday)")
    try:
        return await _run_db_call(db.save_doctor_schedule, str(doctor["id"]), body.model_dump())
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/doctors/{doctor_id}/slots/reopen")
async def reopen_doctor_slots(doctor_id: str, body: AvailabilitySlotsReopenRequest):
    """Make cancelled future slots bookable again."""
    doctor = _resolve_doctor_or_404(doctor_id)
    try:
        return await _run_db_call(db.reopen_doctor_slots, doctor["id"], body.slot_ids)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/doctors/{doctor_id}/slots/cancel")
async def cancel_doctor_slots(doctor_id: str, body: AvailabilitySlotsCancelRequest):
    """Cancel one slot or several at once ("Remove" on a slot, or "Cancel day").

    Booked appointments on those slots are cancelled and the patients notified.
    """
    doctor = _resolve_doctor_or_404(doctor_id)

    try:
        return await _run_db_call(
            db.cancel_doctor_slots, doctor["id"], body.slot_ids, body.reason
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Cancel slots failed doctor_id=%s", doctor_id)
        raise HTTPException(
            status_code=400, detail=f"Cancel slots failed: {exc}"
        ) from exc


@router.post("/slots/{slot_id}/reserve", response_model=ReserveSlotResponse)
async def reserve_slot(slot_id: str, body: ReserveSlotRequest):
    patient = db.get_patient(body.patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    try:
        reserved = db.reserve_slot(
            slot_id=slot_id,
            patient_id=body.patient_id,
            hold_minutes=body.hold_minutes,
        )
    except Exception as exc:
        logger.exception("Slot reservation failed for slot_id=%s", slot_id)
        raise HTTPException(
            status_code=500, detail=f"Slot reservation failed: {exc}"
        ) from exc

    if not reserved:
        raise HTTPException(
            status_code=409,
            detail="Slot is not available anymore. Please choose another slot.",
        )

    return {
        "slot_id": reserved["id"],
        "status": reserved["status"],
        "reserved_until": reserved.get("reserved_until"),
    }


# ---------------------------------------------------------------------------
# Patient portal auth + dashboard APIs
# ---------------------------------------------------------------------------


@router.post("/patient-portal/register")
async def register_patient_portal(body: PatientPortalRegisterRequest):
    doctor = db.get_doctor(body.doctor_id)
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found")

    try:
        profile = db.register_patient_portal_user(
            auth_user_id=body.auth_user_id,
            email=body.email,
            name=body.name,
            phone=body.phone,
            doctor_id=body.doctor_id,
        )
        return profile
    except Exception as exc:
        logger.exception("Patient portal registration failed")
        raise HTTPException(
            status_code=500, detail=f"Registration failed: {exc}"
        ) from exc


@router.get("/patient-portal/me")
async def patient_portal_me(auth_user_id: str):
    profile = await _run_db_call(db.get_patient_by_auth_user_id, auth_user_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Patient profile not found")
    return profile


@router.get("/patient-portal/appointments")
async def patient_portal_appointments(auth_user_id: str):
    profile = await _run_db_call(db.get_patient_by_auth_user_id, auth_user_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Patient profile not found")
    return await _run_db_call(db.list_patient_appointments, profile["id"])


@router.get("/appointments")
async def doctor_appointments(doctor_id: str):
    doctor = await _resolve_doctor_or_404_async(doctor_id)
    return await _run_db_call(db.list_doctor_appointments, doctor["id"])


@router.put("/appointments/{appointment_id}")
async def update_appointment(appointment_id: str, body: AppointmentDoctorUpdateRequest):
    doctor = _resolve_doctor_or_404(body.doctor_id)
    resolved_doctor_id = doctor["id"]

    appointment = db.get_appointment(appointment_id)
    if not appointment:
        raise HTTPException(status_code=404, detail="Appointment not found")
    if appointment.get("doctor_id") != resolved_doctor_id:
        raise HTTPException(status_code=403, detail="Not allowed for this doctor")

    payload = {
        k: v
        for k, v in {
            "status": body.status,
            "consultation_type": body.consultation_type,
            "notes": body.notes,
        }.items()
        if v is not None
    }
    if not payload:
        return appointment

    try:
        if payload.get("status") == "cancelled":
            return db.cancel_appointment(
                appointment_id, cancel_note="Cancelled by doctor", cancelled_by="doctor"
            )
        return db.update_appointment(appointment_id, payload)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Appointment update failed appointment_id=%s", appointment_id)
        raise HTTPException(
            status_code=400, detail=f"Appointment update failed: {exc}"
        ) from exc


@router.post(
    "/appointments/{appointment_id}/consultation-room",
    response_model=ConsultationRoomResponse,
)
async def get_or_create_consultation_room(
    appointment_id: str, body: ConsultationRoomCreateRequest
):
    appointment = db.get_appointment(appointment_id)
    if not appointment:
        raise HTTPException(status_code=404, detail="Appointment not found")

    _validate_consultation_access(appointment, body.actor_role, body.actor_id)

    provider = (
        body.provider if body.provider in {"daily", "100ms", "twilio"} else "daily"
    )
    room = db.get_consultation_room_by_appointment(appointment_id)
    if not room:
        room = db.create_consultation_room(
            appointment_id=appointment_id,
            provider=provider,
            room_name=f"consult-{appointment_id[:8]}",
        )
    return room


# ---------------------------------------------------------------------------
# Video consultation: our own 1:1 WebRTC call (replaces the meet.jit.si embed,
# which forces the first person to sign in and cuts embedded calls short).
# The server only relays connection messages between the doctor's and the
# patient's browsers; audio and video flow directly between them.
# ---------------------------------------------------------------------------

# appointment_id -> {"doctor": WebSocket, "patient": WebSocket}
_video_rooms: dict[str, dict[str, WebSocket]] = {}
_video_rooms_lock = asyncio.Lock()
# Only these message types are relayed, so the channel can't be used for anything else.
_RELAYED_SIGNALS = {"offer", "answer", "ice", "hangup", "media-state"}


@router.get("/consultations/ice-servers")
async def consultation_ice_servers():
    """STUN (and optional TURN) servers the browsers use to connect."""
    servers: list[dict[str, Any]] = [
        {"urls": [u.strip() for u in settings.webrtc_stun_urls.split(",") if u.strip()]}
    ]
    if settings.webrtc_turn_url.strip():
        servers.append(
            {
                "urls": [u.strip() for u in settings.webrtc_turn_url.split(",") if u.strip()],
                "username": settings.webrtc_turn_username,
                "credential": settings.webrtc_turn_credential,
            }
        )
    return {"ice_servers": servers}


@router.websocket("/consultations/{appointment_id}/signal")
async def consultation_signal(websocket: WebSocket, appointment_id: str, actor_role: str, actor_id: str):
    appointment = await run_in_threadpool(db.get_appointment, appointment_id)
    try:
        if not appointment:
            raise HTTPException(status_code=404, detail="Appointment not found")
        role, _ = await run_in_threadpool(_validate_consultation_access, appointment, actor_role, actor_id)
    except HTTPException as exc:
        await websocket.close(code=4403, reason=str(exc.detail)[:120])
        return

    await websocket.accept()
    other_role = "patient" if role == "doctor" else "doctor"

    async with _video_rooms_lock:
        room = _video_rooms.setdefault(appointment_id, {})
        previous = room.get(role)
        room[role] = websocket
        other = room.get(other_role)
    if previous is not None:
        # Same person rejoined (refresh / second tab): the newest tab wins.
        try:
            await previous.send_json({"type": "replaced"})
            await previous.close(code=4000)
        except Exception:
            pass

    await websocket.send_json({"type": "joined", "role": role, "peer_present": other is not None})
    if other is not None:
        try:
            # The one already waiting starts the connection (sends the offer).
            await other.send_json({"type": "peer-joined", "role": role})
        except Exception:
            pass

    try:
        while True:
            message = await websocket.receive_json()
            if not isinstance(message, dict) or message.get("type") not in _RELAYED_SIGNALS:
                continue
            async with _video_rooms_lock:
                target = _video_rooms.get(appointment_id, {}).get(other_role)
            if target is not None:
                try:
                    await target.send_json({**message, "from": role})
                except Exception:
                    pass
    except (WebSocketDisconnect, RuntimeError, ValueError):
        pass
    finally:
        async with _video_rooms_lock:
            room = _video_rooms.get(appointment_id, {})
            if room.get(role) is websocket:
                room.pop(role, None)
                other = room.get(other_role)
                if not room:
                    _video_rooms.pop(appointment_id, None)
            else:
                other = None  # replaced by a newer tab; nothing changed for the peer
        if other is not None:
            try:
                await other.send_json({"type": "peer-left", "role": role})
            except Exception:
                pass


@router.get(
    "/appointments/{appointment_id}/messages",
    response_model=list[ConsultationMessageResponse],
)
async def list_consultation_messages(
    appointment_id: str,
    actor_role: str,
    actor_id: str,
):
    appointment = db.get_appointment(appointment_id)
    if not appointment:
        raise HTTPException(status_code=404, detail="Appointment not found")

    _validate_consultation_access(appointment, actor_role, actor_id)
    return db.list_consultation_messages(appointment_id)


@router.post(
    "/appointments/{appointment_id}/messages",
    response_model=ConsultationMessageResponse,
)
async def create_consultation_message(
    appointment_id: str, body: ConsultationMessageCreateRequest
):
    appointment = db.get_appointment(appointment_id)
    if not appointment:
        raise HTTPException(status_code=404, detail="Appointment not found")

    sender_type, sender_id = _validate_consultation_access(
        appointment, body.actor_role, body.actor_id
    )
    room = db.get_consultation_room_by_appointment(appointment_id)
    if not room:
        room = db.create_consultation_room(
            appointment_id=appointment_id,
            provider="daily",
            room_name=f"consult-{appointment_id[:8]}",
        )

    return db.create_consultation_message(
        {
            "appointment_id": appointment_id,
            "room_id": room.get("id"),
            "sender_type": sender_type,
            "sender_id": sender_id,
            "message": body.message.strip(),
        }
    )


@router.post("/patient-portal/slots/{slot_id}/book")
async def patient_portal_book_slot(slot_id: str, body: PatientPortalBookRequest):
    try:
        booked = db.book_slot_for_patient_portal(
            auth_user_id=body.auth_user_id,
            slot_id=slot_id,
            consultation_type=body.consultation_type,
            notes=body.notes,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Patient booking failed for slot=%s", slot_id)
        raise HTTPException(status_code=500, detail=f"Booking failed: {exc}") from exc

    if not booked:
        slot = db.get_availability_slot(slot_id)
        if not slot:
            raise HTTPException(status_code=404, detail="Slot not found")

        patient = db.get_patient_by_auth_user_id(body.auth_user_id)
        now_dt = datetime.now(timezone.utc)
        reserved_until_raw = slot.get("reserved_until")
        if isinstance(reserved_until_raw, datetime):
            reserved_until = reserved_until_raw
        elif reserved_until_raw is None:
            reserved_until = None
        else:
            try:
                reserved_until = datetime.fromisoformat(
                    str(reserved_until_raw).replace("Z", "+00:00")
                )
            except Exception:
                reserved_until = None
        is_reserved_for_requesting_patient = (
            patient is not None
            and slot.get("status") == "reserved"
            and str(slot.get("reserved_by")) == str(patient.get("id"))
            and reserved_until is not None
            and reserved_until >= now_dt
        )

        status = slot.get("status")
        if status == "booked":
            raise HTTPException(status_code=409, detail="This slot is already booked")
        if status == "reserved":
            if is_reserved_for_requesting_patient:
                raise HTTPException(
                    status_code=409,
                    detail="Your reservation is active but booking could not be finalized. Please retry now or refresh once.",
                )
            raise HTTPException(
                status_code=409,
                detail="This slot is currently reserved. Please try another slot",
            )

        raise HTTPException(
            status_code=409, detail="Slot could not be booked. Try another slot."
        )

    return booked


@router.post("/patient-portal/appointments/{appointment_id}/cancel")
async def patient_portal_cancel_appointment(
    appointment_id: str,
    body: PatientPortalCancelAppointmentRequest,
):
    try:
        return db.cancel_appointment_for_patient_portal(
            auth_user_id=body.auth_user_id,
            appointment_id=appointment_id,
            reason=body.reason,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception(
            "Patient cancel appointment failed appointment_id=%s", appointment_id
        )
        raise HTTPException(status_code=400, detail=f"Cancel failed: {exc}") from exc


@router.post("/patient-portal/appointments/{appointment_id}/reschedule")
async def patient_portal_reschedule_appointment(
    appointment_id: str,
    body: PatientPortalRescheduleAppointmentRequest,
):
    try:
        return db.reschedule_appointment_for_patient_portal(
            auth_user_id=body.auth_user_id,
            appointment_id=appointment_id,
            new_slot_id=body.new_slot_id,
            consultation_type=body.consultation_type,
            notes=body.notes,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception(
            "Patient reschedule appointment failed appointment_id=%s", appointment_id
        )
        raise HTTPException(
            status_code=400, detail=f"Reschedule failed: {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# Patient endpoints
# ---------------------------------------------------------------------------


@router.get("/patients")
async def list_patients(doctor_id: str | None = None):
    return await _run_db_call(db.list_patients, doctor_id=doctor_id)


@router.get("/patients/doctor-portal")
async def list_doctor_portal_patients(doctor_id: str):
    doctor = await _resolve_doctor_or_404_async(doctor_id)
    return await _run_db_call(db.list_doctor_portal_patients, doctor["id"])


@router.post("/patients", status_code=201)
async def create_patient(body: PatientCreate):
    payload = body.model_dump()
    return db.create_patient(payload)


@router.get("/patients/{patient_id}")
async def get_patient(patient_id: str):
    patient = await _run_db_call(db.get_patient, patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    return patient


@router.put("/patients/{patient_id}")
async def update_patient(patient_id: str, body: PatientUpdate):
    patient = db.get_patient(patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    payload = {k: v for k, v in body.model_dump().items() if v is not None}
    if not payload:
        return patient
    return db.update_patient(patient_id, payload)


@router.delete("/patients/{patient_id}", status_code=204)
async def delete_patient(patient_id: str):
    patient = db.get_patient(patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    db.delete_patient(patient_id)


# ---------------------------------------------------------------------------
# Patient conditions
# ---------------------------------------------------------------------------


@router.get("/patients/{patient_id}/conditions")
async def list_conditions(patient_id: str):
    patient = await _run_db_call(db.get_patient, patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    return await _run_db_call(db.list_conditions, patient_id)


@router.post("/patients/{patient_id}/conditions", status_code=201)
async def create_condition(patient_id: str, body: ConditionCreate):
    patient = db.get_patient(patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    payload = body.model_dump()
    payload["patient_id"] = patient_id
    return db.create_condition(payload)


@router.put("/patients/{patient_id}/conditions/{condition_id}")
async def update_condition(patient_id: str, condition_id: str, body: ConditionUpdate):
    payload = {k: v for k, v in body.model_dump().items() if v is not None}
    if not payload:
        raise HTTPException(status_code=400, detail="No fields to update")
    return db.update_condition(condition_id, payload)


@router.delete("/patients/{patient_id}/conditions/{condition_id}", status_code=204)
async def delete_condition(patient_id: str, condition_id: str):
    db.delete_condition(condition_id)


# ---------------------------------------------------------------------------
# Patient medications
# ---------------------------------------------------------------------------


@router.get("/patients/{patient_id}/medications")
async def list_medications(patient_id: str):
    patient = await _run_db_call(db.get_patient, patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    return await _run_db_call(db.list_medications, patient_id)


@router.post("/patients/{patient_id}/medications", status_code=201)
async def create_medication(patient_id: str, body: MedicationCreate):
    patient = db.get_patient(patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    payload = body.model_dump()
    payload["patient_id"] = patient_id
    return db.create_medication(payload)


@router.put("/patients/{patient_id}/medications/{medication_id}")
async def update_medication(
    patient_id: str, medication_id: str, body: MedicationUpdate
):
    payload = {k: v for k, v in body.model_dump().items() if v is not None}
    if not payload:
        raise HTTPException(status_code=400, detail="No fields to update")
    return db.update_medication(medication_id, payload)


@router.delete("/patients/{patient_id}/medications/{medication_id}", status_code=204)
async def delete_medication(patient_id: str, medication_id: str):
    db.delete_medication(medication_id)


# ---------------------------------------------------------------------------
# Workflow CRUD
# ---------------------------------------------------------------------------


@router.get("/workflows")
async def list_workflows(
    doctor_id: str | None = None,
    status: str | None = None,
):
    return await _run_db_call(db.list_workflows, doctor_id=doctor_id, status=status)


@router.get("/workflows/templates", response_model=list[WorkflowTemplateSummary])
async def list_templates():
    return list_workflow_templates()


@router.get("/workflows/templates/{template_id}", response_model=WorkflowTemplateSummary)
async def get_template(template_id: str):
    template = get_workflow_template(template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Workflow template not found")
    return template


@router.post("/workflows/templates/{template_id}/create", status_code=201)
async def create_workflow_from_template(template_id: str, body: WorkflowTemplateCreateRequest):
    template = get_workflow_template(template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Workflow template not found")

    payload = {
        "doctor_id": body.doctor_id,
        "name": body.name or template["name"],
        "description": body.description or template["description"],
        "category": template.get("category") or "Ungrouped",
        "status": body.status,
        "nodes": template.get("nodes") or [],
        "edges": template.get("edges") or [],
    }
    return db.create_workflow(payload)


@router.post("/workflows", status_code=201)
async def create_workflow(body: WorkflowCreate):
    payload = body.model_dump()
    return db.create_workflow(payload)


@router.get("/workflows/{workflow_id}")
async def get_workflow(workflow_id: str):
    wf = await _run_db_call(db.get_workflow, workflow_id)
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return wf


@router.put("/workflows/{workflow_id}")
async def update_workflow(workflow_id: str, body: WorkflowUpdate):
    wf = db.get_workflow(workflow_id)
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")
    payload = {k: v for k, v in body.model_dump().items() if v is not None}
    if not payload:
        return wf
    return db.update_workflow(workflow_id, payload)


@router.delete("/workflows/{workflow_id}", status_code=204)
async def delete_workflow(workflow_id: str):
    wf = db.get_workflow(workflow_id)
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")
    db.delete_workflow(workflow_id)


@router.post("/workflows/ai/generate", response_model=WorkflowAIGenerateResponse)
async def generate_workflow_with_ai(body: WorkflowAIGenerateRequest):
    try:
        return await generate_workflow_from_natural_language(
            prompt=body.prompt,
            doctor_id=body.doctor_id,
        )
    except WorkflowBuilderError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("AI workflow generation failed")
        raise HTTPException(
            status_code=500, detail=f"AI workflow generation failed: {exc}"
        ) from exc


@router.post(
    "/speech/deepgram/transcribe", response_model=SpeechTranscriptionResponse
)
async def transcribe_audio_with_deepgram(file: UploadFile = File(...)):
    api_key = settings.deepgram_api_key.strip()
    if not api_key:
        raise HTTPException(
            status_code=500,
            detail="Deepgram API key is not configured",
        )

    audio_bytes = await file.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="Uploaded audio file is empty")

    content_type = file.content_type or "application/octet-stream"
    model = settings.deepgram_model.strip() or "nova-3"

    def _call_deepgram() -> requests.Response:
        return requests.post(
            "https://api.deepgram.com/v1/listen",
            params={
                "model": model,
                "smart_format": "true",
                "punctuate": "true",
                "language": "en-US",
            },
            headers={
                "Authorization": f"Token {api_key}",
                "Content-Type": content_type,
            },
            data=audio_bytes,
            timeout=60,
        )

    try:
        response = await run_in_threadpool(_call_deepgram)
    except Exception as exc:
        logger.exception("Deepgram request failed")
        raise HTTPException(status_code=502, detail=f"Deepgram request failed: {exc}")

    if not response.ok:
        detail = response.text.strip() or "Deepgram transcription failed"
        raise HTTPException(
            status_code=502,
            detail=f"Deepgram transcription failed ({response.status_code}): {detail}",
        )

    try:
        payload = response.json()
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Deepgram returned invalid JSON: {exc}",
        ) from exc

    transcript = (
        payload.get("results", {})
        .get("channels", [{}])[0]
        .get("alternatives", [{}])[0]
        .get("transcript", "")
    )
    return {
        "transcript": str(transcript or "").strip(),
        "model": model,
    }


# ---------------------------------------------------------------------------
# Transcript-based fallback helpers
# ---------------------------------------------------------------------------


def _detect_confirmation_from_transcript(transcript: str) -> bool:
    """
    Scan the transcript for phrases indicating the patient agreed to an
    appointment.  Only looks at patient/user lines (not the agent).
    """
    import re

    text = transcript.lower()

    # Positive confirmation phrases spoken by the patient
    confirm_phrases = [
        r"\byes\b.*\b(works?|good|great|perfect|fine|sure|sounds? good|that works)\b",
        r"\b(sounds? good|sounds? great|that works|works for me|i can do that)\b",
        r"\b(yes|yeah|yep|yup|sure|absolutely|definitely|of course)\b",
        r"\b(i('?d| would) like to (schedule|book|confirm|make))\b",
        r"\b(please (schedule|book|go ahead))\b",
        r"\b(let'?s do it|go ahead|book it|confirm)\b",
        r"\b(i('?m| am) available)\b",
    ]

    # Negative phrases — if these dominate, don't confirm
    deny_phrases = [
        r"\b(no|nope|not interested|can'?t make it|don'?t want)\b",
        r"\b(i('?m| am) not available|cancel|decline)\b",
    ]

    confirm_count = sum(1 for p in confirm_phrases if re.search(p, text))
    deny_count = sum(1 for p in deny_phrases if re.search(p, text))

    return confirm_count > 0 and confirm_count > deny_count


def _extract_datetime_from_transcript(
    transcript: str, existing_time: str
) -> tuple[str, str]:
    """
    Try to extract a date and time from the transcript text.
    Returns (date_str, time_str) — may be relative like "Thursday" or
    "March 12" which _resolve_date() will convert later.
    """
    import re

    text = transcript.lower()
    found_date = ""
    found_time = existing_time or ""

    # Look for day names
    day_pattern = r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b"
    day_match = re.search(day_pattern, text)
    if day_match:
        found_date = day_match.group(1)

    # Look for "tomorrow" / "today"
    if re.search(r"\btomorrow\b", text):
        found_date = "tomorrow"
    elif re.search(r"\btoday\b", text) and not found_date:
        found_date = "today"

    # Look for "Month Day" like "March 12", "march 12th"
    month_day = re.search(
        r"\b(january|february|march|april|may|june|july|august|september|october|november|december)"
        r"\s+(\d{1,2})(?:st|nd|rd|th)?\b",
        text,
    )
    if month_day:
        found_date = f"{month_day.group(1)} {month_day.group(2)}"

    # Look for time patterns like "2:30", "2:30 PM", "14:30", "2 PM", "1:45 PM"
    if not found_time:
        time_match = re.search(r"\b(\d{1,2}):(\d{2})\s*(am|pm|a\.m\.|p\.m\.)?", text)
        if time_match:
            found_time = f"{time_match.group(1)}:{time_match.group(2)}"
            if time_match.group(3):
                found_time += f" {time_match.group(3).replace('.', '')}"
        else:
            # "2 PM", "3 am"
            time_match2 = re.search(r"\b(\d{1,2})\s*(am|pm|a\.m\.|p\.m\.)\b", text)
            if time_match2:
                found_time = (
                    f"{time_match2.group(1)}:00 {time_match2.group(2).replace('.', '')}"
                )

    # ---- Word-based time parsing (e.g. "one forty-five", "three thirty") ----
    if not found_time:
        word_nums = {
            "one": 1,
            "two": 2,
            "three": 3,
            "four": 4,
            "five": 5,
            "six": 6,
            "seven": 7,
            "eight": 8,
            "nine": 9,
            "ten": 10,
            "eleven": 11,
            "twelve": 12,
        }
        word_mins = {
            "oh five": 5,
            "o five": 5,
            "ten": 10,
            "fifteen": 15,
            "twenty": 20,
            "twenty-five": 25,
            "thirty": 30,
            "thirty-five": 35,
            "forty": 40,
            "forty-five": 45,
            "fifty": 50,
            "fifty-five": 55,
        }
        for hour_word, hour_val in word_nums.items():
            for min_word, min_val in word_mins.items():
                if f"{hour_word} {min_word}" in text:
                    # Assume PM for typical appointment hours (1-6)
                    display_hour = hour_val
                    if display_hour <= 6:
                        display_hour += 12
                    found_time = f"{display_hour}:{min_val:02d}"
                    break
            if found_time:
                break

    return found_date, found_time


# ---------------------------------------------------------------------------
# Date/time helpers for ElevenLabs DCR values
# ---------------------------------------------------------------------------


def _resolve_date(raw: str) -> str:
    """
    Convert a raw date string from ElevenLabs into YYYY-MM-DD format.

    Handles:
      - Already formatted: "2026-03-12" → "2026-03-12"
      - Day names: "Thursday", "thursday" → next Thursday's date
      - Relative: "tomorrow" → tomorrow's date
      - Month + day: "March 12" → "2026-03-12"
      - Empty/unknown → "" (unchanged)
    """
    import re
    from datetime import date, datetime, timedelta
    from zoneinfo import ZoneInfo

    if not raw or not raw.strip():
        return ""

    raw = raw.strip()

    # Already in YYYY-MM-DD format
    if re.match(r"^\d{4}-\d{2}-\d{2}$", raw):
        return raw

    # Relative dates ("tomorrow", "Thursday") must be resolved in clinic time.
    today = datetime.now(ZoneInfo(settings.clinic_timezone)).date()

    # "tomorrow"
    if raw.lower() == "tomorrow":
        return (today + timedelta(days=1)).isoformat()

    # "today"
    if raw.lower() == "today":
        return today.isoformat()

    # Day name like "Thursday", "thursday"
    day_names = {
        "monday": 0,
        "tuesday": 1,
        "wednesday": 2,
        "thursday": 3,
        "friday": 4,
        "saturday": 5,
        "sunday": 6,
    }
    if raw.lower() in day_names:
        target_day = day_names[raw.lower()]
        days_ahead = (target_day - today.weekday()) % 7
        if days_ahead == 0:
            days_ahead = 7  # Next week if today is that day
        return (today + timedelta(days=days_ahead)).isoformat()

    # "March 12", "march 12th", "Mar 12"
    month_names = {
        "jan": 1,
        "january": 1,
        "feb": 2,
        "february": 2,
        "mar": 3,
        "march": 3,
        "apr": 4,
        "april": 4,
        "may": 5,
        "jun": 6,
        "june": 6,
        "jul": 7,
        "july": 7,
        "aug": 8,
        "august": 8,
        "sep": 9,
        "september": 9,
        "oct": 10,
        "october": 10,
        "nov": 11,
        "november": 11,
        "dec": 12,
        "december": 12,
    }
    match = re.match(r"([a-zA-Z]+)\s+(\d{1,2})", raw)
    if match:
        month_str = match.group(1).lower()
        day_num = int(match.group(2))
        month_num = month_names.get(month_str)
        if month_num:
            year = today.year
            candidate = date(year, month_num, day_num)
            if candidate < today:
                candidate = date(year + 1, month_num, day_num)
            return candidate.isoformat()

    # Return as-is if we can't parse it (better than empty)
    return raw


def _resolve_time(raw: str) -> str:
    """
    Convert a raw time string into HH:MM format.

    Handles:
      - Already formatted: "14:00" → "14:00"
      - 12-hour: "2:15 PM", "2:15pm" → "14:15"
      - Partial: "2:15" → "14:15" (assumes PM for appointment times)
      - Words: "two fifteen" → best effort
      - Empty → "09:00" (default)
    """
    import re

    if not raw or not raw.strip():
        return "09:00"

    raw = raw.strip()

    # Already in HH:MM format (24-hour)
    if re.match(r"^\d{1,2}:\d{2}$", raw):
        parts = raw.split(":")
        hour = int(parts[0])
        minute = parts[1]
        # If hour < 8, assume PM for medical appointments
        if hour < 8:
            hour += 12
        return f"{hour:02d}:{minute}"

    # 12-hour format: "2:15 PM", "2:15pm", "10:30 AM", "11 AM", "3pm", "11.30 a.m."
    # (Without the minutes-optional form, "11 AM" fell through to the 09:00 default.)
    match = re.match(r"^(\d{1,2})(?:[:.](\d{2}))?\s*([ap])\.?\s*m\.?$", raw, re.IGNORECASE)
    if match:
        hour = int(match.group(1))
        minute = match.group(2) or "00"
        ampm = match.group(3).lower()
        if ampm == "p" and hour != 12:
            hour += 12
        elif ampm == "a" and hour == 12:
            hour = 0
        return f"{hour:02d}:{minute}"

    # Just a number like "14" or "2"
    match = re.match(r"^(\d{1,2})$", raw)
    if match:
        hour = int(match.group(1))
        if hour < 8:
            hour += 12
        return f"{hour:02d}:00"

    return "09:00"

def _extract_call_refs_from_execution_log(
    execution_log: list[dict[str, Any]] | None,
) -> tuple[str | None, str | None]:
    """Extract the latest conversation_id / call_sid references from execution log."""
    conversation_id: str | None = None
    call_sid: str | None = None

    for step in execution_log or []:
        raw_cid = step.get("conversation_id")
        raw_sid = step.get("call_sid") or step.get("callSid")

        if raw_cid and str(raw_cid).strip():
            conversation_id = str(raw_cid).strip()
        if raw_sid and str(raw_sid).strip():
            call_sid = str(raw_sid).strip()

    return conversation_id, call_sid


# Languages the agents are set up for (ElevenLabs language codes).
SUPPORTED_CALL_LANGUAGES = {"en", "kn", "hi", "or", "ta", "te", "ml", "mr", "bn", "gu", "pa", "as", "sd"}
# The agent may record the language name instead of its code.
_LANGUAGE_NAMES = {
    "english": "en", "kannada": "kn", "hindi": "hi", "odia": "or", "oriya": "or",
    "tamil": "ta", "telugu": "te", "malayalam": "ml", "marathi": "mr", "bengali": "bn",
    "bangla": "bn", "gujarati": "gu", "punjabi": "pa", "assamese": "as", "sindhi": "sd",
}


def _remember_patient_language(call_log: dict[str, Any] | None, language: str) -> None:
    """Save the language a call was held in, so the next call starts in it."""
    raw = (language or "").strip().lower()
    code = _LANGUAGE_NAMES.get(raw, raw[:5])
    patient_id = (call_log or {}).get("patient_id")
    if not patient_id or code not in SUPPORTED_CALL_LANGUAGES:
        return
    try:
        db.update_patient(str(patient_id), {"preferred_language": code})
    except Exception as exc:
        logger.warning("Could not save preferred language for patient %s: %s", patient_id, exc)


def _normalize_dcr_value(entry: Any) -> str:
    """Normalize ElevenLabs DCR values and guard against stringified null-like values."""
    value = entry.get("value", "") if isinstance(entry, dict) else entry
    if value is None:
        return ""

    text = str(value).strip()
    if text.lower() in {"none", "null", "undefined", "n/a", "na"}:
        return ""
    return text


def _extract_call_sid_from_payload(payload: dict[str, Any]) -> str | None:
    """Best-effort extraction of Twilio callSid from ElevenLabs webhook payload."""
    candidates = [
        payload.get("callSid"),
        payload.get("call_sid"),
        payload.get("data", {}).get("callSid"),
        payload.get("data", {}).get("call_sid"),
        payload.get("data", {}).get("metadata", {}).get("callSid"),
        payload.get("data", {}).get("metadata", {}).get("call_sid"),
        payload.get("data", {}).get("metadata", {}).get("twilio_call_sid"),
    ]

    for cand in candidates:
        if cand and str(cand).strip():
            return str(cand).strip()
    return None


def _derive_call_log_status(execution_log: list[dict[str, Any]]) -> str:
    has_error = any(step.get("status") == "error" for step in execution_log)
    if has_error:
        return "failed"

    call_initiated = any(
        step.get("conversation_id") or step.get("call_sid") or step.get("callSid")
        for step in execution_log
    )
    if call_initiated:
        return "running"
    return "completed"


async def _run_follow_up_job(job: dict[str, Any]) -> None:
    job_id = str(job.get("id"))
    call_log_id = str(job.get("call_log_id"))
    _append_follow_up_log(job_id, "info", "Picked up by scheduler", {"call_log_id": call_log_id})

    call_log = db.get_call_log(call_log_id)
    if not call_log:
        db.update_follow_up_job(
            job_id,
            {
                "status": "failed",
                "completed_at": _utc_now_iso(),
                "last_error": "Original call_log not found",
            },
        )
        _append_follow_up_log(job_id, "error", "Original call_log not found")
        return

    patient_id = str(call_log.get("patient_id") or "")
    doctor_id = str(call_log.get("doctor_id") or "")

    try:
        if db.has_active_appointment_for_call_log(call_log_id):
            db.update_follow_up_job(
                job_id,
                {
                    "status": "skipped",
                    "completed_at": _utc_now_iso(),
                    "last_error": None,
                },
            )
            _append_follow_up_log(
                job_id,
                "info",
                "Skipped because appointment already exists for this call_log",
            )
            return
        if patient_id and doctor_id and db.has_active_appointment_for_patient_doctor(
            patient_id,
            doctor_id,
        ):
            db.update_follow_up_job(
                job_id,
                {
                    "status": "skipped",
                    "completed_at": _utc_now_iso(),
                    "last_error": None,
                },
            )
            _append_follow_up_log(
                job_id,
                "info",
                "Skipped because patient already has active appointment with doctor",
                {"patient_id": patient_id, "doctor_id": doctor_id},
            )
            return
    except Exception as exc:
        logger.warning("Follow-up pre-check failed for job %s: %s", job_id, exc)

    if not call_log.get("workflow_id") or not patient_id:
        db.update_follow_up_job(
            job_id,
            {
                "status": "failed",
                "completed_at": _utc_now_iso(),
                "last_error": "Missing workflow_id or patient_id",
            },
        )
        _append_follow_up_log(job_id, "error", "Missing workflow_id or patient_id")
        return

    follow_up_call_log = db.create_call_log(
        {
            "workflow_id": call_log.get("workflow_id"),
            "patient_id": patient_id,
            "trigger_node": "follow_up_due",
            "status": "running",
            "report_id": call_log.get("report_id") or None,
            "doctor_id": call_log.get("doctor_id") or None,
        }
    )
    follow_up_call_log_id = follow_up_call_log["id"]
    _append_follow_up_log(
        job_id,
        "info",
        "Created follow-up call_log",
        {"follow_up_call_log_id": follow_up_call_log_id},
    )

    report_title = ""
    report_date = ""
    if call_log.get("report_id"):
        report = db.get_report(call_log.get("report_id"))
        if report:
            report_data = report.get("report_data") or {}
            report_title = (
                report_data.get("title")
                or report_data.get("report_type")
                or "Medical Report"
            )
            report_date = report_data.get("report_date") or (report.get("created_at") or "")[:10]

    workflow = db.get_workflow(call_log.get("workflow_id"))
    patient = db.get_patient(patient_id)
    if not workflow or not patient:
        db.update_call_log(
            follow_up_call_log_id,
            {
                "status": "failed",
                "execution_log": [
                    {
                        "node_id": "follow_up_validation",
                        "node_type": "internal",
                        "status": "error",
                        "message": "Workflow or patient not found for follow-up execution",
                    }
                ],
            },
        )
        db.update_follow_up_job(
            job_id,
            {
                "status": "failed",
                "last_error": "Workflow or patient not found",
            },
        )
        _append_follow_up_log(job_id, "error", "Workflow or patient not found")
        return

    execution_log = await execute_workflow(
        workflow=workflow,
        patient=patient,
        trigger_node_type="follow_up_due",
        call_log_id=follow_up_call_log_id,
        doctor_id=call_log.get("doctor_id"),
        report_id=call_log.get("report_id"),
        report_title=report_title,
        report_date=report_date,
    )

    final_status = _derive_call_log_status(execution_log)
    db.update_call_log(
        follow_up_call_log_id,
        {"status": final_status, "execution_log": execution_log},
    )

    if final_status == "running":
        asyncio.create_task(_auto_poll_call_result(follow_up_call_log_id))
        _append_follow_up_log(
            job_id,
            "info",
            "Started auto-poll for follow-up call",
            {"follow_up_call_log_id": follow_up_call_log_id},
        )

    db.update_follow_up_job(
        job_id,
        {
            "status": "completed",
            "completed_at": _utc_now_iso(),
            "last_error": None,
            "metadata": {
                **(job.get("metadata") or {}),
                "follow_up_call_log_id": follow_up_call_log_id,
                "follow_up_final_status": final_status,
            },
        },
    )
    _append_follow_up_log(
        job_id,
        "info",
        "Follow-up workflow executed",
        {
            "follow_up_call_log_id": follow_up_call_log_id,
            "follow_up_final_status": final_status,
        },
    )


async def _follow_up_scheduler_loop() -> None:
    global _follow_up_scheduler_last_tick_at

    interval = max(5, int(settings.follow_up_cron_poll_interval_seconds))
    batch_size = max(1, int(settings.follow_up_cron_batch_size))

    while True:
        _follow_up_scheduler_last_tick_at = _utc_now()
        if settings.follow_up_cron_enabled:
            try:
                jobs = db.claim_due_follow_up_jobs(limit=batch_size)
                if jobs:
                    logger.info("Follow-up scheduler claimed %d job(s)", len(jobs))
                for job in jobs:
                    try:
                        await _run_follow_up_job(job)
                    except Exception as exc:
                        logger.exception(
                            "Follow-up scheduler failed for job %s", job.get("id")
                        )
                        attempts = int(job.get("attempt_count") or 0)
                        max_attempts = int(job.get("max_attempts") or 1)
                        if attempts >= max_attempts:
                            db.update_follow_up_job(
                                job["id"],
                                {
                                    "status": "failed",
                                    "completed_at": _utc_now_iso(),
                                    "last_error": str(exc),
                                },
                            )
                        else:
                            retry_delay_minutes = max(5, int(settings.follow_up_cron_delay_minutes))
                            db.update_follow_up_job(
                                job["id"],
                                {
                                    "status": "queued",
                                    "last_error": str(exc),
                                    "scheduled_for": _utc_now() + timedelta(minutes=retry_delay_minutes),
                                },
                            )
                        _append_follow_up_log(job["id"], "error", "Follow-up execution failed", {"error": str(exc)})
            except Exception:
                logger.exception("Follow-up scheduler tick failed")

        await asyncio.sleep(interval)


async def start_follow_up_scheduler() -> None:
    global _follow_up_scheduler_task, _follow_up_scheduler_started_at
    if _follow_up_scheduler_task and not _follow_up_scheduler_task.done():
        return

    _follow_up_scheduler_started_at = _utc_now()
    _follow_up_scheduler_task = asyncio.create_task(_follow_up_scheduler_loop())
    logger.info(
        "Follow-up scheduler started enabled=%s delay_min=%s poll_interval_sec=%s",
        settings.follow_up_cron_enabled,
        settings.follow_up_cron_delay_minutes,
        settings.follow_up_cron_poll_interval_seconds,
    )


def get_follow_up_scheduler_state() -> dict[str, Any]:
    running = bool(_follow_up_scheduler_task and not _follow_up_scheduler_task.done())
    return {
        "enabled": bool(settings.follow_up_cron_enabled),
        "running": running,
        "tables_ready": bool(db.follow_up_tables_ready()),
        "delay_minutes": int(settings.follow_up_cron_delay_minutes),
        "poll_interval_seconds": int(settings.follow_up_cron_poll_interval_seconds),
        "max_attempts": int(settings.follow_up_cron_max_attempts),
        "batch_size": int(settings.follow_up_cron_batch_size),
        "started_at": _follow_up_scheduler_started_at,
        "last_tick_at": _follow_up_scheduler_last_tick_at,
    }


# ---------------------------------------------------------------------------
# Background auto-polling for ElevenLabs call results
# ---------------------------------------------------------------------------


async def _auto_poll_call_result(
    log_id: str, max_attempts: int = 300, interval: int = 4
):
    """
    Background task that polls ElevenLabs every *interval* seconds until the
    call finishes, then processes the result (updates call_log, creates
    an appointment row if the patient confirmed).

    This replaces the need to manually call POST /api/call-logs/{id}/check.

    It is the fallback when the post-call webhook can't reach this server
    (e.g. APP_BASE_URL is localhost), so it polls often: a 30 s interval used
    to add up to half a minute before a booking appeared. 300 x 4 s keeps the
    same ~20-minute limit.
    """
    from app.services.elevenlabs_service import (
        get_conversation,
        get_conversation_by_call_sid,
    )

    logger.info(
        "Auto-poll started for call_log %s (max %d attempts, %ds interval)",
        log_id,
        max_attempts,
        interval,
    )

    # Short wait before the first poll (gives ElevenLabs time to assign the
    # conversation id); short calls can end within seconds.
    await asyncio.sleep(5)

    for attempt in range(1, max_attempts + 1):
        try:
            call_log = db.get_call_log(log_id)
            if not call_log:
                logger.warning("Auto-poll: call_log %s not found, stopping.", log_id)
                return
            if call_log.get("status") == "completed":
                logger.info("Auto-poll: call_log %s already completed.", log_id)
                return

            # Find conversation_id from execution_log
            conversation_id = None
            call_sid = None
            exec_log = call_log.get("execution_log") or []
            for step in exec_log:
                if not isinstance(step, dict):
                    continue
                if step.get("conversation_id"):
                    conversation_id = step["conversation_id"]
                    break
                # Also pick up callSid — set by workflow_engine when
                # ElevenLabs doesn't return conversation_id immediately
                if not call_sid and step.get("call_sid"):
                    call_sid = step["call_sid"]

            # If we have a callSid but no conversation_id yet, try to
            # resolve it by querying ElevenLabs' conversation list
            if not conversation_id and call_sid:
                logger.info(
                    "Auto-poll attempt %d: resolving conversation_id from callSid %s",
                    attempt,
                    call_sid,
                )
                conversation_id = await get_conversation_by_call_sid(call_sid)
                if conversation_id:
                    # Persist it in the execution log so future iterations skip this step
                    exec_log.append(
                        {
                            "node_id": "elevenlabs_id_resolved",
                            "node_type": "internal",
                            "label": "conversation_id resolved",
                            "status": "ok",
                            "conversation_id": conversation_id,
                            "call_sid": call_sid,
                        }
                    )
                    db.update_call_log(log_id, {"execution_log": exec_log})

            if not conversation_id:
                logger.info(
                    "Auto-poll attempt %d: no conversation_id yet, waiting...", attempt
                )
                await asyncio.sleep(interval)
                continue

            # Poll ElevenLabs
            conversation = await get_conversation(conversation_id)
            if conversation is None:
                logger.info(
                    "Auto-poll attempt %d: ElevenLabs returned null conversation for %s",
                    attempt,
                    conversation_id,
                )
                await asyncio.sleep(interval)
                continue
            if not isinstance(conversation, dict):
                logger.warning(
                    "Auto-poll attempt %d: unexpected conversation payload type=%s",
                    attempt,
                    type(conversation).__name__,
                )
                await asyncio.sleep(interval)
                continue

            conv_status = conversation.get("status", "unknown")
            logger.info(
                "Auto-poll attempt %d: conversation status = %s", attempt, conv_status
            )

            # Dump full response keys for debugging
            logger.info(
                "Auto-poll: conversation top-level keys = %s", list(conversation.keys())
            )
            analysis = conversation.get("analysis", {})
            if not isinstance(analysis, dict):
                analysis = {}
            logger.info(
                "Auto-poll: analysis keys = %s",
                list(analysis.keys()) if isinstance(analysis, dict) else type(analysis),
            )
            logger.info("Auto-poll: full analysis = %s", str(analysis)[:2000])

            if conv_status not in ("done", "success", "completed", "interrupted"):
                logger.info(
                    "Auto-poll attempt %d: conversation is still %s. Waiting %ds...",
                    attempt,
                    conv_status,
                    interval,
                )
                await asyncio.sleep(interval)
                continue

            # ---- Conversation is done — extract results ----
            dcr = analysis.get("data_collection_results", {})
            if not isinstance(dcr, dict):
                dcr = {}
            logger.info("Auto-poll: DCR raw = %s", str(dcr)[:1000])

            def _dcr_val(key: str) -> str:
                entry = dcr.get(key, {})
                if isinstance(entry, dict):
                    val = entry.get("value", "")
                else:
                    val = entry
                # Ensure we never return the string "None"
                if val is None:
                    return ""
                result = str(val).strip()
                return "" if result.lower() == "none" else result

            call_outcome = _dcr_val("call_outcome")
            patient_confirmed_raw = _dcr_val("patient_confirmed")
            confirmed_date = _dcr_val("confirmed_date")
            confirmed_time = _dcr_val("confirmed_time")
            doctor_name = _dcr_val("doctor_name")
            availability_notes = _dcr_val("patient_availability_notes")
            _remember_patient_language(call_log, _dcr_val("preferred_language"))

            # Transcript may be a string or a list of message dicts
            raw_transcript = conversation.get("transcript", "")
            if isinstance(raw_transcript, list):
                transcript = "\n".join(
                    f"{msg.get('role', '')}: {msg.get('message', '')}"
                    for msg in raw_transcript
                    if isinstance(msg, dict)
                )
            else:
                transcript = raw_transcript or ""

            logger.info(
                "Auto-poll DCR values — outcome=%s, confirmed=%s, date='%s', time='%s'",
                call_outcome,
                patient_confirmed_raw,
                confirmed_date,
                confirmed_time,
            )
            logger.info("Auto-poll transcript (first 500 chars): %s", transcript[:500])

            # Also grab the AI-generated summary — most reliable source
            transcript_summary = analysis.get("transcript_summary", "") or ""
            call_successful = analysis.get("call_successful", "")
            logger.info("Auto-poll: transcript_summary = %s", transcript_summary)
            logger.info("Auto-poll: call_successful = %s", call_successful)

            patient_confirmed = patient_confirmed_raw.lower() in ("true", "yes", "1")

            # ---- Fallback 1: check transcript_summary from ElevenLabs ----
            if not patient_confirmed and transcript_summary:
                summary_lower = transcript_summary.lower()
                summary_confirm_phrases = [
                    "confirmed",
                    "chose",
                    "selected",
                    "booked",
                    "scheduled",
                    "agreed",
                    "appointment for",
                ]
                if any(phrase in summary_lower for phrase in summary_confirm_phrases):
                    patient_confirmed = True
                    logger.info(
                        "Auto-poll: patient confirmation detected via transcript_summary"
                    )

            # ---- Fallback 2: detect confirmation from raw transcript ----
            if not patient_confirmed and transcript:
                patient_confirmed = _detect_confirmation_from_transcript(transcript)
                if patient_confirmed:
                    logger.info(
                        "Auto-poll: patient confirmation detected via transcript fallback"
                    )

            # ---- Extract date/time: try summary first, then raw transcript ----
            if patient_confirmed and not confirmed_date:
                # Try transcript_summary first (e.g., "Monday at 1:45 PM")
                if transcript_summary:
                    confirmed_date, confirmed_time = _extract_datetime_from_transcript(
                        transcript_summary, confirmed_time
                    )
                    if confirmed_date:
                        logger.info(
                            "Auto-poll: date from summary: %s %s",
                            confirmed_date,
                            confirmed_time,
                        )
                # Fall back to raw transcript
                if not confirmed_date and transcript:
                    confirmed_date, confirmed_time = _extract_datetime_from_transcript(
                        transcript, confirmed_time
                    )
                    if confirmed_date:
                        logger.info(
                            "Auto-poll: date from transcript: %s %s",
                            confirmed_date,
                            confirmed_time,
                        )

            # Parse relative dates like "Thursday", "tomorrow", "March 12" into YYYY-MM-DD
            confirmed_date = _resolve_date(confirmed_date)
            confirmed_time = _resolve_time(confirmed_time)

            # Default call_outcome if DCR didn't provide one
            if not call_outcome:
                call_outcome = "confirmed" if patient_confirmed else "completed"

            elevenlabs_data = {
                "conversation_id": conversation_id,
                "call_outcome": call_outcome,
                "patient_confirmed": patient_confirmed,
                "confirmed_date": confirmed_date,
                "confirmed_time": confirmed_time,
                "doctor_name": doctor_name,
                "patient_availability_notes": availability_notes,
                "transcript": transcript[:5000] if isinstance(transcript, str) else "",
            }

            exec_log.append(
                {
                    "node_id": "elevenlabs_auto_poll",
                    "node_type": "poll_result",
                    "label": "ElevenLabs Call Completed (auto-polled)",
                    "status": "ok",
                    "message": f"Call outcome: {call_outcome}. Patient confirmed: {patient_confirmed}.",
                    **elevenlabs_data,
                }
            )

            db.update_call_log(
                log_id,
                {
                    "outcome": call_outcome or "call_completed",
                    "status": "completed",
                    "execution_log": exec_log,
                },
            )

            # ---- If patient confirmed → create appointment in DB ----
            if (
                patient_confirmed
                and confirmed_date
                and confirmed_date.lower() != "none"
            ):
                doctor_id = _resolve_doctor_id_for_call_log(call_log)
                if not doctor_id:
                    logger.warning(
                        "Auto-poll: No doctor_id found from call_log/workflow/patient — cannot create appointment"
                    )
                    exec_log.append(
                        {
                            "node_id": "appointment_auto_poll",
                            "node_type": "schedule_appointment",
                            "label": "Appointment Creation Skipped",
                            "status": "error",
                            "message": "No doctor_id found on call_log/workflow/patient — cannot create appointment.",
                        }
                    )
                    db.update_call_log(log_id, {"execution_log": exec_log})
                else:
                    patient_id = call_log.get("patient_id")
                    if not patient_id:
                        logger.warning(
                            "Auto-poll: No patient_id found — cannot create appointment"
                        )
                        exec_log.append(
                            {
                                "node_id": "appointment_auto_poll",
                                "node_type": "schedule_appointment",
                                "label": "Appointment Creation Skipped",
                                "status": "error",
                                "message": "No patient_id found on call_log — cannot create appointment.",
                            }
                        )
                        db.update_call_log(log_id, {"execution_log": exec_log})
                        logger.info("Auto-poll finished for call_log %s", log_id)
                        return

                    logger.info(
                        "Auto-poll: Creating appointment row — date=%s time=%s doctor=%s",
                        confirmed_date,
                        confirmed_time,
                        doctor_id,
                    )
                    try:
                        _auto_poll_report_id = call_log.get("report_id")
                        appointment = db.create_appointment_from_call_confirmation(
                            doctor_id=doctor_id,
                            patient_id=patient_id,
                            confirmed_date=confirmed_date,
                            confirmed_time=confirmed_time,
                            notes=(
                                "Scheduled via CareSync AI workflow after call confirmation. "
                                f"Outcome: {call_outcome}"
                            ),
                            report_id=_auto_poll_report_id or None,
                            call_log_id=log_id,
                            call_origin={
                                "source": "auto_poll",
                                "conversation_id": conversation_id,
                                "call_outcome": call_outcome,
                                "confirmed_via_call": True,
                            },
                        )
                        logger.info(
                            "Auto-poll: Appointment created — %s", appointment.get("id")
                        )
                        exec_log.append(
                            {
                                "node_id": "appointment_auto_poll",
                                "node_type": "schedule_appointment",
                                "label": "Appointment Created",
                                "status": "ok",
                                "message": "Appointment stored in database.",
                                "appointment_id": appointment.get("id"),
                            }
                        )
                        db.update_call_log(log_id, {"execution_log": exec_log})
                    except Exception as exc:
                        logger.exception("Auto-poll: Appointment creation failed")
                        exec_log.append(
                            {
                                "node_id": "appointment_auto_poll",
                                "node_type": "schedule_appointment",
                                "label": "Appointment Creation Failed",
                                "status": "error",
                                "message": str(exc),
                            }
                        )
                        db.update_call_log(log_id, {"execution_log": exec_log})
            elif patient_confirmed and not confirmed_date:
                logger.warning(
                    "Auto-poll: Patient confirmed but no date collected from call"
                )
                exec_log.append(
                    {
                        "node_id": "appointment_auto_poll",
                        "node_type": "schedule_appointment",
                        "label": "Appointment Creation Skipped",
                        "status": "error",
                        "message": "Patient confirmed but ElevenLabs did not capture a date. Check your agent's data collection fields.",
                    }
                )
                db.update_call_log(log_id, {"execution_log": exec_log})

            # If booking did not complete, schedule delayed follow-up workflow.
            try:
                latest_call_log = db.get_call_log(log_id) or call_log
                _enqueue_follow_up_if_needed(
                    call_log=latest_call_log,
                    patient_confirmed=patient_confirmed,
                    confirmed_date=confirmed_date,
                    call_outcome=call_outcome,
                    source="auto_poll",
                )
            except Exception as exc:
                logger.warning(
                    "Auto-poll: failed to schedule follow-up cron for call_log %s: %s",
                    log_id,
                    exc,
                )

            logger.info("Auto-poll finished for call_log %s", log_id)
            return

        except Exception as exc:
            logger.warning("Auto-poll attempt %d error: %s", attempt, exc)
            await asyncio.sleep(interval)

    logger.warning("Auto-poll: max attempts reached for call_log %s", log_id)


# ---------------------------------------------------------------------------
# Execute a single workflow manually
# ---------------------------------------------------------------------------


@router.post("/workflows/{workflow_id}/execute")
async def execute_workflow_endpoint(workflow_id: str, body: ExecuteRequest):
    wf = db.get_workflow(workflow_id)
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")

    patient = db.get_patient(body.patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    # ── Fetch report context if report_id provided ─────────────────────────
    report_data: dict[str, Any] = {}
    report_title = ""
    report_date = ""
    if body.report_id:
        rpt = db.get_report(body.report_id)
        if rpt:
            rd = rpt.get("report_data") or {}
            report_title = rd.get("title") or rd.get("report_type") or "Medical Report"
            report_date = rd.get("report_date") or (rpt.get("created_at") or "")[:10]
            report_data = rd

    # ── Resolve doctor for this execution (prefer logged-in doctor override) ──
    doctor_specialty = ""
    requested_doctor_identifier = body.doctor_id or wf.get("doctor_id")
    effective_doctor_id = None
    doc = None

    if requested_doctor_identifier:
        doc = db.resolve_doctor(str(requested_doctor_identifier))

    if not doc:
        patient_doctor_id = patient.get("doctor_id")
        if patient_doctor_id:
            doc = db.get_doctor(str(patient_doctor_id))

    if doc:
        effective_doctor_id = str(doc.get("id"))
        doctor_specialty = doc.get("specialty", "")
        if doc.get("name"):
            wf = dict(wf)
            wf["doctor_name"] = doc["name"]

    # ── Create a call_log row (status = "running") ─────────────────────────
    log_row = db.create_call_log(
        {
            "workflow_id": workflow_id,
            "patient_id": body.patient_id,
            "trigger_node": body.trigger_node_type,
            "status": "running",
            "report_id": body.report_id or None,
            "doctor_id": effective_doctor_id or None,
        }
    )
    log_id = log_row["id"]

    execution_log = await execute_workflow(
        workflow=wf,
        patient=patient,
        trigger_node_type=body.trigger_node_type,
        call_log_id=log_id,
        doctor_id=effective_doctor_id,
        report_id=body.report_id,
        report_title=report_title,
        report_date=report_date,
        doctor_specialty=doctor_specialty,
    )

    # Check if a call was initiated (conversation_id may be delayed; call_sid is immediate)
    call_initiated = any(
        (step.get("conversation_id") or step.get("call_sid") or step.get("callSid"))
        for step in execution_log
    )

    # Determine final status
    has_error = any(s.get("status") == "error" for s in execution_log)
    if has_error:
        final_status = "failed"
    elif call_initiated:
        # Call is in progress — keep status as "running" so the
        # background poller knows it still needs processing
        final_status = "running"
    else:
        final_status = "completed"

    db.update_call_log(
        log_id,
        {
            "status": final_status,
            "execution_log": execution_log,
        },
    )

    # If a call was initiated, start background polling automatically
    if call_initiated:
        asyncio.create_task(_auto_poll_call_result(log_id))
        logger.info("Background auto-poller started for call_log %s", log_id)

    return {
        "call_log_id": log_id,
        "status": final_status,
        "execution_log": execution_log,
        "context_summary": {
            "report_id": body.report_id,
            "report_title": report_title,
            "report_date": report_date,
            "doctor_name": wf.get("doctor_name", ""),
            "doctor_specialty": doctor_specialty,
            "patient_name": patient.get("name", ""),
        },
        "message": (
            "Call initiated — the system will automatically check for results "
            "and create a calendar event when the patient confirms."
            if call_initiated
            else "Workflow executed."
        ),
    }


# ---------------------------------------------------------------------------
# Lab event → find matching ENABLED workflows → execute
# ---------------------------------------------------------------------------


@router.post("/lab-event")
async def lab_event(body: LabEventRequest):
    """
    Simulates an external lab event arriving.
    Finds all ENABLED workflows whose first trigger node matches the event type,
    then executes each one for the given patient.
    """
    patient = db.get_patient(body.patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    # Get all ENABLED workflows (optionally filter by doctor)
    workflows = db.list_workflows(doctor_id=body.doctor_id, status="ENABLED")

    matched_results = []
    for wf in workflows:
        nodes: list[dict] = wf.get("nodes") or []
        # Check if any trigger node matches the incoming event type
        has_matching_trigger = any(
            (n.get("data", {}).get("nodeType", "") or n.get("type", "")).lower()
            == body.trigger_type.lower()
            for n in nodes
        )
        if not has_matching_trigger:
            continue

        log_row = db.create_call_log(
            {
                "workflow_id": wf["id"],
                "patient_id": body.patient_id,
                "trigger_node": body.trigger_type,
                "status": "running",
            }
        )
        log_id = log_row["id"]

        execution_log = await execute_workflow(
            workflow=wf,
            patient=patient,
            trigger_node_type=body.trigger_type,
            call_log_id=log_id,
            doctor_id=wf.get("doctor_id") or body.doctor_id,
            metadata=body.metadata,
            lab_results=body.metadata.get("lab_results", []),
        )

        call_initiated = any(
            (
                step.get("conversation_id")
                or step.get("call_sid")
                or step.get("callSid")
            )
            for step in execution_log
        )
        has_error = any(s.get("status") == "error" for s in execution_log)
        if has_error:
            final_status = "failed"
        elif call_initiated:
            final_status = "running"
        else:
            final_status = "completed"

        db.update_call_log(
            log_id, {"status": final_status, "execution_log": execution_log}
        )

        if call_initiated:
            asyncio.create_task(_auto_poll_call_result(log_id))

        matched_results.append(
            {
                "workflow_id": wf["id"],
                "workflow_name": wf.get("name"),
                "call_log_id": log_id,
                "status": final_status,
            }
        )

    return {
        "trigger_type": body.trigger_type,
        "patient_id": body.patient_id,
        "workflows_executed": len(matched_results),
        "results": matched_results,
    }


# ---------------------------------------------------------------------------
# ElevenLabs live tools (called by the agent DURING a call)
# ---------------------------------------------------------------------------
# Configure these as two webhook "server tools" on the agent, both sending
# header X-Tool-Secret: <ELEVENLABS_TOOL_SECRET> and {{call_log_id}} in the body.
# They answer from the live database, so the agent never offers a time another
# caller has just taken, and a held time can't be booked by a parallel call.


class AgentAvailableTimesRequest(BaseModel):
    call_log_id: str
    date: str = Field(min_length=1, max_length=40)


class AgentHoldSlotRequest(BaseModel):
    call_log_id: str
    date: str = Field(min_length=1, max_length=40)
    time: str = Field(min_length=1, max_length=20)


def _check_agent_tool_secret(request: Request) -> None:
    expected = settings.elevenlabs_tool_secret.strip()
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="ELEVENLABS_TOOL_SECRET is not configured; agent tools are disabled",
        )
    provided = request.headers.get("x-tool-secret", "")
    if not secrets.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="Invalid tool secret")


def _call_context_for_tool(call_log_id: str) -> tuple[str, str]:
    call_log = db.get_call_log(call_log_id)
    if not call_log:
        raise HTTPException(status_code=404, detail="Unknown call_log_id")
    doctor_id = _resolve_doctor_id_for_call_log(call_log)
    patient_id = call_log.get("patient_id")
    if not doctor_id or not patient_id:
        raise HTTPException(status_code=404, detail="Call has no doctor or patient")
    return str(doctor_id), str(patient_id)


def _parse_tool_date(raw: str):
    from datetime import date as date_cls

    resolved = _resolve_date(raw)
    try:
        return date_cls.fromisoformat(resolved) if resolved else None
    except ValueError:
        return None


def _spoken_times(slots: list[dict[str, Any]]) -> list[str]:
    out = []
    for slot in slots:
        start = db._parse_iso_datetime(slot.get("slot_start"))
        if start:
            local = start.astimezone(db.CLINIC_TZ)
            out.append(f"{local.hour % 12 or 12}:{local.strftime('%M %p')}")
    return out


@router.post("/elevenlabs/tools/available-times")
async def agent_tool_available_times(body: AgentAvailableTimesRequest, request: Request):
    """Agent asks: which times are free on the date the patient chose?"""
    _check_agent_tool_secret(request)
    doctor_id, _ = await run_in_threadpool(_call_context_for_tool, body.call_log_id)

    day = _parse_tool_date(body.date)
    if not day:
        return {"available": False, "message": f"I couldn't understand the date '{body.date}'. Please ask the patient for the day again."}

    slots = await _run_db_call(db.get_available_slots_on_date, doctor_id, day)
    times = _spoken_times(slots)
    spoken_date = db._speech_date(day)
    if times:
        return {
            "available": True,
            "date": day.isoformat(),
            "spoken_date": spoken_date,
            "times": times,
            "message": f"On {spoken_date} the open times are: {', '.join(times)}.",
        }

    upcoming = await _run_db_call(db.get_available_slot_options, doctor_id, 60)
    return {
        "available": False,
        "date": day.isoformat(),
        "spoken_date": spoken_date,
        "times": [],
        "message": (
            f"There are no open times on {spoken_date}. "
            f"Days with openings: {db.format_available_dates_for_speech(upcoming)}."
        ),
    }


@router.post("/elevenlabs/tools/hold-slot")
async def agent_tool_hold_slot(body: AgentHoldSlotRequest, request: Request):
    """Agent says: the patient picked this date and time, hold it for them.

    The hold lasts 30 minutes; the post-call booking turns it into an
    appointment. Call this before telling the patient the time is booked.
    """
    _check_agent_tool_secret(request)
    doctor_id, patient_id = await run_in_threadpool(_call_context_for_tool, body.call_log_id)

    day = _parse_tool_date(body.date)
    if not day:
        return {"held": False, "message": f"I couldn't understand the date '{body.date}'. Please confirm the day with the patient."}
    try:
        hh, mm = _resolve_time(body.time).split(":")
        from datetime import time as time_cls

        local_time = time_cls(int(hh), int(mm))
    except (ValueError, TypeError):
        return {"held": False, "message": f"I couldn't understand the time '{body.time}'. Please confirm the time with the patient."}

    result = await _run_db_call(db.hold_slot_for_call, doctor_id, patient_id, day, local_time)
    spoken = f"{db._speech_date(day)} at {local_time.hour % 12 or 12}:{local_time.strftime('%M')} {'AM' if local_time.hour < 12 else 'PM'}"
    if result["held"]:
        return {
            "held": True,
            "confirmed_date": day.isoformat(),
            "confirmed_time": local_time.strftime("%H:%M"),
            "message": f"{spoken} is now held for the patient. Confirm it with them.",
        }

    alternatives = _spoken_times(result.get("alternatives") or [])
    why = (
        "was just taken by another patient"
        if result.get("reason") == "taken"
        else "isn't one of the doctor's appointment times"
    )
    return {
        "held": False,
        "message": (
            f"{spoken} {why}. "
            + (f"Still open that day: {', '.join(alternatives)}." if alternatives else "Nothing else is open that day; offer another day.")
        ),
    }


# ---------------------------------------------------------------------------
# ElevenLabs post-call webhook
# ---------------------------------------------------------------------------


@router.get("/elevenlabs/debug/{conversation_id}")
async def elevenlabs_debug(conversation_id: str):
    """Debug endpoint: fetch raw ElevenLabs conversation data."""
    from app.services.elevenlabs_service import get_conversation

    conversation = await get_conversation(conversation_id)
    return conversation


@router.post("/elevenlabs/webhook")
async def elevenlabs_webhook(request: Request):
    """
    Receives the post-call payload from ElevenLabs after a conversation ends.

    Expected shape (ElevenLabs Conversational AI webhook):
    {
      "type": "conversation_ended" | ...,
      "conversation_id": "...",
      "data": {
        "analysis": {
          "data_collection_results": {
            "call_outcome":              {"value": "appointment_booked", ...},
            "patient_confirmed":         {"value": "true", ...},
            "confirmed_date":            {"value": "2026-03-10", ...},
            "confirmed_time":            {"value": "14:00", ...},
            "doctor_name":               {"value": "Dr. Smith", ...},
            "patient_availability_notes": {"value": "...", ...},
          }
        },
        "transcript": "..."
      }
    }

    If ``patient_confirmed`` is true, creates an appointment row for the
    doctor and updates the call_log.
    """
    import hashlib
    import hmac

    from fastapi.responses import JSONResponse

    # ---- Signature verification ----
    # Read raw bytes first (needed for correct HMAC computation)
    raw_body = await request.body()

    webhook_secret = settings.elevenlabs_webhook_secret
    if webhook_secret:
        sig_header = request.headers.get("ElevenLabs-Signature", "")
        # Header format: "t=<timestamp>,v0=<hmac_hex>"
        try:
            parts = dict(
                item.split("=", 1) for item in sig_header.split(",") if "=" in item
            )
            timestamp = parts.get("t", "")
            received_sig = parts.get("v0", "")
            # ElevenLabs signs: timestamp + "." + raw_body
            signed_payload = f"{timestamp}.".encode() + raw_body
            expected_sig = hmac.new(
                webhook_secret.encode(),
                signed_payload,
                hashlib.sha256,
            ).hexdigest()
            if not hmac.compare_digest(expected_sig, received_sig):
                logger.warning("ElevenLabs webhook: invalid signature")
                return JSONResponse(
                    status_code=401, content={"error": "invalid signature"}
                )
        except Exception as sig_exc:
            logger.warning("ElevenLabs webhook: signature check failed: %s", sig_exc)
            return JSONResponse(
                status_code=401, content={"error": "signature verification failed"}
            )
    else:
        logger.warning(
            "ELEVENLABS_WEBHOOK_SECRET not set — skipping signature verification"
        )

    import json as _json

    payload = _json.loads(raw_body)
    raw_payload_text = raw_body.decode("utf-8", errors="replace")
    logger.info("ElevenLabs webhook received: type=%s", payload.get("type"))
    logger.info(
        "ElevenLabs webhook payload (truncated): %s",
        raw_payload_text[:4000],
    )

    # ---- extract conversation_id / call_sid ----
    conversation_id = payload.get("conversation_id") or payload.get("data", {}).get(
        "conversation_id"
    )
    if conversation_id:
        conversation_id = str(conversation_id).strip()

    call_sid = _extract_call_sid_from_payload(payload)
    logger.info(
        "[11L][webhook][ids] conversation_id=%s call_sid=%s",
        conversation_id,
        call_sid,
    )

    if not conversation_id and not call_sid:
        logger.warning("ElevenLabs webhook missing both conversation_id and call_sid")
        return {
            "success": False,
            "error": "missing conversation_id and call_sid",
        }

    # ---- extract data collection results ----
    data_section = payload.get("data") or {}
    # ElevenLabs sends "analysis": null until analysis is ready.
    analysis = data_section.get("analysis") or {}
    dcr = analysis.get("data_collection_results") or {}

    def _dcr_val(key: str) -> str:
        return _normalize_dcr_value(dcr.get(key, {}))

    call_outcome = _dcr_val("call_outcome")
    patient_confirmed_raw = _dcr_val("patient_confirmed")
    confirmed_date = _dcr_val("confirmed_date")
    confirmed_time = _dcr_val("confirmed_time")
    doctor_name = _dcr_val("doctor_name")
    availability_notes = _dcr_val("patient_availability_notes")
    transcript = data_section.get("transcript", "")

    patient_confirmed = patient_confirmed_raw.lower() in ("true", "yes", "1")
    logger.info(
        "[11L][webhook][dcr] outcome=%s confirmed_raw=%s confirmed=%s date=%s time=%s doctor_name=%s",
        call_outcome,
        patient_confirmed_raw,
        patient_confirmed,
        confirmed_date,
        confirmed_time,
        doctor_name,
    )

    # ---- find the call_log row that matches this conversation ----
    # The workflow engine stored conversation_id in the execution_log.
    # We search call_logs for a running entry whose execution_log contains
    # this conversation_id.
    call_log = None
    if conversation_id:
        call_log = _find_call_log_by_conversation_id(conversation_id)
    if not call_log and call_sid:
        call_log = _find_call_log_by_call_sid(call_sid)

    if not call_log:
        logger.warning(
            "No call_log found for conversation_id=%s call_sid=%s",
            conversation_id,
            call_sid,
        )
        return {"success": False, "error": "no matching call_log"}

    log_id = call_log["id"]
    _remember_patient_language(call_log, _dcr_val("preferred_language"))
    logger.info(
        "[11L][webhook][matched_call_log] call_log_id=%s workflow_id=%s patient_id=%s",
        log_id,
        call_log.get("workflow_id"),
        call_log.get("patient_id"),
    )

    # ---- update call_log with outcome ----
    update_payload: dict[str, Any] = {
        "outcome": call_outcome or "call_completed",
        "status": "completed",
    }

    # Store ElevenLabs data in a separate column or merge into execution_log
    elevenlabs_data = {
        "conversation_id": conversation_id,
        "call_sid": call_sid,
        "call_outcome": call_outcome,
        "patient_confirmed": patient_confirmed,
        "confirmed_date": confirmed_date,
        "confirmed_time": confirmed_time,
        "doctor_name": doctor_name,
        "patient_availability_notes": availability_notes,
        "transcript": transcript[:5000] if transcript else "",
    }

    # Merge ElevenLabs data into the existing execution_log
    existing_log = call_log.get("execution_log") or []
    payload_snapshot = {
        "type": payload.get("type"),
        "conversation_id": conversation_id,
        "call_sid": call_sid,
        "dcr": {
            "call_outcome": call_outcome,
            "patient_confirmed": patient_confirmed_raw,
            "confirmed_date": confirmed_date,
            "confirmed_time": confirmed_time,
            "doctor_name": doctor_name,
            "patient_availability_notes": availability_notes,
        },
        "raw_payload": raw_payload_text[:20000],
    }
    existing_log.append(
        {
            "node_id": "elevenlabs_webhook_raw",
            "node_type": "webhook_debug",
            "label": "ElevenLabs Webhook Payload",
            "status": "info",
            "message": "Captured raw webhook payload for debugging.",
            "webhook_payload": payload_snapshot,
        }
    )
    existing_log.append(
        {
            "node_id": "elevenlabs_webhook",
            "node_type": "webhook",
            "label": "ElevenLabs Call Completed",
            "status": "ok",
            "message": f"Call outcome: {call_outcome}. Patient confirmed: {patient_confirmed}.",
            **elevenlabs_data,
        }
    )
    update_payload["execution_log"] = existing_log
    update_payload["transcript_ref"] = conversation_id or call_sid
    existing_timeline = call_log.get("status_timeline") or []
    existing_timeline.append(
        {
            "status": "completed",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "call_outcome": call_outcome,
            "patient_confirmed": patient_confirmed,
        }
    )
    update_payload["status_timeline"] = existing_timeline

    db.update_call_log(log_id, update_payload)

    # ---- if patient confirmed, create appointment row ----
    appointment = None
    if patient_confirmed and confirmed_date:
        logger.info(
            "[11L][webhook][appointment_path] call_log_id=%s confirmed_date=%s confirmed_time=%s",
            log_id,
            confirmed_date,
            confirmed_time,
        )
        doctor_id = _resolve_doctor_id_for_call_log(call_log)
        patient_id = call_log.get("patient_id")
        report_id = call_log.get("report_id")
        try:
            if not doctor_id or not patient_id:
                raise RuntimeError(
                    "Missing doctor_id or patient_id for appointment creation"
                )

            appointment = db.create_appointment_from_call_confirmation(
                doctor_id=doctor_id,
                patient_id=patient_id,
                confirmed_date=confirmed_date,
                confirmed_time=confirmed_time,
                notes=(
                    "Scheduled via CareSync AI workflow after call confirmation. "
                    f"Outcome: {call_outcome}"
                ),
                report_id=report_id or None,
                call_log_id=log_id,
                call_origin={
                    "source": "elevenlabs_webhook",
                    "conversation_id": conversation_id,
                    "call_sid": call_sid,
                    "call_outcome": call_outcome,
                    "confirmed_via_call": True,
                },
            )
            logger.info("Appointment created from webhook: %s", appointment.get("id"))

            # Append appointment step to execution log
            existing_log.append(
                {
                    "node_id": "appointment_auto",
                    "node_type": "schedule_appointment",
                    "label": "Appointment Created",
                    "status": "ok",
                    "message": "Appointment stored in database.",
                    "appointment_id": appointment.get("id"),
                }
            )
            db.update_call_log(log_id, {"execution_log": existing_log})
        except Exception as exc:
            logger.exception("Failed to create appointment after ElevenLabs call")
            existing_log.append(
                {
                    "node_id": "appointment_auto",
                    "node_type": "schedule_appointment",
                    "label": "Appointment Creation Failed",
                    "status": "error",
                    "message": str(exc),
                }
            )
            db.update_call_log(log_id, {"execution_log": existing_log})
    else:
        logger.info(
            "[11L][webhook][appointment_skipped] call_log_id=%s reason=%s",
            log_id,
            "patient_not_confirmed_or_missing_date",
        )

    try:
        latest_call_log = db.get_call_log(log_id) or call_log
        _enqueue_follow_up_if_needed(
            call_log=latest_call_log,
            patient_confirmed=patient_confirmed,
            confirmed_date=confirmed_date,
            call_outcome=call_outcome,
            source="webhook",
        )
    except Exception as exc:
        logger.warning(
            "[11L][webhook][follow_up_queue_failed] call_log_id=%s error=%s",
            log_id,
            exc,
        )

    return {
        "success": True,
        "call_log_id": log_id,
        "conversation_id": conversation_id,
        "call_sid": call_sid,
        "patient_confirmed": patient_confirmed,
        "appointment_id": appointment.get("id") if appointment else None,
    }


def _find_call_log_by_conversation_id(conversation_id: str) -> dict | None:
    """
    Search recent call_logs for one whose execution_log contains the given
    conversation_id.
    """
    logs = db.list_call_logs()
    for log in logs:
        exec_log = log.get("execution_log") or []
        for step in exec_log:
            if step.get("conversation_id") == conversation_id:
                return log
    return None


def _find_call_log_by_call_sid(call_sid: str) -> dict | None:
    """
    Search recent call_logs for one whose execution_log contains the given call_sid.
    """
    if not call_sid:
        return None

    logs = db.list_call_logs()
    for log in logs:
        exec_log = log.get("execution_log") or []
        for step in exec_log:
            step_call_sid = step.get("call_sid") or step.get("callSid")
            if step_call_sid and str(step_call_sid).strip() == str(call_sid).strip():
                return log
    return None


def _get_doctor_id_from_workflow(workflow_id: str | None) -> str | None:
    """Look up the doctor_id from the workflow record."""
    if not workflow_id:
        return None
    wf = db.get_workflow(workflow_id)
    return wf.get("doctor_id") if wf else None


def _get_doctor_id_from_patient(patient_id: str | None) -> str | None:
    if not patient_id:
        return None
    patient = db.get_patient(patient_id)
    if not patient:
        return None
    doctor_id = patient.get("doctor_id")
    return str(doctor_id) if doctor_id else None


def _resolve_doctor_id_for_call_log(call_log: dict[str, Any]) -> str | None:
    direct = call_log.get("doctor_id")
    if direct:
        return str(direct)

    via_workflow = _get_doctor_id_from_workflow(call_log.get("workflow_id"))
    if via_workflow:
        return str(via_workflow)

    return _get_doctor_id_from_patient(call_log.get("patient_id"))


# ---------------------------------------------------------------------------
# Twilio webhooks (fallback for non-ElevenLabs calls)
# ---------------------------------------------------------------------------


@router.post("/twilio/voice")
async def twilio_voice(request: Request, log_id: str | None = None):
    """
    TwiML webhook — Twilio calls this when the patient picks up.
    Returns a <Say> + <Gather> response.
    """
    call_log: dict = {}
    if log_id:
        call_log = db.get_call_log(log_id) or {}

    patient_message = call_log.get("outcome") or (
        "Hello, this is a message from your healthcare provider. "
        "Press 1 to confirm you received this message. "
        "Press 2 to request a callback."
    )

    gather_url = "/api/twilio/gather"
    if log_id:
        gather_url += f"?log_id={log_id}"

    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Gather numDigits="1" action="{gather_url}" method="POST">
    <Say voice="Polly.Joanna">{patient_message}</Say>
  </Gather>
  <Say voice="Polly.Joanna">We did not receive your input. Goodbye.</Say>
</Response>"""

    return Response(content=twiml, media_type="application/xml")


@router.post("/twilio/gather")
async def twilio_gather(request: Request, log_id: str | None = None):
    """
    Handles the patient's keypress from the Gather.
    Updates the call_log with the keypress value.
    """
    form = await request.form()
    digit = form.get("Digits", "")

    outcome_map = {
        "1": "confirmed",
        "2": "callback_requested",
    }
    outcome = outcome_map.get(str(digit), f"unknown_keypress_{digit}")

    if log_id:
        try:
            db.update_call_log(
                log_id, {"keypress": digit, "outcome": outcome, "status": "completed"}
            )
        except Exception:
            pass  # Don't fail the TwiML response

    if digit == "1":
        reply = "Thank you for confirming. Goodbye."
    elif digit == "2":
        reply = "A member of our team will call you back shortly. Goodbye."
    else:
        reply = "We did not recognise that input. Goodbye."

    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say voice="Polly.Joanna">{reply}</Say>
</Response>"""

    return Response(content=twiml, media_type="application/xml")


# ---------------------------------------------------------------------------
# Call logs
# ---------------------------------------------------------------------------


@router.get("/call-logs")
async def list_call_logs(
    workflow_id: str | None = None,
    doctor_id: str | None = None,
):
    return await _run_db_call(
        db.list_call_logs, workflow_id=workflow_id, doctor_id=doctor_id
    )


@router.get("/follow-up-cron/config")
async def get_follow_up_cron_config():
    return get_follow_up_scheduler_state()


@router.get("/follow-up-cron/jobs")
async def list_follow_up_cron_jobs(
    doctor_id: str | None = None,
    status: str | None = None,
    limit: int = 100,
):
    jobs = await _run_db_call(
        db.list_follow_up_jobs,
        doctor_id=doctor_id,
        status=status,
        limit=limit,
    )
    return jobs


@router.get("/follow-up-cron/jobs/{job_id}/logs")
async def list_follow_up_cron_job_logs(job_id: str, limit: int = 200):
    job = await _run_db_call(db.get_follow_up_job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Follow-up job not found")
    return await _run_db_call(db.list_follow_up_job_logs, job_id, limit)


@router.post("/follow-up-cron/jobs/{job_id}/run")
async def run_follow_up_cron_job_now(job_id: str):
    job = await _run_db_call(db.get_follow_up_job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Follow-up job not found")

    if str(job.get("status") or "").lower() == "running":
        raise HTTPException(status_code=409, detail="Job is already running")

    await _run_db_call(
        db.update_follow_up_job,
        job_id,
        {
            "status": "queued",
            "scheduled_for": _utc_now(),
            "last_error": None,
        },
    )
    _append_follow_up_log(job_id, "info", "Manual run requested from API")
    return {"success": True, "message": "Job queued for immediate execution"}


# ---------------------------------------------------------------------------
# Blood campaign upload and orchestration
# ---------------------------------------------------------------------------


@router.post("/blood-campaigns/upload")
async def upload_blood_campaign_sheet(
    file: UploadFile = File(...),
    doctor_id: str = Form(...),
):
    await _resolve_doctor_or_404_async(doctor_id)

    if not file.filename or not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="Only .xlsx files are accepted")

    contents = await file.read()
    if len(contents) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Excel file must be under 10 MB")

    try:
        result = await _run_db_call(ingest_blood_excel, doctor_id, contents)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Blood campaign upload failed doctor_id=%s", doctor_id)
        raise HTTPException(status_code=500, detail=f"Upload failed: {exc}") from exc

    return {
        "doctor_id": doctor_id,
        **result,
    }


@router.get("/blood-campaigns/donors")
async def list_blood_campaign_donors(doctor_id: str):
    await _resolve_doctor_or_404_async(doctor_id)
    return await _run_db_call(db.list_blood_donors, doctor_id)


@router.get("/blood-campaigns/ngos")
async def list_blood_campaign_ngos(doctor_id: str):
    await _resolve_doctor_or_404_async(doctor_id)
    return await _run_db_call(db.list_blood_ngos, doctor_id)


@router.post("/blood-campaigns/start", status_code=201)
async def start_blood_campaign_endpoint(body: BloodCampaignStartRequest):
    await _resolve_doctor_or_404_async(body.doctor_id)

    try:
        campaign = await start_blood_campaign(
            doctor_id=body.doctor_id,
            blood_type=body.blood_type,
            recipient_name=body.recipient_name,
            reason=body.reason,
            patient_location=body.patient_location,
            batch_size=body.batch_size,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Failed to start blood campaign")
        raise HTTPException(
            status_code=500, detail=f"Failed to start campaign: {exc}"
        ) from exc

    return {
        "campaign_id": campaign.get("id"),
        "status": campaign.get("status"),
    }


@router.post("/blood-requests", status_code=201)
async def create_blood_request(body: BloodRequestCreate):
    """Doctor raises a blood request; donor calling starts immediately.

    The request is stored as a blood campaign so it reuses the donor-calling
    engine. Calling continues until ``units_needed`` donors have accepted.
    """
    doctor = await _resolve_doctor_or_404_async(body.doctor_id)

    if body.required_by and body.required_by < datetime.now(timezone.utc) - timedelta(minutes=5):
        raise HTTPException(status_code=400, detail="'Required by' is in the past")

    if body.patient_id:
        patient = await _run_db_call(db.get_patient, body.patient_id)
        if not patient or str(patient.get("doctor_id")) != str(doctor["id"]):
            raise HTTPException(status_code=404, detail="Patient not found for this doctor")

    try:
        campaign = await start_blood_campaign(
            doctor_id=str(doctor["id"]),
            blood_type=body.blood_type,
            recipient_name=body.recipient_name,
            reason=body.reason,
            patient_location=body.hospital_location,
            batch_size=URGENCY_BATCH_SIZES.get(body.urgency, 3),
            request_details={
                "component": body.component,
                "units_needed": body.units_needed,
                "urgency": body.urgency,
                "required_by": body.required_by.isoformat() if body.required_by else None,
                "hospital_name": body.hospital_name.strip(),
                "ward": (body.ward or "").strip() or None,
                "contact_name": body.contact_name.strip(),
                "contact_phone": body.contact_phone.strip(),
                "patient_id": body.patient_id or None,
            },
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Failed to create blood request doctor_id=%s", body.doctor_id)
        raise HTTPException(
            status_code=500, detail=f"Failed to create blood request: {exc}"
        ) from exc

    return {"request_id": str(campaign.get("id")), "status": campaign.get("status")}


@router.get("/blood-requests")
async def list_blood_requests(doctor_id: str):
    doctor = await _resolve_doctor_or_404_async(doctor_id)
    return await _run_db_call(db.list_blood_requests, str(doctor["id"]))


@router.get("/blood-campaigns/{campaign_id}/map")
async def get_blood_campaign_map(campaign_id: str):
    payload = await _run_db_call(get_blood_campaign_map_points, campaign_id)
    if not payload:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return payload


@router.get("/blood-campaigns/{campaign_id}")
async def get_blood_campaign_status(campaign_id: str):
    payload = await _run_db_call(get_blood_campaign_snapshot, campaign_id)
    if not payload:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return payload


# ---------------------------------------------------------------------------
# Poll ElevenLabs for call result (local dev — no webhook needed)
# ---------------------------------------------------------------------------


@router.post("/call-logs/{log_id}/check")
async def check_call_status(log_id: str):
    """
    Polls ElevenLabs for the conversation result and processes it.

    Use this instead of the webhook during local development (no ngrok needed).
    The frontend can call this endpoint periodically or on-demand after a call
    is initiated.

    Flow:
      1. Find the call_log row → extract conversation_id from its execution_log
      2. Call ElevenLabs GET /v1/convai/conversations/{id}
      3. If the conversation is done, extract data collection results
      4. Update call_log with outcome
            5. If patient confirmed an appointment → create appointment row in DB
    """
    from app.services.elevenlabs_service import (
        get_conversation,
        get_conversation_by_call_sid,
    )

    call_log = db.get_call_log(log_id)
    if not call_log:
        raise HTTPException(status_code=404, detail="Call log not found")

    logger.info(
        "[11L][manual_check][start] call_log_id=%s status=%s",
        log_id,
        call_log.get("status"),
    )

    # Already completed? Return current state.
    if call_log.get("status") == "completed":
        return {
            "status": "completed",
            "call_log": call_log,
            "message": "Call already processed.",
        }

    # Find conversation_id from execution_log
    # Find conversation_id / call_sid from execution_log
    exec_log = call_log.get("execution_log") or []
    conversation_id, call_sid = _extract_call_refs_from_execution_log(exec_log)
    logger.info(
        "[11L][manual_check][refs] call_log_id=%s conversation_id=%s call_sid=%s",
        log_id,
        conversation_id,
        call_sid,
    )

    # conversation_id may not exist at call-init time; resolve by callSid if needed
    if not conversation_id and call_sid:
        conversation_id = await get_conversation_by_call_sid(call_sid)
        if conversation_id:
            logger.info(
                "[11L][manual_check][resolved] call_log_id=%s conversation_id=%s",
                log_id,
                conversation_id,
            )
            exec_log.append(
                {
                    "node_id": "elevenlabs_id_resolved",
                    "node_type": "internal",
                    "label": "conversation_id resolved",
                    "status": "ok",
                    "conversation_id": conversation_id,
                    "call_sid": call_sid,
                }
            )
            db.update_call_log(log_id, {"execution_log": exec_log})

    if not conversation_id:
        logger.info(
            "[11L][manual_check][waiting] call_log_id=%s no_conversation_id_yet",
            log_id,
        )
        return {
            "status": "waiting",
            "message": "No conversation_id found yet. Call is likely still initializing.",
            "call_sid": call_sid,
        }

    # Poll ElevenLabs
    try:
        conversation = await get_conversation(conversation_id)
    except Exception as exc:
        logger.warning("Failed to poll ElevenLabs: %s", exc)
        return {
            "status": "polling_error",
            "message": str(exc),
        }

    conv_status = conversation.get("status", "unknown")
    logger.info(
        "[11L][manual_check][conversation_status] call_log_id=%s conversation_id=%s status=%s",
        log_id,
        conversation_id,
        conv_status,
    )

    # If conversation is still in progress, return early
    if conv_status in ("in_progress", "processing", "initiated", "queued"):
        return {
            "status": "in_progress",
            "message": "Call is still in progress.",
            "conversation_status": conv_status,
            "call_sid": call_sid,
        }

    # Conversation is done — extract data collection results
    # ElevenLabs returns "analysis": null until analysis is ready.
    analysis = conversation.get("analysis") or {}
    dcr = analysis.get("data_collection_results") or {}

    def _dcr_val(key: str) -> str:
        return _normalize_dcr_value(dcr.get(key, {}))

    call_outcome = _dcr_val("call_outcome")
    patient_confirmed_raw = _dcr_val("patient_confirmed")
    confirmed_date = _dcr_val("confirmed_date")
    confirmed_time = _dcr_val("confirmed_time")
    doctor_name = _dcr_val("doctor_name")
    availability_notes = _dcr_val("patient_availability_notes")
    _remember_patient_language(call_log, _dcr_val("preferred_language"))
    transcript = conversation.get("transcript", "")

    patient_confirmed = patient_confirmed_raw.lower() in ("true", "yes", "1")
    logger.info(
        "[11L][manual_check][dcr] call_log_id=%s outcome=%s confirmed=%s date=%s time=%s",
        log_id,
        call_outcome,
        patient_confirmed,
        confirmed_date,
        confirmed_time,
    )

    # Update call_log
    elevenlabs_data = {
        "conversation_id": conversation_id,
        "call_sid": call_sid,
        "call_outcome": call_outcome,
        "patient_confirmed": patient_confirmed,
        "confirmed_date": confirmed_date,
        "confirmed_time": confirmed_time,
        "doctor_name": doctor_name,
        "patient_availability_notes": availability_notes,
        "transcript": transcript[:5000] if isinstance(transcript, str) else "",
    }

    exec_log.append(
        {
            "node_id": "elevenlabs_poll",
            "node_type": "poll_result",
            "label": "ElevenLabs Call Completed (polled)",
            "status": "ok",
            "message": f"Call outcome: {call_outcome}. Patient confirmed: {patient_confirmed}.",
            **elevenlabs_data,
        }
    )

    update_payload: dict[str, Any] = {
        "outcome": call_outcome or "call_completed",
        "status": "completed",
        "execution_log": exec_log,
    }
    db.update_call_log(log_id, update_payload)

    # If patient confirmed → create appointment row
    appointment = None
    if patient_confirmed and confirmed_date:
        logger.info(
            "[11L][manual_check][appointment_path] call_log_id=%s",
            log_id,
        )
        doctor_id = _resolve_doctor_id_for_call_log(call_log)
        patient_id = call_log.get("patient_id")
        report_id = call_log.get("report_id")
        try:
            if not doctor_id or not patient_id:
                raise RuntimeError(
                    "Missing doctor_id or patient_id for appointment creation"
                )

            appointment = db.create_appointment_from_call_confirmation(
                doctor_id=doctor_id,
                patient_id=patient_id,
                confirmed_date=confirmed_date,
                confirmed_time=confirmed_time,
                notes=(
                    "Scheduled via CareSync AI workflow after call confirmation. "
                    f"Outcome: {call_outcome}"
                ),
                report_id=report_id or None,
                call_log_id=log_id,
                call_origin={
                    "source": "polling",
                    "conversation_id": conversation_id,
                    "call_sid": call_sid,
                    "call_outcome": call_outcome,
                    "confirmed_via_call": True,
                },
            )
            logger.info("Appointment created via polling: %s", appointment.get("id"))

            exec_log.append(
                {
                    "node_id": "appointment_poll",
                    "node_type": "schedule_appointment",
                    "label": "Appointment Created",
                    "status": "ok",
                    "message": "Appointment stored in database.",
                    "appointment_id": appointment.get("id"),
                }
            )
            db.update_call_log(log_id, {"execution_log": exec_log})
        except Exception as exc:
            logger.exception("Appointment creation failed during polling")
            exec_log.append(
                {
                    "node_id": "appointment_poll",
                    "node_type": "schedule_appointment",
                    "label": "Appointment Creation Failed",
                    "status": "error",
                    "message": str(exc),
                }
            )
            db.update_call_log(log_id, {"execution_log": exec_log})

    # Format transcript for the response
    transcript_str = ""
    if isinstance(transcript, list):
        lines = []
        for entry in transcript:
            role = entry.get("role", "unknown")
            text = entry.get("message", entry.get("text", ""))
            lines.append(f"{role}: {text}")
        transcript_str = "\n".join(lines)
    elif isinstance(transcript, str):
        transcript_str = transcript

    try:
        latest_call_log = db.get_call_log(log_id) or call_log
        _enqueue_follow_up_if_needed(
            call_log=latest_call_log,
            patient_confirmed=patient_confirmed,
            confirmed_date=confirmed_date,
            call_outcome=call_outcome,
            source="manual_check",
        )
    except Exception as exc:
        logger.warning(
            "[11L][manual_check][follow_up_queue_failed] call_log_id=%s error=%s",
            log_id,
            exc,
        )

    return {
        "status": "completed",
        "call_outcome": call_outcome,
        "patient_confirmed": patient_confirmed,
        "confirmed_date": confirmed_date,
        "confirmed_time": confirmed_time,
        "appointment_id": appointment.get("id") if appointment else None,
        "call_log_id": log_id,
        "conversation_id": conversation_id,
        "call_sid": call_sid,
        "transcript": transcript_str[:5000],
        "context_summary": {
            "report_id": call_log.get("report_id"),
            "report_title": "",
            "doctor_id": call_log.get("doctor_id"),
        },
    }


# ---------------------------------------------------------------------------
# PDF upload & extraction
# ---------------------------------------------------------------------------


@router.post("/pdf/upload")
async def upload_pdf(
    file: UploadFile = File(...),
    patient_id: str = Form(None),
    uploaded_by: str = Form(None),
):
    """
    Upload a medical PDF, extract structured data (patient info, lab results,
    tables), and optionally link it to a patient.
    """
    from app.services.pdf_service import parse_pdf_document

    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")

    contents = await file.read()
    if len(contents) > 20 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="PDF must be under 20 MB")

    try:
        parsed = parse_pdf_document(contents)
    except Exception as exc:
        logger.exception("PDF parsing failed")
        raise HTTPException(status_code=422, detail=f"Failed to parse PDF: {exc}")

    doc_payload = {
        "filename": file.filename,
        "page_count": parsed.get("page_count"),
        "raw_text": parsed.get("raw_text", "")[:50000],
        "patient_info": parsed.get("patient_info", {}),
        "lab_results": parsed.get("lab_results", []),
        "tables_data": parsed.get("tables", []),
    }
    if patient_id:
        doc_payload["patient_id"] = patient_id
    if uploaded_by:
        doc_payload["uploaded_by"] = uploaded_by

    try:
        record = db.create_pdf_document(doc_payload)
    except Exception as exc:
        logger.exception("Failed to save PDF document")
        raise HTTPException(status_code=500, detail=f"DB error: {exc}")

    return {
        "id": record.get("id"),
        "filename": file.filename,
        "page_count": parsed.get("page_count"),
        "patient_info": parsed.get("patient_info", {}),
        "lab_results": parsed.get("lab_results", []),
        "extracted_at": parsed.get("extracted_at"),
    }


@router.post("/pdf/intake")
async def pdf_intake(
    file: UploadFile = File(...),
    doctor_id: str = Form(...),
):
    """
    Upload a medical PDF to create a new patient profile.
    Extracts patient demographics, medications, and lab results from the PDF
    and creates the patient record + medication records automatically.
    """
    from app.services.pdf_service import parse_pdf_document

    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")

    contents = await file.read()
    if len(contents) > 20 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="PDF must be under 20 MB")

    try:
        parsed = parse_pdf_document(contents)
    except Exception as exc:
        logger.exception("PDF parsing failed")
        raise HTTPException(status_code=422, detail=f"Failed to parse PDF: {exc}")

    patient_info = parsed.get("patient_info", {})
    medications = parsed.get("medications", [])
    lab_results = parsed.get("lab_results", [])

    patient_name = patient_info.get("name", "").strip()
    if not patient_name:
        patient_name = f"Patient from {file.filename}"

    dob_raw = patient_info.get("dob", "")
    dob_iso = None
    if dob_raw:
        for fmt in (
            "%m/%d/%Y",
            "%m-%d-%Y",
            "%d/%m/%Y",
            "%d-%m-%Y",
            "%Y-%m-%d",
            "%m/%d/%y",
            "%m-%d-%y",
            "%d/%m/%y",
            "%d-%m-%y",
        ):
            try:
                from datetime import datetime as _dt

                dob_iso = _dt.strptime(dob_raw, fmt).date().isoformat()
                break
            except ValueError:
                continue

    patient_payload: dict[str, Any] = {
        "name": patient_name,
        "phone": patient_info.get("phone", ""),
        "doctor_id": doctor_id,
    }
    if dob_iso:
        patient_payload["dob"] = dob_iso
    if patient_info.get("mrn"):
        patient_payload["mrn"] = patient_info["mrn"]
    if patient_info.get("insurance"):
        patient_payload["insurance"] = patient_info["insurance"]

    try:
        patient_row = db.create_patient(patient_payload)
    except Exception as exc:
        logger.exception("Failed to create patient from PDF")
        raise HTTPException(status_code=500, detail=f"Failed to create patient: {exc}")

    patient_id = patient_row["id"]

    created_medications: list[dict] = []
    for med in medications:
        try:
            med_payload: dict[str, Any] = {
                "patient_id": patient_id,
                "name": med.get("name", ""),
                "status": med.get("status", "active"),
            }
            if med.get("dosage"):
                med_payload["dosage"] = med["dosage"]
            row = db.create_medication(med_payload)
            created_medications.append(row)
        except Exception as exc:
            logger.warning("Failed to create medication %s: %s", med.get("name"), exc)

    try:
        db.create_pdf_document(
            {
                "patient_id": patient_id,
                "filename": file.filename,
                "page_count": parsed.get("page_count"),
                "raw_text": parsed.get("raw_text", "")[:50000],
                "patient_info": patient_info,
                "lab_results": lab_results,
                "tables_data": parsed.get("tables", []),
                "uploaded_by": doctor_id,
            }
        )
    except Exception:
        pass

    return {
        "patient": patient_row,
        "extracted": {
            "patient_info": patient_info,
            "medications": medications,
            "lab_results": lab_results,
            "page_count": parsed.get("page_count"),
        },
        "created_medications": len(created_medications),
    }


@router.post("/patients/{patient_id}/import-pdf")
async def import_pdf_to_patient(patient_id: str, file: UploadFile = File(...)):
    """
    Upload a medical PDF for an existing patient.
    Parses the PDF and updates the patient record with any extracted fields
    that are currently empty (does not overwrite existing data).
    Also creates medication records for any medications found in the PDF.
    """
    from app.services.pdf_service import parse_pdf_document

    patient = db.get_patient(patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")

    contents = await file.read()
    if len(contents) > 20 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="PDF must be under 20 MB")

    try:
        parsed = parse_pdf_document(contents)
    except Exception as exc:
        logger.exception("PDF parsing failed")
        raise HTTPException(status_code=422, detail=f"Failed to parse PDF: {exc}")

    patient_info = parsed.get("patient_info", {})
    medications = parsed.get("medications", [])
    lab_results = parsed.get("lab_results", [])

    # --- Update patient fields that are currently empty ---
    dob_raw = patient_info.get("dob", "")
    dob_iso = None
    if dob_raw:
        for fmt in (
            "%m/%d/%Y",
            "%m-%d-%Y",
            "%d/%m/%Y",
            "%d-%m-%Y",
            "%Y-%m-%d",
            "%m/%d/%y",
            "%m-%d-%y",
            "%d/%m/%y",
            "%d-%m-%y",
        ):
            try:
                from datetime import datetime as _dt

                dob_iso = _dt.strptime(dob_raw, fmt).date().isoformat()
                break
            except ValueError:
                continue

    FIELD_MAP = {
        "name": patient_info.get("name", "").strip(),
        "phone": patient_info.get("phone", "").strip(),
        "dob": dob_iso,
        "mrn": patient_info.get("mrn", "").strip(),
        "insurance": patient_info.get("insurance", "").strip(),
    }

    update_payload: dict[str, Any] = {}
    updated_fields: list[str] = []
    for field, extracted_value in FIELD_MAP.items():
        if extracted_value and not patient.get(field):
            update_payload[field] = extracted_value
            updated_fields.append(field)

    updated_patient = patient
    if update_payload:
        try:
            updated_patient = db.update_patient(patient_id, update_payload)
        except Exception as exc:
            logger.warning("Failed to update patient from PDF: %s", exc)

    # --- Add medications (skip duplicates) ---
    existing_meds = db.list_medications(patient_id)
    existing_med_names = {(m.get("name") or "").lower() for m in existing_meds}

    added_medications: list[dict] = []
    for med in medications:
        med_name = med.get("name", "").strip()
        if not med_name or med_name.lower() in existing_med_names:
            continue
        try:
            med_payload: dict[str, Any] = {
                "patient_id": patient_id,
                "name": med_name,
                "status": med.get("status", "active"),
            }
            if med.get("dosage"):
                med_payload["dosage"] = med["dosage"]
            row = db.create_medication(med_payload)
            added_medications.append(row)
            existing_med_names.add(med_name.lower())
        except Exception as exc:
            logger.warning("Failed to create medication %s: %s", med_name, exc)

    # --- Store PDF document record ---
    try:
        db.create_pdf_document(
            {
                "patient_id": patient_id,
                "filename": file.filename,
                "page_count": parsed.get("page_count"),
                "raw_text": parsed.get("raw_text", "")[:50000],
                "patient_info": patient_info,
                "lab_results": lab_results,
                "tables_data": parsed.get("tables", []),
            }
        )
    except Exception:
        pass

    return {
        "patient": updated_patient,
        "updated_fields": updated_fields,
        "extracted": {
            "patient_info": patient_info,
            "medications": medications,
            "lab_results": lab_results,
            "page_count": parsed.get("page_count"),
        },
        "added_medications": len(added_medications),
        "skipped_medications": len(medications) - len(added_medications),
    }


@router.get("/pdf/documents")
async def list_pdf_documents(patient_id: str | None = None):
    return await _run_db_call(db.list_pdf_documents, patient_id=patient_id)


@router.get("/pdf/documents/{doc_id}")
async def get_pdf_document(doc_id: str):
    doc = await _run_db_call(db.get_pdf_document, doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="PDF document not found")
    return doc


@router.delete("/pdf/documents/{doc_id}", status_code=204)
async def delete_pdf_document(doc_id: str):
    db.delete_pdf_document(doc_id)


@router.post("/pdf/extract-and-execute")
async def extract_pdf_and_execute(
    file: UploadFile = File(...),
    patient_id: str = Form(...),
    workflow_id: str = Form(...),
):
    """
    Upload a report file (PDF/JPG/JPEG/PNG), extract data when possible,
    then execute a workflow with the extracted lab results injected into the
    execution context.
    """
    from app.services.pdf_service import (
        enrich_report_text_with_gemini,
        parse_image_document_with_gemini,
        parse_pdf_document,
        parse_pdf_document_with_gemini,
    )

    if not file.filename:
        raise HTTPException(status_code=400, detail="Missing file name")

    filename_lower = file.filename.lower()
    matched_extension = next(
        (ext for ext in ALLOWED_TRIGGER_UPLOAD_EXTENSIONS if filename_lower.endswith(ext)),
        None,
    )
    if not matched_extension:
        raise HTTPException(
            status_code=400,
            detail="Only PDF, JPG, JPEG, and PNG files are accepted",
        )

    contents = await file.read()
    if len(contents) > 20 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File must be under 20 MB")

    if matched_extension == ".pdf":
        try:
            parsed = parse_pdf_document(contents)
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"Failed to parse PDF: {exc}")

        # If classical PDF extraction is sparse, first try direct Gemini PDF parsing
        # (better for scanned/image-based PDFs), then text-only enrichment.
        if not parsed.get("lab_results") or len(str(parsed.get("raw_text") or "")) < 120:
            gemini_pdf = await parse_pdf_document_with_gemini(contents)
            if gemini_pdf:
                if not parsed.get("patient_info"):
                    parsed["patient_info"] = gemini_pdf.get("patient_info", {})
                if not parsed.get("lab_results"):
                    parsed["lab_results"] = gemini_pdf.get("lab_results", [])
                if not parsed.get("medications"):
                    parsed["medications"] = gemini_pdf.get("medications", [])
                if not parsed.get("tables"):
                    parsed["tables"] = gemini_pdf.get("tables", [])
                if not parsed.get("raw_text"):
                    parsed["raw_text"] = gemini_pdf.get("raw_text", "")

            gemini_enriched = await enrich_report_text_with_gemini(parsed.get("raw_text", ""))
            if gemini_enriched:
                if not parsed.get("patient_info"):
                    parsed["patient_info"] = gemini_enriched.get("patient_info", {})
                if not parsed.get("lab_results"):
                    parsed["lab_results"] = gemini_enriched.get("lab_results", [])
                if not parsed.get("medications"):
                    parsed["medications"] = gemini_enriched.get("medications", [])
                if not parsed.get("tables"):
                    parsed["tables"] = gemini_enriched.get("tables", [])
                if not parsed.get("raw_text"):
                    parsed["raw_text"] = gemini_enriched.get("raw_text", "")
    else:
        mime_type = "image/jpeg" if matched_extension in {".jpg", ".jpeg"} else "image/png"
        parsed = await parse_image_document_with_gemini(contents, mime_type)

    wf = db.get_workflow(workflow_id)
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")

    patient = db.get_patient(patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    # Resolve canonical doctor id for this execution so call logs and
    # appointment creation remain scoped to the correct doctor.
    requested_doctor_identifier = wf.get("doctor_id")
    effective_doctor_id = None
    doc = None
    if requested_doctor_identifier:
        doc = db.resolve_doctor(str(requested_doctor_identifier))
    if not doc and patient.get("doctor_id"):
        doc = db.get_doctor(str(patient.get("doctor_id")))
    if doc:
        effective_doctor_id = str(doc.get("id"))

    doc_record = db.create_pdf_document(
        {
            "patient_id": patient_id,
            "filename": file.filename,
            "page_count": parsed.get("page_count"),
            "raw_text": parsed.get("raw_text", "")[:50000],
            "patient_info": parsed.get("patient_info", {}),
            "lab_results": parsed.get("lab_results", []),
            "tables_data": parsed.get("tables", []),
        }
    )

    log_row = db.create_call_log(
        {
            "workflow_id": workflow_id,
            "patient_id": patient_id,
            "trigger_node": "pdf_upload",
            "status": "running",
            "doctor_id": effective_doctor_id,
        }
    )
    log_id = log_row["id"]

    execution_log = await execute_workflow(
        workflow=wf,
        patient=patient,
        call_log_id=log_id,
        doctor_id=effective_doctor_id,
        lab_results=parsed.get("lab_results", []),
        metadata={
            "pdf_document_id": doc_record.get("id"),
            "patient_info": parsed.get("patient_info", {}),
            "lab_results": parsed.get("lab_results", []),
        },
    )

    doctor_row = db.get_doctor(effective_doctor_id) if effective_doctor_id else None
    slot_options_for_email: list[dict[str, Any]] = []
    if effective_doctor_id:
        try:
            slot_options_for_email = db.get_available_slot_options(
                effective_doctor_id,
                count=3,
            )
        except Exception as exc:
            logger.warning(
                "Could not fetch slot options for email doctor %s: %s",
                effective_doctor_id,
                exc,
            )

    email_sent, email_message = False, "Summary email not sent"
    try:
        email_sent, email_message = await _send_patient_report_summary_email(
            patient=patient,
            doctor=doctor_row,
            lab_results=parsed.get("lab_results", []),
            report_summary_text=_derive_report_summary_text(
                str(parsed.get("raw_text") or ""),
                parsed.get("patient_info", {}),
                parsed.get("lab_results", []),
            ),
            slot_options=slot_options_for_email,
            file_name=file.filename,
        )
        execution_log.append(
            {
                "node_type": "send_email",
                "label": "Send report summary to patient",
                "status": "ok" if email_sent else "skipped",
                "message": email_message,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )
    except Exception as exc:
        logger.exception("Failed to send patient report summary email")
        execution_log.append(
            {
                "node_type": "send_email",
                "label": "Send report summary to patient",
                "status": "error",
                "message": f"Email delivery error: {exc}",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )

    call_initiated = any(
        (step.get("conversation_id") or step.get("call_sid") or step.get("callSid"))
        for step in execution_log
    )
    has_error = any(s.get("status") == "error" for s in execution_log)
    if has_error:
        final_status = "failed"
    elif call_initiated:
        final_status = "running"
    else:
        final_status = "completed"

    db.update_call_log(
        log_id,
        {
            "status": final_status,
            "execution_log": execution_log,
        },
    )

    if call_initiated:
        asyncio.create_task(_auto_poll_call_result(log_id))
        logger.info("Background auto-poller started for pdf call_log %s", log_id)

    return {
        "call_log_id": log_id,
        "pdf_document_id": doc_record.get("id"),
        "status": final_status,
        "uploaded_file_type": matched_extension,
        "extraction_source": parsed.get("extraction_source", "pdf_regex"),
        "patient_summary_email_sent": email_sent,
        "patient_summary_email_message": email_message,
        "lab_results_found": len(parsed.get("lab_results", [])),
        "patient_info_extracted": parsed.get("patient_info", {}),
        "execution_log": execution_log,
    }


# ---------------------------------------------------------------------------
# Notifications CRUD
# ---------------------------------------------------------------------------


@router.get("/notifications")
async def list_notifications(patient_id: str | None = None):
    return await _run_db_call(db.list_notifications, patient_id=patient_id)


@router.post("/notifications/email")
async def send_email_notification(body: EmailNotificationRequest):
    from app.services.smtp_service import send_notification_email

    try:
        result = await send_notification_email(
            to_email=body.to_email,
            subject=body.subject,
            message=body.message,
        )
        return {"sent": True, "provider": "gmail_smtp", "id": result.get("id")}
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Failed to send email notification")
        raise HTTPException(
            status_code=500, detail=f"Failed to send email notification: {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# Lab orders CRUD
# ---------------------------------------------------------------------------


@router.get("/lab-orders")
async def list_lab_orders(patient_id: str | None = None):
    return await _run_db_call(db.list_lab_orders, patient_id=patient_id)


# ---------------------------------------------------------------------------
# Referrals CRUD
# ---------------------------------------------------------------------------


@router.get("/referrals")
async def list_referrals(patient_id: str | None = None):
    return await _run_db_call(db.list_referrals, patient_id=patient_id)


# ---------------------------------------------------------------------------
# Staff assignments CRUD
# ---------------------------------------------------------------------------


@router.get("/staff-assignments")
async def list_staff_assignments(
    patient_id: str | None = None,
    staff_id: str | None = None,
):
    return await _run_db_call(
        db.list_staff_assignments, patient_id=patient_id, staff_id=staff_id
    )


# ---------------------------------------------------------------------------
# Reports CRUD
# ---------------------------------------------------------------------------


@router.get("/reports")
async def list_reports(
    patient_id: str | None = None,
    workflow_id: str | None = None,
):
    return await _run_db_call(
        db.list_reports, patient_id=patient_id, workflow_id=workflow_id
    )


@router.get("/reports/{report_id}")
async def get_report(report_id: str):
    report = await _run_db_call(db.get_report, report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    return report


@router.get("/patients/{patient_id}/reports")
async def list_patient_reports(patient_id: str):
    """List all reports for a patient."""
    patient = await _run_db_call(db.get_patient, patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    return await _run_db_call(db.list_reports, patient_id=patient_id)


# ---------------------------------------------------------------------------
# Report-aware upcoming appointment endpoints
# ---------------------------------------------------------------------------


@router.get("/doctors/{doctor_id}/upcoming-appointments")
async def doctor_upcoming_appointments_with_report(doctor_id: str):
    """List upcoming appointments for a doctor with linked report context."""
    doctor = await _run_db_call(db.resolve_doctor, doctor_id)
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found")
    rows = await _run_db_call(
        db.list_doctor_upcoming_appointments_with_report, doctor["id"]
    )
    return rows


# ---------------------------------------------------------------------------
# Google Calendar (per-doctor OAuth)
# ---------------------------------------------------------------------------


@router.get("/doctors/{doctor_id}/google-calendar")
async def google_calendar_status(doctor_id: str):
    from app.services import google_calendar_service as gcal

    doctor = await _resolve_doctor_or_404_async(doctor_id)
    return await run_in_threadpool(gcal.get_connection_status, str(doctor["id"]))


@router.post("/doctors/{doctor_id}/google-calendar/connect")
async def google_calendar_connect(doctor_id: str):
    """Returns the Google consent URL; the browser goes there to connect."""
    from app.services import google_calendar_service as gcal

    doctor = await _resolve_doctor_or_404_async(doctor_id)
    try:
        return {"auth_url": gcal.build_authorization_url(str(doctor["id"]))}
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/google/oauth/callback")
async def google_oauth_callback(
    code: str | None = None, state: str | None = None, error: str | None = None
):
    """Google redirects here after consent; we store the tokens and send the
    doctor back to Settings with the result."""
    from urllib.parse import urlencode

    from fastapi.responses import RedirectResponse

    from app.services import google_calendar_service as gcal

    def back(status: str, message: str | None = None) -> RedirectResponse:
        query = {"google": status, **({"message": message} if message else {})}
        return RedirectResponse(
            f"{settings.frontend_base_url.rstrip('/')}/settings?{urlencode(query)}", status_code=302
        )

    if error:
        return back("error", "Google sign-in was cancelled" if error == "access_denied" else error)
    if not code or not state:
        return back("error", "Missing code from Google")

    try:
        doctor_id = gcal.verify_state(state)
        await run_in_threadpool(gcal.complete_oauth, doctor_id, code)
    except Exception as exc:
        logger.exception("Google Calendar connect failed")
        return back("error", str(exc)[:200])

    # Put already-booked upcoming appointments on the newly connected calendar.
    try:
        upcoming = await _run_db_call(db.list_doctor_upcoming_appointments_with_report, doctor_id)
        gcal.queue_appointment_sync(
            *(a["id"] for a in upcoming if a.get("status") in {"booked", "confirmed"})
        )
    except Exception as exc:
        logger.warning("Initial Google Calendar sync failed: %s", exc)

    return back("connected")


@router.delete("/doctors/{doctor_id}/google-calendar", status_code=204)
async def google_calendar_disconnect(doctor_id: str):
    from app.services import google_calendar_service as gcal

    doctor = await _resolve_doctor_or_404_async(doctor_id)
    await run_in_threadpool(gcal.disconnect, str(doctor["id"]))


@router.get("/doctors/{doctor_id}/appointment-activity")
async def doctor_appointment_activity(doctor_id: str, days: int = 14):
    """Recent bookings, cancellations and reschedules, for the dashboard and bell."""
    doctor = await _run_db_call(db.resolve_doctor, doctor_id)
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found")
    return await _run_db_call(
        db.list_doctor_appointment_activity, str(doctor["id"]), max(1, min(days, 90))
    )


@router.get("/patient-portal/upcoming-appointments")
async def patient_upcoming_appointments_with_report(auth_user_id: str):
    """List upcoming appointments for a patient with linked report context."""
    patient = await _run_db_call(db.get_patient_by_auth_user_id, auth_user_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    rows = await _run_db_call(
        db.list_patient_upcoming_appointments_with_report, str(patient["id"])
    )
    return rows
