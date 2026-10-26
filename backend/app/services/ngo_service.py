from __future__ import annotations

"""
NGO portal service layer.

Organizations, memberships, server-side sessions, NGO patient registration
(manual + CSV import) and NGO audit events. Patients are written to the
existing ``patients`` table through ``postgres_service.create_patient``; NGO
provenance lives in ``ngo_patient_registrations`` so existing patient rows and
API responses are unchanged.
"""

import base64
import csv
import hashlib
import hmac
import io
import logging
import re
import secrets
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Json

import app.services.postgres_service as db
from app.core.config import settings
from app.services.blood_campaign_service import _normalize_phone

logger = logging.getLogger(__name__)

PATIENT_FIELDS = ("name", "phone", "dob", "mrn", "insurance", "notes", "doctor_id")
REQUIRED_CSV_FIELDS = ("name", "phone")
FIELD_MAX_LENGTHS = {"name": 200, "mrn": 64, "insurance": 200, "notes": 1000}

# Header aliases (after lower-casing and replacing spaces/hyphens with "_").
CSV_HEADER_ALIASES: dict[str, tuple[str, ...]] = {
    "name": ("name", "full_name", "patient_name", "fullname"),
    "phone": ("phone", "phone_number", "mobile", "mobile_number", "contact", "contact_number"),
    "dob": ("dob", "date_of_birth", "birth_date", "birthdate"),
    "mrn": ("mrn", "medical_record_number"),
    "insurance": ("insurance", "insurance_provider"),
    "notes": ("notes", "remarks", "comments"),
    "doctor_id": ("doctor_id", "assigned_doctor_id"),
}
CSV_TEMPLATE_HEADERS = ("name", "phone", "dob", "mrn", "insurance", "notes", "doctor_id")

_DOB_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y")
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
_PBKDF2_ITERATIONS = 600_000
_EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
_DARPAN_ID_RE = re.compile(r"[0-9]{5}")
_OTP_TTL_MINUTES = 10
_OTP_RESEND_SECONDS = 60
_OTP_MAX_ATTEMPTS = 5
# Verified against when the email is unknown so response timing does not
# reveal which NGO accounts exist.
_DUMMY_PASSWORD_HASH = (
    "pbkdf2_sha256$600000$AAAAAAAAAAAAAAAAAAAAAA==$AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
)


class NgoError(Exception):
    """Domain error mapped to an HTTP response by the NGO router."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        **extra: Any,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.extra = extra

    def as_detail(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, **self.extra}


@dataclass(frozen=True)
class NgoContext:
    account_id: str
    ngo_id: str
    ngo_name: str
    email: str
    username: str
    member_role: str


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------


@contextmanager
def _transaction():
    """A non-autocommit connection; commits on success, rolls back on error."""
    with psycopg.connect(db._database_url(), row_factory=dict_row) as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                yield conn, cur


def _lock_ngo(cur, ngo_id: str) -> None:
    # Serializes patient creation per NGO so concurrent registrations/imports
    # cannot race past duplicate checks.
    cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"ngo_patients:{ngo_id}",))


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _is_uuid(value: Any) -> bool:
    try:
        UUID(str(value))
        return True
    except Exception:
        return False


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
    return "pbkdf2_sha256${}${}${}".format(
        _PBKDF2_ITERATIONS,
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(digest).decode("ascii"),
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, iterations, salt_b64, digest_b64 = stored.split("$", 3)
        if scheme != "pbkdf2_sha256":
            return False
        expected = base64.b64decode(digest_b64)
        actual = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            base64.b64decode(salt_b64),
            int(iterations),
        )
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


def _phone_key(phone: str) -> str:
    digits = re.sub(r"\D", "", phone or "")
    return digits[-10:]


def _name_key(name: str) -> str:
    return " ".join((name or "").split()).casefold()


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def record_audit(
    ngo_id: str | None,
    account_id: str | None,
    action: str,
    entity_type: str | None = None,
    entity_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    *,
    cur=None,
) -> None:
    payload = {
        "ngo_id": ngo_id,
        "account_id": account_id,
        "action": action,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "metadata": metadata or {},
    }
    try:
        db._insert_row("ngo_audit_events", payload, cur=cur)
    except Exception:
        if cur is not None:
            raise
        logger.warning("Could not write NGO audit event action=%s", action)


# ---------------------------------------------------------------------------
# Organizations and accounts
# (NGO self-registration below; scripts/create_ngo_account.py for operators)
# ---------------------------------------------------------------------------


def create_ngo_organization(
    name: str,
    *,
    registration_number: str | None = None,
    contact_email: str | None = None,
    contact_phone: str | None = None,
    city: str | None = None,
) -> dict[str, Any]:
    clean_name = " ".join(name.split())
    if not clean_name:
        raise RuntimeError("NGO name is required")
    with db._cursor() as cur:
        cur.execute(
            "SELECT * FROM ngo_organizations WHERE lower(name) = lower(%s) LIMIT 1",
            (clean_name,),
        )
        existing = cur.fetchone()
    if existing:
        return existing
    return db._insert_row(
        "ngo_organizations",
        {
            "name": clean_name,
            "registration_number": registration_number,
            "contact_email": contact_email,
            "contact_phone": contact_phone,
            "city": city,
        },
    )


def _validate_new_account(email: str, password: str, member_role: str) -> str:
    if member_role not in {"admin", "staff"}:
        raise RuntimeError("member_role must be admin or staff")
    if len(password) < 8:
        raise RuntimeError("NGO passwords must be at least 8 characters")
    normalized_email = email.strip().lower()
    if not _EMAIL_RE.fullmatch(normalized_email):
        raise RuntimeError("Enter a valid email address")
    return normalized_email


def _create_ngo_user(
    cur,
    ngo_id: str,
    *,
    email: str,
    password: str,
    username: str,
    mobile: str,
    member_role: str,
) -> dict[str, Any]:
    cur.execute(
        "SELECT id FROM user_accounts WHERE email = %s AND role = 'ngo' LIMIT 1",
        (email,),
    )
    if cur.fetchone():
        raise RuntimeError("An NGO account already exists for this email")
    account = db._insert_row(
        "user_accounts",
        {
            "role": "ngo",
            "email": email,
            "username": username.strip(),
            "mobile": mobile.strip(),
            "password": hash_password(password),
            "is_active": True,
        },
        cur=cur,
    )
    db._insert_row(
        "ngo_memberships",
        {"ngo_id": ngo_id, "account_id": account["id"], "member_role": member_role},
        cur=cur,
    )
    return account


def create_ngo_user(
    ngo_id: str,
    *,
    email: str,
    password: str,
    username: str,
    mobile: str = "",
    member_role: str = "staff",
) -> dict[str, Any]:
    normalized_email = _validate_new_account(email, password, member_role)
    with _transaction() as (_conn, cur):
        cur.execute("SELECT id FROM ngo_organizations WHERE id = %s", (ngo_id,))
        if not cur.fetchone():
            raise RuntimeError("NGO organization not found")
        account = _create_ngo_user(
            cur,
            ngo_id,
            email=normalized_email,
            password=password,
            username=username,
            mobile=mobile,
            member_role=member_role,
        )
    return {
        "account_id": str(account["id"]),
        "email": normalized_email,
        "ngo_id": str(ngo_id),
        "member_role": member_role,
    }


# ---------------------------------------------------------------------------
# NGO self-registration (email OTP, separate from doctor/patient OTPs)
# ---------------------------------------------------------------------------


def create_registration_otp(email: str) -> str:
    """Store a hashed registration OTP and return the plain code to email."""
    normalized_email = email.strip().lower()
    if not _EMAIL_RE.fullmatch(normalized_email):
        raise NgoError(
            422, "validation_error", "Enter a valid email address",
            field_errors={"email": "Enter a valid email address"},
        )
    with db._cursor() as cur:
        cur.execute(
            "SELECT 1 FROM user_accounts WHERE email = %s AND role = 'ngo' LIMIT 1",
            (normalized_email,),
        )
        if cur.fetchone():
            raise NgoError(
                409, "account_exists", "An NGO account already exists for this email. Please log in.",
                field_errors={"email": "Already registered"},
            )
        cur.execute(
            """
            SELECT 1 FROM ngo_email_otps
            WHERE email = %s AND purpose = 'register'
              AND created_at > now() - (%s || ' seconds')::interval
            LIMIT 1
            """,
            (normalized_email, str(_OTP_RESEND_SECONDS)),
        )
        if cur.fetchone():
            raise NgoError(429, "otp_rate_limited", "Please wait a minute before requesting another code")
        code = f"{secrets.randbelow(1_000_000):06d}"
        cur.execute(
            """
            UPDATE ngo_email_otps SET used_at = now()
            WHERE email = %s AND purpose = 'register' AND used_at IS NULL
            """,
            (normalized_email,),
        )
        cur.execute(
            """
            INSERT INTO ngo_email_otps (email, purpose, code_hash, expires_at)
            VALUES (%s, 'register', %s, now() + (%s || ' minutes')::interval)
            """,
            (normalized_email, _hash_token(code), str(_OTP_TTL_MINUTES)),
        )
    return code


def _consume_registration_otp(cur, email: str, code: str) -> bool:
    cur.execute(
        """
        SELECT id, code_hash, attempts FROM ngo_email_otps
        WHERE email = %s AND purpose = 'register' AND used_at IS NULL AND expires_at > now()
        ORDER BY created_at DESC
        LIMIT 1
        FOR UPDATE
        """,
        (email,),
    )
    row = cur.fetchone()
    if not row or row["attempts"] >= _OTP_MAX_ATTEMPTS:
        return False
    if not hmac.compare_digest(row["code_hash"], _hash_token(code.strip())):
        cur.execute("UPDATE ngo_email_otps SET attempts = attempts + 1 WHERE id = %s", (row["id"],))
        return False
    cur.execute("UPDATE ngo_email_otps SET used_at = now() WHERE id = %s", (row["id"],))
    return True


def _ensure_ngo_unique(cur, name: str, darpan_id: str) -> None:
    cur.execute("SELECT 1 FROM ngo_organizations WHERE lower(name) = lower(%s)", (name,))
    if cur.fetchone():
        raise NgoError(
            409, "ngo_exists", "An NGO with this name is already registered",
            field_errors={"ngo_name": "Already registered"},
        )
    cur.execute("SELECT 1 FROM ngo_organizations WHERE darpan_id = %s", (darpan_id,))
    if cur.fetchone():
        raise NgoError(
            409, "darpan_id_exists", "An NGO with this Darpan ID is already registered",
            field_errors={"darpan_id": "Already registered"},
        )


def register_ngo(
    *,
    ngo_name: str,
    city: str | None,
    darpan_id: str,
    contact_phone: str | None,
    admin_name: str,
    email: str,
    mobile: str,
    password: str,
    otp_code: str,
) -> dict[str, Any]:
    """Create an NGO organization with its first admin account, then sign in."""
    clean_name = " ".join(ngo_name.split())
    field_errors: dict[str, str] = {}
    if len(clean_name) < 3:
        field_errors["ngo_name"] = "NGO name must be at least 3 characters"
    if len(admin_name.strip()) < 2:
        field_errors["admin_name"] = "Your name must be at least 2 characters"
    darpan_id = (darpan_id or "").strip()
    if not _DARPAN_ID_RE.fullmatch(darpan_id):
        field_errors["darpan_id"] = "Darpan ID must be exactly 5 digits"
    try:
        normalized_email = _validate_new_account(email, password, "admin")
    except RuntimeError as exc:
        key = "password" if "password" in str(exc).lower() else "email"
        field_errors[key] = str(exc)
        normalized_email = email.strip().lower()
    if mobile.strip():
        try:
            mobile = normalize_patient_phone(mobile)
        except ValueError as exc:
            field_errors["mobile"] = str(exc)
    if field_errors:
        raise NgoError(422, "validation_error", "Please correct the highlighted fields", field_errors=field_errors)

    # Reject already-registered NGOs before spending the OTP (re-checked below).
    with db._cursor() as cur:
        _ensure_ngo_unique(cur, clean_name, darpan_id)

    # The OTP is consumed in its own transaction so failed attempts are counted
    # even when the rest of the registration is rejected.
    with _transaction() as (_conn, cur):
        otp_ok = _consume_registration_otp(cur, normalized_email, otp_code)
    if not otp_ok:
        raise NgoError(
            401, "invalid_otp", "Invalid or expired verification code",
            field_errors={"otp_code": "Invalid or expired code"},
        )

    try:
        with _transaction() as (_conn, cur):
            _ensure_ngo_unique(cur, clean_name, darpan_id)
            org = db._insert_row(
                "ngo_organizations",
                {
                    "name": clean_name,
                    "darpan_id": darpan_id,
                    "contact_email": normalized_email,
                    "contact_phone": (contact_phone or "").strip() or None,
                    "city": (city or "").strip() or None,
                },
                cur=cur,
            )
            try:
                account = _create_ngo_user(
                    cur,
                    str(org["id"]),
                    email=normalized_email,
                    password=password,
                    username=admin_name,
                    mobile=mobile,
                    member_role="admin",
                )
            except RuntimeError as exc:
                raise NgoError(
                    409, "account_exists", str(exc), field_errors={"email": "Already registered"}
                ) from exc
            record_audit(str(org["id"]), str(account["id"]), "ngo_registered", "ngo", str(org["id"]), cur=cur)
    except psycopg.errors.UniqueViolation as exc:
        raise NgoError(409, "ngo_exists", "This NGO or email is already registered") from exc

    return login_ngo_account(normalized_email, password)


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------


def login_ngo_account(email: str, password: str) -> dict[str, Any]:
    normalized_email = email.strip().lower()
    with db._cursor() as cur:
        cur.execute(
            """
            SELECT ua.id AS account_id, ua.email, ua.username, ua.mobile, ua.password,
                   m.member_role, o.id AS ngo_id, o.name AS ngo_name
            FROM user_accounts ua
            JOIN ngo_memberships m ON m.account_id = ua.id AND m.is_active = TRUE
            JOIN ngo_organizations o ON o.id = m.ngo_id AND o.is_active = TRUE
            WHERE ua.email = %s AND ua.role = 'ngo' AND ua.is_active = TRUE
            LIMIT 1
            """,
            (normalized_email,),
        )
        row = cur.fetchone()

    stored_hash = (row.get("password") if row else None) or _DUMMY_PASSWORD_HASH
    if not verify_password(password, stored_hash) or not row:
        record_audit(
            str(row["ngo_id"]) if row else None,
            str(row["account_id"]) if row else None,
            "login_failed",
        )
        raise RuntimeError("Invalid email or password")

    token = secrets.token_urlsafe(32)
    expires_at = _utc_now() + timedelta(hours=settings.ngo_session_ttl_hours)
    db._insert_row(
        "ngo_sessions",
        {
            "token_hash": _hash_token(token),
            "account_id": row["account_id"],
            "ngo_id": row["ngo_id"],
            "expires_at": expires_at,
        },
    )
    record_audit(str(row["ngo_id"]), str(row["account_id"]), "login")

    account_id = str(row["account_id"])
    return {
        "token": token,
        "expires_at": expires_at.isoformat(),
        "user": {
            "sub": account_id,
            "name": row.get("username") or row["email"],
            "email": row["email"],
            "username": row.get("username"),
            "mobile": row.get("mobile"),
            "role": "ngo",
            "account_id": account_id,
            "ngo_id": str(row["ngo_id"]),
            "ngo_name": row["ngo_name"],
            "ngo_member_role": row["member_role"],
        },
    }


def get_ngo_context(token: str) -> NgoContext | None:
    if not token:
        return None
    with db._cursor() as cur:
        cur.execute(
            """
            SELECT s.account_id, s.ngo_id, o.name AS ngo_name, ua.email, ua.username,
                   m.member_role
            FROM ngo_sessions s
            JOIN user_accounts ua ON ua.id = s.account_id
                 AND ua.role = 'ngo' AND ua.is_active = TRUE
            JOIN ngo_memberships m ON m.account_id = s.account_id
                 AND m.ngo_id = s.ngo_id AND m.is_active = TRUE
            JOIN ngo_organizations o ON o.id = s.ngo_id AND o.is_active = TRUE
            WHERE s.token_hash = %s
              AND s.revoked_at IS NULL
              AND s.expires_at > now()
            LIMIT 1
            """,
            (_hash_token(token),),
        )
        row = cur.fetchone()
    if not row:
        return None
    return NgoContext(
        account_id=str(row["account_id"]),
        ngo_id=str(row["ngo_id"]),
        ngo_name=row["ngo_name"],
        email=row["email"],
        username=row.get("username") or "",
        member_role=row["member_role"],
    )


def revoke_ngo_session(token: str) -> None:
    with db._cursor() as cur:
        cur.execute(
            "UPDATE ngo_sessions SET revoked_at = now() WHERE token_hash = %s AND revoked_at IS NULL",
            (_hash_token(token),),
        )


# ---------------------------------------------------------------------------
# Validation and duplicate detection (shared by manual + CSV registration)
# ---------------------------------------------------------------------------


def _parse_dob(raw: str) -> date:
    for fmt in _DOB_FORMATS:
        try:
            parsed = datetime.strptime(raw, fmt).date()
            break
        except ValueError:
            continue
    else:
        raise ValueError("Date of birth must be YYYY-MM-DD or DD/MM/YYYY")
    if parsed > date.today():
        raise ValueError("Date of birth cannot be in the future")
    if parsed.year < 1900:
        raise ValueError("Date of birth must be after 1900")
    return parsed


def normalize_patient_phone(raw: Any) -> str:
    """Existing CareSync normalization (+91 + 10 digits) without silent truncation."""
    digits = re.sub(r"\D", "", str(raw or ""))
    valid_shapes = (
        len(digits) == 10
        or (len(digits) == 11 and digits.startswith("0"))
        or (len(digits) == 12 and digits.startswith("91"))
    )
    if not valid_shapes:
        raise ValueError("Phone number must be a 10-digit number, optionally with +91 or 0 prefix")
    return _normalize_phone(raw)


def validate_patient_fields(
    data: dict[str, Any],
    *,
    default_doctor_id: str | None = None,
    active_doctor_ids: set[str] | None = None,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Return (normalized_payload, field_errors)."""
    errors: dict[str, str] = {}
    out: dict[str, Any] = {}

    def text(field: str) -> str:
        value = data.get(field)
        return " ".join(str(value).split()) if value is not None else ""

    name = text("name")
    if not name:
        errors["name"] = "Full name is required"
    elif len(name) < 2:
        errors["name"] = "Full name must be at least 2 characters"
    elif len(name) > FIELD_MAX_LENGTHS["name"]:
        errors["name"] = f"Full name must be at most {FIELD_MAX_LENGTHS['name']} characters"
    elif not name[0].isalpha():
        errors["name"] = "Full name must start with a letter"
    else:
        out["name"] = name

    phone_raw = text("phone")
    if not phone_raw:
        errors["phone"] = "Phone number is required"
    else:
        try:
            out["phone"] = normalize_patient_phone(phone_raw)
        except ValueError as exc:
            errors["phone"] = str(exc)

    dob_raw = text("dob")
    if dob_raw:
        try:
            out["dob"] = _parse_dob(dob_raw).isoformat()
        except ValueError as exc:
            errors["dob"] = str(exc)
    else:
        out["dob"] = None

    for field in ("mrn", "insurance"):
        value = text(field)
        if len(value) > FIELD_MAX_LENGTHS[field]:
            errors[field] = f"Must be at most {FIELD_MAX_LENGTHS[field]} characters"
        out[field] = value or None

    notes_value = str(data.get("notes") or "").strip()
    if len(notes_value) > FIELD_MAX_LENGTHS["notes"]:
        errors["notes"] = f"Must be at most {FIELD_MAX_LENGTHS['notes']} characters"
    out["notes"] = notes_value or None

    doctor_id = text("doctor_id") or (default_doctor_id or "")
    if not doctor_id:
        errors["doctor_id"] = "An assigned doctor is required"
    elif not _is_uuid(doctor_id):
        errors["doctor_id"] = "Assigned doctor ID is not valid"
    elif active_doctor_ids is not None and doctor_id.lower() not in active_doctor_ids:
        errors["doctor_id"] = "Assigned doctor was not found or is inactive"
    else:
        out["doctor_id"] = doctor_id.lower()

    return out, errors


def _active_doctor_ids() -> set[str]:
    with db._cursor() as cur:
        cur.execute("SELECT id FROM doctors WHERE active = TRUE")
        return {str(r["id"]).lower() for r in cur.fetchall()}


def find_duplicate(cur, ngo_id: str, normalized: dict[str, Any]) -> dict[str, Any] | None:
    """
    Duplicate rules (phone alone is never treated as identity):
      * duplicate: same NGO, same phone (last 10 digits), same name, and the
        dates of birth match or one is missing -> always skipped.
      * review: same NGO and same phone with a different name, same NGO and
        same name + DOB with a different phone, or a patient elsewhere in
        CareSync with the same name + phone -> needs explicit approval.
    Matches outside the NGO never expose the other record.
    """
    phone_key = _phone_key(normalized["phone"])
    name_key = _name_key(normalized["name"])
    dob = normalized.get("dob")

    cur.execute(
        """
        SELECT p.id, p.name, p.phone, p.dob
        FROM patients p
        JOIN ngo_patient_registrations r ON r.patient_id = p.id
        WHERE r.ngo_id = %s
          AND (
                right(regexp_replace(p.phone, '\\D', '', 'g'), 10) = %s
             OR lower(regexp_replace(trim(p.name), '\\s+', ' ', 'g')) = %s
          )
        """,
        (ngo_id, phone_key, name_key),
    )
    review_reason = None
    for row in cur.fetchall():
        same_phone = _phone_key(row["phone"]) == phone_key
        same_name = _name_key(row["name"]) == name_key
        dob_compatible = not dob or not row.get("dob") or row.get("dob") == dob
        if same_phone and same_name and dob_compatible:
            return {
                "kind": "duplicate",
                "patient_id": str(row["id"]),
                "reason": "Patient with the same name, phone and date of birth is already registered by your NGO",
            }
        if same_phone and not same_name:
            review_reason = review_reason or (
                "Phone number is already registered by your NGO to a patient with a different name"
            )
        elif same_name and dob and row.get("dob") == dob and not same_phone:
            review_reason = review_reason or (
                "A patient with the same name and date of birth but a different phone is registered by your NGO"
            )
        elif same_phone and same_name:
            review_reason = review_reason or (
                "Patient with the same name and phone but a different date of birth is registered by your NGO"
            )

    if review_reason:
        return {"kind": "review", "reason": review_reason}

    cur.execute(
        """
        SELECT 1
        FROM patients p
        WHERE right(regexp_replace(p.phone, '\\D', '', 'g'), 10) = %s
          AND lower(regexp_replace(trim(p.name), '\\s+', ' ', 'g')) = %s
          AND NOT EXISTS (
                SELECT 1 FROM ngo_patient_registrations r
                WHERE r.patient_id = p.id AND r.ngo_id = %s
          )
        LIMIT 1
        """,
        (phone_key, name_key, ngo_id),
    )
    if cur.fetchone():
        return {
            "kind": "review",
            "reason": "A patient with the same name and phone may already exist in CareSync",
        }
    return None


def _insert_ngo_patient(
    cur,
    ctx: NgoContext,
    normalized: dict[str, Any],
    *,
    source: str,
    import_id: str | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    patient_payload = {
        "doctor_id": normalized["doctor_id"],
        "name": normalized["name"],
        "phone": normalized["phone"],
        "dob": normalized.get("dob"),
        "mrn": normalized.get("mrn"),
        "insurance": normalized.get("insurance"),
        "notes": normalized.get("notes"),
    }
    patient = db.create_patient(patient_payload, cur=cur)
    db._insert_row(
        "ngo_patient_registrations",
        {
            "patient_id": patient["id"],
            "ngo_id": ctx.ngo_id,
            "source": source,
            "import_id": import_id,
            "registered_by_account_id": ctx.account_id,
            "idempotency_key": idempotency_key,
        },
        cur=cur,
    )
    return patient


# ---------------------------------------------------------------------------
# Manual registration
# ---------------------------------------------------------------------------


def register_manual_patient(
    ctx: NgoContext,
    data: dict[str, Any],
    *,
    idempotency_key: str | None = None,
    confirm_possible_duplicate: bool = False,
) -> dict[str, Any]:
    normalized, errors = validate_patient_fields(data, active_doctor_ids=_active_doctor_ids())
    if errors:
        raise NgoError(422, "validation_error", "Please correct the highlighted fields", field_errors=errors)

    with _transaction() as (_conn, cur):
        _lock_ngo(cur, ctx.ngo_id)

        if idempotency_key:
            cur.execute(
                """
                SELECT patient_id FROM ngo_patient_registrations
                WHERE ngo_id = %s AND idempotency_key = %s
                """,
                (ctx.ngo_id, idempotency_key),
            )
            existing = cur.fetchone()
            if existing:
                return {"patient_id": str(existing["patient_id"]), "replayed": True}

        duplicate = find_duplicate(cur, ctx.ngo_id, normalized)
        if duplicate and duplicate["kind"] == "duplicate":
            raise NgoError(
                409,
                "duplicate_patient",
                duplicate["reason"],
                patient_id=duplicate["patient_id"],
            )
        if duplicate and duplicate["kind"] == "review" and not confirm_possible_duplicate:
            raise NgoError(409, "possible_duplicate", duplicate["reason"], requires_confirmation=True)

        patient = _insert_ngo_patient(
            cur, ctx, normalized, source="manual", idempotency_key=idempotency_key
        )
        record_audit(
            ctx.ngo_id,
            ctx.account_id,
            "patient_registered",
            "patient",
            str(patient["id"]),
            {"source": "manual", "possible_duplicate_confirmed": bool(duplicate)},
            cur=cur,
        )
    return {"patient_id": str(patient["id"]), "replayed": False}


# ---------------------------------------------------------------------------
# Patient listing / details / dashboard
# ---------------------------------------------------------------------------

_FOLLOW_UP_PENDING_SQL = """
    EXISTS (
        SELECT 1 FROM follow_up_jobs f
        WHERE f.patient_id = p.id
          AND f.status NOT IN ('completed', 'failed', 'cancelled', 'skipped')
    )
"""

_NEXT_APPOINTMENT_SQL = """
    (
        SELECT min(s.slot_start)
        FROM appointments a
        JOIN availability_slots s ON s.id = a.slot_id
        WHERE a.patient_id = p.id
          AND a.status IN ('booked', 'confirmed')
          AND s.slot_start > now()
    )
"""


def list_ngo_patients(
    ngo_id: str,
    *,
    search: str | None = None,
    source: str | None = None,
    follow_up: str | None = None,
    registered_from: date | None = None,
    registered_to: date | None = None,
    import_id: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    where = ["r.ngo_id = %s"]
    params: list[Any] = [ngo_id]

    if search:
        term = search.strip()
        digits = re.sub(r"\D", "", term)
        clauses = ["p.name ILIKE %s ESCAPE '\\'"]
        params.append(f"%{_escape_like(term)}%")
        if len(digits) >= 3:
            clauses.append("regexp_replace(p.phone, '\\D', '', 'g') LIKE %s")
            params.append(f"%{digits}%")
        where.append("(" + " OR ".join(clauses) + ")")
    if source in {"manual", "csv"}:
        where.append("r.source = %s")
        params.append(source)
    if follow_up == "pending":
        where.append(_FOLLOW_UP_PENDING_SQL)
    elif follow_up == "none":
        where.append("NOT " + _FOLLOW_UP_PENDING_SQL)
    if registered_from:
        where.append("r.created_at >= %s")
        params.append(registered_from)
    if registered_to:
        where.append("r.created_at < %s")
        params.append(registered_to + timedelta(days=1))
    if import_id:
        where.append("r.import_id = %s")
        params.append(import_id)

    where_sql = " AND ".join(where)
    offset = (page - 1) * page_size

    with db._cursor() as cur:
        cur.execute(
            f"""
            SELECT count(*)::int AS total
            FROM ngo_patient_registrations r
            JOIN patients p ON p.id = r.patient_id
            WHERE {where_sql}
            """,
            params,
        )
        total = cur.fetchone()["total"]
        cur.execute(
            f"""
            SELECT p.id, p.name, p.phone, p.dob, p.doctor_id,
                   d.name AS doctor_name,
                   r.source, r.import_id, r.created_at AS registered_at,
                   {_FOLLOW_UP_PENDING_SQL} AS follow_up_pending,
                   {_NEXT_APPOINTMENT_SQL} AS next_appointment_at
            FROM ngo_patient_registrations r
            JOIN patients p ON p.id = r.patient_id
            LEFT JOIN doctors d ON d.id::text = p.doctor_id
            WHERE {where_sql}
            ORDER BY r.created_at DESC, p.id
            LIMIT %s OFFSET %s
            """,
            [*params, page_size, offset],
        )
        rows = [db._json_safe(r) for r in cur.fetchall()]

    return {
        "items": rows,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": max(1, -(-total // page_size)),
    }


def get_ngo_patient(ctx: NgoContext, patient_id: str) -> dict[str, Any]:
    if not _is_uuid(patient_id):
        raise NgoError(404, "not_found", "Patient not found")
    with db._cursor() as cur:
        cur.execute(
            f"""
            SELECT p.id, p.name, p.phone, p.dob, p.mrn, p.insurance, p.notes,
                   p.doctor_id, d.name AS doctor_name, d.specialty AS doctor_specialty,
                   r.source, r.import_id, r.created_at AS registered_at,
                   ua.username AS registered_by,
                   {_FOLLOW_UP_PENDING_SQL} AS follow_up_pending
            FROM ngo_patient_registrations r
            JOIN patients p ON p.id = r.patient_id
            LEFT JOIN doctors d ON d.id::text = p.doctor_id
            LEFT JOIN user_accounts ua ON ua.id = r.registered_by_account_id
            WHERE r.ngo_id = %s AND r.patient_id = %s
            """,
            (ctx.ngo_id, patient_id),
        )
        patient = cur.fetchone()
        if not patient:
            record_audit(ctx.ngo_id, ctx.account_id, "patient_access_denied", "patient", patient_id)
            raise NgoError(404, "not_found", "Patient not found")

        cur.execute(
            """
            SELECT a.id, a.status, a.consultation_type, s.slot_start, s.slot_end,
                   d.name AS doctor_name
            FROM appointments a
            JOIN availability_slots s ON s.id = a.slot_id
            LEFT JOIN doctors d ON d.id = a.doctor_id
            WHERE a.patient_id = %s
            ORDER BY s.slot_start DESC
            LIMIT 20
            """,
            (patient_id,),
        )
        appointments = list(cur.fetchall())
        cur.execute(
            """
            SELECT status, scheduled_for, attempt_count, created_at
            FROM follow_up_jobs
            WHERE patient_id = %s
            ORDER BY created_at DESC
            LIMIT 10
            """,
            (patient_id,),
        )
        follow_ups = list(cur.fetchall())

    record_audit(ctx.ngo_id, ctx.account_id, "patient_viewed", "patient", patient_id)
    return db._json_safe({**patient, "appointments": appointments, "follow_ups": follow_ups})


def get_dashboard(ngo_id: str) -> dict[str, Any]:
    with db._cursor() as cur:
        cur.execute(
            f"""
            SELECT
                count(*)::int AS total_patients,
                count(*) FILTER (WHERE r.source = 'manual')::int AS manual_patients,
                count(*) FILTER (WHERE r.source = 'csv')::int AS csv_patients,
                count(*) FILTER (WHERE {_FOLLOW_UP_PENDING_SQL})::int AS follow_up_pending
            FROM ngo_patient_registrations r
            JOIN patients p ON p.id = r.patient_id
            WHERE r.ngo_id = %s
            """,
            (ngo_id,),
        )
        counts = cur.fetchone()
        cur.execute(
            """
            SELECT a.id, a.status, s.slot_start, p.id AS patient_id, p.name AS patient_name,
                   d.name AS doctor_name
            FROM appointments a
            JOIN availability_slots s ON s.id = a.slot_id
            JOIN ngo_patient_registrations r ON r.patient_id = a.patient_id AND r.ngo_id = %s
            JOIN patients p ON p.id = a.patient_id
            LEFT JOIN doctors d ON d.id = a.doctor_id
            WHERE a.status IN ('booked', 'confirmed') AND s.slot_start > now()
            ORDER BY s.slot_start
            LIMIT 10
            """,
            (ngo_id,),
        )
        upcoming = list(cur.fetchall())
        cur.execute(
            """
            SELECT count(*)::int AS n
            FROM appointments a
            JOIN availability_slots s ON s.id = a.slot_id
            JOIN ngo_patient_registrations r ON r.patient_id = a.patient_id AND r.ngo_id = %s
            WHERE a.status IN ('booked', 'confirmed') AND s.slot_start > now()
            """,
            (ngo_id,),
        )
        upcoming_count = cur.fetchone()["n"]
        cur.execute(
            """
            SELECT p.id, p.name, r.source, r.created_at AS registered_at
            FROM ngo_patient_registrations r
            JOIN patients p ON p.id = r.patient_id
            WHERE r.ngo_id = %s
            ORDER BY r.created_at DESC
            LIMIT 8
            """,
            (ngo_id,),
        )
        recent = list(cur.fetchall())
        cur.execute(
            """
            SELECT count(*)::int AS total,
                   count(*) FILTER (WHERE status = 'completed' AND failed_count = 0)::int AS successful,
                   count(*) FILTER (WHERE status = 'failed' OR failed_count > 0)::int AS with_failures
            FROM ngo_patient_imports
            WHERE ngo_id = %s AND status <> 'previewed'
            """,
            (ngo_id,),
        )
        import_counts = cur.fetchone()

    return db._json_safe(
        {
            **counts,
            "upcoming_appointments": upcoming_count,
            "upcoming": upcoming,
            "recent_registrations": recent,
            "imports": import_counts,
            "recent_imports": list_imports(ngo_id, page=1, page_size=5)["items"],
        }
    )


# ---------------------------------------------------------------------------
# CSV import
# ---------------------------------------------------------------------------


def _normalize_header(header: str) -> str:
    return re.sub(r"[\s\-]+", "_", header.strip().lstrip("﻿").lower())


def _auto_mapping(headers: list[str]) -> dict[str, str]:
    normalized = {_normalize_header(h): h for h in headers}
    mapping: dict[str, str] = {}
    for field, aliases in CSV_HEADER_ALIASES.items():
        for alias in aliases:
            if alias in normalized:
                mapping[field] = normalized[alias]
                break
    return mapping


def parse_csv(content: bytes, mapping_override: dict[str, str] | None = None) -> dict[str, Any]:
    if not content.strip():
        raise NgoError(400, "empty_file", "The uploaded file is empty")
    if b"\x00" in content:
        raise NgoError(400, "malformed_csv", "The file does not look like a text CSV file")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise NgoError(
            400, "invalid_encoding", "The file must be UTF-8 encoded (save as 'CSV UTF-8')"
        ) from exc

    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = ","

    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True)
    try:
        all_rows = list(reader)
    except csv.Error as exc:
        raise NgoError(400, "malformed_csv", f"Could not parse CSV: {exc}") from exc

    header_index = next((i for i, r in enumerate(all_rows) if any(c.strip() for c in r)), None)
    if header_index is None:
        raise NgoError(400, "empty_file", "The uploaded file has no header row")
    headers = [h.strip().lstrip("﻿") for h in all_rows[header_index]]
    if any(not h for h in headers):
        raise NgoError(400, "malformed_csv", "Every column must have a header")
    lowered = [h.lower() for h in headers]
    if len(set(lowered)) != len(lowered):
        raise NgoError(400, "malformed_csv", "Column headers must be unique")

    if mapping_override:
        mapping = {}
        for field, header in mapping_override.items():
            if not header:
                continue
            if field not in PATIENT_FIELDS:
                raise NgoError(400, "invalid_mapping", f"Unknown patient field '{field}'")
            if header not in headers:
                raise NgoError(400, "invalid_mapping", f"Column '{header}' is not in the file")
            mapping[field] = header
        if len(set(mapping.values())) != len(mapping):
            raise NgoError(400, "invalid_mapping", "Each column can be mapped to only one field")
    else:
        mapping = _auto_mapping(headers)

    missing = [f for f in REQUIRED_CSV_FIELDS if f not in mapping]
    if missing:
        raise NgoError(
            422,
            "missing_required_columns",
            "Required columns are missing: " + ", ".join(missing),
            headers=headers,
            mapping=mapping,
            missing=missing,
        )

    data_rows: list[dict[str, Any]] = []
    empty_rows = 0
    header_pos = {h: i for i, h in enumerate(headers)}
    for offset, cells in enumerate(all_rows[header_index + 1 :]):
        line_number = header_index + offset + 2  # 1-based, header counted
        if not any(c.strip() for c in cells):
            empty_rows += 1
            continue
        raw = {field: cells[header_pos[h]].strip() if header_pos[h] < len(cells) else "" for field, h in mapping.items()}
        extra_values = len(cells) > len(headers) and any(c.strip() for c in cells[len(headers) :])
        data_rows.append({"row_number": line_number, "raw": raw, "extra_values": extra_values})

    if not data_rows:
        raise NgoError(400, "empty_file", "The file has a header row but no patient rows")
    if len(data_rows) > settings.ngo_csv_max_rows:
        raise NgoError(
            413,
            "too_many_rows",
            f"The file has {len(data_rows)} rows; the limit is {settings.ngo_csv_max_rows}",
        )

    return {
        "headers": headers,
        "mapping": mapping,
        "ignored_columns": [h for h in headers if h not in mapping.values()],
        "rows": data_rows,
        "empty_rows_skipped": empty_rows,
    }


def preview_import(
    ctx: NgoContext,
    *,
    file_name: str,
    content: bytes,
    default_doctor_id: str | None,
    mapping_override: dict[str, str] | None = None,
) -> dict[str, Any]:
    active_doctors = _active_doctor_ids()
    if default_doctor_id and (
        not _is_uuid(default_doctor_id) or default_doctor_id.lower() not in active_doctors
    ):
        raise NgoError(
            422,
            "validation_error",
            "Default doctor was not found or is inactive",
            field_errors={"default_doctor_id": "Select an active doctor"},
        )

    parsed = parse_csv(content, mapping_override)
    counts = {"valid": 0, "invalid": 0, "duplicate": 0, "review": 0}
    seen_in_file: dict[tuple[str, str], int] = {}
    row_records: list[dict[str, Any]] = []

    with _transaction() as (_conn, cur):
        for row in parsed["rows"]:
            normalized, field_errors = validate_patient_fields(
                row["raw"],
                default_doctor_id=default_doctor_id,
                active_doctor_ids=active_doctors,
            )
            errors = [{"field": f, "message": m} for f, m in field_errors.items()]
            if row["extra_values"]:
                errors.append({"field": None, "message": "Row has more values than there are columns"})

            status = "valid"
            if errors:
                status = "invalid"
            else:
                key = (_phone_key(normalized["phone"]), _name_key(normalized["name"]))
                if key in seen_in_file:
                    status = "duplicate"
                    errors.append(
                        {"field": None, "message": f"Duplicate of row {seen_in_file[key]} in this file"}
                    )
                else:
                    seen_in_file[key] = row["row_number"]
                    dup = find_duplicate(cur, ctx.ngo_id, normalized)
                    if dup:
                        status = dup["kind"]
                        errors.append({"field": None, "message": dup["reason"]})
            counts[status] += 1
            row_records.append(
                {
                    "row_number": row["row_number"],
                    "raw_data": row["raw"],
                    "normalized": normalized if status != "invalid" else None,
                    "status": status,
                    "errors": errors,
                }
            )

        import_row = db._insert_row(
            "ngo_patient_imports",
            {
                "ngo_id": ctx.ngo_id,
                "created_by_account_id": ctx.account_id,
                "file_name": (file_name or "upload.csv")[:255],
                "file_size_bytes": len(content),
                "default_doctor_id": default_doctor_id,
                "column_mapping": parsed["mapping"],
                "status": "previewed",
                "total_rows": len(row_records),
                "valid_rows": counts["valid"],
                "invalid_rows": counts["invalid"],
                "duplicate_rows": counts["duplicate"],
                "review_rows": counts["review"],
            },
            cur=cur,
        )
        import_id = str(import_row["id"])
        cur.executemany(
            """
            INSERT INTO ngo_patient_import_rows
                (import_id, row_number, raw_data, normalized, status, errors)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            [
                (
                    import_id,
                    r["row_number"],
                    Json(r["raw_data"]),
                    Json(r["normalized"]) if r["normalized"] is not None else None,
                    r["status"],
                    Json(r["errors"]),
                )
                for r in row_records
            ],
        )
        record_audit(
            ctx.ngo_id,
            ctx.account_id,
            "import_previewed",
            "import",
            import_id,
            {"total_rows": len(row_records), **counts},
            cur=cur,
        )

    return {
        "import_id": import_id,
        "file_name": import_row["file_name"],
        "headers": parsed["headers"],
        "mapping": parsed["mapping"],
        "ignored_columns": parsed["ignored_columns"],
        "empty_rows_skipped": parsed["empty_rows_skipped"],
        "total_rows": len(row_records),
        "valid_rows": counts["valid"],
        "invalid_rows": counts["invalid"],
        "duplicate_rows": counts["duplicate"],
        "review_rows": counts["review"],
        "rows": db._json_safe(row_records),
    }


def _import_summary(import_row: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "id", "file_name", "status", "total_rows", "valid_rows", "invalid_rows",
        "duplicate_rows", "review_rows", "inserted_count", "skipped_count",
        "failed_count", "created_at", "confirmed_at", "completed_at",
    )
    summary = {k: import_row.get(k) for k in keys}
    summary["created_by"] = import_row.get("created_by")
    return db._json_safe(summary)


def confirm_import(
    ctx: NgoContext,
    import_id: str,
    *,
    approved_review_rows: list[int] | None = None,
) -> dict[str, Any]:
    if not _is_uuid(import_id):
        raise NgoError(404, "not_found", "Import not found")
    approved = set(approved_review_rows or [])

    with _transaction() as (conn, cur):
        cur.execute(
            "SELECT * FROM ngo_patient_imports WHERE id = %s AND ngo_id = %s FOR UPDATE",
            (import_id, ctx.ngo_id),
        )
        import_row = cur.fetchone()
        if not import_row:
            raise NgoError(404, "not_found", "Import not found")
        if import_row["status"] in {"completed", "failed"}:
            return {**_import_summary(import_row), "already_processed": True}
        expires_at = import_row["created_at"] + timedelta(hours=settings.ngo_import_preview_ttl_hours)
        if expires_at < _utc_now():
            raise NgoError(409, "preview_expired", "This preview has expired; upload the file again")

        _lock_ngo(cur, ctx.ngo_id)
        cur.execute(
            """
            SELECT id, row_number, status, normalized
            FROM ngo_patient_import_rows
            WHERE import_id = %s
            ORDER BY row_number
            """,
            (import_id,),
        )
        rows = list(cur.fetchall())

        inserted = skipped = failed = 0
        for row in rows:
            status = row["status"]
            if status == "invalid":
                failed += 1
                continue
            if status == "duplicate" or (status == "review" and row["row_number"] not in approved):
                skipped += 1
                cur.execute(
                    "UPDATE ngo_patient_import_rows SET status = 'skipped', updated_at = now() WHERE id = %s",
                    (row["id"],),
                )
                continue

            normalized = row["normalized"] or {}
            try:
                with conn.transaction():  # savepoint per row
                    # Re-check: records may have been added since the preview.
                    dup = find_duplicate(cur, ctx.ngo_id, normalized)
                    if dup and (dup["kind"] == "duplicate" or status != "review"):
                        cur.execute(
                            """
                            UPDATE ngo_patient_import_rows
                            SET status = 'skipped', errors = errors || %s::jsonb, updated_at = now()
                            WHERE id = %s
                            """,
                            (Json([{"field": None, "message": dup["reason"]}]), row["id"]),
                        )
                        skipped += 1
                        continue
                    patient = _insert_ngo_patient(
                        cur, ctx, normalized, source="csv", import_id=import_id
                    )
                    cur.execute(
                        """
                        UPDATE ngo_patient_import_rows
                        SET status = 'inserted', patient_id = %s, updated_at = now()
                        WHERE id = %s
                        """,
                        (patient["id"], row["id"]),
                    )
                    inserted += 1
            except Exception:
                logger.exception("NGO import row failed import_id=%s row=%s", import_id, row["row_number"])
                cur.execute(
                    """
                    UPDATE ngo_patient_import_rows
                    SET status = 'failed', errors = errors || %s::jsonb, updated_at = now()
                    WHERE id = %s
                    """,
                    (Json([{"field": None, "message": "Could not save this row"}]), row["id"]),
                )
                failed += 1

        cur.execute(
            """
            UPDATE ngo_patient_imports
            SET status = 'completed', inserted_count = %s, skipped_count = %s,
                failed_count = %s, confirmed_by_account_id = %s,
                confirmed_at = now(), completed_at = now(), updated_at = now()
            WHERE id = %s
            RETURNING *
            """,
            (inserted, skipped, failed, ctx.account_id, import_id),
        )
        import_row = cur.fetchone()
        record_audit(
            ctx.ngo_id,
            ctx.account_id,
            "import_confirmed",
            "import",
            import_id,
            {
                "inserted": inserted,
                "skipped": skipped,
                "failed": failed,
                "approved_review_rows": len(approved),
            },
            cur=cur,
        )

    return {**_import_summary(import_row), "already_processed": False}


def list_imports(ngo_id: str, *, page: int = 1, page_size: int = 20) -> dict[str, Any]:
    with db._cursor() as cur:
        cur.execute(
            "SELECT count(*)::int AS total FROM ngo_patient_imports WHERE ngo_id = %s",
            (ngo_id,),
        )
        total = cur.fetchone()["total"]
        cur.execute(
            """
            SELECT i.*, ua.username AS created_by
            FROM ngo_patient_imports i
            LEFT JOIN user_accounts ua ON ua.id = i.created_by_account_id
            WHERE i.ngo_id = %s
            ORDER BY i.created_at DESC
            LIMIT %s OFFSET %s
            """,
            (ngo_id, page_size, (page - 1) * page_size),
        )
        items = [_import_summary(r) for r in cur.fetchall()]
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": max(1, -(-total // page_size)),
    }


def get_import(ctx: NgoContext, import_id: str) -> dict[str, Any]:
    if not _is_uuid(import_id):
        raise NgoError(404, "not_found", "Import not found")
    with db._cursor() as cur:
        cur.execute(
            """
            SELECT i.*, ua.username AS created_by
            FROM ngo_patient_imports i
            LEFT JOIN user_accounts ua ON ua.id = i.created_by_account_id
            WHERE i.id = %s AND i.ngo_id = %s
            """,
            (import_id, ctx.ngo_id),
        )
        import_row = cur.fetchone()
        if not import_row:
            raise NgoError(404, "not_found", "Import not found")
        cur.execute(
            """
            SELECT row_number, status, raw_data, errors, patient_id
            FROM ngo_patient_import_rows
            WHERE import_id = %s
            ORDER BY row_number
            """,
            (import_id,),
        )
        rows = list(cur.fetchall())
    return {
        **_import_summary(import_row),
        "column_mapping": import_row.get("column_mapping") or {},
        "rows": db._json_safe(rows),
    }


def _csv_safe(value: Any) -> str:
    text = "" if value is None else str(value)
    if text.startswith(_FORMULA_PREFIXES):
        return "'" + text
    return text


def build_error_csv(ctx: NgoContext, import_id: str) -> tuple[str, str]:
    detail = get_import(ctx, import_id)
    rejected = [r for r in detail["rows"] if r["status"] not in {"valid", "inserted"}]
    fields = [f for f in PATIENT_FIELDS if f in (detail.get("column_mapping") or {})]

    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["row_number", "status", *fields, "errors"])
    for r in rejected:
        raw = r.get("raw_data") or {}
        messages = "; ".join(e.get("message", "") for e in (r.get("errors") or []))
        writer.writerow(
            [r["row_number"], r["status"], *[_csv_safe(raw.get(f)) for f in fields], _csv_safe(messages)]
        )
    record_audit(ctx.ngo_id, ctx.account_id, "import_errors_downloaded", "import", import_id)
    safe_name = re.sub(r"[^A-Za-z0-9_.-]", "_", (detail.get("file_name") or "import").rsplit(".", 1)[0])
    return out.getvalue(), f"{safe_name}_errors.csv"


def csv_template() -> str:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(CSV_TEMPLATE_HEADERS)
    return out.getvalue()


def list_audit_events(ngo_id: str, limit: int = 50) -> list[dict[str, Any]]:
    with db._cursor() as cur:
        cur.execute(
            """
            SELECT e.id, e.action, e.entity_type, e.entity_id, e.metadata, e.created_at,
                   ua.username AS actor
            FROM ngo_audit_events e
            LEFT JOIN user_accounts ua ON ua.id = e.account_id
            WHERE e.ngo_id = %s
            ORDER BY e.created_at DESC
            LIMIT %s
            """,
            (ngo_id, limit),
        )
        return [db._json_safe(r) for r in cur.fetchall()]
