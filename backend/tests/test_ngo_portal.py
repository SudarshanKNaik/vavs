import csv
import io
import random
import uuid

import pytest


def _phone() -> str:
    return "9" + "".join(random.choices("0123456789", k=9))


def _csv(rows: list[list[str]]) -> bytes:
    out = io.StringIO()
    csv.writer(out).writerows(rows)
    return out.getvalue().encode("utf-8")


def _preview(client, ngo, content: bytes, doctor_id: str | None, name="patients.csv", mapping=None):
    data = {}
    if doctor_id:
        data["default_doctor_id"] = doctor_id
    if mapping is not None:
        import json

        data["column_mapping"] = json.dumps(mapping)
    return client.post(
        "/api/ngo/patients/import/preview",
        headers=ngo["headers"],
        files={"file": (name, content, "text/csv")},
        data=data,
    )


def _register(client, ngo, doctor_id, **overrides):
    body = {"name": "Lakshmi Patil", "phone": _phone(), "doctor_id": doctor_id, **overrides}
    headers = dict(ngo["headers"])
    key = overrides.pop("_key", None)
    if key:
        headers["Idempotency-Key"] = key
    body.pop("_key", None)
    return client.post("/api/ngo/patients", json=body, headers=headers)


# ---------------------------------------------------------------------------
# Authentication / authorization
# ---------------------------------------------------------------------------

NGO_GET_ENDPOINTS = [
    "/api/ngo/me",
    "/api/ngo/dashboard",
    "/api/ngo/patients",
    f"/api/ngo/patients/{uuid.uuid4()}",
    "/api/ngo/imports",
    f"/api/ngo/imports/{uuid.uuid4()}",
    f"/api/ngo/imports/{uuid.uuid4()}/errors",
    "/api/ngo/audit-events",
]


@pytest.mark.parametrize("path", NGO_GET_ENDPOINTS)
def test_ngo_endpoints_require_session(client, path):
    assert client.get(path).status_code == 401
    assert client.get(path, headers={"Authorization": "Bearer not-a-real-token"}).status_code == 401


def test_ngo_write_endpoints_require_session(client, doctor_id):
    assert client.post("/api/ngo/patients", json={"name": "X Y", "phone": _phone(), "doctor_id": doctor_id}).status_code == 401
    assert client.post("/api/ngo/patients/import/confirm", json={"import_id": str(uuid.uuid4())}).status_code == 401
    resp = client.post(
        "/api/ngo/patients/import/preview",
        files={"file": ("a.csv", b"name,phone\nA B,9876543210\n", "text/csv")},
    )
    assert resp.status_code == 401


def test_doctor_and_patient_tokens_do_not_grant_ngo_access(client):
    from app.services import postgres_service as db

    email = f"doc-{uuid.uuid4().hex[:8]}@example.org"
    db.register_user_account("doctor", email, "secret123", "Dr Who", "9876500000")
    login = client.post("/api/auth/login", json={"role": "doctor", "email": email, "password": "secret123"})
    assert login.status_code == 200
    assert login.json()["user"]["role"] == "doctor"
    token = login.json()["token"]
    assert client.get("/api/ngo/dashboard", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_doctor_patient_auth_does_not_handle_ngo(client, ngo_a):
    # NGO auth lives only under /api/ngo/auth/*; the doctor/patient endpoints reject it.
    resp = client.post("/api/auth/login", json={"role": "ngo", "email": ngo_a["email"], "password": ngo_a["password"]})
    assert resp.status_code == 422
    resp = client.post(
        "/api/auth/register",
        json={"role": "ngo", "email": "x@example.org", "password": "secret123",
              "username": "x", "mobile": "9876543210", "otp_code": "123456"},
    )
    assert resp.status_code == 422
    resp = client.post("/api/auth/otp/send", json={"role": "ngo", "email": "x@example.org", "purpose": "register"})
    assert resp.status_code == 422


@pytest.fixture()
def sent_otps(monkeypatch):
    from app.services import smtp_service

    sent: dict[str, str] = {}

    async def fake_send_otp_email(to_email, otp_code, purpose):
        sent[to_email] = otp_code
        return {"id": "test"}

    monkeypatch.setattr(smtp_service, "send_otp_email", fake_send_otp_email)
    return sent


_used_darpan_ids: set[str] = set()


def _darpan_id() -> str:
    while True:
        value = f"{random.randint(0, 99999):05d}"
        if value not in _used_darpan_ids:
            _used_darpan_ids.add(value)
            return value


def _register_body(email: str, otp: str, **overrides) -> dict:
    return {
        "ngo_name": f"Seva Trust {uuid.uuid4().hex[:6]}",
        "darpan_id": _darpan_id(),
        "city": "Dharwad",
        "admin_name": "Priya Desai",
        "email": email,
        "mobile": "9876501234",
        "password": "a-strong-password",
        "otp_code": otp,
        **overrides,
    }


def test_ngo_self_registration(client, sent_otps, db_conn):
    email = f"seva-{uuid.uuid4().hex[:8]}@example.org"
    sent = client.post("/api/ngo/auth/otp/send", json={"email": email})
    assert sent.status_code == 200, sent.text
    otp = sent_otps[email]
    # Only a hash of the code is stored.
    assert db_conn.execute("SELECT count(*) FROM ngo_email_otps WHERE code_hash = %s", (otp,)).fetchone()[0] == 0

    # Resend is rate limited.
    assert client.post("/api/ngo/auth/otp/send", json={"email": email}).status_code == 429

    wrong = client.post("/api/ngo/auth/register", json=_register_body(email, "000000" if otp != "000000" else "111111"))
    assert wrong.status_code == 401
    assert wrong.json()["detail"]["code"] == "invalid_otp"

    body = _register_body(email, otp)
    resp = client.post("/api/ngo/auth/register", json=body)
    assert resp.status_code == 201, resp.text
    session = resp.json()
    assert session["user"]["role"] == "ngo"
    assert session["user"]["ngo_name"] == body["ngo_name"]
    assert session["user"]["ngo_member_role"] == "admin"
    headers = {"Authorization": f"Bearer {session['token']}"}
    assert client.get("/api/ngo/dashboard", headers=headers).json()["total_patients"] == 0

    # OTP cannot be reused, and the email is now taken.
    again = client.post("/api/ngo/auth/register", json=_register_body(email, otp))
    assert again.status_code == 401
    assert client.post("/api/ngo/auth/otp/send", json={"email": email}).status_code == 409

    # The new admin can log in through the NGO login endpoint.
    login = client.post("/api/ngo/auth/login", json={"email": email, "password": body["password"]})
    assert login.status_code == 200


def test_ngo_registration_validation_and_duplicate_name(client, sent_otps):
    email = f"dup-{uuid.uuid4().hex[:8]}@example.org"
    client.post("/api/ngo/auth/otp/send", json={"email": email})
    bad = client.post(
        "/api/ngo/auth/register",
        json=_register_body(email, sent_otps[email], ngo_name="AB", admin_name="X", mobile="123"),
    )
    assert bad.status_code == 422
    assert set(bad.json()["detail"]["field_errors"]) >= {"ngo_name", "admin_name", "mobile"}
    short_pw = client.post("/api/ngo/auth/register", json=_register_body(email, sent_otps[email], password="short"))
    assert short_pw.status_code == 422

    first_email = f"first-{uuid.uuid4().hex[:8]}@example.org"
    client.post("/api/ngo/auth/otp/send", json={"email": first_email})
    name = f"Unique Name Trust {uuid.uuid4().hex[:6]}"
    ok = client.post("/api/ngo/auth/register", json=_register_body(first_email, sent_otps[first_email], ngo_name=name))
    assert ok.status_code == 201
    dup = client.post(
        "/api/ngo/auth/register", json=_register_body(email, sent_otps[email], ngo_name=name.upper())
    )
    assert dup.status_code == 409
    assert dup.json()["detail"]["code"] == "ngo_exists"


@pytest.mark.parametrize("darpan_id", ["", "1234", "123456", "12a45", "12 345"])
def test_ngo_registration_requires_5_digit_darpan_id(client, sent_otps, darpan_id):
    email = f"darpan-{uuid.uuid4().hex[:8]}@example.org"
    client.post("/api/ngo/auth/otp/send", json={"email": email})
    resp = client.post("/api/ngo/auth/register", json=_register_body(email, sent_otps[email], darpan_id=darpan_id))
    assert resp.status_code == 422
    assert "darpan_id" in resp.json()["detail"]["field_errors"]


def test_ngo_darpan_id_is_unique_and_stored(client, sent_otps, db_conn):
    darpan = _darpan_id()
    first = f"d1-{uuid.uuid4().hex[:8]}@example.org"
    client.post("/api/ngo/auth/otp/send", json={"email": first})
    ok = client.post("/api/ngo/auth/register", json=_register_body(first, sent_otps[first], darpan_id=darpan))
    assert ok.status_code == 201
    stored = db_conn.execute(
        "SELECT darpan_id FROM ngo_organizations WHERE id = %s", (ok.json()["user"]["ngo_id"],)
    ).fetchone()[0]
    assert stored == darpan

    second = f"d2-{uuid.uuid4().hex[:8]}@example.org"
    client.post("/api/ngo/auth/otp/send", json={"email": second})
    dup = client.post("/api/ngo/auth/register", json=_register_body(second, sent_otps[second], darpan_id=darpan))
    assert dup.status_code == 409
    assert dup.json()["detail"]["code"] == "darpan_id_exists"
    # The duplicate was rejected before the OTP was spent, so the code still works.
    retry = client.post("/api/ngo/auth/register", json=_register_body(second, sent_otps[second]))
    assert retry.status_code == 201


def test_ngo_otp_attempts_are_limited(client, sent_otps):
    email = f"brute-{uuid.uuid4().hex[:8]}@example.org"
    client.post("/api/ngo/auth/otp/send", json={"email": email})
    real = sent_otps[email]
    wrong = "000000" if real != "000000" else "111111"
    for _ in range(5):
        assert client.post("/api/ngo/auth/register", json=_register_body(email, wrong)).status_code == 401
    # Even the correct code is refused after too many attempts.
    assert client.post("/api/ngo/auth/register", json=_register_body(email, real)).status_code == 401


def test_ngo_login_and_logout(client, ngo_a, db_conn):
    bad = client.post("/api/ngo/auth/login", json={"email": ngo_a["email"], "password": "wrong-password"})
    assert bad.status_code == 401
    unknown = client.post("/api/ngo/auth/login", json={"email": "nobody@example.org", "password": "x"})
    assert unknown.status_code == 401

    me = client.get("/api/ngo/me", headers=ngo_a["headers"])
    assert me.status_code == 200
    assert me.json()["ngo_id"] == ngo_a["ngo_id"]

    # Password is stored hashed, tokens only as hashes.
    stored = db_conn.execute("SELECT password FROM user_accounts WHERE email = %s", (ngo_a["email"],)).fetchone()[0]
    assert stored.startswith("pbkdf2_sha256$") and ngo_a["password"] not in stored
    assert db_conn.execute("SELECT count(*) FROM ngo_sessions WHERE token_hash = %s", (ngo_a["token"],)).fetchone()[0] == 0

    assert client.post("/api/ngo/auth/logout", headers=ngo_a["headers"]).status_code == 204
    assert client.get("/api/ngo/me", headers=ngo_a["headers"]).status_code == 401


def test_deactivated_membership_loses_access(client, ngo_a, db_conn):
    db_conn.execute(
        "UPDATE ngo_memberships SET is_active = FALSE WHERE ngo_id = %s", (ngo_a["ngo_id"],)
    )
    assert client.get("/api/ngo/me", headers=ngo_a["headers"]).status_code == 401


# ---------------------------------------------------------------------------
# Manual registration
# ---------------------------------------------------------------------------


def test_manual_registration_creates_existing_patient_model(client, ngo_a, doctor_id, db_conn):
    phone = _phone()
    resp = _register(client, ngo_a, doctor_id, phone=f"+91 {phone[:5]} {phone[5:]}", dob="15/08/1980",
                     notes="Referred from village camp")
    assert resp.status_code == 201, resp.text
    patient_id = resp.json()["patient_id"]

    row = db_conn.execute(
        "SELECT doctor_id, name, phone, dob, risk_level FROM patients WHERE id = %s", (patient_id,)
    ).fetchone()
    assert row == (doctor_id, "Lakshmi Patil", f"+91{phone}", "1980-08-15", "low")
    reg = db_conn.execute(
        "SELECT ngo_id::text, source FROM ngo_patient_registrations WHERE patient_id = %s", (patient_id,)
    ).fetchone()
    assert reg == (ngo_a["ngo_id"], "manual")

    detail = client.get(f"/api/ngo/patients/{patient_id}", headers=ngo_a["headers"])
    assert detail.status_code == 200
    assert detail.json()["source"] == "manual"

    # Visible to the assigned doctor through the existing patient endpoints.
    doctor_patients = client.get("/api/patients", params={"doctor_id": doctor_id}).json()
    assert any(p["id"] == patient_id for p in doctor_patients)

    # Registration must not trigger workflows / calls.
    calls = db_conn.execute("SELECT count(*) FROM call_logs WHERE patient_id = %s", (patient_id,)).fetchone()[0]
    assert calls == 0

    events = db_conn.execute(
        "SELECT action FROM ngo_audit_events WHERE entity_id = %s ORDER BY created_at", (patient_id,)
    ).fetchall()
    assert [e[0] for e in events] == ["patient_registered", "patient_viewed"]


def test_manual_registration_validation_errors(client, ngo_a, doctor_id):
    resp = _register(client, ngo_a, doctor_id, name="=HYPERLINK(1)", phone="12345", dob="2999-01-01")
    assert resp.status_code == 422
    errors = resp.json()["detail"]["field_errors"]
    assert set(errors) >= {"name", "phone", "dob"}

    resp = _register(client, ngo_a, str(uuid.uuid4()))
    assert resp.status_code == 422
    assert "doctor_id" in resp.json()["detail"]["field_errors"]

    resp = client.post("/api/ngo/patients", json={"name": "Only Name"}, headers=ngo_a["headers"])
    assert resp.status_code == 422  # pydantic: missing phone/doctor_id


def test_manual_registration_idempotency_key(client, ngo_a, doctor_id, db_conn):
    key = str(uuid.uuid4())
    phone = _phone()
    first = _register(client, ngo_a, doctor_id, phone=phone, _key=key)
    second = _register(client, ngo_a, doctor_id, phone=phone, _key=key)
    assert first.status_code == 201 and second.status_code == 201
    assert first.json()["patient_id"] == second.json()["patient_id"]
    assert second.json()["replayed"] is True
    count = db_conn.execute(
        "SELECT count(*) FROM ngo_patient_registrations WHERE ngo_id = %s AND idempotency_key = %s",
        (ngo_a["ngo_id"], key),
    ).fetchone()[0]
    assert count == 1


def test_manual_duplicate_and_possible_duplicate(client, ngo_a, doctor_id):
    phone = _phone()
    assert _register(client, ngo_a, doctor_id, phone=phone, dob="1990-01-01").status_code == 201

    dup = _register(client, ngo_a, doctor_id, phone=phone, name="  lakshmi   patil ", dob="1990-01-01")
    assert dup.status_code == 409
    assert dup.json()["detail"]["code"] == "duplicate_patient"

    # Same phone, different person (shared family phone) -> review, not a block.
    review = _register(client, ngo_a, doctor_id, phone=phone, name="Ravi Patil")
    assert review.status_code == 409
    assert review.json()["detail"]["code"] == "possible_duplicate"
    ok = _register(client, ngo_a, doctor_id, phone=phone, name="Ravi Patil", confirm_possible_duplicate=True)
    assert ok.status_code == 201


# ---------------------------------------------------------------------------
# Organization isolation
# ---------------------------------------------------------------------------


def test_ngo_isolation(client, ngo_a, ngo_b, doctor_id):
    patient_id = _register(client, ngo_a, doctor_id).json()["patient_id"]
    preview = _preview(client, ngo_a, _csv([["name", "phone"], ["Asha Rao", _phone()]]), doctor_id)
    import_id = preview.json()["import_id"]

    assert client.get(f"/api/ngo/patients/{patient_id}", headers=ngo_b["headers"]).status_code == 404
    assert client.get("/api/ngo/patients", headers=ngo_b["headers"]).json()["total"] == 0
    assert client.get(f"/api/ngo/imports/{import_id}", headers=ngo_b["headers"]).status_code == 404
    assert client.get(f"/api/ngo/imports/{import_id}/errors", headers=ngo_b["headers"]).status_code == 404
    confirm = client.post("/api/ngo/patients/import/confirm", json={"import_id": import_id}, headers=ngo_b["headers"])
    assert confirm.status_code == 404
    assert client.get("/api/ngo/imports", headers=ngo_b["headers"]).json()["total"] == 0
    assert client.get("/api/ngo/dashboard", headers=ngo_b["headers"]).json()["total_patients"] == 0

    # A patient created outside any NGO is not visible either.
    outsider = client.post("/api/patients", json={"name": "Clinic Patient", "phone": _phone(), "doctor_id": doctor_id})
    assert client.get(f"/api/ngo/patients/{outsider.json()['id']}", headers=ngo_a["headers"]).status_code == 404


# ---------------------------------------------------------------------------
# CSV import
# ---------------------------------------------------------------------------


def test_csv_template_download(client):
    resp = client.get("/api/ngo/patients/import/template")
    assert resp.status_code == 200
    assert resp.text.strip().split(",")[:2] == ["name", "phone"]


def test_csv_preview_and_confirm(client, ngo_a, doctor_id, db_conn):
    existing_phone = _phone()
    _register(client, ngo_a, doctor_id, name="Meena Kulkarni", phone=existing_phone)
    p1, p2 = _phone(), _phone()
    content = "﻿" + (
        " Full Name , Mobile ,Date of Birth,Village\n"
        f"  Suresh  Hegde , {p1} ,1975-03-02,Dharwad\n"
        "\n"
        f"Geeta Joshi,0{p2},31/12/1988,Hubli\n"
        f"Suresh Hegde,{p1},,Dharwad\n"           # duplicate of row 2 in file
        f"Meena Kulkarni,{existing_phone},,Hubli\n"  # already registered by NGO
        "Bad Row,123,not-a-date,Hubli\n"          # invalid
        ",,,\n"
    )
    resp = _preview(client, ngo_a, content.encode("utf-8"), doctor_id)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["mapping"] == {"name": "Full Name", "phone": "Mobile", "dob": "Date of Birth"}
    assert body["ignored_columns"] == ["Village"]
    assert body["empty_rows_skipped"] == 2
    assert (body["total_rows"], body["valid_rows"], body["invalid_rows"], body["duplicate_rows"]) == (5, 2, 1, 2)
    invalid = next(r for r in body["rows"] if r["status"] == "invalid")
    assert {e["field"] for e in invalid["errors"]} == {"phone", "dob"}

    # Nothing is saved before confirmation.
    assert client.get("/api/ngo/patients", headers=ngo_a["headers"], params={"source": "csv"}).json()["total"] == 0

    import_id = body["import_id"]
    confirm = client.post("/api/ngo/patients/import/confirm", json={"import_id": import_id}, headers=ngo_a["headers"])
    assert confirm.status_code == 200, confirm.text
    result = confirm.json()
    assert (result["inserted_count"], result["skipped_count"], result["failed_count"]) == (2, 2, 1)
    assert result["already_processed"] is False

    # Repeating the confirm request is safe.
    again = client.post("/api/ngo/patients/import/confirm", json={"import_id": import_id}, headers=ngo_a["headers"])
    assert again.json()["already_processed"] is True
    listed = client.get("/api/ngo/patients", headers=ngo_a["headers"], params={"import_id": import_id}).json()
    assert listed["total"] == 2
    assert {p["name"] for p in listed["items"]} == {"Suresh Hegde", "Geeta Joshi"}
    assert all(p["source"] == "csv" for p in listed["items"])
    geeta = next(p for p in listed["items"] if p["name"] == "Geeta Joshi")
    assert geeta["phone"] == f"+91{p2}" and geeta["dob"] == "1988-12-31"

    # Re-uploading the same file flags everything as duplicates.
    second = _preview(client, ngo_a, content.encode("utf-8"), doctor_id).json()
    assert second["valid_rows"] == 0

    history = client.get("/api/ngo/imports", headers=ngo_a["headers"]).json()
    assert [i["id"] for i in history["items"]] == [second["import_id"], import_id]
    assert history["items"][1]["status"] == "completed" and history["items"][0]["status"] == "previewed"


def test_csv_review_rows_need_explicit_approval(client, ngo_a, doctor_id):
    shared_phone = _phone()
    _register(client, ngo_a, doctor_id, name="Kavya Naik", phone=shared_phone)
    content = _csv([["name", "phone"], ["Rohan Naik", shared_phone], ["Divya Naik", shared_phone]])
    preview = _preview(client, ngo_a, content, doctor_id).json()
    assert preview["review_rows"] == 2
    rohan_row = next(r["row_number"] for r in preview["rows"] if r["raw_data"]["name"] == "Rohan Naik")
    result = client.post(
        "/api/ngo/patients/import/confirm",
        json={"import_id": preview["import_id"], "approved_review_rows": [rohan_row]},
        headers=ngo_a["headers"],
    ).json()
    assert (result["inserted_count"], result["skipped_count"]) == (1, 1)


def test_csv_column_mapping_override(client, ngo_a, doctor_id):
    content = _csv([["Beneficiary", "Contact No"], ["Anil Kumar", _phone()]])
    missing = _preview(client, ngo_a, content, doctor_id)
    assert missing.status_code == 422
    detail = missing.json()["detail"]
    assert detail["code"] == "missing_required_columns"
    assert detail["headers"] == ["Beneficiary", "Contact No"]

    mapped = _preview(client, ngo_a, content, doctor_id, mapping={"name": "Beneficiary", "phone": "Contact No"})
    assert mapped.status_code == 200
    assert mapped.json()["valid_rows"] == 1

    bad = _preview(client, ngo_a, content, doctor_id, mapping={"name": "Nope", "phone": "Contact No"})
    assert bad.status_code == 400


def test_csv_requires_doctor(client, ngo_a):
    content = _csv([["name", "phone"], ["Anil Kumar", _phone()]])
    body = _preview(client, ngo_a, content, None).json()
    assert body["invalid_rows"] == 1
    assert body["rows"][0]["errors"][0]["field"] == "doctor_id"
    assert _preview(client, ngo_a, content, str(uuid.uuid4())).status_code == 422


@pytest.mark.parametrize(
    "name,content,status,code",
    [
        ("patients.xlsx", b"name,phone\nA B,9876543210\n", 415, "unsupported_file_type"),
        ("patients.csv", b"", 400, "empty_file"),
        ("patients.csv", b"name,phone\n", 400, "empty_file"),
        ("patients.csv", "name,phone\nJos\xe9,9876543210\n".encode("latin-1"), 400, "invalid_encoding"),
        ("patients.csv", b"PK\x03\x04\x00\x00binary", 400, "malformed_csv"),
        ("patients.csv", b'name,phone\n"Unclosed "quote" here,9876543210\n', 400, "malformed_csv"),
        ("patients.csv", b"name,name\nA,B\n", 400, "malformed_csv"),
    ],
)
def test_csv_malformed_inputs(client, ngo_a, doctor_id, name, content, status, code):
    resp = _preview(client, ngo_a, content, doctor_id, name=name)
    assert resp.status_code == status, resp.text
    assert resp.json()["detail"]["code"] == code


def test_csv_size_and_row_limits(client, ngo_a, doctor_id, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "ngo_csv_max_bytes", 200)
    big = b"name,phone\n" + b"Long Name Person,9876543210\n" * 20
    resp = _preview(client, ngo_a, big, doctor_id)
    assert resp.status_code == 413 and resp.json()["detail"]["code"] == "file_too_large"

    monkeypatch.setattr(settings, "ngo_csv_max_bytes", 1024 * 1024)
    monkeypatch.setattr(settings, "ngo_csv_max_rows", 3)
    rows = [["name", "phone"]] + [[f"Person {chr(65 + i)}", _phone()] for i in range(4)]
    resp = _preview(client, ngo_a, _csv(rows), doctor_id)
    assert resp.status_code == 413 and resp.json()["detail"]["code"] == "too_many_rows"


def test_csv_partial_failure_is_reported(client, ngo_a, doctor_id, monkeypatch):
    from app.services import ngo_service

    content = _csv([["name", "phone"], ["Good One", _phone()], ["Explodes Here", _phone()], ["Good Two", _phone()]])
    preview = _preview(client, ngo_a, content, doctor_id).json()

    real_insert = ngo_service._insert_ngo_patient

    def flaky_insert(cur, ctx, normalized, **kwargs):
        if normalized["name"] == "Explodes Here":
            cur.execute("SELECT 1/0")  # real database error inside the row savepoint
        return real_insert(cur, ctx, normalized, **kwargs)

    monkeypatch.setattr(ngo_service, "_insert_ngo_patient", flaky_insert)
    result = client.post(
        "/api/ngo/patients/import/confirm", json={"import_id": preview["import_id"]}, headers=ngo_a["headers"]
    ).json()
    assert (result["inserted_count"], result["skipped_count"], result["failed_count"]) == (2, 0, 1)

    detail = client.get(f"/api/ngo/imports/{preview['import_id']}", headers=ngo_a["headers"]).json()
    statuses = {r["raw_data"]["name"]: r["status"] for r in detail["rows"]}
    assert statuses == {"Good One": "inserted", "Explodes Here": "failed", "Good Two": "inserted"}


def test_error_csv_escapes_formulas(client, ngo_a, doctor_id):
    content = _csv([["name", "phone"], ["=HYPERLINK(\"http://evil\")", "+919876543210"], ["Valid Person", _phone()]])
    preview = _preview(client, ngo_a, content, doctor_id).json()
    client.post("/api/ngo/patients/import/confirm", json={"import_id": preview["import_id"]}, headers=ngo_a["headers"])
    resp = client.get(f"/api/ngo/imports/{preview['import_id']}/errors", headers=ngo_a["headers"])
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    rows = list(csv.reader(io.StringIO(resp.text)))
    assert rows[0] == ["row_number", "status", "name", "phone", "errors"]
    assert len(rows) == 2
    assert rows[1][2].startswith("'=") and rows[1][3].startswith("'+")


def test_dashboard_uses_real_counts(client, ngo_a, doctor_id):
    _register(client, ngo_a, doctor_id)
    preview = _preview(client, ngo_a, _csv([["name", "phone"], ["Csv Person", _phone()]]), doctor_id).json()
    client.post("/api/ngo/patients/import/confirm", json={"import_id": preview["import_id"]}, headers=ngo_a["headers"])
    dash = client.get("/api/ngo/dashboard", headers=ngo_a["headers"]).json()
    assert (dash["total_patients"], dash["manual_patients"], dash["csv_patients"]) == (2, 1, 1)
    assert dash["imports"]["total"] == 1 and dash["imports"]["successful"] == 1
    assert len(dash["recent_registrations"]) == 2
    assert dash["upcoming_appointments"] == 0 and dash["follow_up_pending"] == 0


def test_patient_list_search_filters_pagination(client, ngo_a, doctor_id):
    phones = [_phone() for _ in range(5)]
    for i, phone in enumerate(phones):
        _register(client, ngo_a, doctor_id, name=f"Search Person {chr(65 + i)}", phone=phone)
    page1 = client.get("/api/ngo/patients", headers=ngo_a["headers"], params={"page_size": 2}).json()
    assert page1["total"] == 5 and page1["total_pages"] == 3 and len(page1["items"]) == 2
    by_phone = client.get("/api/ngo/patients", headers=ngo_a["headers"], params={"search": phones[2][-6:]}).json()
    assert [p["name"] for p in by_phone["items"]] == ["Search Person C"]
    by_name = client.get("/api/ngo/patients", headers=ngo_a["headers"], params={"search": "person b"}).json()
    assert by_name["total"] == 1
    wildcard = client.get("/api/ngo/patients", headers=ngo_a["headers"], params={"search": "%"}).json()
    assert wildcard["total"] == 0
    assert client.get("/api/ngo/patients", headers=ngo_a["headers"], params={"source": "csv"}).json()["total"] == 0
    assert client.get("/api/ngo/patients", headers=ngo_a["headers"], params={"follow_up": "none"}).json()["total"] == 5
    assert client.get("/api/ngo/patients", headers=ngo_a["headers"], params={"page_size": 500}).status_code == 422
