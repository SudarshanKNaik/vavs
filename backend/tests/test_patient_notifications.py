"""Patient SMS + email notifications for appointment changes (Twilio/SMTP faked)."""

import random
import uuid
from datetime import datetime, timedelta, timezone

import pytest


class _RunNow:
    """Stands in for the background executor so notifications run inline."""

    def submit(self, fn, *args, **kwargs):
        fn(*args, **kwargs)


@pytest.fixture()
def outbox(monkeypatch):
    from app.core.config import settings
    from app.services import notification_service, sms_service, smtp_service

    sent = {"sms": [], "email": []}
    monkeypatch.setattr(notification_service, "_executor", _RunNow())
    monkeypatch.setattr(settings, "notify_patients_sms", True)
    monkeypatch.setattr(settings, "notify_patients_email", True)
    monkeypatch.setattr(settings, "smtp_username", "clinic@example.org")
    monkeypatch.setattr(settings, "smtp_password", "not-used")
    monkeypatch.setattr(sms_service, "sms_configured", lambda: True)
    monkeypatch.setattr(
        sms_service,
        "send_sms_sync",
        lambda to, body: sent["sms"].append((sms_service.normalize_sms_number(to), body)) or "SMfake",
    )
    monkeypatch.setattr(
        smtp_service,
        "_send_email_sync",
        lambda to, subject, html, text=None: sent["email"].append((to, subject, text)) or {"id": "x"},
    )
    return sent


@pytest.fixture()
def clinic(db_conn):
    """A fresh doctor, a patient with phone + email, and three future slots."""
    doctor_id = db_conn.execute(
        """
        INSERT INTO doctors (name, specialty, language, consultation_type, fee, active)
        VALUES ('Dr. Asha Rao (Hubli, Karnataka)', 'General Physician', 'English', 'video', 500, TRUE)
        RETURNING id::text
        """
    ).fetchone()[0]
    phone = "9" + "".join(random.choices("0123456789", k=9))
    patient_id = db_conn.execute(
        "INSERT INTO patients (doctor_id, name, phone) VALUES (%s, 'Kiran Patil', %s) RETURNING id::text",
        (doctor_id, phone),
    ).fetchone()[0]
    auth_user_id = str(uuid.uuid4())
    email = f"kiran-{uuid.uuid4().hex[:6]}@example.org"
    db_conn.execute(
        "INSERT INTO patient_accounts (auth_user_id, patient_id, email) VALUES (%s, %s, %s)",
        (auth_user_id, patient_id, email),
    )
    base = datetime(2031, 3, 4, 5, 0, tzinfo=timezone.utc)  # 10:30 AM IST, a Tuesday
    slot_ids = []
    for i in range(3):
        start = base + timedelta(days=i)
        slot_ids.append(
            db_conn.execute(
                "INSERT INTO availability_slots (doctor_id, slot_start, slot_end) VALUES (%s, %s, %s) RETURNING id::text",
                (doctor_id, start, start + timedelta(minutes=30)),
            ).fetchone()[0]
        )
    return {
        "doctor_id": doctor_id, "patient_id": patient_id, "phone": phone, "email": email,
        "auth_user_id": auth_user_id, "slots": slot_ids,
    }


def _book(clinic, slot_index=0):
    from app.services import postgres_service as db

    slot_id = clinic["slots"][slot_index]
    assert db.reserve_slot(slot_id, clinic["patient_id"])
    appointment = db._finalize_reserved_slot_booking(slot_id, clinic["patient_id"], "video", None)
    assert appointment
    return appointment


def test_booking_sends_sms_and_email(outbox, clinic):
    _book(clinic)
    assert len(outbox["sms"]) == 1
    to, body = outbox["sms"][0]
    assert to == f"+91{clinic['phone']}"
    assert body == "CareSync: Your appointment with Dr. Asha Rao is confirmed for Tue 4 Mar, 10:30 AM."
    assert len(outbox["email"]) == 1
    assert outbox["email"][0][0] == clinic["email"]
    assert outbox["email"][0][1].startswith("Appointment confirmed")


def test_patient_reschedule_notifies_once_with_old_and_new_time(outbox, clinic):
    from app.services import postgres_service as db

    appointment = _book(clinic)
    outbox["sms"].clear()
    outbox["email"].clear()

    db.reschedule_appointment_for_patient_portal(clinic["auth_user_id"], str(appointment["id"]), clinic["slots"][1])
    # One "moved" message, not a cancellation for the old slot plus a new booking.
    assert [b for _, b in outbox["sms"]] == [
        "CareSync: Your appointment with Dr. Asha Rao is moved to Wed 5 Mar, 10:30 AM (was Tue 4 Mar, 10:30 AM)."
    ]
    assert len(outbox["email"]) == 1 and outbox["email"][0][1].startswith("Appointment rescheduled")


def test_patient_cancel_confirms_cancellation(outbox, clinic):
    from app.services import postgres_service as db

    appointment = _book(clinic)
    outbox["sms"].clear()
    outbox["email"].clear()

    db.cancel_appointment_for_patient_portal(clinic["auth_user_id"], str(appointment["id"]))
    assert [b for _, b in outbox["sms"]] == ["CareSync: Your appointment with Dr. Asha Rao on Tue 4 Mar, 10:30 AM is cancelled."]
    assert outbox["email"][0][1] == "Appointment cancelled: Tue 4 Mar, 10:30 AM"

    # Cancelling again does not notify twice.
    db.cancel_appointment(str(appointment["id"]), cancelled_by="patient")
    assert len(outbox["sms"]) == 1


def test_doctor_cancelling_a_day_tells_the_patient_why(outbox, clinic):
    from app.services import postgres_service as db

    _book(clinic, 2)
    outbox["sms"].clear()
    outbox["email"].clear()

    result = db.cancel_doctor_slots(clinic["doctor_id"], clinic["slots"], reason="Doctor on emergency leave")
    assert result["cancelled_appointments"] == 1
    assert len(outbox["sms"]) == 1
    body = outbox["sms"][0][1]
    assert "was cancelled by the clinic" in body and "Reason: Doctor on emergency leave." in body
    assert "Thu 6 Mar, 10:30 AM" in body
    assert outbox["email"][0][1].startswith("Appointment cancelled by the clinic")
    assert "Doctor on emergency leave" in outbox["email"][0][2]


def test_clinic_move_message(outbox, clinic):
    from app.services import notification_service

    appointment = _book(clinic, 1)
    outbox["sms"].clear()
    previous = datetime(2031, 3, 4, 5, 0, tzinfo=timezone.utc)
    result = notification_service.notify_appointment_sync(str(appointment["id"]), "moved", previous_start=previous)
    assert result == {"sms": "sent", "email": "sent"}
    assert outbox["sms"][0][1].startswith(
        "CareSync: Dr. Asha Rao is unavailable at your original time, so your appointment is moved to "
        "Wed 5 Mar, 10:30 AM (was Tue 4 Mar, 10:30 AM)."
    )


def test_channels_skip_cleanly(outbox, clinic, db_conn, monkeypatch):
    from app.core.config import settings
    from app.services import notification_service

    appointment = _book(clinic)
    db_conn.execute("UPDATE patients SET phone = '12345' WHERE id = %s", (clinic["patient_id"],))
    db_conn.execute("DELETE FROM patient_accounts WHERE patient_id = %s", (clinic["patient_id"],))
    result = notification_service.notify_appointment_sync(str(appointment["id"]), "cancelled", cancelled_by="doctor")
    assert result == {"sms": "skipped: no valid mobile number", "email": "skipped: no email on file"}

    monkeypatch.setattr(settings, "notify_patients_sms", False)
    monkeypatch.setattr(settings, "notify_patients_email", False)
    result = notification_service.notify_appointment_sync(str(appointment["id"]), "booked")
    assert result == {"sms": "disabled", "email": "disabled"}


def test_sms_failure_never_breaks_the_booking(outbox, clinic, monkeypatch):
    from app.services import sms_service

    def boom(to, body):
        raise RuntimeError("Twilio is down")

    monkeypatch.setattr(sms_service, "send_sms_sync", boom)
    appointment = _book(clinic)
    assert appointment["status"] == "booked"
    assert len(outbox["email"]) == 1  # email still went out


@pytest.mark.parametrize(
    "raw,expected",
    [("9876543210", "+919876543210"), ("+91 98765 43210", "+919876543210"), ("09876543210", "+919876543210"),
     ("12345", None), ("", None), (None, None)],
)
def test_sms_number_normalization(raw, expected):
    from app.services.sms_service import normalize_sms_number

    assert normalize_sms_number(raw) == expected
