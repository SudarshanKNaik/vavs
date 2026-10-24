"""
ElevenLabs Conversational AI Service
-------------------------------------
Initiates outbound phone calls using ElevenLabs' Conversational AI
connected to Twilio.  ElevenLabs manages the full voice conversation
(informing the patient about lab results, scheduling an appointment, etc.).

After the call ends, results can be fetched via polling (GET conversation)
or received via webhook at ``POST /api/elevenlabs/webhook``.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any
from uuid import UUID

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

ELEVENLABS_BASE = "https://api.elevenlabs.io/v1"


def _mask_phone(raw_phone: str) -> str:
    digits = "".join(ch for ch in str(raw_phone or "") if ch.isdigit())
    if len(digits) <= 4:
        return "***"
    return f"***{digits[-4:]}"


def _json_safe(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    return value


def _normalize_to_india_e164(raw_phone: str) -> str:
    digits = "".join(ch for ch in str(raw_phone or "") if ch.isdigit())
    if not digits:
        return "+91"

    # Keep only the local 10-digit Indian mobile part and force +91 prefix.
    local_number = digits[-10:]
    return f"+91{local_number}"


async def initiate_outbound_call(
    patient_phone: str,
    patient_name: str,
    doctor_name: str,
    lab_result_summary: str | None = None,
    facility_name: str | None = None,
    facility_address: str | None = None,
    facility_phone_number: str | None = None,
    call_reason: str | None = None,
    available_slots: str | None = None,
    extra_context: dict[str, Any] | None = None,
    report_title: str | None = None,
    report_date: str | None = None,
    doctor_specialty: str | None = None,
    agent_id_override: str | None = None,
    phone_number_id_override: str | None = None,
) -> dict[str, Any]:
    """
    Start an ElevenLabs Conversational AI outbound call to *patient_phone*.

    The ElevenLabs agent (configured in their dashboard) handles the entire
    conversation.  We inject dynamic context about the patient and lab
    results so the agent can reference them during the call.

    Prerequisites:
      - An ElevenLabs agent created in the dashboard (ELEVENLABS_AGENT_ID)
      - A phone number imported into ElevenLabs (Twilio integration) which
        gives you an ELEVENLABS_PHONE_NUMBER_ID
      - ELEVENLABS_API_KEY set in .env

    Returns the ElevenLabs API response (includes ``conversation_id``).
    """
    if not settings.elevenlabs_api_key:
        raise RuntimeError("ELEVENLABS_API_KEY is not configured")
    if not settings.elevenlabs_agent_id:
        raise RuntimeError("ELEVENLABS_AGENT_ID is not configured")
    if not settings.elevenlabs_phone_number_id:
        raise RuntimeError(
            "ELEVENLABS_PHONE_NUMBER_ID is not configured. "
            "Import your Twilio phone number in the ElevenLabs dashboard "
            "(Phone Numbers section) to get this ID."
        )

    agent_id = (agent_id_override or settings.elevenlabs_agent_id).strip()
    phone_number_id = (
        phone_number_id_override or settings.elevenlabs_phone_number_id
    ).strip()
    if not agent_id:
        raise RuntimeError("No ElevenLabs agent_id available for outbound call")
    if not phone_number_id:
        raise RuntimeError("No ElevenLabs phone_number_id available for outbound call")

    normalized_phone = _normalize_to_india_e164(patient_phone)

    # ----- build dynamic variables that the agent prompt can reference -----
    dynamic_variables = {
        "patient_name": patient_name,
        "doctor_name": doctor_name,
        "lab_result_summary": lab_result_summary or "recent lab results",
        "facility_name": facility_name or "Credit Valley Medical Centre",
        "facility_address": facility_address or "",
        "facility_phone_number": facility_phone_number or "",
        "call_reason": call_reason or "recent lab results",
        "reason": call_reason or "recent lab results",
        "available_slots": available_slots
        or "Monday at 10:00 AM, Wednesday at 2:00 PM, or Friday at 9:00 AM",
        "report_title": report_title or "your recent medical report",
        "report_date": report_date or "",
        "doctor_specialty": doctor_specialty or "",
        **(extra_context or {}),
    }

    # ----- build the request payload -----
    # Docs: POST /v1/convai/twilio/outbound-call
    # Required: agent_id, agent_phone_number_id, to_number
    payload: dict[str, Any] = {
        "agent_id": agent_id,
        "agent_phone_number_id": phone_number_id,
        "to_number": normalized_phone,
        "conversation_initiation_client_data": {
            "dynamic_variables": dynamic_variables,
        },
    }

    url = f"{ELEVENLABS_BASE}/convai/twilio/outbound-call"
    headers = {
        "xi-api-key": settings.elevenlabs_api_key,
        "Content-Type": "application/json",
    }

    logger.info(
        "[11L][outbound_call][request] to=%s agent_id=%s phone_number_id=%s call_log_id=%s workflow_id=%s report_id=%s dynamic_keys=%s",
        _mask_phone(normalized_phone),
        agent_id,
        phone_number_id,
        str(dynamic_variables.get("call_log_id", "")),
        str(dynamic_variables.get("workflow_id", "")),
        str(dynamic_variables.get("report_id", "")),
        sorted(list(dynamic_variables.keys())),
    )

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(url, json=_json_safe(payload), headers=headers)

    logger.info(
        "[11L][outbound_call][response] status=%s body=%s",
        resp.status_code,
        resp.text[:1200],
    )

    if resp.status_code >= 400:
        body = resp.text
        logger.error("ElevenLabs API error %s: %s", resp.status_code, body)
        raise RuntimeError(f"ElevenLabs API error {resp.status_code}: {body}")

    data = resp.json()

    # ElevenLabs sometimes wraps Twilio errors in HTTP 200 responses
    if data.get("success") is False:
        msg = data.get("message", "Unknown Twilio/ElevenLabs error")
        logger.error("ElevenLabs call failed underlying validation: %s", msg)
        raise RuntimeError(f"ElevenLabs setup failure: {msg}")

    logger.info(
        "[11L][outbound_call][accepted] conversation_id=%s callSid=%s",
        data.get("conversation_id"),
        data.get("callSid"),
    )
    return data


async def get_conversation(conversation_id: str) -> dict[str, Any]:
    """Fetch conversation details (transcript, analysis) from ElevenLabs."""
    url = f"{ELEVENLABS_BASE}/convai/conversations/{conversation_id}"
    headers = {"xi-api-key": settings.elevenlabs_api_key}

    logger.info(
        "[11L][get_conversation][request] conversation_id=%s",
        conversation_id,
    )

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(url, headers=headers)

    logger.info(
        "[11L][get_conversation][response] conversation_id=%s status=%s",
        conversation_id,
        resp.status_code,
    )

    if resp.status_code >= 400:
        logger.error("ElevenLabs GET conversation error: %s", resp.text)
        raise RuntimeError(f"ElevenLabs error {resp.status_code}: {resp.text}")

    data = resp.json()
    if isinstance(data, dict):
        analysis = data.get("analysis") or {}
        dcr = analysis.get("data_collection_results") if isinstance(analysis, dict) else {}
        dcr_keys = sorted(list(dcr.keys())) if isinstance(dcr, dict) else []
        logger.info(
            "[11L][get_conversation][parsed] conversation_id=%s conv_status=%s has_analysis=%s dcr_keys=%s",
            conversation_id,
            data.get("status", "unknown"),
            isinstance(analysis, dict),
            dcr_keys,
        )
    else:
        logger.warning(
            "[11L][get_conversation][parsed] conversation_id=%s unexpected_type=%s",
            conversation_id,
            type(data).__name__,
        )
    return data


async def list_recent_conversations(page_size: int = 10) -> list[dict[str, Any]]:
    """
    Fetch the most recent conversations for the configured agent.
    Used to find the conversation_id for a call that didn't return one immediately.
    """
    url = f"{ELEVENLABS_BASE}/convai/conversations"
    headers = {"xi-api-key": settings.elevenlabs_api_key}
    params: dict[str, Any] = {"page_size": page_size}
    if settings.elevenlabs_agent_id:
        params["agent_id"] = settings.elevenlabs_agent_id

    logger.info(
        "[11L][list_conversations][request] page_size=%s agent_id=%s",
        page_size,
        settings.elevenlabs_agent_id,
    )

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(url, headers=headers, params=params)

    logger.info(
        "[11L][list_conversations][response] status=%s",
        resp.status_code,
    )

    if resp.status_code >= 400:
        logger.error("ElevenLabs list conversations error: %s", resp.text)
        return []

    data = resp.json()
    # API returns {"conversations": [...]} or a list directly
    if isinstance(data, dict):
        conversations = data.get("conversations", [])
    else:
        conversations = data if isinstance(data, list) else []

    logger.info(
        "[11L][list_conversations][parsed] count=%s",
        len(conversations),
    )
    return conversations


async def get_conversation_by_call_sid(call_sid: str) -> str | None:
    """
    Look up the ElevenLabs conversation_id by Twilio callSid.

    ElevenLabs stores the callSid as metadata on the conversation.
    We fetch the most recent conversations and match on it.
    Returns the conversation_id string, or None if not found yet.
    """
    try:
        logger.info(
            "[11L][resolve_by_call_sid][start] call_sid=%s",
            call_sid,
        )
        convos = await list_recent_conversations(page_size=20)
        logger.info(
            "[11L][resolve_by_call_sid][scan] call_sid=%s candidates=%s",
            call_sid,
            len(convos),
        )
        for convo in convos:
            # The callSid may appear in metadata.twilio_sid or directly
            meta = convo.get("metadata", {}) or {}
            if (
                meta.get("twilio_call_sid") == call_sid
                or meta.get("callSid") == call_sid
                or convo.get("call_sid") == call_sid
            ):
                cid = convo.get("conversation_id") or convo.get("id")
                if cid:
                    logger.info(
                        "[11L][resolve_by_call_sid][found] call_sid=%s conversation_id=%s",
                        call_sid,
                        cid,
                    )
                    return cid
        logger.info(
            "[11L][resolve_by_call_sid][not_found] call_sid=%s",
            call_sid,
        )
    except Exception as exc:
        logger.warning("get_conversation_by_call_sid failed: %s", exc)
    return None
