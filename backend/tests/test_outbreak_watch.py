"""Outbreak Watch: symptom extraction, cluster detection and the API."""

import random
import uuid
from datetime import datetime, time, timedelta, timezone

import pytest

from app.services import outbreak_service as ow
from app.services import postgres_service as db


@pytest.mark.parametrize(
    "text, expected",
    [
        ("I have fever and body pain since 3 days", ["body_pain", "fever"]),
        ("No fever, just cough", ["cough"]),
        ("bukhar nahi hai, but loose motions", ["diarrhoea"]),
        ("ನನಗೆ ಜ್ವರ ಮತ್ತು ತಲೆನೋವು ಇದೆ", ["fever", "headache"]),
        ("मुझे बुखार और जोड़ों में दर्द है", ["body_pain", "fever"]),
        ("I don't have any fever", []),
        ("fever is gone now", []),
        ("none", []),
    ],
)
def test_extract_symptoms(text, expected):
    assert ow.extract_symptoms(text) == expected


def test_only_patient_speech_counts():
    transcript = [
        {"role": "agent", "message": "Do you have any fever or cough?"},
        {"role": "user", "message": "No, I'm fine. Tuesday works."},
    ]
    assert ow.extract_symptoms(ow.patient_speech(transcript)) == []
    assert ow.patient_speech("Agent asks about fever with no speaker roles") == ""


@pytest.mark.parametrize(
    "symptoms, syndrome",
    [
        (["fever", "body_pain"], "dengue_like"),
        (["low_platelets"], "dengue_like"),
        (["diarrhoea", "fever"], "gastro"),
        (["cough", "fever"], "respiratory"),
        (["fever"], "fever"),
        (["headache"], None),
    ],
)
def test_classify_syndrome(symptoms, syndrome):
    assert ow.classify_syndrome(symptoms) == syndrome


def test_locate_matches_known_areas_and_keeps_unknown_ones():
    assert ow.locate("12, near temple, Old Hubli") == ow.LOCALITIES["old hubli"]
    assert ow.locate("rajnagar") == ("Rajnagar", None, None)
    assert ow.locate("  ") is None


def test_poisson_sf():
    assert ow.poisson_sf(0, 2.0) == 1.0
    assert ow.poisson_sf(1, 2.0) == pytest.approx(1 - 2.718281828 ** -2)


def _reports(today, area, syndrome, per_day_counts):
    rows = []
    for days_ago, n in per_day_counts.items():
        at = datetime.combine(today - timedelta(days=days_ago), time(12), tzinfo=db.CLINIC_TZ)
        rows += [{"locality": area, "latitude": 15.36, "longitude": 75.15, "symptoms": ["fever"],
                  "syndrome": syndrome, "reported_at": at}] * n
    return rows


def test_summarise_flags_a_new_cluster_and_not_a_steady_area():
    today = datetime.now(timezone.utc).astimezone(db.CLINIC_TZ).date()
    surge = _reports(today, "Old Hubli", "dengue_like", {0: 3, 1: 3, 2: 2, 3: 1, 20: 1})
    steady = _reports(today, "Vidyanagar", "respiratory", {d: 1 for d in range(0, 35, 3)})
    summary = ow.summarise(surge + steady, today)

    levels = {(s["locality"], s["syndrome"]): s["level"] for s in summary["signals"]}
    assert levels[("Old Hubli", "dengue_like")] == "alert"
    assert levels[("Vidyanagar", "respiratory")] == "normal"
    assert summary["signals"][0]["locality"] == "Old Hubli"
    assert summary["platelets"]["dengue_cases_this_week"] == 9
    assert summary["platelets"]["projected_units"] >= 1
    assert "Old Hubli" in ow.build_brief(summary | {"today": today.isoformat()})


def test_summary_endpoint_with_demo_data(client):
    doctor_id = f"outbreak-{uuid.uuid4().hex[:8]}"
    empty = client.get("/api/outbreak/summary", params={"doctor_id": doctor_id}).json()
    assert empty["reports_in_window"] == 0 and empty["signals"] == []

    assert client.post("/api/outbreak/demo-data", json={"doctor_id": doctor_id}).json()["inserted"] > 0
    summary = client.get("/api/outbreak/summary", params={"doctor_id": doctor_id}).json()
    assert summary["demo_reports"] > 0
    assert any(s["level"] == "alert" for s in summary["signals"])
    assert all(a["latitude"] is not None for a in summary["areas"])

    assert client.delete("/api/outbreak/demo-data", params={"doctor_id": doctor_id}).json()["deleted"] > 0
    assert client.get("/api/outbreak/summary", params={"doctor_id": doctor_id}).json()["demo_reports"] == 0


def test_finished_call_records_symptoms_once(db_conn):
    doctor_id = f"outbreak-{uuid.uuid4().hex[:8]}"
    phone = "9" + "".join(random.choices("0123456789", k=9))
    patient_id = db_conn.execute(
        "INSERT INTO patients (doctor_id, name, phone, locality) VALUES (%s, 'Meena', %s, 'Keshwapur') RETURNING id::text",
        (doctor_id, phone),
    ).fetchone()[0]
    call_log = db_conn.execute(
        "INSERT INTO call_logs (patient_id, doctor_id, status) VALUES (%s, %s, 'completed') RETURNING id::text, created_at",
        (patient_id, doctor_id),
    ).fetchone()
    log = {"id": call_log[0], "patient_id": patient_id, "doctor_id": doctor_id, "created_at": call_log[1]}
    transcript = [{"role": "user", "message": "I have high fever and joint pain"}]

    report = ow.record_call_symptoms(log, "", transcript)
    assert report["syndrome"] == "dengue_like" and report["locality"] == "Keshwapur"
    ow.record_call_symptoms(log, "fever, rash", transcript)  # webhook and poller both fire

    rows = db_conn.execute(
        "SELECT symptoms FROM symptom_reports WHERE call_log_id = %s", (call_log[0],)
    ).fetchall()
    assert len(rows) == 1 and "rash" in rows[0][0]
    assert ow.record_call_symptoms(log | {"id": str(uuid.uuid4())}, "none", []) is None


def test_resolve_place_geocodes_areas_outside_hubli(monkeypatch):
    monkeypatch.setattr(ow, "geocode_place", lambda q: {"latitude": 12.93, "longitude": 77.62})
    assert ow.resolve_place("Koramangala, Bengaluru") == ("Koramangala", 12.93, 77.62)
    # Built-in areas never hit the network.
    monkeypatch.setattr(ow, "geocode_place", lambda q: pytest.fail("should not geocode"))
    assert ow.resolve_place("Old Hubli")[0] == "Old Hubli"


def test_demo_roles_put_dengue_neighbours_together_and_gastro_far_away():
    areas = [("Hub", 0.0, 0.0), ("Far", 0.2, 0.2), ("Near1", 0.01, 0.0), ("Near2", 0.0, 0.02), ("Mid", 0.1, 0.0)]
    names = [a[0] for a in ow._assign_demo_roles(areas)]
    assert names[:4] == ["Hub", "Near1", "Far", "Near2"]


def test_demo_data_for_another_city(client, monkeypatch):
    areas = [(f"Area {i}", 18.5 + i * 0.01, 73.8 + (i % 3) * 0.01) for i in range(12)]
    monkeypatch.setattr(ow, "city_areas", lambda city: ("Pune", areas))
    doctor_id = f"outbreak-{uuid.uuid4().hex[:8]}"
    res = client.post("/api/outbreak/demo-data", json={"doctor_id": doctor_id, "city": "pune"}).json()
    assert res["region"] == "Pune" and res["inserted"] > 0

    summary = client.get("/api/outbreak/summary", params={"doctor_id": doctor_id}).json()
    assert summary["demo_region"] == "Pune"
    assert {a["locality"] for a in summary["areas"]} <= {a[0] for a in areas}
    assert any(s["level"] == "alert" for s in summary["signals"])


def test_unknown_city_is_a_clear_error(client, monkeypatch):
    monkeypatch.setattr(ow, "geocode_place", lambda q: None)
    res = client.post("/api/outbreak/demo-data", json={"doctor_id": "x", "city": "Nowhereville"})
    assert res.status_code == 422 and "Couldn't find" in res.json()["detail"]
