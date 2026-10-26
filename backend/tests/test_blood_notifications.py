"""SMS + email alongside blood request calls (calls, Twilio and SMTP faked)."""

import asyncio
import uuid

import pytest

import app.services.blood_campaign_service as svc
import app.services.postgres_service as db

HOSPITAL = (15.3578, 75.1205)


class _RunNow:
    def submit(self, fn, *args, **kwargs):
        fn(*args, **kwargs)


def _phone() -> str:
    return "9" + str(uuid.uuid4().int)[:9]


@pytest.fixture()
def blood_doctor(db_conn):
    """A doctor with a login email, so the summary email has somewhere to go."""
    account_id = db_conn.execute(
        """
        INSERT INTO user_accounts (role, email, username, mobile, password)
        VALUES ('doctor', %s, 'Dr Blood', '9876500000', 'x') RETURNING id::text
        """,
        (f"blood-doc-{uuid.uuid4().hex[:6]}@example.org",),
    ).fetchone()[0]
    doctor_id = db_conn.execute(
        """
        INSERT INTO doctors (auth_user_id, name, specialty, language, consultation_type, fee, active)
        VALUES (%s, 'Dr. Blood Test', 'Haematology', 'English', 'video', 0, TRUE) RETURNING id::text
        """,
        (account_id,),
    ).fetchone()[0]
    email = db_conn.execute("SELECT email FROM user_accounts WHERE id = %s", (account_id,)).fetchone()[0]
    return {"doctor_id": doctor_id, "email": email}


@pytest.fixture()
def outbox(monkeypatch):
    from app.core.config import settings
    from app.services import blood_notification_service, sms_service, smtp_service

    sent = {"sms": [], "email": []}
    monkeypatch.setattr(blood_notification_service, "_executor", _RunNow())
    monkeypatch.setattr(settings, "notify_blood_sms", True)
    monkeypatch.setattr(settings, "notify_blood_email", True)
    monkeypatch.setattr(settings, "smtp_username", "clinic@example.org")
    monkeypatch.setattr(settings, "smtp_password", "not-used")
    monkeypatch.setattr(sms_service, "sms_configured", lambda: True)
    monkeypatch.setattr(
        sms_service, "send_sms_sync",
        lambda to, body: sent["sms"].append((sms_service.normalize_sms_number(to), body)) or "SMfake",
    )
    monkeypatch.setattr(
        smtp_service, "_send_email_sync",
        lambda to, subject, html, text=None: sent["email"].append((to, subject, text)) or {"id": "x"},
    )
    monkeypatch.setattr(svc.settings, "elevenlabs_agent_id", "agent_test")
    monkeypatch.setattr(svc.settings, "elevenlabs_phone_number_id", "phone_test")
    return sent


def _donor(doctor_id: str, name: str, km_north: float) -> dict:
    phone = _phone()
    db.upsert_blood_donors(
        doctor_id,
        [{
            "name": name, "gender": "male", "phone_number": phone,
            "location": f"{HOSPITAL[0] + km_north / 111},{HOSPITAL[1]}",
            "latitude": HOSPITAL[0] + km_north / 111, "longitude": HOSPITAL[1],
            "last_donated_date": "2020-01-01", "blood_type": "O+",
        }],
    )
    return {"name": name, "phone": phone}


def _org(doctor_id: str, name: str) -> dict:
    phone = _phone()
    db.upsert_blood_orgs(
        doctor_id,
        [{"ngo_name": name, "phone_number": phone, "location": f"{HOSPITAL[0]},{HOSPITAL[1]}",
          "latitude": HOSPITAL[0], "longitude": HOSPITAL[1]}],
    )
    return {"name": name, "phone": phone}


def _campaign(doctor_id: str, **extra) -> str:
    row = db.create_blood_campaign(
        {
            "doctor_id": doctor_id, "blood_type": "O+", "recipient_name": "Secret Patient",
            "patient_location": "KIMS Hospital, Hubli", "patient_latitude": HOSPITAL[0],
            "patient_longitude": HOSPITAL[1], "batch_size": 3, "status": "draft",
            "source": "donors", "component": "whole_blood", "units_needed": 1, "urgency": "urgent",
            "hospital_name": "KIMS", "ward": "Ward 4", "contact_name": "Nurse Rekha",
            "contact_phone": _phone(),
        }
        | extra
    )
    return str(row["id"])


def _run(cid: str, monkeypatch, outcomes: dict[str, str]):
    """outcomes: phone -> 'yes' | 'no' | 'missed' (donor) or 'yes' | 'no' (org)."""
    conversations: dict[str, str] = {}

    async def fake_call(**kwargs):
        convo = f"conv-{uuid.uuid4().hex[:8]}"
        conversations[convo] = outcomes[kwargs["patient_phone"].replace("+91", "")[-10:]]
        return {"conversation_id": convo, "callSid": "CA1"}

    async def fake_get_conversation(conversation_id):
        outcome = conversations[conversation_id]
        if outcome == "missed":
            return {"status": "initiated", "analysis": None}
        dcr = {"donor_consent": {"value": outcome}, "availability": {"value": outcome}}
        return {"status": "done", "analysis": {"data_collection_results": dcr}, "metadata": {"call_duration_secs": 40}}

    async def fake_twilio(_sid):
        return "no-answer"

    async def no_sleep(_):
        return None

    monkeypatch.setattr(svc, "initiate_outbound_call", fake_call)
    monkeypatch.setattr(svc, "get_conversation", fake_get_conversation)
    monkeypatch.setattr(svc, "get_twilio_call_status", fake_twilio)
    monkeypatch.setattr(svc.asyncio, "sleep", no_sleep)
    asyncio.run(svc.run_blood_campaign_dispatch(cid))


def _texts_to(outbox, phone: str) -> list[str]:
    return [body for to, body in outbox["sms"] if to == f"+91{phone}"]


def test_donor_yes_no_and_missed(outbox, blood_doctor, monkeypatch):
    doc = blood_doctor["doctor_id"]
    yes, no, missed = _donor(doc, "Arjun", 1), _donor(doc, "Bhavya", 2), _donor(doc, "Chetan", 3)
    cid = _campaign(doc)
    contact = db.get_blood_campaign(cid)["contact_phone"]

    _run(cid, monkeypatch, {yes["phone"]: "yes", no["phone"]: "no", missed["phone"]: "missed"})

    assert db.get_blood_campaign(cid)["status"] == "stopped"
    donor_sms = _texts_to(outbox, yes["phone"])
    assert donor_sms == [
        "CareSync BloodConnect: Thank you for agreeing to donate O+ blood. Please go to KIMS, Ward 4 "
        f"(KIMS Hospital, Hubli) and ask for Nurse Rekha {contact}."
    ]
    assert _texts_to(outbox, no["phone"]) == []  # never message someone who declined
    appeal = _texts_to(outbox, missed["phone"])
    assert len(appeal) == 1 and "urgently needs O+ whole blood" in appeal[0]
    contact_sms = _texts_to(outbox, contact)
    assert len(contact_sms) == 1 and "Donor Arjun" in contact_sms[0] and yes["phone"] in contact_sms[0]

    # The patient's name never leaves the hospital.
    assert not any("Secret Patient" in body for _, body in outbox["sms"])

    assert len(outbox["email"]) == 1
    to, subject, text = outbox["email"][0]
    assert to == blood_doctor["email"]
    assert subject == "Blood request O+ whole blood: 1 confirmed"
    assert "Arjun (donor)" in text

    messages = svc.get_blood_campaign_snapshot(cid)["messages"]
    assert sorted(m["kind"] for m in messages) == [
        "contact_update", "doctor_summary", "donor_accepted", "donor_missed"
    ]
    assert all(m["status"] == "sent" for m in messages)


def test_org_yes_messages_org_and_contact(outbox, blood_doctor, monkeypatch, db_conn):
    doc = blood_doctor["doctor_id"]
    # Organizations are shared by every doctor: set aside the others for this
    # test and remove ours afterwards, so other tests' rankings are unaffected.
    others = [r[0] for r in db_conn.execute("SELECT id FROM blood_donor_org").fetchall()]
    db_conn.execute("UPDATE blood_donor_org SET latitude = latitude + 50 WHERE id = ANY(%s)", (others,))
    org = _org(doc, "Red Cross Hubli")
    try:
        cid = _campaign(doc, source="orgs", component="packed_rbc", units_needed=2)
        contact = db.get_blood_campaign(cid)["contact_phone"]

        _run(cid, monkeypatch, {org["phone"]: "yes"})

        org_sms = _texts_to(outbox, org["phone"])
        assert len(org_sms) == 1 and "O+ red blood cell for KIMS, Ward 4" in org_sms[0]
        assert "Red Cross Hubli confirmed" in _texts_to(outbox, contact)[0]
    finally:
        db_conn.execute("DELETE FROM blood_donor_org WHERE phone_number = %s", (org["phone"],))
        db_conn.execute("UPDATE blood_donor_org SET latitude = latitude - 50 WHERE id = ANY(%s)", (others,))


def test_nobody_found_tells_contact_and_doctor(outbox, blood_doctor, monkeypatch):
    doc = blood_doctor["doctor_id"]
    no = _donor(doc, "Deepa", 1)
    cid = _campaign(doc, urgency="planned")
    contact = db.get_blood_campaign(cid)["contact_phone"]

    _run(cid, monkeypatch, {no["phone"]: "no"})

    assert db.get_blood_campaign(cid)["status"] == "completed"
    summary = _texts_to(outbox, contact)
    assert len(summary) == 1 and "No donor or blood bank has confirmed" in summary[0] and "(1 contacted)" in summary[0]
    assert outbox["email"][0][1] == "Blood request O+ whole blood: nobody confirmed"


def test_missed_call_appeal_only_for_urgent_requests(outbox, blood_doctor, monkeypatch):
    doc = blood_doctor["doctor_id"]
    missed = _donor(doc, "Esha", 1)
    cid = _campaign(doc, urgency="planned")
    _run(cid, monkeypatch, {missed["phone"]: "missed"})
    assert _texts_to(outbox, missed["phone"]) == []


def test_messages_are_sent_once(outbox, blood_doctor, monkeypatch):
    from app.services import blood_notification_service as notes

    doc = blood_doctor["doctor_id"]
    yes = _donor(doc, "Farhan", 1)
    cid = _campaign(doc)
    _run(cid, monkeypatch, {yes["phone"]: "yes"})
    before = len(outbox["sms"]) + len(outbox["email"])

    attempt_id = str(db.list_campaign_attempts(cid)[0]["id"])
    assert notes.notify_attempt_sync(attempt_id) == {"target": "duplicate", "contact": "duplicate"}
    assert notes.notify_campaign_summary_sync(cid) == {"doctor": "duplicate"}
    assert len(outbox["sms"]) + len(outbox["email"]) == before


def test_sms_failure_does_not_stop_the_search(outbox, blood_doctor, monkeypatch):
    from app.services import sms_service

    def boom(to, body):
        raise RuntimeError("Twilio is down")

    monkeypatch.setattr(sms_service, "send_sms_sync", boom)
    doc = blood_doctor["doctor_id"]
    yes = _donor(doc, "Gita", 1)
    cid = _campaign(doc)
    _run(cid, monkeypatch, {yes["phone"]: "yes"})

    assert db.get_blood_campaign(cid)["status"] == "stopped"
    statuses = {m["kind"]: m["status"] for m in svc.get_blood_campaign_snapshot(cid)["messages"]}
    assert statuses["donor_accepted"] == "failed" and statuses["doctor_summary"] == "sent"


def test_channels_can_be_switched_off(outbox, blood_doctor, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "notify_blood_sms", False)
    monkeypatch.setattr(settings, "notify_blood_email", False)
    doc = blood_doctor["doctor_id"]
    yes = _donor(doc, "Hari", 1)
    cid = _campaign(doc)
    _run(cid, monkeypatch, {yes["phone"]: "yes"})
    assert outbox == {"sms": [], "email": []}
