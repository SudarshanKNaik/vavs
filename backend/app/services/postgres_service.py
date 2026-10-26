from __future__ import annotations

"""
PostgreSQL service layer.

This module replaces Supabase client calls with direct PostgreSQL access.
"""

import logging
import secrets
import time as _time_module
from dataclasses import dataclass
from functools import lru_cache
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Json

from app.core.config import settings

logger = logging.getLogger(__name__)


def _database_url() -> str:
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL must be set in backend/.env")
    return settings.database_url


@contextmanager
def _cursor():
    with psycopg.connect(
        _database_url(), autocommit=True, row_factory=dict_row
    ) as conn:
        with conn.cursor() as cur:
            yield cur


def _first_row(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    return rows[0] if rows else None


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso_datetime(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def _slot_is_open(slot: dict[str, Any], now_dt: datetime) -> bool:
    status = slot.get("status")
    if status == "available":
        return True
    if status == "reserved":
        reserved_until = _parse_iso_datetime(slot.get("reserved_until"))
        return reserved_until is not None and reserved_until < now_dt
    return False


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


def _to_db_value(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return Json(_json_safe(value))
    return value


def _as_text_id(value: Any) -> str:
    return str(value).strip()


def _same_id(left: Any, right: Any) -> bool:
    if left is None or right is None:
        return False
    return _as_text_id(left) == _as_text_id(right)


@lru_cache(maxsize=256)
def _table_has_column(table_name: str, column_name: str) -> bool:
    with _cursor() as cur:
        cur.execute(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = %s
              AND column_name = %s
            LIMIT 1
            """,
            (table_name, column_name),
        )
        return cur.fetchone() is not None


def _clinic_timezone():
    try:
        return ZoneInfo(settings.clinic_timezone)
    except (ZoneInfoNotFoundError, ValueError):
        return timezone.utc


CLINIC_TZ = _clinic_timezone()


# ---------------------------------------------------------------------------
# Per-doctor schedule rules (editable on the Manage Availability page)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DoctorSchedule:
    day_start: time
    day_end: time
    break_start: time | None
    break_end: time | None
    slot_minutes: int
    # Python weekdays: 0 = Monday ... 6 = Sunday.
    working_days: frozenset[int]
    window_days: int

    def is_working_day(self, day: date) -> bool:
        return day.weekday() in self.working_days

    def in_break(self, local_time: time) -> bool:
        return bool(
            self.break_start and self.break_end and self.break_start <= local_time < self.break_end
        )

    def is_inside_hours(self, dt: datetime) -> bool:
        local = dt.astimezone(CLINIC_TZ)
        if not self.is_working_day(local.date()):
            return False
        if local.time() < self.day_start or local.time() >= self.day_end:
            return False
        return not self.in_break(local.time())

    def slots_for_day(self, day: date) -> list[tuple[datetime, datetime]]:
        """(start, end) in UTC for every slot on a clinic-local day."""
        if not self.is_working_day(day):
            return []
        slots: list[tuple[datetime, datetime]] = []
        step = timedelta(minutes=self.slot_minutes)
        current = datetime.combine(day, self.day_start, tzinfo=CLINIC_TZ)
        day_end = datetime.combine(day, self.day_end, tzinfo=CLINIC_TZ)
        break_start = datetime.combine(day, self.break_start, tzinfo=CLINIC_TZ) if self.break_start else None
        break_end = datetime.combine(day, self.break_end, tzinfo=CLINIC_TZ) if self.break_end else None
        while current + step <= day_end:
            slot_end = current + step
            overlaps_break = break_start and break_end and current < break_end and break_start < slot_end
            if overlaps_break:
                current = max(current + step, break_end)  # resume right after the break
                continue
            slots.append((current.astimezone(timezone.utc), slot_end.astimezone(timezone.utc)))
            current = slot_end
        return slots

    def next_working_day(self, day: date) -> date:
        candidate = day + timedelta(days=1)
        for _ in range(7):
            if self.is_working_day(candidate):
                return candidate
            candidate += timedelta(days=1)
        return candidate

    def to_dict(self) -> dict[str, Any]:
        fmt = lambda t: t.strftime("%H:%M") if t else None  # noqa: E731
        return {
            "day_start": fmt(self.day_start),
            "day_end": fmt(self.day_end),
            "break_start": fmt(self.break_start),
            "break_end": fmt(self.break_end),
            "slot_minutes": self.slot_minutes,
            "working_days": sorted(d + 1 for d in self.working_days),  # ISO 1..7
            "window_days": self.window_days,
        }


# Used until a doctor saves their own rules (the old fixed clinic schedule).
DEFAULT_SCHEDULE = DoctorSchedule(
    day_start=time(10, 30),
    day_end=time(16, 30),
    break_start=time(13, 30),
    break_end=time(14, 30),
    slot_minutes=30,
    working_days=frozenset(range(6)),  # Monday to Saturday
    window_days=30,
)

_SCHEDULE_CACHE_SECONDS = 30
_schedule_cache: dict[str, tuple[float, DoctorSchedule]] = {}


def get_doctor_schedule(doctor_id: str) -> DoctorSchedule:
    key = str(doctor_id)
    cached = _schedule_cache.get(key)
    if cached and _time_module.monotonic() - cached[0] < _SCHEDULE_CACHE_SECONDS:
        return cached[1]

    schedule = DEFAULT_SCHEDULE
    if _table_exists("doctor_schedule_settings"):
        with _cursor() as cur:
            cur.execute("SELECT * FROM doctor_schedule_settings WHERE doctor_id = %s", (key,))
            row = cur.fetchone()
        if row:
            schedule = DoctorSchedule(
                day_start=row["day_start"],
                day_end=row["day_end"],
                break_start=row["break_start"],
                break_end=row["break_end"],
                slot_minutes=int(row["slot_minutes"]),
                working_days=frozenset(int(d) - 1 for d in row["working_days"]),
                window_days=int(row["window_days"]),
            )
    _schedule_cache[key] = (_time_module.monotonic(), schedule)
    return schedule


def _table_exists(table_name: str) -> bool:
    with _cursor() as cur:
        cur.execute("SELECT to_regclass(%s) IS NOT NULL AS ok", (f"public.{table_name}",))
        return bool(cur.fetchone()["ok"])


def _ensure_doctor_rolling_slots(doctor_id: str, from_day: date | None = None) -> None:
    schedule = get_doctor_schedule(doctor_id)
    base_day = from_day or datetime.now(CLINIC_TZ).date()
    target_days = [
        base_day + timedelta(days=offset) for offset in range(schedule.window_days)
    ]

    # One statement for the whole window: with a month of slots (~260 per
    # doctor) a query per slot made every slot lookup slow.
    starts: list[datetime] = []
    ends: list[datetime] = []
    for day in target_days:
        for slot_start, slot_end in schedule.slots_for_day(day):
            starts.append(slot_start)
            ends.append(slot_end)
    if not starts:
        return

    with _cursor() as cur:
        cur.execute(
            """
            INSERT INTO availability_slots (
                doctor_id,
                slot_start,
                slot_end,
                status,
                created_at,
                updated_at
            )
            SELECT %s, s.slot_start, s.slot_end, 'available', now(), now()
            FROM unnest(%s::timestamptz[], %s::timestamptz[]) AS s(slot_start, slot_end)
            -- Never overlap an existing slot: after the doctor changes slot
            -- length or hours, booked/removed slots from the old rules stay put.
            WHERE NOT EXISTS (
                SELECT 1 FROM availability_slots o
                WHERE o.doctor_id = %s
                  AND o.slot_start < s.slot_end
                  AND o.slot_end > s.slot_start
            )
            ON CONFLICT (doctor_id, slot_start, slot_end) DO NOTHING
            """,
            (doctor_id, starts, ends, doctor_id),
        )


def save_doctor_schedule(doctor_id: str, values: dict[str, Any]) -> dict[str, Any]:
    """Save a doctor's schedule rules and rebuild their upcoming slots.

    Unbooked future slots that don't fit the new rules are removed and new
    ones are generated. Booked appointments are never touched; the result
    reports how many now fall outside the new hours so the doctor can decide.
    """
    def _t(value: Any) -> time | None:
        if value in (None, ""):
            return None
        return value if isinstance(value, time) else time.fromisoformat(str(value))

    new = DoctorSchedule(
        day_start=_t(values["day_start"]),
        day_end=_t(values["day_end"]),
        break_start=_t(values.get("break_start")),
        break_end=_t(values.get("break_end")),
        slot_minutes=int(values["slot_minutes"]),
        working_days=frozenset(int(d) - 1 for d in values["working_days"]),
        window_days=int(values["window_days"]),
    )
    if not (new.day_start and new.day_end) or new.day_start >= new.day_end:
        raise RuntimeError("The day must end after it starts")
    if (new.break_start is None) != (new.break_end is None):
        raise RuntimeError("Set both break start and break end, or neither")
    if new.break_start and not (new.day_start <= new.break_start < new.break_end <= new.day_end):
        raise RuntimeError("The break must be inside working hours")
    if not 10 <= new.slot_minutes <= 120:
        raise RuntimeError("Slot length must be between 10 and 120 minutes")
    if not new.working_days or not new.working_days <= set(range(7)):
        raise RuntimeError("Choose at least one working day")
    if not 1 <= new.window_days <= 90:
        raise RuntimeError("Booking window must be between 1 and 90 days")
    if not any(new.slots_for_day(d) for d in (date(2026, 1, 5) + timedelta(days=i) for i in range(7))):
        raise RuntimeError("These hours leave no room for a single slot")

    with _cursor() as cur:
        cur.execute(
            """
            INSERT INTO doctor_schedule_settings (
                doctor_id, day_start, day_end, break_start, break_end,
                slot_minutes, working_days, window_days, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s::smallint[], %s, now())
            ON CONFLICT (doctor_id) DO UPDATE SET
                day_start = EXCLUDED.day_start,
                day_end = EXCLUDED.day_end,
                break_start = EXCLUDED.break_start,
                break_end = EXCLUDED.break_end,
                slot_minutes = EXCLUDED.slot_minutes,
                working_days = EXCLUDED.working_days,
                window_days = EXCLUDED.window_days,
                updated_at = now()
            """,
            (
                doctor_id, new.day_start, new.day_end, new.break_start, new.break_end,
                new.slot_minutes, sorted(d + 1 for d in new.working_days), new.window_days,
            ),
        )
    _schedule_cache.pop(str(doctor_id), None)

    # Which future slots the new rules produce.
    today = datetime.now(CLINIC_TZ).date()
    wanted = {
        pair
        for offset in range(new.window_days)
        for pair in new.slots_for_day(today + timedelta(days=offset))
    }

    with _cursor() as cur:
        cur.execute(
            """
            SELECT s.id, s.slot_start, s.slot_end, s.status,
                   EXISTS (SELECT 1 FROM appointments a WHERE a.slot_id = s.id) AS has_appointment,
                   EXISTS (
                       SELECT 1 FROM appointments a
                       WHERE a.slot_id = s.id AND a.status IN ('booked', 'confirmed')
                   ) AS has_active_appointment
            FROM availability_slots s
            WHERE s.doctor_id = %s AND s.slot_start > now()
            """,
            (doctor_id,),
        )
        future = list(cur.fetchall())

    to_remove = [
        row["id"]
        for row in future
        if (row["slot_start"], row["slot_end"]) not in wanted
        and not row["has_appointment"]
        # Live holds (a patient on a call right now) are left alone; they expire.
        and row["status"] in {"available", "cancelled"}
    ]
    booked_outside = [
        row for row in future
        if row["has_active_appointment"] and not new.is_inside_hours(row["slot_start"])
    ]

    removed = 0
    if to_remove:
        with _cursor() as cur:
            cur.execute(
                "DELETE FROM availability_slots WHERE id = ANY(%s::uuid[]) RETURNING id",
                (to_remove,),
            )
            removed = len(cur.fetchall())

    with _cursor() as cur:
        cur.execute(
            "SELECT count(*) AS n FROM availability_slots WHERE doctor_id = %s AND slot_start > now()",
            (doctor_id,),
        )
        before = int(cur.fetchone()["n"])
    _ensure_doctor_rolling_slots(doctor_id)
    with _cursor() as cur:
        cur.execute(
            "SELECT count(*) AS n FROM availability_slots WHERE doctor_id = %s AND slot_start > now()",
            (doctor_id,),
        )
        after = int(cur.fetchone()["n"])

    return {
        "schedule": new.to_dict(),
        "slots_removed": removed,
        "slots_added": after - before,
        "booked_outside_new_hours": len(booked_outside),
    }


def _find_next_rebooking_slot(
    doctor_id: str, preferred_start: datetime, after_day: date
) -> dict[str, Any] | None:
    schedule = get_doctor_schedule(doctor_id)
    preferred_local_time = (
        preferred_start.astimezone(CLINIC_TZ).time()
        if schedule.is_inside_hours(preferred_start)
        else schedule.day_start
    )
    search_day = after_day
    for _ in range(14):
        if not schedule.is_working_day(search_day):
            search_day += timedelta(days=1)
            continue

        _ensure_doctor_rolling_slots(doctor_id, search_day)
        preferred_dt = datetime.combine(search_day, preferred_local_time, tzinfo=CLINIC_TZ)
        day_start = datetime.combine(search_day, time(0, 0), tzinfo=CLINIC_TZ)

        with _cursor() as cur:
            cur.execute(
                """
                SELECT id, doctor_id, slot_start, slot_end, status
                FROM availability_slots
                WHERE doctor_id = %s
                  AND slot_start >= %s AND slot_start < %s
                  AND status = 'available'
                ORDER BY ABS(EXTRACT(EPOCH FROM (slot_start - %s))), slot_start
                LIMIT 1
                """,
                (doctor_id, day_start, day_start + timedelta(days=1), preferred_dt),
            )
            row = cur.fetchone()
        if row:
            return row

        search_day += timedelta(days=1)

    return None


def _insert_row(table: str, payload: dict[str, Any], *, cur=None) -> dict[str, Any]:
    """Insert one row. Pass ``cur`` to run inside a caller-managed transaction."""
    if not payload:
        raise RuntimeError(f"Cannot insert empty payload into {table}")

    columns = list(payload.keys())
    values = [_to_db_value(payload[col]) for col in columns]

    query = sql.SQL("INSERT INTO {} ({}) VALUES ({}) RETURNING *").format(
        sql.Identifier(table),
        sql.SQL(", ").join(sql.Identifier(c) for c in columns),
        sql.SQL(", ").join(sql.Placeholder() for _ in columns),
    )

    if cur is not None:
        cur.execute(query, values)
        row = cur.fetchone()
    else:
        with _cursor() as own_cur:
            own_cur.execute(query, values)
            row = own_cur.fetchone()

    if not row:
        raise RuntimeError(f"Insert failed for table {table}")
    return row


def _update_rows(
    table: str,
    payload: dict[str, Any],
    where: dict[str, Any],
    *,
    require_match: bool = True,
) -> dict[str, Any]:
    if not payload:
        raise RuntimeError("No fields to update")
    if not where:
        raise RuntimeError("Unsafe update without WHERE clause")

    set_cols = list(payload.keys())
    where_cols = list(where.keys())

    query = sql.SQL("UPDATE {} SET {} WHERE {} RETURNING *").format(
        sql.Identifier(table),
        sql.SQL(", ").join(
            sql.SQL("{} = {}").format(sql.Identifier(c), sql.Placeholder())
            for c in set_cols
        ),
        sql.SQL(" AND ").join(
            sql.SQL("{} = {}").format(sql.Identifier(c), sql.Placeholder())
            for c in where_cols
        ),
    )

    values = [_to_db_value(payload[c]) for c in set_cols] + [
        _to_db_value(where[c]) for c in where_cols
    ]

    with _cursor() as cur:
        cur.execute(query, values)
        row = cur.fetchone()

    if require_match and not row:
        raise RuntimeError(f"No row updated in {table}")

    return row or {}


def _delete_rows(table: str, where: dict[str, Any]) -> None:
    if not where:
        raise RuntimeError("Unsafe delete without WHERE clause")

    where_cols = list(where.keys())
    query = sql.SQL("DELETE FROM {} WHERE {}").format(
        sql.Identifier(table),
        sql.SQL(" AND ").join(
            sql.SQL("{} = {}").format(sql.Identifier(c), sql.Placeholder())
            for c in where_cols
        ),
    )

    with _cursor() as cur:
        cur.execute(query, [_to_db_value(where[c]) for c in where_cols])


def _first_active_doctor_id() -> str | None:
    with _cursor() as cur:
        cur.execute(
            "SELECT id FROM doctors WHERE active = TRUE ORDER BY created_at LIMIT 1"
        )
        row = cur.fetchone()
    return row["id"] if row else None


def _build_login_payload(account: dict[str, Any]) -> dict[str, Any]:
    role = account["role"]
    auth_user_id = _as_text_id(account["id"])

    if role == "doctor":
        doctor = get_doctor_by_auth_user_id(auth_user_id)
        if not doctor:
            doctor = _insert_row(
                "doctors",
                {
                    "auth_user_id": auth_user_id,
                    "name": account.get("username") or account["email"],
                    "specialty": "General Physician",
                    "language": "English",
                    "consultation_type": "video",
                    "fee": 500,
                    "rating_avg": 0,
                    "rating_count": 0,
                    "active": True,
                    "is_available": False,
                },
            )

        return {
            "token": secrets.token_urlsafe(24),
            "user": {
                "sub": doctor["id"],
                "name": doctor.get("name") or account.get("username") or "Doctor",
                "email": account["email"],
                "username": account.get("username"),
                "mobile": account.get("mobile"),
                "role": "doctor",
                "account_id": auth_user_id,
                "doctor_id": doctor["id"],
            },
        }

    patient = get_patient_by_auth_user_id(auth_user_id)
    if not patient:
        doctor_id = _first_active_doctor_id()
        if not doctor_id:
            raise RuntimeError("No doctor available to link patient account")

        created_patient = _insert_row(
            "patients",
            {
                "doctor_id": doctor_id,
                "name": account.get("username") or account["email"],
                "phone": account.get("mobile") or "",
                "notes": "Created from local auth",
            },
        )

        _insert_row(
            "patient_accounts",
            {
                "auth_user_id": auth_user_id,
                "patient_id": created_patient["id"],
                "email": account["email"],
            },
        )

        patient = {
            **created_patient,
            "auth_user_id": auth_user_id,
            "email": account["email"],
        }

    return {
        "token": secrets.token_urlsafe(24),
        "user": {
            "sub": account["id"],
            "name": patient.get("name") or account.get("username") or "Patient",
            "email": account["email"],
            "username": account.get("username"),
            "mobile": account.get("mobile"),
            "role": "patient",
            "account_id": auth_user_id,
            "patient_id": patient["id"],
            "doctor_id": patient.get("doctor_id"),
        },
    }


# ---------------------------------------------------------------------------
# Health helper
# ---------------------------------------------------------------------------


def ping_db() -> bool:
    try:
        with _cursor() as cur:
            cur.execute("SELECT 1 AS ok")
            row = cur.fetchone()
        return bool(row and row.get("ok") == 1)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------


def register_user_account(
    role: str,
    email: str,
    password: str,
    username: str,
    mobile: str,
) -> dict[str, Any]:
    if role not in {"doctor", "patient"}:
        raise RuntimeError("Role must be either doctor or patient")

    normalized_email = email.strip().lower()
    with _cursor() as cur:
        cur.execute(
            """
            SELECT id
            FROM user_accounts
            WHERE email = %s AND role = %s
            LIMIT 1
            """,
            (normalized_email, role),
        )
        existing = cur.fetchone()
    if existing:
        raise RuntimeError("An account already exists for this email and role")

    account = _insert_row(
        "user_accounts",
        {
            "role": role,
            "email": normalized_email,
            "username": username.strip(),
            "mobile": mobile.strip(),
            "password": password,
            "is_active": True,
        },
    )

    return _build_login_payload(account)


def login_user_account(role: str, email: str, password: str) -> dict[str, Any]:
    if role not in {"doctor", "patient"}:
        raise RuntimeError("Role must be either doctor or patient")

    normalized_email = email.strip().lower()
    with _cursor() as cur:
        cur.execute(
            """
            SELECT *
            FROM user_accounts
            WHERE email = %s AND role = %s AND is_active = TRUE
            LIMIT 1
            """,
            (normalized_email, role),
        )
        account = cur.fetchone()

    if not account or account.get("password") != password:
        raise RuntimeError("Invalid email or password")

    return _build_login_payload(account)


def save_email_otp(
    role: str,
    email: str,
    purpose: str,
    otp_code: str,
    expires_minutes: int = 10,
) -> None:
    normalized_email = email.strip().lower()

    with _cursor() as cur:
        cur.execute(
            """
            DELETE FROM email_otp_codes
            WHERE role = %s AND email = %s AND purpose = %s AND used_at IS NULL
            """,
            (role, normalized_email, purpose),
        )
        cur.execute(
            """
            INSERT INTO email_otp_codes (role, email, purpose, otp_code, expires_at)
            VALUES (%s, %s, %s, %s, now() + (%s || ' minutes')::interval)
            """,
            (role, normalized_email, purpose, otp_code, str(expires_minutes)),
        )


def verify_email_otp(role: str, email: str, purpose: str, otp_code: str) -> bool:
    normalized_email = email.strip().lower()

    with _cursor() as cur:
        cur.execute(
            """
            SELECT id
            FROM email_otp_codes
            WHERE role = %s
              AND email = %s
              AND purpose = %s
              AND otp_code = %s
              AND used_at IS NULL
              AND expires_at > now()
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (role, normalized_email, purpose, otp_code),
        )
        row = cur.fetchone()

        if not row:
            return False

        cur.execute(
            "UPDATE email_otp_codes SET used_at = now() WHERE id = %s",
            (row["id"],),
        )
        return True


# ---------------------------------------------------------------------------
# Workflow helpers
# ---------------------------------------------------------------------------


def list_workflows(
    doctor_id: str | None = None, status: str | None = None
) -> list[dict[str, Any]]:
    sql_text = "SELECT * FROM workflows"
    where: list[str] = []
    params: list[Any] = []

    if doctor_id:
        where.append("doctor_id = %s")
        params.append(doctor_id)
    if status:
        where.append("status = %s")
        params.append(status)

    if where:
        sql_text += " WHERE " + " AND ".join(where)
    sql_text += " ORDER BY created_at DESC"

    with _cursor() as cur:
        cur.execute(sql_text, params)
        return list(cur.fetchall())


# ---------------------------------------------------------------------------
# Doctor directory + availability helpers
# ---------------------------------------------------------------------------


def get_doctor(doctor_id: str) -> dict[str, Any] | None:
    try:
        UUID(str(doctor_id))
    except Exception:
        return None

    with _cursor() as cur:
        cur.execute("SELECT * FROM doctors WHERE id = %s LIMIT 1", (doctor_id,))
        return cur.fetchone()


def get_doctor_by_auth_user_id(auth_user_id: Any) -> dict[str, Any] | None:
    auth_user_id_text = _as_text_id(auth_user_id)
    with _cursor() as cur:
        cur.execute(
            "SELECT * FROM doctors WHERE auth_user_id = %s LIMIT 1",
            (auth_user_id_text,),
        )
        return cur.fetchone()


def _get_user_account_by_id(account_id: Any) -> dict[str, Any] | None:
    account_id_text = _as_text_id(account_id)
    try:
        UUID(account_id_text)
    except Exception:
        return None

    with _cursor() as cur:
        cur.execute("SELECT * FROM user_accounts WHERE id = %s LIMIT 1", (account_id_text,))
        return cur.fetchone()


def _ensure_doctor_for_auth_user_id(auth_user_id: Any) -> dict[str, Any] | None:
    auth_user_id_text = _as_text_id(auth_user_id)
    doctor = get_doctor_by_auth_user_id(auth_user_id_text)
    if doctor:
        return doctor

    account = _get_user_account_by_id(auth_user_id_text)
    if not account or account.get("role") != "doctor":
        return None

    return _insert_row(
        "doctors",
        {
            "auth_user_id": auth_user_id_text,
            "name": account.get("username") or account.get("email") or "Doctor",
            "specialty": "General Physician",
            "language": "English",
            "consultation_type": "video",
            "fee": 500,
            "rating_avg": 0,
            "rating_count": 0,
            "active": True,
            "is_available": False,
        },
    )


def resolve_doctor(doctor_identifier: str) -> dict[str, Any] | None:
    doctor = get_doctor(doctor_identifier)
    if doctor:
        return doctor

    return _ensure_doctor_for_auth_user_id(doctor_identifier)


def get_doctor_availability_settings(doctor_id: str) -> dict[str, Any]:
    doctor = get_doctor(doctor_id)
    if not doctor:
        raise RuntimeError("Doctor not found")

    today_utc = datetime.now(timezone.utc).date()
    with _cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*)::int AS pending_count
            FROM appointments a
            JOIN availability_slots s ON s.id = a.slot_id
            WHERE a.doctor_id = %s
              AND a.status IN ('booked', 'confirmed')
              AND s.slot_start::date = %s
            """,
            (doctor["id"], today_utc),
        )
        row = cur.fetchone() or {"pending_count": 0}

    return {
        "doctor_id": _as_text_id(doctor["id"]),
        "is_available": bool(doctor.get("is_available", True)),
        "pending_today_appointments": int(row.get("pending_count", 0)),
    }


def set_doctor_availability(
    doctor_id: str,
    *,
    is_available: bool,
    confirm_reschedule_today: bool = False,
) -> dict[str, Any]:
    doctor = get_doctor(doctor_id)
    if not doctor:
        raise RuntimeError("Doctor not found")

    resolved_doctor_id = doctor["id"]
    today_utc = datetime.now(timezone.utc).date()

    with _cursor() as cur:
        cur.execute(
            """
            SELECT
                a.id AS appointment_id,
                a.slot_id,
                a.status,
                a.notes,
                s.slot_start,
                s.slot_end
            FROM appointments a
            JOIN availability_slots s ON s.id = a.slot_id
            WHERE a.doctor_id = %s
              AND a.status IN ('booked', 'confirmed')
              AND s.slot_start::date = %s
            ORDER BY s.slot_start
            """,
            (resolved_doctor_id, today_utc),
        )
        today_appointments = list(cur.fetchall())

    if not is_available and today_appointments and not confirm_reschedule_today:
        raise RuntimeError(
            f"CONFIRM_REQUIRED:{len(today_appointments)} appointment(s) today will be moved to next working day"
        )

    moved_count = 0
    if not is_available and today_appointments:
        next_working_day = get_doctor_schedule(resolved_doctor_id).next_working_day(today_utc)
        for appointment in today_appointments:
            target_slot = _find_next_rebooking_slot(
                resolved_doctor_id,
                appointment["slot_start"],
                next_working_day,
            )
            if not target_slot:
                raise RuntimeError("Could not find a target slot for rescheduling")

            with _cursor() as cur:
                cur.execute(
                    """
                    UPDATE availability_slots
                    SET status = 'cancelled',
                        reserved_by = NULL,
                        reserved_until = NULL,
                        updated_at = now()
                    WHERE id = %s
                    """,
                    (appointment["slot_id"],),
                )
                cur.execute(
                    """
                    UPDATE availability_slots
                    SET status = 'booked',
                        reserved_by = NULL,
                        reserved_until = NULL,
                        updated_at = now()
                    WHERE id = %s
                    """,
                    (target_slot["id"],),
                )
                cur.execute(
                    """
                    UPDATE appointments
                    SET slot_id = %s,
                        status = 'booked',
                        notes = TRIM(BOTH FROM CONCAT(COALESCE(notes, ''), %s)),
                        updated_at = now()
                    WHERE id = %s
                    """,
                    (
                        target_slot["id"],
                        f"\nAuto-rescheduled because doctor marked unavailable on {today_utc.isoformat()}.",
                        appointment["appointment_id"],
                    ),
                )
            moved_count += 1
            _calendar_sync(appointment["appointment_id"])
            _patient_notice(
                appointment["appointment_id"], "moved", previous_start=appointment["slot_start"]
            )

        with _cursor() as cur:
            cur.execute(
                """
                UPDATE availability_slots
                SET status = 'cancelled',
                    reserved_by = NULL,
                    reserved_until = NULL,
                    updated_at = now()
                WHERE doctor_id = %s
                  AND slot_start::date = %s
                  AND status IN ('available', 'reserved')
                """,
                (resolved_doctor_id, today_utc),
            )

    _update_rows(
        "doctors",
        {"is_available": is_available, "updated_at": _utc_now_iso()},
        {"id": resolved_doctor_id},
    )

    if is_available:
        _ensure_doctor_rolling_slots(resolved_doctor_id)

    return {
        "doctor_id": _as_text_id(resolved_doctor_id),
        "is_available": is_available,
        "rescheduled_appointments": moved_count,
    }


def list_doctors(
    specialty: str | None = None,
    language: str | None = None,
    consultation_type: str | None = None,
    available_now: bool | None = None,
) -> list[dict[str, Any]]:
    sql_text = "SELECT * FROM doctors WHERE active = TRUE"
    params: list[Any] = []

    if specialty:
        sql_text += " AND specialty ILIKE %s"
        params.append(f"%{specialty}%")
    if language:
        sql_text += " AND language ILIKE %s"
        params.append(f"%{language}%")
    if consultation_type:
        sql_text += " AND consultation_type = %s"
        params.append(consultation_type)

    sql_text += " ORDER BY name"

    with _cursor() as cur:
        cur.execute(sql_text, params)
        doctors = list(cur.fetchall())

    if not doctors:
        return []

    for doctor in doctors:
        if bool(doctor.get("is_available", True)):
            _ensure_doctor_rolling_slots(doctor["id"])

    doctor_ids = [d["id"] for d in doctors]
    now_dt = datetime.now(timezone.utc)

    with _cursor() as cur:
        cur.execute(
            """
            SELECT doctor_id, slot_start, slot_end, status, reserved_until
            FROM availability_slots
            WHERE doctor_id = ANY(%s::uuid[])
              AND slot_end >= %s
            ORDER BY slot_start
            """,
            (doctor_ids, now_dt),
        )
        slot_rows = list(cur.fetchall())

    per_doctor: dict[str, list[dict[str, Any]]] = {}
    for row in slot_rows:
        if _slot_is_open(row, now_dt):
            per_doctor.setdefault(row["doctor_id"], []).append(row)

    result: list[dict[str, Any]] = []
    for doctor in doctors:
        is_toggle_available = bool(doctor.get("is_available", True))
        slots = per_doctor.get(doctor["id"], [])
        is_available_now = (
            any(
                (
                    s.get("slot_start") is not None
                    and s.get("slot_end") is not None
                    and s["slot_start"] <= now_dt <= s["slot_end"]
                )
                for s in slots
            )
            if is_toggle_available
            else False
        )
        next_slot_start = (
            slots[0]["slot_start"] if (slots and is_toggle_available) else None
        )

        if available_now is not None and is_available_now != available_now:
            continue

        result.append(
            {
                **doctor,
                "id": _as_text_id(doctor["id"]),
                "is_available": is_toggle_available,
                "available_now": is_available_now,
                "next_slot_start": next_slot_start.isoformat()
                if isinstance(next_slot_start, datetime)
                else next_slot_start,
            }
        )

    return result


def list_doctor_availability(doctor_id: str) -> list[dict[str, Any]]:
    doctor = get_doctor(doctor_id)
    if not doctor or not bool(doctor.get("is_available", True)):
        return []

    _ensure_doctor_rolling_slots(doctor_id)

    now_dt = datetime.now(timezone.utc)
    with _cursor() as cur:
        cur.execute(
            """
            SELECT id, doctor_id, slot_start, slot_end, status, reserved_until
            FROM availability_slots
            WHERE doctor_id = %s AND slot_end >= %s
            ORDER BY slot_start
            """,
            (doctor_id, now_dt),
        )
        rows = list(cur.fetchall())
    open_rows = _drop_google_busy(doctor_id, [row for row in rows if _slot_is_open(row, now_dt)])
    return [
        {
            **row,
            "id": _as_text_id(row["id"]),
            "doctor_id": _as_text_id(row["doctor_id"]),
            "slot_start": row["slot_start"].isoformat()
            if isinstance(row.get("slot_start"), datetime)
            else row.get("slot_start"),
            "slot_end": row["slot_end"].isoformat()
            if isinstance(row.get("slot_end"), datetime)
            else row.get("slot_end"),
        }
        for row in open_rows
    ]


def reserve_slot(
    slot_id: str, patient_id: str, hold_minutes: int = 10
) -> dict[str, Any] | None:
    with _cursor() as cur:
        cur.execute(
            "SELECT * FROM reserve_availability_slot(%s, %s, %s)",
            (slot_id, patient_id, hold_minutes),
        )
        return cur.fetchone()


def _finalize_reserved_slot_booking(
    slot_id: str,
    patient_id: str,
    consultation_type: str,
    notes: str | None,
    *,
    send_confirmation: bool = True,
) -> dict[str, Any] | None:
    with _cursor() as cur:
        cur.execute(
            """
            WITH reserved AS (
                UPDATE availability_slots
                SET status = 'booked',
                    reserved_by = NULL,
                    reserved_until = NULL,
                    updated_at = now()
                WHERE id = %s
                  AND status = 'reserved'
                  AND reserved_by = %s
                  AND reserved_until IS NOT NULL
                  AND reserved_until >= now()
                RETURNING doctor_id
            )
            INSERT INTO appointments (
                doctor_id,
                patient_id,
                slot_id,
                status,
                consultation_type,
                notes
            )
            SELECT
                reserved.doctor_id,
                %s,
                %s,
                'booked',
                %s,
                %s
            FROM reserved
            RETURNING *
            """,
            (slot_id, patient_id, patient_id, slot_id, consultation_type, notes),
        )
        appointment = cur.fetchone()
    # Every new booking (portal, reschedule, AI call) passes through here.
    if appointment:
        _calendar_sync(appointment["id"])
        if send_confirmation:
            _booking_notice(appointment["id"])
    return appointment


def get_availability_slot(slot_id: str) -> dict[str, Any] | None:
    with _cursor() as cur:
        cur.execute(
            "SELECT * FROM availability_slots WHERE id = %s LIMIT 1", (slot_id,)
        )
        return cur.fetchone()


def list_doctor_slots(
    doctor_id: str,
    include_past: bool = False,
    status: str | None = None,
) -> list[dict[str, Any]]:
    doctor = get_doctor(doctor_id)
    if doctor and bool(doctor.get("is_available", True)):
        _ensure_doctor_rolling_slots(doctor_id)

    sql_text = """
    SELECT id, doctor_id, slot_start, slot_end, status, reserved_until, reserved_by, created_at, updated_at
    FROM availability_slots
    WHERE doctor_id = %s
    """
    params: list[Any] = [doctor_id]

    if not include_past:
        sql_text += " AND slot_end >= %s"
        params.append(datetime.now(timezone.utc))
    if status:
        sql_text += " AND status = %s"
        params.append(status)

    sql_text += " ORDER BY slot_start"

    with _cursor() as cur:
        cur.execute(sql_text, params)
        return list(cur.fetchall())


def create_doctor_slot(
    doctor_id: str,
    slot_start: str,
    slot_end: str,
    status: str = "available",
) -> dict[str, Any]:
    start_dt = _parse_iso_datetime(slot_start)
    if not start_dt:
        raise RuntimeError("Invalid slot_start datetime")
    if not get_doctor_schedule(doctor_id).is_working_day(start_dt.astimezone(CLINIC_TZ).date()):
        raise RuntimeError("That day is not one of the doctor's working days")

    return _insert_row(
        "availability_slots",
        {
            "doctor_id": doctor_id,
            "slot_start": slot_start,
            "slot_end": slot_end,
            "status": status,
        },
    )


def update_doctor_slot(
    doctor_id: str, slot_id: str, payload: dict[str, Any]
) -> dict[str, Any]:
    updates = {**payload, "updated_at": _utc_now_iso()}
    return _update_rows(
        "availability_slots", updates, {"id": slot_id, "doctor_id": doctor_id}
    )


def delete_doctor_slot(doctor_id: str, slot_id: str) -> None:
    _delete_rows("availability_slots", {"id": slot_id, "doctor_id": doctor_id})


# ---------------------------------------------------------------------------
# Doctor feedback helpers
# ---------------------------------------------------------------------------


def create_doctor_feedback(
    doctor_id: str,
    rating: int,
    comment: str | None = None,
    patient_id: str | None = None,
) -> dict[str, Any]:
    feedback = _insert_row(
        "doctor_feedback",
        {
            "doctor_id": doctor_id,
            "patient_id": patient_id,
            "rating": rating,
            "comment": comment,
        },
    )

    with _cursor() as cur:
        cur.execute(
            """
            SELECT COALESCE(AVG(rating), 0) AS rating_avg, COUNT(*) AS rating_count
            FROM doctor_feedback
            WHERE doctor_id = %s
            """,
            (doctor_id,),
        )
        agg = cur.fetchone() or {"rating_avg": 0, "rating_count": 0}

    _update_rows(
        "doctors",
        {
            "rating_avg": float(agg["rating_avg"]),
            "rating_count": int(agg["rating_count"]),
            "updated_at": _utc_now_iso(),
        },
        {"id": doctor_id},
    )

    return feedback


def list_doctor_feedback(doctor_id: str, limit: int = 20) -> list[dict[str, Any]]:
    with _cursor() as cur:
        cur.execute(
            """
            SELECT id, doctor_id, patient_id, rating, comment, created_at
            FROM doctor_feedback
            WHERE doctor_id = %s
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (doctor_id, limit),
        )
        return list(cur.fetchall())


# ---------------------------------------------------------------------------
# Patient portal helpers
# ---------------------------------------------------------------------------


def get_patient_account_by_auth_user_id(auth_user_id: Any) -> dict[str, Any] | None:
    auth_user_id_text = _as_text_id(auth_user_id)
    with _cursor() as cur:
        cur.execute(
            "SELECT * FROM patient_accounts WHERE auth_user_id = %s LIMIT 1",
            (auth_user_id_text,),
        )
        return cur.fetchone()


def get_patient_by_auth_user_id(auth_user_id: Any) -> dict[str, Any] | None:
    account = get_patient_account_by_auth_user_id(auth_user_id)
    if not account:
        return None
    patient = get_patient(account["patient_id"])
    if not patient:
        return None
    return {
        **patient,
        "auth_user_id": account["auth_user_id"],
        "email": account.get("email"),
    }


def get_patient_account_email(patient_id: Any) -> str | None:
    patient_id_text = _as_text_id(patient_id)
    if not patient_id_text:
        return None
    with _cursor() as cur:
        cur.execute(
            """
            SELECT email
            FROM patient_accounts
            WHERE patient_id = %s
              AND email IS NOT NULL
              AND email <> ''
            ORDER BY created_at DESC NULLS LAST
            LIMIT 1
            """,
            (patient_id_text,),
        )
        row = cur.fetchone()
    return row.get("email") if row else None


def register_patient_portal_user(
    auth_user_id: Any,
    email: str,
    name: str,
    phone: str,
    doctor_id: str,
) -> dict[str, Any]:
    auth_user_id_text = _as_text_id(auth_user_id)
    existing = get_patient_by_auth_user_id(auth_user_id_text)
    if existing:
        return existing

    patient = _insert_row(
        "patients",
        {
            "doctor_id": doctor_id,
            "name": name,
            "phone": phone,
            "notes": "Created from patient portal",
        },
    )

    _insert_row(
        "patient_accounts",
        {
            "auth_user_id": auth_user_id_text,
            "patient_id": patient["id"],
            "email": email,
        },
    )

    return {**patient, "auth_user_id": auth_user_id_text, "email": email}


def list_patient_appointments(patient_id: str) -> list[dict[str, Any]]:
    has_report_id = _table_has_column("appointments", "report_id")
    has_call_log_id = _table_has_column("appointments", "call_log_id")

    report_id_expr = "a.report_id" if has_report_id else "NULL::uuid AS report_id"
    call_log_id_expr = (
        "a.call_log_id" if has_call_log_id else "NULL::uuid AS call_log_id"
    )
    report_title_expr = (
        "r.report_data->>'title' AS report_title"
        if has_report_id
        else "NULL::text AS report_title"
    )
    report_date_expr = (
        "r.report_data->>'report_date' AS report_date"
        if has_report_id
        else "NULL::text AS report_date"
    )
    report_join = "LEFT JOIN reports r ON r.id = a.report_id" if has_report_id else ""

    with _cursor() as cur:
        cur.execute(
            f"""
            SELECT
                a.id,
                a.doctor_id,
                a.patient_id,
                a.slot_id,
                a.status,
                a.consultation_type,
                a.notes,
                a.created_at,
                {report_id_expr},
                {call_log_id_expr},
                d.name AS doctor_name,
                d.specialty AS doctor_specialty,
                s.slot_start,
                s.slot_end,
                {report_title_expr},
                {report_date_expr}
            FROM appointments a
            LEFT JOIN doctors d ON d.id = a.doctor_id
            LEFT JOIN availability_slots s ON s.id = a.slot_id
            {report_join}
            WHERE a.patient_id = %s
            ORDER BY a.created_at DESC
            """,
            (patient_id,),
        )
        return list(cur.fetchall())


def create_appointment_from_call_confirmation(
    doctor_id: str,
    patient_id: str,
    confirmed_date: str,
    confirmed_time: str | None = None,
    *,
    consultation_type: str = "video",
    notes: str | None = None,
    report_id: str | None = None,
    call_log_id: str | None = None,
    call_origin: dict[str, Any] | None = None,
) -> dict[str, Any]:
    time_str = (confirmed_time or "09:00").strip() or "09:00"
    local_start_dt = datetime.fromisoformat(f"{confirmed_date}T{time_str}:00")
    if local_start_dt.tzinfo is None:
        local_start_dt = local_start_dt.replace(tzinfo=CLINIC_TZ)
    start_dt = local_start_dt.astimezone(timezone.utc)

    with _cursor() as cur:
        cur.execute(
            """
            SELECT id, status, reserved_by, reserved_until
            FROM availability_slots
            WHERE doctor_id = %s
              AND slot_start >= %s
              AND slot_start < %s
            LIMIT 1
            """,
            (doctor_id, start_dt, start_dt + timedelta(minutes=1)),
        )
        slot = cur.fetchone()

    # Never invent a slot: if the agent confirmed a time the doctor doesn't
    # offer (outside hours, a break, a cancelled day), fail so the call log
    # shows it and staff can follow up, instead of silently booking it.
    if not slot:
        raise RuntimeError(
            f"No slot exists at {local_start_dt.strftime('%Y-%m-%d %H:%M')} clinic time; "
            "the confirmed time does not match the doctor's schedule"
        )
    if slot.get("status") == "cancelled":
        raise RuntimeError(
            f"The slot at {local_start_dt.strftime('%Y-%m-%d %H:%M')} clinic time was "
            "cancelled by the doctor and cannot be booked"
        )
    if slot.get("status") == "booked":
        # The webhook and the auto-poll can both confirm the same call; return
        # the existing booking for this patient rather than failing.
        with _cursor() as cur:
            cur.execute(
                """
                SELECT * FROM appointments
                WHERE slot_id = %s AND patient_id = %s AND status <> 'cancelled'
                LIMIT 1
                """,
                (slot["id"], patient_id),
            )
            existing_for_patient = cur.fetchone()
        if existing_for_patient:
            return existing_for_patient
        raise RuntimeError(
            f"The slot at {local_start_dt.strftime('%Y-%m-%d %H:%M')} clinic time is "
            "already booked by another patient"
        )

    reserved_until_dt = _parse_iso_datetime(slot.get("reserved_until"))
    is_reserved_by_same_patient = (
        slot.get("status") == "reserved"
        and _same_id(slot.get("reserved_by"), patient_id)
        and reserved_until_dt is not None
        and reserved_until_dt >= datetime.now(timezone.utc)
    )

    if not is_reserved_by_same_patient:
        reserved = reserve_slot(
            slot_id=slot["id"], patient_id=patient_id, hold_minutes=10
        )
        if not reserved:
            raise RuntimeError("Confirmed slot is not available for booking")

    def _attempt_book() -> dict[str, Any] | None:
        return _finalize_reserved_slot_booking(
            slot_id=slot["id"],
            patient_id=patient_id,
            consultation_type=consultation_type,
            notes=notes,
        )

    try:
        appointment = _attempt_book()
    except Exception as exc:
        msg = str(exc)
        if "Slot is not reserved for this patient or reservation expired" in msg:
            retry_reserved = reserve_slot(
                slot_id=slot["id"], patient_id=patient_id, hold_minutes=10
            )
            if not retry_reserved:
                with _cursor() as cur:
                    cur.execute(
                        "SELECT * FROM appointments WHERE slot_id = %s AND patient_id = %s LIMIT 1",
                        (slot["id"], patient_id),
                    )
                    existing_for_patient = cur.fetchone()
                if existing_for_patient:
                    return existing_for_patient
                raise RuntimeError("Confirmed slot is not available for booking")

            try:
                appointment = _attempt_book()
            except Exception as retry_exc:
                retry_msg = str(retry_exc)
                if (
                    "uq_appointments_slot_id" in retry_msg
                    or "duplicate key value" in retry_msg
                    or "23505" in retry_msg
                ):
                    with _cursor() as cur:
                        cur.execute(
                            "SELECT * FROM appointments WHERE slot_id = %s LIMIT 1",
                            (slot["id"],),
                        )
                        existing = cur.fetchone()
                    if existing:
                        return existing
                if "Slot is not reserved for this patient or reservation expired" in retry_msg:
                    with _cursor() as cur:
                        cur.execute(
                            "SELECT * FROM appointments WHERE slot_id = %s AND patient_id = %s LIMIT 1",
                            (slot["id"], patient_id),
                        )
                        existing_for_patient = cur.fetchone()
                    if existing_for_patient:
                        return existing_for_patient
                    raise RuntimeError("Confirmed slot is not available for booking")
                raise
        else:
            raise

    if not appointment:
        with _cursor() as cur:
            cur.execute(
                "SELECT * FROM appointments WHERE slot_id = %s LIMIT 1",
                (slot["id"],),
            )
            existing = cur.fetchone()
        if existing:
            return existing
        raise RuntimeError("Appointment booking failed")

    has_report_id_col = _table_has_column("appointments", "report_id")
    has_call_log_id_col = _table_has_column("appointments", "call_log_id")
    has_call_origin_col = _table_has_column("appointments", "call_origin")

    if appointment and (report_id or call_log_id or call_origin):
        update_fields: dict[str, Any] = {}
        if report_id and has_report_id_col:
            update_fields["report_id"] = report_id
        if call_log_id and has_call_log_id_col:
            update_fields["call_log_id"] = call_log_id
        if call_origin and has_call_origin_col:
            update_fields["call_origin"] = Json(_json_safe(call_origin))
        if update_fields:
            update_fields["updated_at"] = _utc_now_iso()
            _update_rows("appointments", update_fields, {"id": appointment["id"]})
            appointment = dict(appointment)
            appointment.update(
                {
                    k: (v.adapted if hasattr(v, "adapted") else v)
                    for k, v in update_fields.items()
                }
            )

    return appointment


def list_doctor_appointments(doctor_id: str) -> list[dict[str, Any]]:
    has_report_id = _table_has_column("appointments", "report_id")
    has_call_log_id = _table_has_column("appointments", "call_log_id")
    has_call_origin = _table_has_column("appointments", "call_origin")

    report_id_expr = "a.report_id" if has_report_id else "NULL::uuid AS report_id"
    call_log_id_expr = (
        "a.call_log_id" if has_call_log_id else "NULL::uuid AS call_log_id"
    )
    call_origin_expr = (
        "a.call_origin" if has_call_origin else "NULL::jsonb AS call_origin"
    )
    report_title_expr = (
        "r.report_data->>'title' AS report_title"
        if has_report_id
        else "NULL::text AS report_title"
    )
    report_date_expr = (
        "r.report_data->>'report_date' AS report_date"
        if has_report_id
        else "NULL::text AS report_date"
    )
    report_join = "LEFT JOIN reports r ON r.id = a.report_id" if has_report_id else ""
    if _table_has_column("appointments", "cancelled_by"):
        change_cols = (
            "a.cancelled_by, a.cancelled_at, a.rescheduled_to_appointment_id, "
            "s2.slot_start AS rescheduled_to_slot_start"
        )
        change_join = (
            "LEFT JOIN appointments a2 ON a2.id = a.rescheduled_to_appointment_id "
            "LEFT JOIN availability_slots s2 ON s2.id = a2.slot_id"
        )
    else:
        change_cols = (
            "NULL::text AS cancelled_by, NULL::timestamptz AS cancelled_at, "
            "NULL::uuid AS rescheduled_to_appointment_id, "
            "NULL::timestamptz AS rescheduled_to_slot_start"
        )
        change_join = ""

    with _cursor() as cur:
        cur.execute(
            f"""
            SELECT
                a.id,
                a.doctor_id,
                a.patient_id,
                a.slot_id,
                a.status,
                a.consultation_type,
                a.notes,
                a.created_at,
                {report_id_expr},
                {call_log_id_expr},
                {call_origin_expr},
                p.name AS patient_name,
                p.phone AS patient_phone,
                s.slot_start,
                s.slot_end,
                {report_title_expr},
                {report_date_expr},
                {change_cols}
            FROM appointments a
            LEFT JOIN patients p ON p.id = a.patient_id
            LEFT JOIN availability_slots s ON s.id = a.slot_id
            {report_join}
            {change_join}
            WHERE a.doctor_id = %s
            ORDER BY a.created_at DESC
            """,
            (doctor_id,),
        )
        return list(cur.fetchall())


def list_doctor_appointment_activity(doctor_id: str, days: int = 14, limit: int = 30) -> list[dict[str, Any]]:
    """Recent appointment changes for the doctor's dashboard and bell, newest first.

    One row per event: 'booked' (new appointment), 'cancelled' (with who did
    it) or 'rescheduled' (patient moved it; includes the new time).
    """
    if not _table_has_column("appointments", "cancelled_by"):
        return []
    with _cursor() as cur:
        cur.execute(
            """
            SELECT * FROM (
                SELECT
                    CASE WHEN a.rescheduled_to_appointment_id IS NOT NULL THEN 'rescheduled' ELSE 'cancelled' END AS kind,
                    a.id AS appointment_id,
                    a.cancelled_at AS happened_at,
                    a.cancelled_by AS actor,
                    p.name AS patient_name,
                    s.slot_start,
                    s2.slot_start AS new_slot_start
                FROM appointments a
                JOIN patients p ON p.id = a.patient_id
                LEFT JOIN availability_slots s ON s.id = a.slot_id
                LEFT JOIN appointments a2 ON a2.id = a.rescheduled_to_appointment_id
                LEFT JOIN availability_slots s2 ON s2.id = a2.slot_id
                WHERE a.doctor_id = %s
                  AND a.status = 'cancelled'
                  AND a.cancelled_at > now() - make_interval(days => %s)

                UNION ALL

                -- New bookings, except the new half of a reschedule (shown above).
                SELECT
                    'booked', a.id, a.created_at, NULL, p.name, s.slot_start, NULL
                FROM appointments a
                JOIN patients p ON p.id = a.patient_id
                LEFT JOIN availability_slots s ON s.id = a.slot_id
                WHERE a.doctor_id = %s
                  AND a.created_at > now() - make_interval(days => %s)
                  AND NOT EXISTS (
                        SELECT 1 FROM appointments old
                        WHERE old.rescheduled_to_appointment_id = a.id
                  )
            ) events
            ORDER BY happened_at DESC
            LIMIT %s
            """,
            (doctor_id, days, doctor_id, days, limit),
        )
        return _json_safe(list(cur.fetchall()))


def get_appointment(appointment_id: str) -> dict[str, Any] | None:
    with _cursor() as cur:
        cur.execute(
            """
            SELECT id, doctor_id, patient_id, slot_id, status, consultation_type, notes, created_at, updated_at
            FROM appointments
            WHERE id = %s
            LIMIT 1
            """,
            (appointment_id,),
        )
        return cur.fetchone()


def update_appointment(appointment_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    return _update_rows(
        "appointments",
        {**payload, "updated_at": _utc_now_iso()},
        {"id": appointment_id},
    )


def _drop_google_busy(doctor_id: str, slots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Hide open slots that clash with the doctor's Google Calendar (fails open)."""
    try:
        from app.services.google_calendar_service import drop_busy_slots

        return drop_busy_slots(str(doctor_id), slots)
    except Exception as exc:
        logger.warning("Google busy-time filter skipped: %s", exc)
        return slots


def _booking_notice(appointment_id: Any, rescheduled_from: Any = None) -> None:
    """SMS + email the patient their confirmed (or rescheduled) appointment, in the background."""
    _patient_notice(
        appointment_id,
        "rescheduled" if rescheduled_from else "booked",
        rescheduled_from=rescheduled_from,
    )


def _patient_notice(appointment_id: Any, event: str, **details: Any) -> None:
    """Queue a patient SMS/email for an appointment change (best-effort)."""
    try:
        from app.services.notification_service import queue_appointment_notification

        queue_appointment_notification(appointment_id, event, **details)
    except Exception as exc:  # never let a notification break the change
        logger.warning("Could not queue patient notification: %s", exc)


def _calendar_sync(*appointment_ids: Any) -> None:
    """Mirror these appointments to the doctor's Google Calendar (background, best-effort)."""
    try:
        from app.services.google_calendar_service import queue_appointment_sync

        queue_appointment_sync(*appointment_ids)
    except Exception as exc:  # never let calendar sync break a booking
        logger.warning("Could not queue Google Calendar sync: %s", exc)


def cancel_appointment(
    appointment_id: str,
    cancel_note: str | None = None,
    *,
    cancelled_by: str = "system",
    rescheduled_to_appointment_id: str | None = None,
) -> dict[str, Any]:
    """Cancel an appointment and free its slot.

    ``cancelled_by`` ('patient' | 'doctor' | 'system') and the reschedule link
    let the doctor's dashboard show who changed what. When the doctor cancels,
    the patient gets a notification.
    """
    appointment = get_appointment(appointment_id)
    if not appointment:
        raise RuntimeError("Appointment not found")

    if appointment["status"] == "cancelled":
        return appointment

    merged_note = appointment.get("notes") or ""
    if cancel_note:
        merged_note = f"{merged_note}\n{cancel_note}".strip()

    changes: dict[str, Any] = {
        "status": "cancelled",
        "notes": merged_note if merged_note else appointment.get("notes"),
    }
    if _table_has_column("appointments", "cancelled_by"):
        changes["cancelled_by"] = cancelled_by
        changes["cancelled_at"] = _utc_now_iso()
        if rescheduled_to_appointment_id:
            changes["rescheduled_to_appointment_id"] = rescheduled_to_appointment_id
    updated = update_appointment(appointment_id, changes)
    _calendar_sync(appointment_id)
    if not rescheduled_to_appointment_id:
        _patient_notice(appointment_id, "cancelled", cancelled_by=cancelled_by)

    if cancelled_by == "doctor":
        slot = get_availability_slot(str(appointment["slot_id"])) or {}
        start = _parse_iso_datetime(slot.get("slot_start"))
        when = (
            start.astimezone(CLINIC_TZ).strftime("%A %d %B %Y at %I:%M %p")
            if start
            else "your scheduled time"
        )
        create_notification(
            {
                "patient_id": appointment["patient_id"],
                "recipient": "patient",
                "message": (
                    f"Your appointment on {when} was cancelled by the doctor. "
                    "Please book a new slot from the patient portal."
                ),
                "priority": "high",
            }
        )

    _update_rows(
        "availability_slots",
        {
            "status": "available",
            "reserved_by": None,
            "reserved_until": None,
            "updated_at": _utc_now_iso(),
        },
        {"id": appointment["slot_id"]},
    )

    return updated


def cancel_appointment_for_patient_portal(
    auth_user_id: str,
    appointment_id: str,
    reason: str | None = None,
) -> dict[str, Any]:
    patient = get_patient_by_auth_user_id(auth_user_id)
    if not patient:
        raise RuntimeError("Patient profile not found for this auth user")

    appointment = get_appointment(appointment_id)
    if not appointment or appointment["patient_id"] != patient["id"]:
        raise RuntimeError("Appointment not found for this patient")

    # Cancelling frees the slot, so a finished visit must not reopen it.
    if appointment["status"] in {"completed", "in_progress", "no_show"}:
        raise RuntimeError(f"A {appointment['status']} appointment can't be cancelled")

    cancel_note = "Cancelled by patient via portal"
    if reason:
        cancel_note = f"{cancel_note}: {reason.strip()}"

    return cancel_appointment(appointment_id, cancel_note=cancel_note, cancelled_by="patient")


def cancel_doctor_slots(
    doctor_id: str,
    slot_ids: list[str],
    reason: str | None = None,
) -> dict[str, Any]:
    """Cancel a set of a doctor's slots (e.g. a whole day) in one transaction.

    Slots become 'cancelled' so patients can't book them and the rolling
    generator doesn't recreate them. Active appointments on those slots are
    cancelled and each affected patient gets a notification. Slots whose
    appointment is already completed are left untouched.
    """
    if not slot_ids:
        raise RuntimeError("No slots selected")

    cancel_note = "Cancelled by doctor"
    if reason and reason.strip():
        cancel_note = f"{cancel_note}: {reason.strip()}"

    with _cursor() as cur:
        with cur.connection.transaction():
            cur.execute(
                """
                SELECT s.id, s.slot_start, s.status
                FROM availability_slots s
                WHERE s.doctor_id = %s
                  AND s.id = ANY(%s::uuid[])
                  AND s.status <> 'cancelled'
                  AND NOT EXISTS (
                        SELECT 1 FROM appointments a
                        WHERE a.slot_id = s.id
                          AND a.status IN ('completed', 'in_progress', 'no_show')
                  )
                FOR UPDATE
                """,
                (doctor_id, slot_ids),
            )
            slots = list(cur.fetchall())
            target_ids = [row["id"] for row in slots]

            cancelled_appointments: list[dict[str, Any]] = []
            if target_ids:
                cur.execute(
                    """
                    UPDATE appointments
                    SET status = 'cancelled',
                        notes = trim(both E'\n' from coalesce(notes, '') || E'\n' || %s),
                        cancelled_by = 'doctor',
                        cancelled_at = now(),
                        updated_at = now()
                    WHERE slot_id = ANY(%s::uuid[])
                      AND status IN ('booked', 'confirmed')
                    RETURNING id, patient_id, slot_id
                    """,
                    (cancel_note, target_ids),
                )
                cancelled_appointments = list(cur.fetchall())

                cur.execute(
                    """
                    UPDATE availability_slots
                    SET status = 'cancelled',
                        reserved_by = NULL,
                        reserved_until = NULL,
                        updated_at = now()
                    WHERE id = ANY(%s::uuid[])
                    """,
                    (target_ids,),
                )

                start_by_slot = {row["id"]: row["slot_start"] for row in slots}
                for appt in cancelled_appointments:
                    start = _parse_iso_datetime(start_by_slot.get(appt["slot_id"]))
                    when = (
                        start.astimezone(CLINIC_TZ).strftime("%A %d %B %Y at %I:%M %p")
                        if start
                        else "your scheduled time"
                    )
                    message = (
                        f"Your appointment on {when} was cancelled by the doctor. "
                        "Please book a new slot from the patient portal."
                    )
                    if reason and reason.strip():
                        message = f"{message} Reason: {reason.strip()}"
                    cur.execute(
                        """
                        INSERT INTO notifications (patient_id, recipient, message, priority)
                        VALUES (%s, 'patient', %s, 'high')
                        """,
                        (appt["patient_id"], message),
                    )

    _calendar_sync(*(appt["id"] for appt in cancelled_appointments))
    for appt in cancelled_appointments:
        _patient_notice(appt["id"], "cancelled", cancelled_by="doctor", reason=reason)

    return _json_safe(
        {
            "cancelled_slots": len(target_ids),
            "skipped_slots": len(slot_ids) - len(target_ids),
            "cancelled_appointments": len(cancelled_appointments),
            "notified_patient_ids": sorted(
                {str(appt["patient_id"]) for appt in cancelled_appointments}
            ),
        }
    )


def reopen_doctor_slots(doctor_id: str, slot_ids: list[str]) -> dict[str, Any]:
    """Make cancelled future slots bookable again (undo Remove / Cancel day).

    Previously cancelled appointments stay cancelled; patients rebook if they
    still want the time.
    """
    if not slot_ids:
        raise RuntimeError("No slots selected")

    with _cursor() as cur:
        cur.execute(
            """
            UPDATE availability_slots
            SET status = 'available',
                reserved_by = NULL,
                reserved_until = NULL,
                updated_at = now()
            WHERE doctor_id = %s
              AND id = ANY(%s::uuid[])
              AND status = 'cancelled'
              AND slot_start > now()
            RETURNING id
            """,
            (doctor_id, slot_ids),
        )
        reopened = list(cur.fetchall())

    return {
        "reopened_slots": len(reopened),
        "skipped_slots": len(slot_ids) - len(reopened),
    }


def reschedule_appointment_for_patient_portal(
    auth_user_id: str,
    appointment_id: str,
    new_slot_id: str,
    consultation_type: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    patient = get_patient_by_auth_user_id(auth_user_id)
    if not patient:
        raise RuntimeError("Patient profile not found for this auth user")

    current = get_appointment(appointment_id)
    if not current or current["patient_id"] != patient["id"]:
        raise RuntimeError("Appointment not found for this patient")

    if current["status"] in {"cancelled", "completed", "no_show"}:
        raise RuntimeError("Only active appointments can be rescheduled")

    reserved = reserve_slot(
        slot_id=new_slot_id, patient_id=patient["id"], hold_minutes=10
    )
    if not reserved:
        raise RuntimeError("New slot is not available")

    new_appointment = _finalize_reserved_slot_booking(
        slot_id=new_slot_id,
        patient_id=patient["id"],
        consultation_type=consultation_type or current["consultation_type"],
        notes=notes or current.get("notes"),
        send_confirmation=False,  # a "rescheduled" email goes out below instead
    )

    if not new_appointment:
        raise RuntimeError("Could not book the selected slot")

    cancel_appointment(
        current["id"],
        cancel_note=f"Rescheduled to slot {new_slot_id}",
        cancelled_by="patient",
        rescheduled_to_appointment_id=str(new_appointment["id"]),
    )
    _booking_notice(new_appointment["id"], rescheduled_from=current["id"])
    doctor = get_doctor(str(new_appointment["doctor_id"]))

    with _cursor() as cur:
        cur.execute(
            "SELECT id, slot_start, slot_end FROM availability_slots WHERE id = %s LIMIT 1",
            (new_appointment["slot_id"],),
        )
        slot = cur.fetchone() or {}

    return {
        **new_appointment,
        "doctor_name": doctor.get("name") if doctor else "Doctor",
        "doctor_specialty": doctor.get("specialty") if doctor else None,
        "slot_start": slot.get("slot_start"),
        "slot_end": slot.get("slot_end"),
        "rescheduled_from_appointment_id": appointment_id,
    }


def book_slot_for_patient_portal(
    auth_user_id: str,
    slot_id: str,
    consultation_type: str = "video",
    notes: str | None = None,
) -> dict[str, Any] | None:
    patient = get_patient_by_auth_user_id(auth_user_id)
    if not patient:
        raise RuntimeError("Patient profile not found for this auth user")

    patient_id = patient["id"]

    slot_row = get_availability_slot(slot_id)
    now_dt = datetime.now(timezone.utc)

    can_book_existing_reservation = False
    if slot_row and slot_row.get("status") == "reserved":
        reserved_until_dt = _parse_iso_datetime(slot_row.get("reserved_until"))
        can_book_existing_reservation = (
            _same_id(slot_row.get("reserved_by"), patient_id)
            and reserved_until_dt is not None
            and reserved_until_dt >= now_dt
        )

    if not can_book_existing_reservation:
        reserved = reserve_slot(slot_id=slot_id, patient_id=patient_id, hold_minutes=10)
        if not reserved:
            latest_slot = get_availability_slot(slot_id)
            latest_reserved_until = _parse_iso_datetime(
                latest_slot.get("reserved_until") if latest_slot else None
            )
            if (
                latest_slot
                and latest_slot.get("status") == "reserved"
                and _same_id(latest_slot.get("reserved_by"), patient_id)
                and latest_reserved_until is not None
                and latest_reserved_until >= now_dt
            ):
                can_book_existing_reservation = True
            else:
                return None

    def _attempt_book() -> dict[str, Any] | None:
        return _finalize_reserved_slot_booking(
            slot_id=slot_id,
            patient_id=patient_id,
            consultation_type=consultation_type,
            notes=notes,
        )

    try:
        appointment = _attempt_book()
    except Exception as exc:
        msg = str(exc)
        if (
            "uq_appointments_slot_id" in msg
            or "duplicate key value" in msg
            or "23505" in msg
        ):
            return None
        if "Slot is not reserved for this patient or reservation expired" in msg:
            retry_reserved = reserve_slot(
                slot_id=slot_id, patient_id=patient_id, hold_minutes=10
            )
            if not retry_reserved:
                latest_slot = get_availability_slot(slot_id)
                latest_reserved_until = _parse_iso_datetime(
                    latest_slot.get("reserved_until") if latest_slot else None
                )
                if not (
                    latest_slot
                    and latest_slot.get("status") == "reserved"
                    and _same_id(latest_slot.get("reserved_by"), patient_id)
                    and latest_reserved_until is not None
                    and latest_reserved_until >= datetime.now(timezone.utc)
                ):
                    return None

            try:
                appointment = _attempt_book()
            except Exception as retry_exc:
                retry_msg = str(retry_exc)
                if (
                    "uq_appointments_slot_id" in retry_msg
                    or "duplicate key value" in retry_msg
                    or "23505" in retry_msg
                    or "Slot is not reserved for this patient or reservation expired"
                    in retry_msg
                ):
                    return None
                raise
        else:
            raise

    if not appointment:
        return None

    doctor = get_doctor(str(appointment["doctor_id"]))
    slot = get_availability_slot(appointment["slot_id"]) or {}

    slot_start = slot.get("slot_start")
    doctor_name = doctor.get("name") if doctor else "Doctor"
    patient_display = patient.get("name") or patient.get("email") or "Patient"

    create_notification(
        {
            "patient_id": patient_id,
            "recipient": patient_display,
            "message": f"Appointment confirmed with {doctor_name} on {slot_start}. Type: {consultation_type}.",
            "priority": "normal",
            "status": "unread",
        }
    )

    return {
        **appointment,
        "doctor_name": doctor_name,
        "doctor_specialty": doctor.get("specialty") if doctor else None,
        "slot_start": slot_start,
        "slot_end": slot.get("slot_end"),
    }


# ---------------------------------------------------------------------------
# CRUD helpers
# ---------------------------------------------------------------------------


def get_workflow(workflow_id: str) -> dict[str, Any] | None:
    with _cursor() as cur:
        cur.execute("SELECT * FROM workflows WHERE id = %s LIMIT 1", (workflow_id,))
        return cur.fetchone()


def create_workflow(payload: dict[str, Any]) -> dict[str, Any]:
    return _insert_row("workflows", payload)


def update_workflow(workflow_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    return _update_rows("workflows", payload, {"id": workflow_id})


def delete_workflow(workflow_id: str) -> None:
    _delete_rows("workflows", {"id": workflow_id})


def create_patient(payload: dict[str, Any], *, cur=None) -> dict[str, Any]:
    return _insert_row("patients", payload, cur=cur)


def get_patient(patient_id: str) -> dict[str, Any] | None:
    with _cursor() as cur:
        cur.execute("SELECT * FROM patients WHERE id = %s LIMIT 1", (patient_id,))
        return cur.fetchone()


def list_patients(doctor_id: str | None = None) -> list[dict[str, Any]]:
    with _cursor() as cur:
        if doctor_id:
            cur.execute("SELECT * FROM patients WHERE doctor_id = %s", (doctor_id,))
        else:
            cur.execute("SELECT * FROM patients")
        return list(cur.fetchall())


def list_doctor_portal_patients(doctor_id: str) -> list[dict[str, Any]]:
    # Some environments can be partially migrated; fall back safely.
    if not _table_has_column("appointments", "id"):
        return list_patients(doctor_id)

    has_appointment_created_at = _table_has_column("appointments", "created_at")
    last_appointment_expr = (
        "MAX(created_at) AS last_appointment_at"
        if has_appointment_created_at
        else "NULL::timestamptz AS last_appointment_at"
    )

    with _cursor() as cur:
        cur.execute(
            f"""
            SELECT
                p.*,
                COALESCE(da.appointment_count, 0)::int AS appointment_count,
                da.last_appointment_at
            FROM patients p
            LEFT JOIN (
                SELECT
                    patient_id,
                    COUNT(*)::int AS appointment_count,
                    {last_appointment_expr}
                FROM appointments
                WHERE doctor_id = %s
                GROUP BY patient_id
            ) da ON da.patient_id = p.id
            WHERE p.doctor_id = %s::text
               OR da.patient_id IS NOT NULL
            ORDER BY da.last_appointment_at DESC NULLS LAST, p.name ASC
            """,
            (doctor_id, doctor_id),
        )
        return list(cur.fetchall())


def update_patient(patient_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    return _update_rows("patients", payload, {"id": patient_id})


def delete_patient(patient_id: str) -> None:
    _delete_rows("patients", {"id": patient_id})


def list_conditions(patient_id: str) -> list[dict[str, Any]]:
    with _cursor() as cur:
        cur.execute(
            "SELECT * FROM patient_conditions WHERE patient_id = %s ORDER BY created_at DESC",
            (patient_id,),
        )
        return list(cur.fetchall())


def create_condition(payload: dict[str, Any]) -> dict[str, Any]:
    return _insert_row("patient_conditions", payload)


def update_condition(condition_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    return _update_rows("patient_conditions", payload, {"id": condition_id})


def delete_condition(condition_id: str) -> None:
    _delete_rows("patient_conditions", {"id": condition_id})


def create_call_log(payload: dict[str, Any]) -> dict[str, Any]:
    return _insert_row("call_logs", payload)


def get_call_log(log_id: str) -> dict[str, Any] | None:
    with _cursor() as cur:
        cur.execute("SELECT * FROM call_logs WHERE id = %s LIMIT 1", (log_id,))
        return cur.fetchone()


def update_call_log(log_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    return _update_rows("call_logs", payload, {"id": log_id})


def list_call_logs(
    workflow_id: str | None = None, doctor_id: str | None = None
) -> list[dict[str, Any]]:
    sql_text = "SELECT cl.* FROM call_logs cl"
    params: list[Any] = []
    where: list[str] = []

    if doctor_id:
        # Prefer explicit doctor ownership stored on call_logs.
        # Fall back to patient.doctor_id only for older rows where call_logs.doctor_id is NULL.
        sql_text += " LEFT JOIN patients p ON p.id = cl.patient_id"
        where.append("(cl.doctor_id = %s OR (cl.doctor_id IS NULL AND p.doctor_id = %s))")
        params.extend([doctor_id, doctor_id])

    if workflow_id:
        where.append("cl.workflow_id = %s")
        params.append(workflow_id)

    if where:
        sql_text += " WHERE " + " AND ".join(where)
    sql_text += " ORDER BY cl.created_at DESC"

    with _cursor() as cur:
        cur.execute(sql_text, params)
        return list(cur.fetchall())


def create_follow_up_job(payload: dict[str, Any]) -> dict[str, Any]:
    if not follow_up_tables_ready():
        return {}
    return _insert_row("follow_up_jobs", payload)


def get_follow_up_job(job_id: str) -> dict[str, Any] | None:
    if not follow_up_tables_ready():
        return None
    with _cursor() as cur:
        cur.execute("SELECT * FROM follow_up_jobs WHERE id = %s LIMIT 1", (job_id,))
        return cur.fetchone()


def get_follow_up_job_by_call_log(call_log_id: str) -> dict[str, Any] | None:
    if not follow_up_tables_ready():
        return None
    with _cursor() as cur:
        cur.execute(
            "SELECT * FROM follow_up_jobs WHERE call_log_id = %s LIMIT 1",
            (call_log_id,),
        )
        return cur.fetchone()


def update_follow_up_job(job_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    if not follow_up_tables_ready():
        return {}
    return _update_rows(
        "follow_up_jobs",
        {**payload, "updated_at": _utc_now_iso()},
        {"id": job_id},
    )


def list_follow_up_jobs(
    doctor_id: str | None = None,
    status: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    if not follow_up_tables_ready():
        return []
    sql_text = "SELECT * FROM follow_up_jobs"
    params: list[Any] = []
    where: list[str] = []

    if doctor_id:
        where.append("doctor_id = %s")
        params.append(doctor_id)
    if status:
        where.append("status = %s")
        params.append(status)

    if where:
        sql_text += " WHERE " + " AND ".join(where)

    safe_limit = max(1, min(int(limit), 500))
    sql_text += " ORDER BY scheduled_for ASC LIMIT %s"
    params.append(safe_limit)

    with _cursor() as cur:
        cur.execute(sql_text, params)
        return list(cur.fetchall())


def claim_due_follow_up_jobs(limit: int = 10) -> list[dict[str, Any]]:
    if not follow_up_tables_ready():
        return []
    safe_limit = max(1, min(int(limit), 100))
    with _cursor() as cur:
        cur.execute(
            """
            WITH due AS (
                SELECT id
                FROM follow_up_jobs
                WHERE status = 'queued'
                  AND scheduled_for <= now()
                ORDER BY scheduled_for ASC
                FOR UPDATE SKIP LOCKED
                LIMIT %s
            )
            UPDATE follow_up_jobs j
            SET status = 'running',
                attempt_count = j.attempt_count + 1,
                last_run_at = now(),
                updated_at = now()
            FROM due
            WHERE j.id = due.id
            RETURNING j.*
            """,
            (safe_limit,),
        )
        return list(cur.fetchall())


def create_follow_up_job_log(payload: dict[str, Any]) -> dict[str, Any]:
    if not follow_up_tables_ready():
        return {}
    return _insert_row("follow_up_job_logs", payload)


def list_follow_up_job_logs(job_id: str, limit: int = 200) -> list[dict[str, Any]]:
    if not follow_up_tables_ready():
        return []
    safe_limit = max(1, min(int(limit), 1000))
    with _cursor() as cur:
        cur.execute(
            """
            SELECT *
            FROM follow_up_job_logs
            WHERE job_id = %s
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (job_id, safe_limit),
        )
        return list(cur.fetchall())


def has_active_appointment_for_call_log(call_log_id: str) -> bool:
    with _cursor() as cur:
        cur.execute(
            """
            SELECT 1
            FROM appointments
            WHERE call_log_id = %s
              AND status NOT IN ('cancelled', 'no_show')
            LIMIT 1
            """,
            (call_log_id,),
        )
        return cur.fetchone() is not None


def has_active_appointment_for_patient_doctor(patient_id: str, doctor_id: str) -> bool:
    with _cursor() as cur:
        cur.execute(
            """
            SELECT 1
            FROM appointments
            WHERE patient_id = %s
              AND doctor_id = %s
              AND status NOT IN ('cancelled', 'no_show')
            LIMIT 1
            """,
            (patient_id, doctor_id),
        )
        return cur.fetchone() is not None


def follow_up_tables_ready() -> bool:
        with _cursor() as cur:
                cur.execute(
                        """
                        SELECT table_name
                        FROM information_schema.tables
                        WHERE table_schema = 'public'
                            AND table_name IN ('follow_up_jobs', 'follow_up_job_logs')
                        """
                )
                rows = cur.fetchall()
        names = {r.get("table_name") for r in rows}
        return "follow_up_jobs" in names and "follow_up_job_logs" in names


def list_medications(patient_id: str) -> list[dict[str, Any]]:
    with _cursor() as cur:
        cur.execute(
            "SELECT * FROM patient_medications WHERE patient_id = %s ORDER BY created_at DESC",
            (patient_id,),
        )
        return list(cur.fetchall())


def create_medication(payload: dict[str, Any]) -> dict[str, Any]:
    return _insert_row("patient_medications", payload)


def update_medication(medication_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    return _update_rows("patient_medications", payload, {"id": medication_id})


def delete_medication(medication_id: str) -> None:
    _delete_rows("patient_medications", {"id": medication_id})


def create_notification(payload: dict[str, Any]) -> dict[str, Any]:
    return _insert_row("notifications", payload)


def list_notifications(patient_id: str | None = None) -> list[dict[str, Any]]:
    with _cursor() as cur:
        if patient_id:
            cur.execute(
                "SELECT * FROM notifications WHERE patient_id = %s ORDER BY created_at DESC",
                (patient_id,),
            )
        else:
            cur.execute("SELECT * FROM notifications ORDER BY created_at DESC")
        return list(cur.fetchall())


def create_lab_order(payload: dict[str, Any]) -> dict[str, Any]:
    return _insert_row("lab_orders", payload)


def list_lab_orders(patient_id: str | None = None) -> list[dict[str, Any]]:
    with _cursor() as cur:
        if patient_id:
            cur.execute(
                "SELECT * FROM lab_orders WHERE patient_id = %s ORDER BY created_at DESC",
                (patient_id,),
            )
        else:
            cur.execute("SELECT * FROM lab_orders ORDER BY created_at DESC")
        return list(cur.fetchall())


def create_referral(payload: dict[str, Any]) -> dict[str, Any]:
    return _insert_row("referrals", payload)


def list_referrals(patient_id: str | None = None) -> list[dict[str, Any]]:
    with _cursor() as cur:
        if patient_id:
            cur.execute(
                "SELECT * FROM referrals WHERE patient_id = %s ORDER BY created_at DESC",
                (patient_id,),
            )
        else:
            cur.execute("SELECT * FROM referrals ORDER BY created_at DESC")
        return list(cur.fetchall())


def create_staff_assignment(payload: dict[str, Any]) -> dict[str, Any]:
    return _insert_row("staff_assignments", payload)


def list_staff_assignments(
    patient_id: str | None = None,
    staff_id: str | None = None,
) -> list[dict[str, Any]]:
    sql_text = "SELECT * FROM staff_assignments"
    params: list[Any] = []
    where: list[str] = []

    if patient_id:
        where.append("patient_id = %s")
        params.append(patient_id)
    if staff_id:
        where.append("staff_id = %s")
        params.append(staff_id)

    if where:
        sql_text += " WHERE " + " AND ".join(where)
    sql_text += " ORDER BY created_at DESC"

    with _cursor() as cur:
        cur.execute(sql_text, params)
        return list(cur.fetchall())


def create_report(payload: dict[str, Any]) -> dict[str, Any]:
    return _insert_row("reports", payload)


def get_report(report_id: str) -> dict[str, Any] | None:
    with _cursor() as cur:
        cur.execute("SELECT * FROM reports WHERE id = %s LIMIT 1", (report_id,))
        return cur.fetchone()


def list_reports(
    patient_id: str | None = None,
    workflow_id: str | None = None,
) -> list[dict[str, Any]]:
    sql_text = "SELECT * FROM reports"
    params: list[Any] = []
    where: list[str] = []

    if patient_id:
        where.append("patient_id = %s")
        params.append(patient_id)
    if workflow_id:
        where.append("workflow_id = %s")
        params.append(workflow_id)

    if where:
        sql_text += " WHERE " + " AND ".join(where)
    sql_text += " ORDER BY created_at DESC"

    with _cursor() as cur:
        cur.execute(sql_text, params)
        return list(cur.fetchall())


def create_pdf_document(payload: dict[str, Any]) -> dict[str, Any]:
    return _insert_row("pdf_documents", payload)


def get_pdf_document(doc_id: str) -> dict[str, Any] | None:
    with _cursor() as cur:
        cur.execute("SELECT * FROM pdf_documents WHERE id = %s LIMIT 1", (doc_id,))
        return cur.fetchone()


def list_pdf_documents(patient_id: str | None = None) -> list[dict[str, Any]]:
    sql_text = """
    SELECT id, patient_id, filename, page_count, patient_info, lab_results, tables_data, uploaded_by, created_at
    FROM pdf_documents
    """
    params: list[Any] = []
    if patient_id:
        sql_text += " WHERE patient_id = %s"
        params.append(patient_id)
    sql_text += " ORDER BY created_at DESC"

    with _cursor() as cur:
        cur.execute(sql_text, params)
        return list(cur.fetchall())


def delete_pdf_document(doc_id: str) -> None:
    _delete_rows("pdf_documents", {"id": doc_id})


# ---------------------------------------------------------------------------
# Consultation room + chat helpers
# ---------------------------------------------------------------------------


def get_consultation_room_by_appointment(appointment_id: str) -> dict[str, Any] | None:
    with _cursor() as cur:
        cur.execute(
            """
            SELECT id, appointment_id, provider, room_name, room_url, created_at, updated_at
            FROM consultation_rooms
            WHERE appointment_id = %s
            LIMIT 1
            """,
            (appointment_id,),
        )
        return cur.fetchone()


def create_consultation_room(
    appointment_id: str,
    provider: str = "daily",
    room_name: str | None = None,
) -> dict[str, Any]:
    existing = get_consultation_room_by_appointment(appointment_id)
    if existing:
        return existing

    safe_room_name = room_name or f"consult-{appointment_id[:8]}"
    room_url: str | None = None

    appointment = get_appointment(appointment_id)
    if appointment and appointment.get("consultation_type") == "video":
        # Video runs in our own browser-to-browser call on the consultation
        # page (no third-party sign-in), so the "URL" is that page.
        provider = "webrtc"
        room_url = f"/consultation/{appointment_id}"

    return _insert_row(
        "consultation_rooms",
        {
            "appointment_id": appointment_id,
            "provider": provider,
            "room_name": safe_room_name,
            "room_url": room_url,
        },
    )


def list_consultation_messages(
    appointment_id: str, limit: int = 200
) -> list[dict[str, Any]]:
    with _cursor() as cur:
        cur.execute(
            """
            SELECT id, appointment_id, room_id, sender_type, sender_id, message, created_at
            FROM consultation_messages
            WHERE appointment_id = %s
            ORDER BY created_at ASC
            LIMIT %s
            """,
            (appointment_id, limit),
        )
        return list(cur.fetchall())


def create_consultation_message(payload: dict[str, Any]) -> dict[str, Any]:
    return _insert_row("consultation_messages", payload)


# ---------------------------------------------------------------------------
# Report-aware slot & appointment helpers
# ---------------------------------------------------------------------------


NO_SLOTS_AVAILABLE_TEXT = (
    "NO OPEN SLOTS. There are currently no open appointment slots. Do not offer "
    "or confirm any date or time; tell the patient the clinic will call back to schedule."
)


def get_available_slot_options(doctor_id: str, count: int = 12) -> list[dict[str, Any]]:
    """Return the next `count` bookable slots for a doctor (used for offering during call).

    Only slots inside clinic working hours on working days are returned, so the
    agent never offers a time the clinic doesn't actually work.
    """
    _ensure_doctor_rolling_slots(doctor_id)
    return _bookable_slots(doctor_id, datetime.now(timezone.utc), None, count)


def _bookable_slots(
    doctor_id: str,
    start_after: datetime,
    start_before: datetime | None,
    limit: int,
) -> list[dict[str, Any]]:
    """Open slots in clinic working hours, soonest first.

    A reservation whose hold expired counts as open (same rule as
    reserve_availability_slot), so a time a caller abandoned is offered again.
    """
    with _cursor() as cur:
        cur.execute(
            """
            SELECT id, doctor_id, slot_start, slot_end, status
            FROM availability_slots
            WHERE doctor_id = %s
              AND (
                    status = 'available'
                 OR (status = 'reserved' AND reserved_until IS NOT NULL AND reserved_until < now())
              )
              AND slot_start > %s
              AND (%s::timestamptz IS NULL OR slot_start < %s::timestamptz)
            ORDER BY slot_start
            LIMIT %s
            """,
            # Over-fetch so filtering out-of-hours rows still leaves `limit` slots.
            (doctor_id, start_after, start_before, start_before, limit * 4),
        )
        rows = list(cur.fetchall())

    schedule = get_doctor_schedule(doctor_id)
    bookable = []
    for row in rows:
        start = _parse_iso_datetime(row.get("slot_start"))
        if not start or not schedule.is_inside_hours(start):
            continue
        bookable.append(row)
    return _drop_google_busy(doctor_id, bookable)[:limit]


def get_available_slots_on_date(doctor_id: str, day: date) -> list[dict[str, Any]]:
    """Open slots on one clinic-local day (for the agent's live "times on date" tool)."""
    _ensure_doctor_rolling_slots(doctor_id)
    day_start = datetime.combine(day, time(0, 0), tzinfo=CLINIC_TZ)
    start_after = max(day_start, datetime.now(CLINIC_TZ))
    return _bookable_slots(doctor_id, start_after, day_start + timedelta(days=1), 50)


def _speech_date(day: date) -> str:
    return f"{day.strftime('%A')} {day.day} {day.strftime('%B')}"


def format_available_dates_for_speech(slots: list[dict[str, Any]]) -> str:
    """Just the days that have openings, e.g. "Tuesday 27 October or Wednesday 28 October".

    Lets the agent offer dates first and only read out times for the day the
    patient picks, instead of reciting every slot.
    """
    days = sorted(
        {
            start.astimezone(CLINIC_TZ).date()
            for start in (_parse_iso_datetime(s.get("slot_start")) for s in slots)
            if start
        }
    )
    if not days:
        return NO_SLOTS_AVAILABLE_TEXT
    labels = [_speech_date(d) for d in days]
    return labels[0] if len(labels) == 1 else ", ".join(labels[:-1]) + " or " + labels[-1]


def hold_slot_for_call(
    doctor_id: str,
    patient_id: str,
    day: date,
    local_time: time,
    hold_minutes: int = 30,
) -> dict[str, Any]:
    """Reserve one slot for a patient while they're on the phone with the agent.

    The hold is atomic (reserve_availability_slot), so two simultaneous calls
    can't both get the same time: the second caller is told it was just taken.
    Holding a new time releases this patient's other live holds with this
    doctor, so changing their mind mid-call doesn't block several slots. The
    post-call booking then converts the hold into an appointment.
    """
    local_start = datetime.combine(day, local_time, tzinfo=CLINIC_TZ)
    start_utc = local_start.astimezone(timezone.utc)

    with _cursor() as cur:
        cur.execute(
            """
            SELECT id, slot_end FROM availability_slots
            WHERE doctor_id = %s AND slot_start >= %s AND slot_start < %s
            LIMIT 1
            """,
            (doctor_id, start_utc, start_utc + timedelta(minutes=1)),
        )
        slot = cur.fetchone()

    on_schedule = bool(
        slot
        and start_utc > datetime.now(timezone.utc)
        and get_doctor_schedule(doctor_id).is_inside_hours(start_utc)
    )
    if on_schedule and not _drop_google_busy(
        doctor_id, [{"slot_start": start_utc, "slot_end": slot["slot_end"]}]
    ):
        on_schedule = False  # the doctor has something else in their calendar then
    held = None
    if on_schedule:
        held = reserve_slot(slot_id=str(slot["id"]), patient_id=patient_id, hold_minutes=hold_minutes)

    if held:
        with _cursor() as cur:
            cur.execute(
                """
                UPDATE availability_slots
                SET status = 'available', reserved_by = NULL, reserved_until = NULL, updated_at = now()
                WHERE doctor_id = %s
                  AND reserved_by = %s
                  AND status = 'reserved'
                  AND id <> %s
                """,
                (doctor_id, patient_id, held["id"]),
            )
        return {"held": True, "slot": held}

    return {
        "held": False,
        # "taken": a real slot someone else holds or booked (e.g. a parallel call);
        # "not_on_schedule": the doctor doesn't offer that time at all.
        "reason": "taken" if on_schedule else "not_on_schedule",
        "alternatives": get_available_slots_on_date(doctor_id, day),
    }


def _speech_time(local_dt: datetime) -> str:
    # Build unpadded hour manually: "%-I" is POSIX-only and fails on Windows.
    return f"{local_dt.hour % 12 or 12}:{local_dt.strftime('%M %p')}"


def format_slot_options_for_speech(slots: list[dict[str, Any]]) -> str:
    """Format slots for the ElevenLabs agent, grouped by day in clinic time.

    Example: "Tuesday 27 October 2026 (2026-10-27): 10:30 AM, 11:00 AM; Wednesday ..."
    The ISO date lets the agent fill `confirmed_date` exactly.
    """
    by_day: dict[date, list[str]] = {}
    for slot in slots:
        start = _parse_iso_datetime(slot.get("slot_start"))
        if not start:
            continue
        local = start.astimezone(CLINIC_TZ)
        by_day.setdefault(local.date(), []).append(_speech_time(local))

    if not by_day:
        return NO_SLOTS_AVAILABLE_TEXT

    parts = [
        f"{day.strftime('%A')} {day.day} {day.strftime('%B %Y')} ({day.isoformat()}): "
        + ", ".join(times)
        for day, times in sorted(by_day.items())
    ]
    return "; ".join(parts)


def list_doctor_upcoming_appointments_with_report(
    doctor_id: str,
) -> list[dict[str, Any]]:
    """List upcoming appointments for a doctor, including report context and call origin."""
    has_report_id = _table_has_column("appointments", "report_id")
    has_call_log_id = _table_has_column("appointments", "call_log_id")
    has_call_origin = _table_has_column("appointments", "call_origin")

    report_id_expr = "a.report_id" if has_report_id else "NULL::uuid AS report_id"
    call_log_id_expr = (
        "a.call_log_id" if has_call_log_id else "NULL::uuid AS call_log_id"
    )
    call_origin_expr = (
        "a.call_origin" if has_call_origin else "NULL::jsonb AS call_origin"
    )
    report_title_expr = (
        "r.report_data->>'title' AS report_title"
        if has_report_id
        else "NULL::text AS report_title"
    )
    report_date_expr = (
        "r.report_data->>'report_date' AS report_date"
        if has_report_id
        else "NULL::text AS report_date"
    )
    report_type_expr = (
        "r.report_data->>'report_type' AS report_type"
        if has_report_id
        else "NULL::text AS report_type"
    )
    report_join = "LEFT JOIN reports r ON r.id = a.report_id" if has_report_id else ""

    now = datetime.now(timezone.utc)
    with _cursor() as cur:
        cur.execute(
            f"""
            SELECT
                a.id,
                a.doctor_id,
                a.patient_id,
                a.slot_id,
                a.status,
                a.consultation_type,
                a.notes,
                a.created_at,
                {report_id_expr},
                {call_log_id_expr},
                {call_origin_expr},
                p.name AS patient_name,
                p.phone AS patient_phone,
                s.slot_start,
                s.slot_end,
                {report_title_expr},
                {report_date_expr},
                {report_type_expr}
            FROM appointments a
            LEFT JOIN patients p ON p.id = a.patient_id
            LEFT JOIN availability_slots s ON s.id = a.slot_id
            {report_join}
            WHERE a.doctor_id = %s
              AND (s.slot_start IS NULL OR s.slot_start >= %s)
            ORDER BY s.slot_start ASC NULLS LAST
            """,
            (doctor_id, now),
        )
        return list(cur.fetchall())


def list_patient_upcoming_appointments_with_report(
    patient_id: str,
) -> list[dict[str, Any]]:
    """List upcoming appointments for a patient, including report context."""
    has_report_id = _table_has_column("appointments", "report_id")
    has_call_log_id = _table_has_column("appointments", "call_log_id")
    has_call_origin = _table_has_column("appointments", "call_origin")

    report_id_expr = "a.report_id" if has_report_id else "NULL::uuid AS report_id"
    call_log_id_expr = (
        "a.call_log_id" if has_call_log_id else "NULL::uuid AS call_log_id"
    )
    call_origin_expr = (
        "a.call_origin" if has_call_origin else "NULL::jsonb AS call_origin"
    )
    report_title_expr = (
        "r.report_data->>'title' AS report_title"
        if has_report_id
        else "NULL::text AS report_title"
    )
    report_date_expr = (
        "r.report_data->>'report_date' AS report_date"
        if has_report_id
        else "NULL::text AS report_date"
    )
    report_join = "LEFT JOIN reports r ON r.id = a.report_id" if has_report_id else ""

    now = datetime.now(timezone.utc)
    with _cursor() as cur:
        cur.execute(
            f"""
            SELECT
                a.id,
                a.doctor_id,
                a.patient_id,
                a.slot_id,
                a.status,
                a.consultation_type,
                a.notes,
                a.created_at,
                {report_id_expr},
                {call_log_id_expr},
                {call_origin_expr},
                d.name AS doctor_name,
                d.specialty AS doctor_specialty,
                s.slot_start,
                s.slot_end,
                {report_title_expr},
                {report_date_expr}
            FROM appointments a
            LEFT JOIN doctors d ON d.id = a.doctor_id::uuid
            LEFT JOIN availability_slots s ON s.id = a.slot_id
            {report_join}
            WHERE a.patient_id = %s
              AND (s.slot_start IS NULL OR s.slot_start >= %s)
              AND a.status NOT IN ('cancelled', 'completed', 'no_show')
            ORDER BY s.slot_start ASC NULLS LAST
            """,
            (patient_id, now),
        )
        return list(cur.fetchall())


# ---------------------------------------------------------------------------
# Blood campaign helpers
# ---------------------------------------------------------------------------


def upsert_blood_donors(
    doctor_id: str,
    donors: list[dict[str, Any]],
) -> dict[str, int]:
    created = 0
    updated = 0

    with _cursor() as cur:
        for donor in donors:
            cur.execute(
                """
                INSERT INTO blood_donors (
                    doctor_id,
                    name,
                    gender,
                    phone_number,
                    location,
                    latitude,
                    longitude,
                    last_donated_date,
                    blood_type,
                    updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, now())
                ON CONFLICT (doctor_id, phone_number)
                DO UPDATE SET
                    name = EXCLUDED.name,
                    gender = EXCLUDED.gender,
                    location = EXCLUDED.location,
                    latitude = EXCLUDED.latitude,
                    longitude = EXCLUDED.longitude,
                    last_donated_date = EXCLUDED.last_donated_date,
                    blood_type = EXCLUDED.blood_type,
                    updated_at = now()
                RETURNING (xmax = 0) AS inserted
                """,
                (
                    doctor_id,
                    donor["name"],
                    donor["gender"],
                    donor["phone_number"],
                    donor["location"],
                    donor.get("latitude"),
                    donor.get("longitude"),
                    donor["last_donated_date"],
                    donor["blood_type"],
                ),
            )
            row = cur.fetchone() or {}
            if row.get("inserted"):
                created += 1
            else:
                updated += 1

    return {"created": created, "updated": updated}


def upsert_blood_ngos(
    doctor_id: str,
    ngos: list[dict[str, Any]],
) -> dict[str, int]:
    created = 0
    updated = 0

    with _cursor() as cur:
        for ngo in ngos:
            cur.execute(
                """
                INSERT INTO blood_ngos (
                    doctor_id,
                    ngo_name,
                    phone_number,
                    location,
                    latitude,
                    longitude,
                    updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, now())
                ON CONFLICT (doctor_id, phone_number, ngo_name)
                DO UPDATE SET
                    location = EXCLUDED.location,
                    latitude = EXCLUDED.latitude,
                    longitude = EXCLUDED.longitude,
                    updated_at = now()
                RETURNING (xmax = 0) AS inserted
                """,
                (
                    doctor_id,
                    ngo["ngo_name"],
                    ngo["phone_number"],
                    ngo["location"],
                    ngo.get("latitude"),
                    ngo.get("longitude"),
                ),
            )
            row = cur.fetchone() or {}
            if row.get("inserted"):
                created += 1
            else:
                updated += 1

    return {"created": created, "updated": updated}


def list_blood_donors(doctor_id: str) -> list[dict[str, Any]]:
    with _cursor() as cur:
        cur.execute(
            """
            SELECT *
            FROM blood_donors
            WHERE doctor_id = %s
            ORDER BY created_at DESC
            """,
            (doctor_id,),
        )
        return list(cur.fetchall())


def list_blood_ngos(doctor_id: str) -> list[dict[str, Any]]:
    with _cursor() as cur:
        cur.execute(
            """
            SELECT *
            FROM blood_ngos
            WHERE doctor_id = %s
            ORDER BY created_at DESC
            """,
            (doctor_id,),
        )
        return list(cur.fetchall())


def create_blood_campaign(payload: dict[str, Any]) -> dict[str, Any]:
    return _insert_row("blood_campaigns", payload)


def get_blood_campaign(campaign_id: str) -> dict[str, Any] | None:
    with _cursor() as cur:
        cur.execute(
            "SELECT * FROM blood_campaigns WHERE id = %s LIMIT 1",
            (campaign_id,),
        )
        return cur.fetchone()


def update_blood_campaign(campaign_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    return _update_rows("blood_campaigns", payload, {"id": campaign_id})


def list_call_worker_pools(
    doctor_id: str,
    *,
    is_active: bool | None = True,
) -> list[dict[str, Any]]:
    sql_text = "SELECT * FROM call_worker_pools WHERE doctor_id = %s"
    params: list[Any] = [doctor_id]
    if is_active is not None:
        sql_text += " AND is_active = %s"
        params.append(is_active)
    sql_text += " ORDER BY created_at ASC"

    with _cursor() as cur:
        cur.execute(sql_text, params)
        return list(cur.fetchall())


def create_campaign_attempt(payload: dict[str, Any]) -> dict[str, Any]:
    with _cursor() as cur:
        cur.execute(
            """
            INSERT INTO blood_campaign_donor_attempts (
                campaign_id,
                donor_id,
                worker_pool_id,
                status,
                eligibility_reason,
                message,
                started_at,
                completed_at,
                updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now())
            ON CONFLICT (campaign_id, donor_id)
            DO UPDATE SET
                worker_pool_id = COALESCE(EXCLUDED.worker_pool_id, blood_campaign_donor_attempts.worker_pool_id),
                status = EXCLUDED.status,
                eligibility_reason = EXCLUDED.eligibility_reason,
                message = EXCLUDED.message,
                started_at = COALESCE(EXCLUDED.started_at, blood_campaign_donor_attempts.started_at),
                completed_at = EXCLUDED.completed_at,
                updated_at = now()
            RETURNING *
            """,
            (
                payload["campaign_id"],
                payload["donor_id"],
                payload.get("worker_pool_id"),
                payload.get("status", "queued"),
                payload.get("eligibility_reason"),
                payload.get("message"),
                payload.get("started_at"),
                payload.get("completed_at"),
            ),
        )
        row = cur.fetchone()
    return row or {}


def update_campaign_attempt(attempt_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    return _update_rows("blood_campaign_donor_attempts", payload, {"id": attempt_id})


def list_campaign_attempts(campaign_id: str) -> list[dict[str, Any]]:
    with _cursor() as cur:
        cur.execute(
            """
            SELECT
                a.*,
                d.name AS donor_name,
                d.phone_number AS donor_phone_number,
                d.blood_type AS donor_blood_type,
                d.location AS donor_location,
                d.latitude AS donor_latitude,
                d.longitude AS donor_longitude,
                wp.worker_name
            FROM blood_campaign_donor_attempts a
            JOIN blood_donors d ON d.id = a.donor_id
            LEFT JOIN call_worker_pools wp ON wp.id = a.worker_pool_id
            WHERE a.campaign_id = %s
            ORDER BY a.created_at ASC
            """,
            (campaign_id,),
        )
        return list(cur.fetchall())


# Donor groups that can give red cells to each recipient group. Used for whole
# blood, packed RBC and (as the usual ABO-compatible preference) platelets.
_RED_CELL_COMPATIBLE_DONORS: dict[str, list[str]] = {
    "O-": ["O-"],
    "O+": ["O+", "O-"],
    "A-": ["A-", "O-"],
    "A+": ["A+", "A-", "O+", "O-"],
    "B-": ["B-", "O-"],
    "B+": ["B+", "B-", "O+", "O-"],
    "AB-": ["AB-", "A-", "B-", "O-"],
    "AB+": ["AB+", "AB-", "A+", "A-", "B+", "B-", "O+", "O-"],
}

# Plasma is the reverse of red cells: AB is the universal plasma donor and the
# Rh factor doesn't matter, so only the ABO group is compared.
_PLASMA_COMPATIBLE_ABO: dict[str, list[str]] = {
    "O": ["O", "A", "B", "AB"],
    "A": ["A", "AB"],
    "B": ["B", "AB"],
    "AB": ["AB"],
}


def compatible_donor_blood_types(recipient_blood_type: str, component: str) -> list[str]:
    recipient = (recipient_blood_type or "").strip().upper()
    if component == "plasma":
        abo = recipient.rstrip("+-")
        return [
            f"{group}{rh}"
            for group in _PLASMA_COMPATIBLE_ABO.get(abo, [])
            for rh in ("+", "-")
        ]
    return list(_RED_CELL_COMPATIBLE_DONORS.get(recipient, []))


def list_campaign_eligible_donors(
    campaign_id: str,
    *,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    campaign = get_blood_campaign(campaign_id)
    if not campaign:
        return []
    allowed_types = compatible_donor_blood_types(
        campaign.get("blood_type") or "", campaign.get("component") or "whole_blood"
    )
    if not allowed_types:
        return []

    with _cursor() as cur:
        cur.execute(
            """
            SELECT d.*
            FROM blood_donors d
            JOIN blood_campaigns c ON c.id = %s
            LEFT JOIN blood_campaign_donor_attempts a
                ON a.campaign_id = c.id AND a.donor_id = d.id
            WHERE d.doctor_id = c.doctor_id
              AND UPPER(d.blood_type) = ANY(%s::text[])
              AND a.id IS NULL
              -- Not while another request is calling them, and not if they've
              -- already agreed to donate for another request recently.
              AND NOT EXISTS (
                    SELECT 1 FROM blood_campaign_donor_attempts o
                    WHERE o.donor_id = d.id
                      AND o.campaign_id <> c.id
                      AND (
                            o.status IN ('queued', 'active')
                         OR (o.status = 'accepted' AND o.updated_at > now() - INTERVAL '90 days')
                      )
              )
              AND (
                    CASE
                        WHEN LOWER(d.gender) IN ('male', 'm') THEN d.last_donated_date + INTERVAL '90 days'
                        WHEN LOWER(d.gender) IN ('female', 'f') THEN d.last_donated_date + INTERVAL '120 days'
                        ELSE d.last_donated_date + INTERVAL '120 days'
                    END
                  ) <= CURRENT_DATE
            -- Nearest donors first when both locations are known (a flat-earth
            -- approximation is plenty for ranking within a city); others last.
            ORDER BY
                CASE
                    WHEN d.latitude IS NULL OR d.longitude IS NULL
                      OR c.patient_latitude IS NULL OR c.patient_longitude IS NULL
                    THEN NULL
                    ELSE power(d.latitude - c.patient_latitude, 2)
                       + power((d.longitude - c.patient_longitude)
                               * cos(radians(c.patient_latitude)), 2)
                END ASC NULLS LAST,
                d.created_at ASC
            LIMIT %s OFFSET %s
            """,
            (campaign_id, allowed_types, limit, offset),
        )
        return list(cur.fetchall())


def list_blood_requests(doctor_id: str, limit: int = 50) -> list[dict[str, Any]]:
    """A doctor's blood requests, newest first, with donor-call progress counts."""
    with _cursor() as cur:
        cur.execute(
            """
            SELECT
                c.*,
                COUNT(a.id) AS donors_contacted,
                COUNT(a.id) FILTER (WHERE a.status = 'accepted') AS donors_accepted,
                COUNT(a.id) FILTER (WHERE a.status IN ('queued', 'active')) AS calls_in_progress
            FROM blood_campaigns c
            LEFT JOIN blood_campaign_donor_attempts a ON a.campaign_id = c.id
            WHERE c.doctor_id = %s
            GROUP BY c.id
            ORDER BY c.created_at DESC
            LIMIT %s
            """,
            (doctor_id, limit),
        )
        return _json_safe(list(cur.fetchall()))
