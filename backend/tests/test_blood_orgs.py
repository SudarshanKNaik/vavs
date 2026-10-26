import asyncio
import uuid

import pytest

import app.services.blood_campaign_service as svc
import app.services.postgres_service as db

# Hubli hospital and organizations at known distances from it.
HOSPITAL = (15.3578, 75.1205)
NEAR_ORG = (15.3620, 75.1260)  # ~0.7 km
MID_ORG = (15.3790, 75.1330)  # ~3 km
FAR_ORG = (15.4900, 75.0100)  # ~19 km
OUT_OF_RADIUS_ORG = (15.8497, 74.4977)  # Belagavi, ~70 km


def _phone() -> str:
    return "+91" + "9" + "".join(str(uuid.uuid4().int)[:9])


def _org(doctor_id: str, name: str, coords: tuple[float, float]) -> dict:
    rows = db.upsert_blood_orgs(
        doctor_id,
        [
            {
                "ngo_name": name,
                "phone_number": _phone(),
                "location": f"{coords[0]},{coords[1]}",
                "latitude": coords[0],
                "longitude": coords[1],
            }
        ],
    )
    assert rows["created"] == 1
    return next(o for o in db.list_blood_orgs(doctor_id) if o["org_name"] == name)


def _campaign(doctor_id: str, source: str = "orgs", **extra) -> dict:
    return db.create_blood_campaign(
        {
            "doctor_id": doctor_id,
            "blood_type": "O+",
            "recipient_name": "Test Patient",
            "patient_location": f"{HOSPITAL[0]},{HOSPITAL[1]}",
            "patient_latitude": HOSPITAL[0],
            "patient_longitude": HOSPITAL[1],
            "batch_size": 3,
            "status": "draft",
            "source": source,
            "hospital_name": "KIMS",
        }
        | extra
    )


def _attempt(campaign_id: str, org_id: str, status: str) -> dict:
    row = db.create_campaign_attempt(
        {"campaign_id": campaign_id, "org_id": org_id, "status": status}
    )
    return row


@pytest.fixture()
def clean_orgs(doctor_id, db_conn):
    """Each test gets its own doctor_id namespace by clearing org rows first."""
    db_conn.execute("DELETE FROM blood_donor_org WHERE doctor_id = %s", (doctor_id,))
    db_conn.execute("DELETE FROM blood_campaigns WHERE doctor_id = %s", (doctor_id,))
    yield doctor_id


def test_orgs_ranked_nearest_first_and_radius_enforced(clean_orgs):
    doctor_id = clean_orgs
    far = _org(doctor_id, "Far", FAR_ORG)
    near = _org(doctor_id, "Near", NEAR_ORG)
    mid = _org(doctor_id, "Mid", MID_ORG)
    _org(doctor_id, "Outside", OUT_OF_RADIUS_ORG)
    campaign = _campaign(doctor_id)

    targets = db.list_campaign_eligible_targets(str(campaign["id"]), limit=10)

    assert [t["id"] for t in targets] == [near["id"], mid["id"], far["id"]]
    assert all(t["target_type"] == "org" for t in targets)
    assert all(t["distance_km"] <= 20 for t in targets)


def test_hangup_retried_first_then_dropped_after_second(clean_orgs):
    doctor_id = clean_orgs
    near = _org(doctor_id, "Near", NEAR_ORG)
    mid = _org(doctor_id, "Mid", MID_ORG)
    far = _org(doctor_id, "Far", FAR_ORG)
    campaign = _campaign(doctor_id)
    cid = str(campaign["id"])

    # Near answered "no" (final); Mid hung up once.
    _attempt(cid, str(near["id"]), "declined")
    _attempt(cid, str(mid["id"]), "hangup")

    ids = [t["id"] for t in db.list_campaign_eligible_targets(cid, limit=3)]
    assert ids == [mid["id"], far["id"]]  # retry first, near is final

    second = _attempt(cid, str(mid["id"]), "hangup")
    assert second["attempt_number"] == 2

    ids = [t["id"] for t in db.list_campaign_eligible_targets(cid, limit=3)]
    assert ids == [far["id"]]  # dropped after the second hang-up


def test_in_flight_org_is_not_called_twice(clean_orgs):
    doctor_id = clean_orgs
    near = _org(doctor_id, "Near", NEAR_ORG)
    campaign = _campaign(doctor_id)
    _attempt(str(campaign["id"]), str(near["id"]), "active")
    assert db.list_campaign_eligible_targets(str(campaign["id"]), limit=3) == []


def test_donors_source_ignores_orgs(clean_orgs):
    doctor_id = clean_orgs
    _org(doctor_id, "Near", NEAR_ORG)
    campaign = _campaign(doctor_id, source="donors")
    assert db.list_campaign_eligible_targets(str(campaign["id"]), limit=3) == []


def test_any_source_mixes_donors_and_orgs_by_distance(clean_orgs, db_conn):
    doctor_id = clean_orgs
    org = _org(doctor_id, "Mid", MID_ORG)
    phone = _phone()
    db_conn.execute(
        """
        INSERT INTO blood_donors (doctor_id, name, gender, phone_number, location,
                                  latitude, longitude, last_donated_date, blood_type)
        VALUES (%s, 'Close Donor', 'male', %s, 'x', %s, %s, '2020-01-01', 'O+')
        """,
        (doctor_id, phone, NEAR_ORG[0], NEAR_ORG[1]),
    )
    campaign = _campaign(doctor_id, source="any")

    targets = db.list_campaign_eligible_targets(str(campaign["id"]), limit=3)
    assert [(t["target_type"], t["name"]) for t in targets] == [
        ("donor", "Close Donor"),
        ("org", "Mid"),
    ]
    assert targets[1]["id"] == org["id"]
    db_conn.execute("DELETE FROM blood_donors WHERE doctor_id = %s", (doctor_id,))


def test_classify_org_call():
    def convo(**dcr):
        return {
            "status": "done",
            "analysis": {"data_collection_results": {k: {"value": v} for k, v in dcr.items()}},
        }

    assert svc._classify_org_call(convo(availability="yes", units_available="2 units")) == (
        "accepted",
        2,
    )
    assert svc._classify_org_call(convo(availability="no")) == ("declined", None)
    assert svc._classify_org_call(convo(call_outcome="not_available")) == ("declined", None)
    assert svc._classify_org_call(convo()) == ("hangup", None)
    assert svc._classify_org_call({"status": "failed"}) == ("hangup", None)


def test_dispatch_retries_hangup_then_stops_on_acceptance(clean_orgs, monkeypatch):
    doctor_id = clean_orgs
    near = _org(doctor_id, "Near", NEAR_ORG)
    mid = _org(doctor_id, "Mid", MID_ORG)
    far = _org(doctor_id, "Far", FAR_ORG)
    campaign = _campaign(doctor_id, batch_size=2)
    cid = str(campaign["id"])

    monkeypatch.setattr(svc.settings, "elevenlabs_agent_id", "agent_test")
    monkeypatch.setattr(svc.settings, "elevenlabs_phone_number_id", "phone_test")

    calls_by_phone: dict[str, int] = {}
    # Batches of 2: [Near, Mid] then [Near again, Far]. Near hangs up both
    # times, Mid says no, Far has the blood.
    script = {
        near["phone_number"]: ["hangup", "hangup"],
        mid["phone_number"]: ["no"],
        far["phone_number"]: ["yes"],
    }
    conversations: dict[str, str] = {}

    async def fake_call(**kwargs):
        phone = kwargs["patient_phone"]
        n = calls_by_phone.get(phone, 0)
        calls_by_phone[phone] = n + 1
        convo_id = f"conv-{uuid.uuid4().hex[:8]}"
        conversations[convo_id] = script[phone][n]
        assert kwargs["extra_context"]["call_type"] == "org"
        return {"conversation_id": convo_id, "callSid": "CA1"}

    async def fake_get_conversation(conversation_id):
        outcome = conversations[conversation_id]
        dcr = {} if outcome == "hangup" else {"availability": {"value": outcome}}
        return {"status": "done", "analysis": {"data_collection_results": dcr}}

    async def no_sleep(_):
        return None

    monkeypatch.setattr(svc, "initiate_outbound_call", fake_call)
    monkeypatch.setattr(svc, "get_conversation", fake_get_conversation)
    monkeypatch.setattr(svc.asyncio, "sleep", no_sleep)

    asyncio.run(svc.run_blood_campaign_dispatch(cid))

    final = db.get_blood_campaign(cid)
    assert final["status"] == "stopped"
    # Near hung up in batch 1 and was retried in batch 2 alongside Far.
    assert calls_by_phone[near["phone_number"]] == 2
    assert calls_by_phone[mid["phone_number"]] == 1
    assert calls_by_phone[far["phone_number"]] == 1

    attempts = db.list_campaign_attempts(cid)
    far_attempt = next(a for a in attempts if str(a["org_id"]) == str(far["id"]))
    assert far_attempt["status"] == "accepted"
    assert far_attempt["target_type"] == "org"


def test_orgs_are_shared_across_doctors(clean_orgs, db_conn):
    doctor_id = clean_orgs
    other_doctor = str(uuid.uuid4())
    db.upsert_blood_orgs(
        other_doctor,
        [
            {
                "ngo_name": "Shared Bank",
                "phone_number": _phone(),
                "location": "x",
                "latitude": NEAR_ORG[0],
                "longitude": NEAR_ORG[1],
            }
        ],
    )
    campaign = _campaign(doctor_id)
    names = [t["name"] for t in db.list_campaign_eligible_targets(str(campaign["id"]), limit=5)]
    # Orgs are shared, so don't leave this one behind for other tests.
    db_conn.execute("DELETE FROM blood_donor_org WHERE doctor_id = %s", (other_doctor,))
    assert "Shared Bank" in names


def test_blood_request_requires_requesting_body_details(client, doctor_id):
    resp = client.post(
        "/api/blood-requests",
        json={
            "doctor_id": doctor_id,
            "blood_type": "O+",
            "recipient_name": "No Hospital Patient",
            "source": "any",
        },
    )
    assert resp.status_code == 422
    missing = {err["loc"][-1] for err in resp.json()["detail"]}
    assert {"hospital_name", "hospital_location", "contact_name", "contact_phone"} <= missing


def _run_single_org_call(monkeypatch, doctor_id, conversation_fn, twilio_status="in-progress"):
    """Dispatch a one-org campaign whose only call is shaped by conversation_fn."""
    _org(doctor_id, "Solo", NEAR_ORG)
    campaign = _campaign(doctor_id, batch_size=1)
    monkeypatch.setattr(svc.settings, "elevenlabs_agent_id", "agent_test")
    monkeypatch.setattr(svc.settings, "elevenlabs_phone_number_id", "phone_test")

    async def fake_call(**kwargs):
        return {"conversation_id": "conv-solo", "callSid": "CA-solo"}

    async def fake_twilio(call_sid):
        return twilio_status

    async def no_sleep(_):
        return None

    monkeypatch.setattr(svc, "initiate_outbound_call", fake_call)
    monkeypatch.setattr(svc, "get_conversation", conversation_fn)
    monkeypatch.setattr(svc, "get_twilio_call_status", fake_twilio)
    monkeypatch.setattr(svc.asyncio, "sleep", no_sleep)
    # One org that hangs up twice is dropped, so the campaign ends.
    asyncio.run(svc.run_blood_campaign_dispatch(str(campaign["id"])))
    return [a["status"] for a in db.list_campaign_attempts(str(campaign["id"]))]


def test_unanswered_call_is_a_hangup_not_calling_forever(clean_orgs, monkeypatch):
    async def initiated_forever(_):
        return {"status": "initiated", "metadata": {"call_duration_secs": 0}}

    statuses = _run_single_org_call(
        monkeypatch, clean_orgs, initiated_forever, twilio_status="no-answer"
    )
    assert statuses == ["hangup", "hangup"]  # tried, retried once, then dropped


def test_unanswered_call_without_twilio_times_out_as_hangup(clean_orgs, monkeypatch):
    async def initiated_forever(_):
        return {"status": "initiated", "metadata": {"call_duration_secs": 0}}

    statuses = _run_single_org_call(
        monkeypatch, clean_orgs, initiated_forever, twilio_status=None
    )
    assert statuses == ["hangup", "hangup"]


def test_org_decline_is_declined_even_when_analysis_arrives_late(clean_orgs, monkeypatch):
    polls = {"n": 0}

    async def late_analysis(_):
        polls["n"] += 1
        if polls["n"] < 3:  # call is "done" but ElevenLabs hasn't analysed it yet
            return {"status": "done", "metadata": {"call_duration_secs": 29}}
        return {
            "status": "done",
            "metadata": {"call_duration_secs": 29},
            "analysis": {
                "data_collection_results": {
                    "donor_consent": {"value": "no"},
                    "call_outcome": {"value": "declined"},
                }
            },
        }

    statuses = _run_single_org_call(monkeypatch, clean_orgs, late_analysis)
    assert statuses == ["declined"]
