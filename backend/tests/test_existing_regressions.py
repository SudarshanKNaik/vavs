"""Smoke checks that existing doctor/patient/workflow APIs behave as before."""

import random
import uuid


def _phone() -> str:
    return "8" + "".join(random.choices("0123456789", k=9))


ORIGINAL_PATIENT_KEYS = {
    "id", "doctor_id", "name", "phone", "dob", "mrn", "insurance",
    "primary_physician", "last_visit", "risk_level", "notes", "created_at", "updated_at",
}


def test_health(client):
    assert client.get("/health").json() == {"status": "ok", "database": "ok"}


def test_existing_patient_crud_contract_unchanged(client, doctor_id):
    created = client.post("/api/patients", json={"name": "Legacy Patient", "phone": "555-0100", "doctor_id": doctor_id})
    assert created.status_code == 201
    body = created.json()
    assert set(body) == ORIGINAL_PATIENT_KEYS
    assert body["phone"] == "555-0100"  # existing endpoint still stores phone as given

    pid = body["id"]
    assert client.get(f"/api/patients/{pid}").json()["name"] == "Legacy Patient"
    assert client.put(f"/api/patients/{pid}", json={"notes": "updated"}).json()["notes"] == "updated"
    assert any(p["id"] == pid for p in client.get("/api/patients/doctor-portal", params={"doctor_id": doctor_id}).json())
    assert client.delete(f"/api/patients/{pid}").status_code == 204


def test_doctor_and_patient_login_unchanged(client):
    from app.services import postgres_service as db

    email = f"pat-{uuid.uuid4().hex[:8]}@example.org"
    db.register_user_account("patient", email, "secret123", "Pat Person", _phone())
    resp = client.post("/api/auth/login", json={"role": "patient", "email": email, "password": "secret123"})
    assert resp.status_code == 200
    user = resp.json()["user"]
    assert user["role"] == "patient" and user["patient_id"]
    assert client.get("/api/patient-portal/me", params={"auth_user_id": user["account_id"]}).status_code == 200
    bad = client.post("/api/auth/login", json={"role": "patient", "email": email, "password": "nope"})
    assert bad.status_code == 401
    assert client.post("/api/auth/login", json={"role": "admin", "email": email, "password": "x"}).status_code == 422


def test_doctor_listing_and_appointments(client, doctor_id):
    doctors = client.get("/api/doctors")
    assert doctors.status_code == 200 and len(doctors.json()) >= 1
    assert client.get("/api/appointments", params={"doctor_id": doctor_id}).status_code == 200
    assert client.get(f"/api/doctors/{doctor_id}/slots").status_code == 200


def test_workflow_crud_and_lab_event_dispatch(client, doctor_id):
    wf = client.post(
        "/api/workflows",
        json={"doctor_id": doctor_id, "name": "Regression WF", "status": "DRAFT", "nodes": [], "edges": []},
    )
    assert wf.status_code == 201
    wf_id = wf.json()["id"]
    assert any(w["id"] == wf_id for w in client.get("/api/workflows", params={"doctor_id": doctor_id}).json())

    patient = client.post("/api/patients", json={"name": "Wf Patient", "phone": _phone(), "doctor_id": doctor_id}).json()
    resp = client.post(
        "/api/lab-event",
        json={"trigger_type": "lab_results_received", "patient_id": patient["id"], "doctor_id": doctor_id},
    )
    assert resp.status_code == 200
    assert resp.json()["workflows_executed"] == 0  # DRAFT workflows are not executed
    assert client.delete(f"/api/workflows/{wf_id}").status_code == 204
