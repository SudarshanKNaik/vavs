from __future__ import annotations

"""
NGO portal routes, mounted under /api/ngo.

Every route except sign-up, login and the CSV template requires a server-verified NGO session
(``Authorization: Bearer <token>`` issued by POST /api/ngo/auth/login or
/api/ngo/auth/register). The NGO is always derived from that session, never from the
request.
"""

import json
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, Response, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app.core.config import settings
from app.services import ngo_service
from app.services.ngo_service import NgoContext, NgoError

router = APIRouter(prefix="/ngo", tags=["ngo"])


# ---------------------------------------------------------------------------
# Auth dependency
# ---------------------------------------------------------------------------


def _bearer_token(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        return ""
    return authorization[7:].strip()


async def require_ngo_user(
    authorization: str | None = Header(default=None),
) -> NgoContext:
    token = _bearer_token(authorization)
    ctx = await run_in_threadpool(ngo_service.get_ngo_context, token) if token else None
    if not ctx:
        raise HTTPException(
            status_code=401,
            detail={"code": "unauthorized", "message": "NGO sign-in required"},
            headers={"WWW-Authenticate": "Bearer"},
        )
    return ctx


def _error_response(exc: NgoError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.as_detail()})


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class NgoPatientCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    phone: str = Field(min_length=1, max_length=20)
    doctor_id: str = Field(min_length=1, max_length=64)
    dob: str | None = Field(default=None, max_length=20)
    mrn: str | None = Field(default=None, max_length=64)
    insurance: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=1000)
    confirm_possible_duplicate: bool = False


class ImportConfirmRequest(BaseModel):
    import_id: str
    approved_review_rows: list[int] = Field(default_factory=list, max_length=10000)


class NgoLoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=200)


class NgoOtpRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)


class NgoRegisterRequest(BaseModel):
    ngo_name: str = Field(min_length=1, max_length=200)
    city: str | None = Field(default=None, max_length=100)
    darpan_id: str = Field(default="", max_length=10)  # 5 digits; validated in the service
    contact_phone: str | None = Field(default=None, max_length=20)
    admin_name: str = Field(min_length=1, max_length=200)
    email: str = Field(min_length=3, max_length=254)
    mobile: str = Field(default="", max_length=20)
    password: str = Field(min_length=8, max_length=200)
    otp_code: str = Field(min_length=6, max_length=6)


# ---------------------------------------------------------------------------
# NGO authentication (separate from doctor/patient /api/auth/*)
# ---------------------------------------------------------------------------


@router.post("/auth/otp/send")
async def ngo_send_registration_otp(body: NgoOtpRequest):
    from app.services.smtp_service import send_otp_email

    try:
        code = await run_in_threadpool(ngo_service.create_registration_otp, body.email)
    except NgoError as exc:
        return _error_response(exc)
    try:
        await send_otp_email(body.email.strip().lower(), code, "NGO registration")
    except Exception:
        return _error_response(
            NgoError(502, "email_failed", "Could not send the verification email. Please try again.")
        )
    return {"sent": True, "expires_in_minutes": 10}


@router.post("/auth/register", status_code=201)
async def ngo_register(body: NgoRegisterRequest):
    try:
        return await run_in_threadpool(lambda: ngo_service.register_ngo(**body.model_dump()))
    except NgoError as exc:
        return _error_response(exc)


@router.post("/auth/login")
async def ngo_login(body: NgoLoginRequest):
    try:
        return await run_in_threadpool(ngo_service.login_ngo_account, body.email, body.password)
    except RuntimeError:
        return _error_response(NgoError(401, "invalid_credentials", "Invalid email or password"))


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------


@router.get("/me")
async def ngo_me(ctx: NgoContext = Depends(require_ngo_user)):
    return {
        "account_id": ctx.account_id,
        "ngo_id": ctx.ngo_id,
        "ngo_name": ctx.ngo_name,
        "email": ctx.email,
        "username": ctx.username,
        "member_role": ctx.member_role,
    }


@router.post("/auth/logout", status_code=204)
async def ngo_logout(
    authorization: str | None = Header(default=None),
    ctx: NgoContext = Depends(require_ngo_user),
):
    await run_in_threadpool(ngo_service.revoke_ngo_session, _bearer_token(authorization))
    await run_in_threadpool(ngo_service.record_audit, ctx.ngo_id, ctx.account_id, "logout")
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Dashboard + patients
# ---------------------------------------------------------------------------


@router.get("/dashboard")
async def ngo_dashboard(ctx: NgoContext = Depends(require_ngo_user)):
    return await run_in_threadpool(ngo_service.get_dashboard, ctx.ngo_id)


@router.get("/patients")
async def ngo_list_patients(
    ctx: NgoContext = Depends(require_ngo_user),
    search: str | None = Query(default=None, max_length=100),
    source: str | None = Query(default=None, pattern="^(manual|csv)$"),
    follow_up: str | None = Query(default=None, pattern="^(pending|none)$"),
    registered_from: date | None = None,
    registered_to: date | None = None,
    import_id: str | None = Query(default=None, max_length=64),
    page: int = Query(default=1, ge=1, le=10000),
    page_size: int = Query(default=20, ge=1, le=100),
):
    if import_id and not ngo_service._is_uuid(import_id):
        raise HTTPException(status_code=422, detail={"code": "validation_error", "message": "Invalid import id"})
    return await run_in_threadpool(
        lambda: ngo_service.list_ngo_patients(
            ctx.ngo_id,
            search=search,
            source=source,
            follow_up=follow_up,
            registered_from=registered_from,
            registered_to=registered_to,
            import_id=import_id,
            page=page,
            page_size=page_size,
        )
    )


@router.post("/patients", status_code=201)
async def ngo_create_patient(
    body: NgoPatientCreate,
    ctx: NgoContext = Depends(require_ngo_user),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", max_length=100),
):
    payload = body.model_dump(exclude={"confirm_possible_duplicate"})
    try:
        return await run_in_threadpool(
            lambda: ngo_service.register_manual_patient(
                ctx,
                payload,
                idempotency_key=idempotency_key,
                confirm_possible_duplicate=body.confirm_possible_duplicate,
            )
        )
    except NgoError as exc:
        return _error_response(exc)


@router.get("/patients/{patient_id}")
async def ngo_get_patient(patient_id: str, ctx: NgoContext = Depends(require_ngo_user)):
    try:
        return await run_in_threadpool(ngo_service.get_ngo_patient, ctx, patient_id)
    except NgoError as exc:
        return _error_response(exc)


# ---------------------------------------------------------------------------
# CSV import
# ---------------------------------------------------------------------------


@router.get("/patients/import/template")
async def ngo_import_template():
    return Response(
        content=ngo_service.csv_template(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="caresync_ngo_patients_template.csv"'},
    )


@router.post("/patients/import/preview")
async def ngo_import_preview(
    ctx: NgoContext = Depends(require_ngo_user),
    file: UploadFile = File(...),
    default_doctor_id: str | None = Form(default=None),
    column_mapping: str | None = Form(default=None),
):
    file_name = file.filename or "upload.csv"
    if not file_name.lower().endswith(".csv"):
        return _error_response(NgoError(415, "unsupported_file_type", "Only .csv files are accepted"))

    content = await file.read(settings.ngo_csv_max_bytes + 1)
    if len(content) > settings.ngo_csv_max_bytes:
        return _error_response(
            NgoError(
                413,
                "file_too_large",
                f"The file exceeds the {settings.ngo_csv_max_bytes // 1024} KB limit",
            )
        )

    mapping: dict[str, str] | None = None
    if column_mapping:
        try:
            parsed = json.loads(column_mapping)
            if not isinstance(parsed, dict) or not all(
                isinstance(k, str) and (v is None or isinstance(v, str)) for k, v in parsed.items()
            ):
                raise ValueError
            mapping = {k: v for k, v in parsed.items() if v}
        except ValueError:
            return _error_response(NgoError(400, "invalid_mapping", "column_mapping must be a JSON object"))

    try:
        return await run_in_threadpool(
            lambda: ngo_service.preview_import(
                ctx,
                file_name=file_name,
                content=content,
                default_doctor_id=(default_doctor_id or "").strip() or None,
                mapping_override=mapping,
            )
        )
    except NgoError as exc:
        return _error_response(exc)


@router.post("/patients/import/confirm")
async def ngo_import_confirm(body: ImportConfirmRequest, ctx: NgoContext = Depends(require_ngo_user)):
    try:
        return await run_in_threadpool(
            lambda: ngo_service.confirm_import(
                ctx, body.import_id, approved_review_rows=body.approved_review_rows
            )
        )
    except NgoError as exc:
        return _error_response(exc)


@router.get("/imports")
async def ngo_list_imports(
    ctx: NgoContext = Depends(require_ngo_user),
    page: int = Query(default=1, ge=1, le=10000),
    page_size: int = Query(default=20, ge=1, le=100),
):
    return await run_in_threadpool(
        lambda: ngo_service.list_imports(ctx.ngo_id, page=page, page_size=page_size)
    )


@router.get("/imports/{import_id}")
async def ngo_get_import(import_id: str, ctx: NgoContext = Depends(require_ngo_user)):
    try:
        return await run_in_threadpool(ngo_service.get_import, ctx, import_id)
    except NgoError as exc:
        return _error_response(exc)


@router.get("/imports/{import_id}/errors")
async def ngo_import_errors(import_id: str, ctx: NgoContext = Depends(require_ngo_user)):
    try:
        content, filename = await run_in_threadpool(ngo_service.build_error_csv, ctx, import_id)
    except NgoError as exc:
        return _error_response(exc)
    return Response(
        content=content,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/audit-events")
async def ngo_audit_events(
    ctx: NgoContext = Depends(require_ngo_user),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[dict[str, Any]]:
    return await run_in_threadpool(ngo_service.list_audit_events, ctx.ngo_id, limit)
