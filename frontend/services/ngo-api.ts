// NGO portal API client. Every call sends the NGO session token issued by
// /api/auth/login (role "ngo"); the backend derives the NGO from that token.

import type {
  FollowUpFilter,
  ImportConfirmResult,
  ImportPreview,
  NgoDashboard,
  NgoErrorDetail,
  NgoImportDetail,
  NgoPatientCreateResult,
  NgoPatientDetail,
  NgoPatientInput,
  NgoPatientListItem,
  Paginated,
  PatientField,
  RegistrationSource,
} from "@/types/ngo";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export class NgoApiError extends Error {
  status: number;
  detail: NgoErrorDetail;

  constructor(status: number, detail: NgoErrorDetail) {
    super(detail.message);
    this.status = status;
    this.detail = detail;
  }
}

type PydanticIssue = { loc?: (string | number)[]; msg?: string };

export function toNgoErrorDetail(status: number, body: unknown): NgoErrorDetail {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (detail && typeof detail === "object" && !Array.isArray(detail) && "message" in detail) {
    return detail as NgoErrorDetail;
  }
  if (Array.isArray(detail)) {
    // FastAPI request-validation errors: map body.<field> to field errors.
    const fieldErrors: Record<string, string> = {};
    for (const issue of detail as PydanticIssue[]) {
      const field = issue.loc?.[issue.loc.length - 1];
      if (typeof field === "string" && !fieldErrors[field]) {
        fieldErrors[field] = issue.msg || "Invalid value";
      }
    }
    return { code: "validation_error", message: "Please correct the highlighted fields", field_errors: fieldErrors };
  }
  if (typeof detail === "string") return { code: "error", message: detail };
  if (status === 401) return { code: "unauthorized", message: "Your session has expired. Please sign in again." };
  return { code: "error", message: `Request failed (${status})` };
}

async function request<T>(token: string, path: string, init: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}/api/ngo${path}`, {
      ...init,
      headers: { ...(init.headers || {}), Authorization: `Bearer ${token}` },
    });
  } catch {
    throw new NgoApiError(0, { code: "network_error", message: "Could not reach the server. Check your connection." });
  }
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new NgoApiError(response.status, toNgoErrorDetail(response.status, body));
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

async function download(token: string, path: string): Promise<{ blob: Blob; filename: string }> {
  const response = await fetch(`${API_URL}/api/ngo${path}`, {
    headers: { Authorization: `Bearer ${token}` },
  }).catch(() => null);
  if (!response) throw new NgoApiError(0, { code: "network_error", message: "Could not reach the server." });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new NgoApiError(response.status, toNgoErrorDetail(response.status, body));
  }
  const disposition = response.headers.get("Content-Disposition") || "";
  const filename = /filename="([^"]+)"/.exec(disposition)?.[1] || "download.csv";
  return { blob: await response.blob(), filename };
}

// ---------------------------------------------------------------------------
// NGO authentication (public; separate from doctor/patient /api/auth/*)
// ---------------------------------------------------------------------------

export interface NgoSession {
  token: string;
  expires_at: string;
  user: {
    sub: string;
    name: string;
    email: string;
    username?: string;
    mobile?: string;
    role: "ngo";
    account_id: string;
    ngo_id: string;
    ngo_name: string;
    ngo_member_role: "admin" | "staff";
  };
}

export interface NgoRegisterInput {
  ngo_name: string;
  city?: string;
  /** NGO Darpan ID: exactly 5 digits. */
  darpan_id: string;
  contact_phone?: string;
  admin_name: string;
  email: string;
  mobile?: string;
  password: string;
  otp_code: string;
}

async function publicPost<T>(path: string, body: unknown): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}/api/ngo${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    throw new NgoApiError(0, { code: "network_error", message: "Could not reach the server. Check your connection." });
  }
  if (!response.ok) {
    const data = await response.json().catch(() => null);
    throw new NgoApiError(response.status, toNgoErrorDetail(response.status, data));
  }
  return response.json() as Promise<T>;
}

export function ngoLogin(email: string, password: string) {
  return publicPost<NgoSession>("/auth/login", { email, password });
}

export function sendNgoRegistrationOtp(email: string) {
  return publicPost<{ sent: boolean; expires_in_minutes: number }>("/auth/otp/send", { email });
}

export function registerNgo(input: NgoRegisterInput) {
  return publicPost<NgoSession>("/auth/register", input);
}

// ---------------------------------------------------------------------------
// Portal
// ---------------------------------------------------------------------------

export function getNgoDashboard(token: string) {
  return request<NgoDashboard>(token, "/dashboard");
}

export interface NgoPatientQuery {
  search?: string;
  source?: RegistrationSource | "";
  follow_up?: FollowUpFilter | "";
  registered_from?: string;
  registered_to?: string;
  import_id?: string;
  page?: number;
  page_size?: number;
}

export function listNgoPatients(token: string, query: NgoPatientQuery = {}) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== null && value !== "") params.set(key, String(value));
  }
  const qs = params.toString();
  return request<Paginated<NgoPatientListItem>>(token, `/patients${qs ? `?${qs}` : ""}`);
}

export function getNgoPatient(token: string, patientId: string) {
  return request<NgoPatientDetail>(token, `/patients/${encodeURIComponent(patientId)}`);
}

export function createNgoPatient(token: string, payload: NgoPatientInput, idempotencyKey: string) {
  return request<NgoPatientCreateResult>(token, "/patients", {
    method: "POST",
    headers: { "Content-Type": "application/json", "Idempotency-Key": idempotencyKey },
    body: JSON.stringify(payload),
  });
}

export function previewNgoImport(
  token: string,
  file: File,
  defaultDoctorId: string,
  mapping?: Partial<Record<PatientField, string>>,
) {
  const form = new FormData();
  form.append("file", file);
  if (defaultDoctorId) form.append("default_doctor_id", defaultDoctorId);
  if (mapping) form.append("column_mapping", JSON.stringify(mapping));
  return request<ImportPreview>(token, "/patients/import/preview", { method: "POST", body: form });
}

export function confirmNgoImport(token: string, importId: string, approvedReviewRows: number[]) {
  return request<ImportConfirmResult>(token, "/patients/import/confirm", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ import_id: importId, approved_review_rows: approvedReviewRows }),
  });
}

export function getNgoImport(token: string, importId: string) {
  return request<NgoImportDetail>(token, `/imports/${encodeURIComponent(importId)}`);
}

export function downloadNgoImportErrors(token: string, importId: string) {
  return download(token, `/imports/${encodeURIComponent(importId)}/errors`);
}

export function ngoImportTemplateUrl() {
  return `${API_URL}/api/ngo/patients/import/template`;
}

export function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
