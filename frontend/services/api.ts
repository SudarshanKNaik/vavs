// This is api.ts and this is used for handling requests to the FastAPI backend.

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export interface DoctorListItem {
  id: string;
  name: string;
  specialty: string;
  language: string;
  consultation_type: string;
  fee: number;
  rating_avg: number;
  rating_count: number;
  is_available: boolean;
  available_now: boolean;
  next_slot_start: string | null;
}

export interface DoctorAvailabilitySlot {
  id: string;
  doctor_id: string;
  slot_start: string;
  slot_end: string;
  status: string;
}

export interface DoctorFeedbackItem {
  id: string;
  doctor_id: string;
  patient_id?: string | null;
  rating: number;
  comment?: string | null;
  created_at: string;
}

export interface DoctorManagedSlot extends DoctorAvailabilitySlot {
  reserved_until?: string | null;
  reserved_by?: string | null;
  created_at?: string;
  updated_at?: string;
}

export interface DoctorAvailabilitySettings {
  doctor_id: string;
  is_available: boolean;
  pending_today_appointments: number;
  rescheduled_appointments?: number;
}

export interface PatientPortalProfile {
  id: string;
  auth_user_id: string;
  email: string;
  name: string;
  phone: string;
  doctor_id: string;
  created_at: string;
}

export interface PatientPortalAppointment {
  id: string;
  doctor_id: string;
  patient_id: string;
  slot_id: string;
  status: string;
  consultation_type: string;
  created_at: string;
  doctor_name?: string;
  doctor_specialty?: string;
  slot_start?: string;
  slot_end?: string;
  report_id?: string | null;
  call_log_id?: string | null;
  report_title?: string | null;
  report_date?: string | null;
}

export interface DoctorAppointmentItem {
  id: string;
  doctor_id: string;
  patient_id: string;
  slot_id: string;
  status: string;
  consultation_type: string;
  notes?: string | null;
  created_at: string;
  patient_name?: string;
  patient_phone?: string;
  slot_start?: string;
  slot_end?: string;
  report_id?: string | null;
  call_log_id?: string | null;
  call_origin?: Record<string, unknown> | null;
  report_title?: string | null;
  report_date?: string | null;
}

export interface DoctorPortalPatientItem {
  id: string;
  doctor_id?: string | null;
  name: string;
  phone: string;
  dob?: string | null;
  mrn?: string | null;
  insurance?: string | null;
  risk_level?: string | null;
  appointment_count?: number;
  last_appointment_at?: string | null;
}

export interface ConsultationRoom {
  id: string;
  appointment_id: string;
  provider: string;
  room_name: string;
  room_url?: string | null;
}

export interface ConsultationMessage {
  id: string;
  appointment_id: string;
  room_id?: string | null;
  sender_type: "doctor" | "patient" | "system";
  sender_id?: string | null;
  message: string;
  created_at: string;
}

export interface ReportItem {
  id: string;
  workflow_id?: string | null;
  patient_id?: string | null;
  call_log_id?: string | null;
  report_data?: Record<string, unknown>;
  created_at: string;
}

export interface SlotOption {
  id: string;
  slot_start: string;
  slot_end: string;
  status: string;
}

export interface CallContextSummary {
  report_id?: string | null;
  report_title?: string;
  report_date?: string;
  doctor_name?: string;
  doctor_specialty?: string;
  patient_name?: string;
}

export interface CallStatusResult {
  status: string;
  call_outcome?: string;
  patient_confirmed?: boolean;
  confirmed_date?: string;
  confirmed_time?: string;
  appointment_id?: string | null;
  call_log_id?: string;
  conversation_id?: string;
  call_sid?: string;
  transcript?: string;
  context_summary?: CallContextSummary;
  message?: string;
  conversation_status?: string;
}

export interface FollowUpCronConfig {
  enabled: boolean;
  running: boolean;
  delay_minutes: number;
  poll_interval_seconds: number;
  max_attempts: number;
  batch_size: number;
  started_at?: string | null;
  last_tick_at?: string | null;
}

export interface FollowUpJob {
  id: string;
  call_log_id: string;
  workflow_id?: string | null;
  doctor_id?: string | null;
  patient_id?: string | null;
  reason?: string | null;
  status: string;
  scheduled_for: string;
  attempt_count: number;
  max_attempts: number;
  last_run_at?: string | null;
  completed_at?: string | null;
  last_error?: string | null;
  metadata?: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
}

export interface FollowUpJobLog {
  id: string;
  job_id: string;
  level: string;
  message: string;
  metadata?: Record<string, unknown> | null;
  created_at: string;
}

export interface ExecuteWorkflowResult {
  call_log_id: string | null;
  status: string;
  execution_log: unknown[];
  context_summary?: CallContextSummary;
  message?: string;
}

export interface ExtractPdfAndExecuteResult {
  call_log_id: string | null;
  pdf_document_id?: string | null;
  status: string;
  uploaded_file_type?: string;
  patient_summary_email_sent?: boolean;
  patient_summary_email_message?: string;
  lab_results_found?: number;
  patient_info_extracted?: Record<string, unknown>;
  execution_log: unknown[];
}

// ---------------------------------------------------------------------------
// Lab event
// ---------------------------------------------------------------------------

export async function simulateLabEvent(
  triggerType: string,
  patientId: string,
  doctorId?: string,
  metadata?: Record<string, unknown>,
) {
  const response = await fetch(`${API_URL}/api/lab-event`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      trigger_type: triggerType,
      patient_id: patientId,
      doctor_id: doctorId ?? null,
      metadata: metadata ?? {},
    }),
  });
  return response.json();
}

// ---------------------------------------------------------------------------
// Doctor directory + availability (Phase 1)
// ---------------------------------------------------------------------------

export async function listDoctors(filters?: {
  specialty?: string;
  language?: string;
  consultation_type?: string;
  available_now?: boolean;
}) {
  const params = new URLSearchParams();
  if (filters?.specialty) params.set("specialty", filters.specialty);
  if (filters?.language) params.set("language", filters.language);
  if (filters?.consultation_type)
    params.set("consultation_type", filters.consultation_type);
  if (typeof filters?.available_now === "boolean") {
    params.set("available_now", String(filters.available_now));
  }

  const qs = params.toString();
  const response = await fetch(`${API_URL}/api/doctors${qs ? `?${qs}` : ""}`);
  if (!response.ok) {
    const detail = await response.text().catch(() => response.statusText);
    throw new Error(`Failed to fetch doctors (${response.status}): ${detail}`);
  }
  return response.json() as Promise<DoctorListItem[]>;
}

export async function listDoctorAvailability(doctorId: string) {
  const response = await fetch(
    `${API_URL}/api/doctors/${doctorId}/availability`,
  );
  if (!response.ok) {
    const detail = await response.text().catch(() => response.statusText);
    throw new Error(
      `Failed to fetch availability (${response.status}): ${detail}`,
    );
  }
  return response.json() as Promise<DoctorAvailabilitySlot[]>;
}

export async function listDoctorFeedback(doctorId: string, limit = 20) {
  const response = await fetch(
    `${API_URL}/api/doctors/${doctorId}/feedback?limit=${limit}`,
  );
  if (!response.ok) {
    const detail = await response.text().catch(() => response.statusText);
    throw new Error(
      `Failed to fetch doctor feedback (${response.status}): ${detail}`,
    );
  }
  return response.json() as Promise<DoctorFeedbackItem[]>;
}

export async function submitDoctorFeedback(
  doctorId: string,
  payload: { rating: number; comment?: string; patient_id?: string },
) {
  const params = new URLSearchParams();
  if (payload.patient_id) params.set("patient_id", payload.patient_id);
  const qs = params.toString();

  const response = await fetch(
    `${API_URL}/api/doctors/${doctorId}/feedback${qs ? `?${qs}` : ""}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        rating: payload.rating,
        comment: payload.comment ?? null,
        tags: [],
      }),
    },
  );

  if (!response.ok) {
    const detail = await response.text().catch(() => response.statusText);
    throw new Error(
      `Failed to submit feedback (${response.status}): ${detail}`,
    );
  }

  return response.json();
}

export async function listDoctorSlots(
  doctorId: string,
  options?: { includePast?: boolean; status?: string },
) {
  const params = new URLSearchParams();
  if (typeof options?.includePast === "boolean") {
    params.set("include_past", String(options.includePast));
  }
  if (options?.status) {
    params.set("status", options.status);
  }
  const qs = params.toString();

  const response = await fetch(
    `${API_URL}/api/doctors/${doctorId}/slots${qs ? `?${qs}` : ""}`,
  );
  if (!response.ok) {
    const detail = await response.text().catch(() => response.statusText);
    throw new Error(
      `Failed to fetch doctor slots (${response.status}): ${detail}`,
    );
  }
  return response.json() as Promise<DoctorManagedSlot[]>;
}

export async function getDoctorAvailabilitySettings(doctorId: string) {
  const response = await fetch(
    `${API_URL}/api/doctors/${doctorId}/availability/settings`,
  );
  if (!response.ok) {
    const detail = await response.text().catch(() => response.statusText);
    throw new Error(
      `Failed to fetch doctor availability settings (${response.status}): ${detail}`,
    );
  }
  return response.json() as Promise<DoctorAvailabilitySettings>;
}

export async function updateDoctorAvailabilitySettings(
  doctorId: string,
  payload: { is_available: boolean; confirm_reschedule_today?: boolean },
) {
  const response = await fetch(
    `${API_URL}/api/doctors/${doctorId}/availability/settings`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );

  if (!response.ok) {
    let detail: unknown = null;
    try {
      detail = await response.json();
    } catch {
      detail = await response.text().catch(() => response.statusText);
    }

    const error = new Error(
      `Failed to update doctor availability settings (${response.status}): ${typeof detail === "string" ? detail : JSON.stringify(detail)}`,
    ) as Error & { status?: number; detail?: unknown };
    error.status = response.status;
    error.detail = detail;
    throw error;
  }

  return response.json() as Promise<DoctorAvailabilitySettings>;
}

export async function createDoctorSlot(
  doctorId: string,
  payload: { slot_start: string; slot_end: string; status?: string },
) {
  const response = await fetch(`${API_URL}/api/doctors/${doctorId}/slots`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const detail = await response.text().catch(() => response.statusText);
    throw new Error(`Failed to create slot (${response.status}): ${detail}`);
  }
  return response.json() as Promise<DoctorManagedSlot>;
}

export async function updateDoctorSlot(
  doctorId: string,
  slotId: string,
  payload: { slot_start?: string; slot_end?: string; status?: string },
) {
  const response = await fetch(
    `${API_URL}/api/doctors/${doctorId}/slots/${slotId}`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
  if (!response.ok) {
    const detail = await response.text().catch(() => response.statusText);
    throw new Error(`Failed to update slot (${response.status}): ${detail}`);
  }
  return response.json() as Promise<DoctorManagedSlot>;
}

export async function deleteDoctorSlot(doctorId: string, slotId: string) {
  const response = await fetch(
    `${API_URL}/api/doctors/${doctorId}/slots/${slotId}`,
    {
      method: "DELETE",
    },
  );
  if (!response.ok) {
    const detail = await response.text().catch(() => response.statusText);
    throw new Error(`Failed to delete slot (${response.status}): ${detail}`);
  }
}

export async function reserveSlot(
  slotId: string,
  payload: { patient_id: string; hold_minutes?: number },
) {
  const response = await fetch(`${API_URL}/api/slots/${slotId}/reserve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    const detail = await response.text().catch(() => response.statusText);
    throw new Error(`Failed to reserve slot (${response.status}): ${detail}`);
  }
  return response.json();
}

export async function registerPatientPortal(payload: {
  auth_user_id: string;
  email: string;
  name: string;
  phone: string;
  doctor_id: string;
}) {
  const response = await fetch(`${API_URL}/api/patient-portal/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const detail = await response.text().catch(() => response.statusText);
    throw new Error(
      `Failed to register patient profile (${response.status}): ${detail}`,
    );
  }
  return response.json() as Promise<PatientPortalProfile>;
}

export async function getPatientPortalMe(authUserId: string) {
  const params = new URLSearchParams({ auth_user_id: authUserId });
  const response = await fetch(
    `${API_URL}/api/patient-portal/me?${params.toString()}`,
  );
  if (response.status === 404) return null;
  if (!response.ok) {
    const detail = await response.text().catch(() => response.statusText);
    throw new Error(
      `Failed to fetch patient profile (${response.status}): ${detail}`,
    );
  }
  return response.json() as Promise<PatientPortalProfile>;
}

export async function listPatientPortalAppointments(authUserId: string) {
  const params = new URLSearchParams({ auth_user_id: authUserId });
  const response = await fetch(
    `${API_URL}/api/patient-portal/appointments?${params.toString()}`,
  );
  if (!response.ok) {
    const detail = await response.text().catch(() => response.statusText);
    throw new Error(
      `Failed to fetch appointments (${response.status}): ${detail}`,
    );
  }
  return response.json() as Promise<PatientPortalAppointment[]>;
}

export async function bookPatientPortalSlot(
  slotId: string,
  payload: { auth_user_id: string; consultation_type?: string; notes?: string },
) {
  const response = await fetch(
    `${API_URL}/api/patient-portal/slots/${slotId}/book`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
  if (!response.ok) {
    const detail = await response.text().catch(() => response.statusText);
    throw new Error(`Failed to book slot (${response.status}): ${detail}`);
  }
  return response.json() as Promise<PatientPortalAppointment>;
}

export async function listDoctorAppointments(doctorId: string) {
  const params = new URLSearchParams({ doctor_id: doctorId });
  const response = await fetch(
    `${API_URL}/api/appointments?${params.toString()}`,
  );
  if (!response.ok) {
    const detail = await response.text().catch(() => response.statusText);
    throw new Error(
      `Failed to fetch doctor appointments (${response.status}): ${detail}`,
    );
  }
  return response.json() as Promise<DoctorAppointmentItem[]>;
}

export async function updateDoctorAppointment(
  appointmentId: string,
  payload: {
    doctor_id: string;
    status?: string;
    consultation_type?: string;
    notes?: string;
  },
) {
  const response = await fetch(`${API_URL}/api/appointments/${appointmentId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const detail = await response.text().catch(() => response.statusText);
    throw new Error(
      `Failed to update appointment (${response.status}): ${detail}`,
    );
  }
  return response.json() as Promise<DoctorAppointmentItem>;
}

export async function getOrCreateConsultationRoom(
  appointmentId: string,
  payload: {
    actor_role: "doctor" | "patient";
    actor_id: string;
    provider?: string;
  },
) {
  const response = await fetch(
    `${API_URL}/api/appointments/${appointmentId}/consultation-room`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
  if (!response.ok) {
    const detail = await response.text().catch(() => response.statusText);
    throw new Error(
      `Failed to open consultation room (${response.status}): ${detail}`,
    );
  }
  return response.json() as Promise<ConsultationRoom>;
}

export async function listConsultationMessages(
  appointmentId: string,
  actorRole: "doctor" | "patient",
  actorId: string,
) {
  const params = new URLSearchParams({
    actor_role: actorRole,
    actor_id: actorId,
  });
  const response = await fetch(
    `${API_URL}/api/appointments/${appointmentId}/messages?${params.toString()}`,
  );
  if (!response.ok) {
    const detail = await response.text().catch(() => response.statusText);
    throw new Error(
      `Failed to fetch consultation messages (${response.status}): ${detail}`,
    );
  }
  return response.json() as Promise<ConsultationMessage[]>;
}

export async function createConsultationMessage(
  appointmentId: string,
  payload: {
    actor_role: "doctor" | "patient";
    actor_id: string;
    message: string;
  },
) {
  const response = await fetch(
    `${API_URL}/api/appointments/${appointmentId}/messages`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
  if (!response.ok) {
    const detail = await response.text().catch(() => response.statusText);
    throw new Error(
      `Failed to send consultation message (${response.status}): ${detail}`,
    );
  }
  return response.json() as Promise<ConsultationMessage>;
}

export async function cancelPatientPortalAppointment(
  appointmentId: string,
  payload: { auth_user_id: string; reason?: string },
) {
  const response = await fetch(
    `${API_URL}/api/patient-portal/appointments/${appointmentId}/cancel`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
  if (!response.ok) {
    const detail = await response.text().catch(() => response.statusText);
    throw new Error(
      `Failed to cancel appointment (${response.status}): ${detail}`,
    );
  }
  return response.json() as Promise<PatientPortalAppointment>;
}

export async function reschedulePatientPortalAppointment(
  appointmentId: string,
  payload: {
    auth_user_id: string;
    new_slot_id: string;
    consultation_type?: string;
    notes?: string;
  },
) {
  const response = await fetch(
    `${API_URL}/api/patient-portal/appointments/${appointmentId}/reschedule`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
  if (!response.ok) {
    const detail = await response.text().catch(() => response.statusText);
    throw new Error(
      `Failed to reschedule appointment (${response.status}): ${detail}`,
    );
  }
  return response.json() as Promise<PatientPortalAppointment>;
}

// ---------------------------------------------------------------------------
// Workflow CRUD
// ---------------------------------------------------------------------------

export async function listWorkflows(doctorId?: string, status?: string) {
  const params = new URLSearchParams();
  if (doctorId) params.set("doctor_id", doctorId);
  if (status) params.set("status", status);
  const qs = params.toString();
  const response = await fetch(`${API_URL}/api/workflows${qs ? `?${qs}` : ""}`);
  if (!response.ok) {
    const detail = await response.text().catch(() => response.statusText);
    throw new Error(
      `Failed to fetch workflows (${response.status}): ${detail}`,
    );
  }
  return response.json();
}

export async function getWorkflow(workflowId: string) {
  const response = await fetch(`${API_URL}/api/workflows/${workflowId}`);
  return response.json();
}

export async function createWorkflow(payload: {
  doctor_id: string;
  name: string;
  description?: string;
  category?: string;
  status?: string;
  nodes?: unknown[];
  edges?: unknown[];
}) {
  const response = await fetch(`${API_URL}/api/workflows`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return response.json();
}

export async function updateWorkflow(
  workflowId: string,
  payload: {
    name?: string;
    description?: string;
    category?: string;
    status?: string;
    nodes?: unknown[];
    edges?: unknown[];
  },
) {
  const response = await fetch(`${API_URL}/api/workflows/${workflowId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return response.json();
}

export async function deleteWorkflow(workflowId: string) {
  const response = await fetch(`${API_URL}/api/workflows/${workflowId}`, {
    method: "DELETE",
  });
  return response;
}

export interface WorkflowAIGenerateResult {
  workflow_name: string;
  workflow_description: string;
  nodes: unknown[];
  edges: unknown[];
  notes: string[];
  warnings: string[];
}

export interface WorkflowTemplateItem {
  id: string;
  name: string;
  description: string;
  category: string;
  use_case: string;
  nodes: unknown[];
  edges: unknown[];
}

export interface DeepgramTranscriptionResult {
  transcript: string;
  model: string;
}

export async function transcribeAudioWithDeepgram(
  audioBlob: Blob,
): Promise<DeepgramTranscriptionResult> {
  const formData = new FormData();

  let extension = "webm";
  if (audioBlob.type.includes("ogg")) extension = "ogg";
  if (audioBlob.type.includes("mp4") || audioBlob.type.includes("mpeg")) {
    extension = "m4a";
  }

  formData.append("file", audioBlob, `speech.${extension}`);

  let response: Response;
  try {
    response = await fetch(`${API_URL}/api/speech/deepgram/transcribe`, {
      method: "POST",
      body: formData,
    });
  } catch (err: unknown) {
    const errMsg = err instanceof Error ? err.message : "Network error";
    throw new Error(
      `Could not reach transcription service at ${API_URL}. Start backend and verify CORS/network settings. (${errMsg})`,
    );
  }

  if (!response.ok) {
    const detail = await response.text().catch(() => response.statusText);
    throw new Error(`Deepgram transcription failed (${response.status}): ${detail}`);
  }

  return response.json() as Promise<DeepgramTranscriptionResult>;
}

export async function generateWorkflowFromPrompt(payload: {
  prompt: string;
  doctor_id?: string | null;
}): Promise<WorkflowAIGenerateResult> {
  const response = await fetch(`${API_URL}/api/workflows/ai/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const detail = await response.text().catch(() => response.statusText);
    throw new Error(
      `Failed to generate workflow with AI (${response.status}): ${detail}`,
    );
  }
  return response.json() as Promise<WorkflowAIGenerateResult>;
}

export async function listWorkflowTemplates(): Promise<WorkflowTemplateItem[]> {
  const response = await fetch(`${API_URL}/api/workflows/templates`);
  if (!response.ok) {
    const detail = await response.text().catch(() => response.statusText);
    throw new Error(
      `Failed to fetch workflow templates (${response.status}): ${detail}`,
    );
  }
  return response.json() as Promise<WorkflowTemplateItem[]>;
}

export async function createWorkflowFromTemplate(
  templateId: string,
  payload: {
    doctor_id: string;
    name?: string;
    description?: string;
    status?: string;
  },
) {
  const response = await fetch(
    `${API_URL}/api/workflows/templates/${templateId}/create`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
  if (!response.ok) {
    const detail = await response.text().catch(() => response.statusText);
    throw new Error(
      `Failed to create workflow from template (${response.status}): ${detail}`,
    );
  }
  return response.json();
}

// ---------------------------------------------------------------------------
// Patients
// ---------------------------------------------------------------------------

export async function listPatients(doctorId?: string) {
  const params = new URLSearchParams();
  if (doctorId) params.set("doctor_id", doctorId);
  const qs = params.toString();
  const response = await fetch(`${API_URL}/api/patients${qs ? `?${qs}` : ""}`);
  return response.json();
}

export async function listDoctorPortalPatients(doctorId: string) {
  const params = new URLSearchParams({ doctor_id: doctorId });
  const response = await fetch(
    `${API_URL}/api/patients/doctor-portal?${params.toString()}`,
  );
  if (!response.ok) {
    const detail = await response.text().catch(() => response.statusText);
    throw new Error(
      `Failed to fetch doctor portal patients (${response.status}): ${detail}`,
    );
  }
  return response.json() as Promise<DoctorPortalPatientItem[]>;
}

export async function getPatient(patientId: string) {
  const response = await fetch(`${API_URL}/api/patients/${patientId}`);
  if (!response.ok) {
    throw new Error(`Failed to fetch patient (${response.status})`);
  }
  return response.json();
}

export async function createPatient(payload: {
  name: string;
  phone: string;
  doctor_id: string;
}) {
  const response = await fetch(`${API_URL}/api/patients`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return response.json();
}

export async function updatePatient(
  patientId: string,
  payload: {
    name?: string;
    phone?: string;
    dob?: string | null;
    mrn?: string | null;
    insurance?: string | null;
    primary_physician?: string | null;
    last_visit?: string | null;
    risk_level?: string;
    notes?: string | null;
  },
) {
  const response = await fetch(`${API_URL}/api/patients/${patientId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return response.json();
}

export async function deletePatient(patientId: string) {
  const response = await fetch(`${API_URL}/api/patients/${patientId}`, {
    method: "DELETE",
  });
  return response;
}

// ---------------------------------------------------------------------------
// Patient conditions
// ---------------------------------------------------------------------------

export async function listConditions(patientId: string) {
  const response = await fetch(
    `${API_URL}/api/patients/${patientId}/conditions`,
  );
  return response.json();
}

export async function createCondition(
  patientId: string,
  payload: {
    icd10_code: string;
    description: string;
    hcc_category?: string;
    raf_impact?: number;
    status?: string;
  },
) {
  const response = await fetch(
    `${API_URL}/api/patients/${patientId}/conditions`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
  return response.json();
}

export async function updateCondition(
  patientId: string,
  conditionId: string,
  payload: {
    icd10_code?: string;
    description?: string;
    hcc_category?: string;
    raf_impact?: number;
    status?: string;
  },
) {
  const response = await fetch(
    `${API_URL}/api/patients/${patientId}/conditions/${conditionId}`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
  return response.json();
}

export async function deleteCondition(patientId: string, conditionId: string) {
  const response = await fetch(
    `${API_URL}/api/patients/${patientId}/conditions/${conditionId}`,
    {
      method: "DELETE",
    },
  );
  return response;
}

// ---------------------------------------------------------------------------
// Execute workflow
// ---------------------------------------------------------------------------

export async function executeWorkflow(
  workflowId: string,
  patientId: string,
  triggerNodeType?: string,
) {
  const response = await fetch(
    `${API_URL}/api/workflows/${workflowId}/execute`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        patient_id: patientId,
        trigger_node_type: triggerNodeType ?? null,
      }),
    },
  );
  return response.json();
}

export async function executeWorkflowWithContext(
  workflowId: string,
  payload: {
    patient_id: string;
    trigger_node_type?: string | null;
    report_id?: string | null;
    doctor_id?: string | null;
  },
): Promise<ExecuteWorkflowResult> {
  const response = await fetch(
    `${API_URL}/api/workflows/${workflowId}/execute`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
  if (!response.ok) {
    const detail = await response.text().catch(() => response.statusText);
    throw new Error(
      `Failed to execute workflow (${response.status}): ${detail}`,
    );
  }
  return response.json() as Promise<ExecuteWorkflowResult>;
}

// ---------------------------------------------------------------------------
// Call logs
// ---------------------------------------------------------------------------

export async function listCallLogs(workflowId?: string, doctorId?: string) {
  const params = new URLSearchParams();
  if (workflowId) params.set("workflow_id", workflowId);
  if (doctorId) params.set("doctor_id", doctorId);
  const qs = params.toString();
  const response = await fetch(`${API_URL}/api/call-logs${qs ? `?${qs}` : ""}`);
  return response.json();
}

export async function checkCallStatus(
  callLogId: string,
): Promise<CallStatusResult> {
  const response = await fetch(`${API_URL}/api/call-logs/${callLogId}/check`, {
    method: "POST",
  });
  if (!response.ok) {
    const detail = await response.text().catch(() => response.statusText);
    throw new Error(
      `Failed to check call status (${response.status}): ${detail}`,
    );
  }
  return response.json() as Promise<CallStatusResult>;
}

export async function getFollowUpCronConfig(): Promise<FollowUpCronConfig> {
  const response = await fetch(`${API_URL}/api/follow-up-cron/config`);
  if (!response.ok) {
    const detail = await response.text().catch(() => response.statusText);
    throw new Error(
      `Failed to fetch follow-up cron config (${response.status}): ${detail}`,
    );
  }
  return response.json() as Promise<FollowUpCronConfig>;
}

export async function listFollowUpCronJobs(
  params?: {
    doctor_id?: string;
    status?: string;
    limit?: number;
  },
): Promise<FollowUpJob[]> {
  const query = new URLSearchParams();
  if (params?.doctor_id) query.set("doctor_id", params.doctor_id);
  if (params?.status) query.set("status", params.status);
  if (typeof params?.limit === "number") query.set("limit", String(params.limit));

  const qs = query.toString();
  const response = await fetch(
    `${API_URL}/api/follow-up-cron/jobs${qs ? `?${qs}` : ""}`,
  );
  if (!response.ok) {
    const detail = await response.text().catch(() => response.statusText);
    throw new Error(
      `Failed to fetch follow-up cron jobs (${response.status}): ${detail}`,
    );
  }
  return response.json() as Promise<FollowUpJob[]>;
}

export async function listFollowUpCronJobLogs(
  jobId: string,
  limit = 200,
): Promise<FollowUpJobLog[]> {
  const response = await fetch(
    `${API_URL}/api/follow-up-cron/jobs/${jobId}/logs?limit=${limit}`,
  );
  if (!response.ok) {
    const detail = await response.text().catch(() => response.statusText);
    throw new Error(
      `Failed to fetch follow-up cron job logs (${response.status}): ${detail}`,
    );
  }
  return response.json() as Promise<FollowUpJobLog[]>;
}

export async function runFollowUpCronJobNow(jobId: string): Promise<{ success: boolean; message?: string }> {
  const response = await fetch(`${API_URL}/api/follow-up-cron/jobs/${jobId}/run`, {
    method: "POST",
  });
  if (!response.ok) {
    const detail = await response.text().catch(() => response.statusText);
    throw new Error(
      `Failed to trigger follow-up cron job (${response.status}): ${detail}`,
    );
  }
  return response.json() as Promise<{ success: boolean; message?: string }>;
}

export async function listPatientReports(
  patientId: string,
): Promise<ReportItem[]> {
  const response = await fetch(
    `${API_URL}/api/reports?patient_id=${encodeURIComponent(patientId)}`,
  );
  if (!response.ok) {
    const detail = await response.text().catch(() => response.statusText);
    throw new Error(`Failed to fetch reports (${response.status}): ${detail}`);
  }
  return response.json() as Promise<ReportItem[]>;
}

export async function listDoctorUpcomingAppointments(
  doctorId: string,
): Promise<DoctorAppointmentItem[]> {
  const response = await fetch(
    `${API_URL}/api/doctors/${doctorId}/upcoming-appointments`,
  );
  if (!response.ok) {
    const detail = await response.text().catch(() => response.statusText);
    throw new Error(
      `Failed to fetch upcoming appointments (${response.status}): ${detail}`,
    );
  }
  return response.json() as Promise<DoctorAppointmentItem[]>;
}

export async function listPatientUpcomingAppointments(
  authUserId: string,
): Promise<PatientPortalAppointment[]> {
  const params = new URLSearchParams({ auth_user_id: authUserId });
  const response = await fetch(
    `${API_URL}/api/patient-portal/upcoming-appointments?${params.toString()}`,
  );
  if (!response.ok) {
    const detail = await response.text().catch(() => response.statusText);
    throw new Error(
      `Failed to fetch patient upcoming appointments (${response.status}): ${detail}`,
    );
  }
  return response.json() as Promise<PatientPortalAppointment[]>;
}

// ---------------------------------------------------------------------------
// Patient medications
// ---------------------------------------------------------------------------

export async function listMedications(patientId: string) {
  const response = await fetch(
    `${API_URL}/api/patients/${patientId}/medications`,
  );
  return response.json();
}

export async function createMedication(
  patientId: string,
  payload: {
    name: string;
    dosage?: string;
    frequency?: string;
    route?: string;
    prescriber?: string;
    start_date?: string;
    end_date?: string;
    status?: string;
    notes?: string;
  },
) {
  const response = await fetch(
    `${API_URL}/api/patients/${patientId}/medications`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
  return response.json();
}

export async function updateMedication(
  patientId: string,
  medicationId: string,
  payload: {
    name?: string;
    dosage?: string;
    frequency?: string;
    route?: string;
    prescriber?: string;
    start_date?: string;
    end_date?: string;
    status?: string;
    notes?: string;
  },
) {
  const response = await fetch(
    `${API_URL}/api/patients/${patientId}/medications/${medicationId}`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
  return response.json();
}

export async function deleteMedication(
  patientId: string,
  medicationId: string,
) {
  const response = await fetch(
    `${API_URL}/api/patients/${patientId}/medications/${medicationId}`,
    {
      method: "DELETE",
    },
  );
  return response;
}

// ---------------------------------------------------------------------------
// PDF upload & extraction
// ---------------------------------------------------------------------------

export async function uploadPdf(
  file: File,
  patientId?: string,
  uploadedBy?: string,
) {
  const formData = new FormData();
  formData.append("file", file);
  if (patientId) formData.append("patient_id", patientId);
  if (uploadedBy) formData.append("uploaded_by", uploadedBy);

  const response = await fetch(`${API_URL}/api/pdf/upload`, {
    method: "POST",
    body: formData,
  });
  if (!response.ok) {
    const detail = await response.text().catch(() => response.statusText);
    throw new Error(`PDF upload failed (${response.status}): ${detail}`);
  }
  return response.json();
}

export async function pdfIntake(file: File, doctorId: string) {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("doctor_id", doctorId);

  const response = await fetch(`${API_URL}/api/pdf/intake`, {
    method: "POST",
    body: formData,
  });
  if (!response.ok) {
    const detail = await response.text().catch(() => response.statusText);
    throw new Error(`PDF intake failed (${response.status}): ${detail}`);
  }
  return response.json();
}

export async function importPdfToPatient(file: File, patientId: string) {
  const formData = new FormData();
  formData.append("file", file);

  const response = await fetch(
    `${API_URL}/api/patients/${patientId}/import-pdf`,
    {
      method: "POST",
      body: formData,
    },
  );
  if (!response.ok) {
    const detail = await response.text().catch(() => response.statusText);
    throw new Error(`PDF import failed (${response.status}): ${detail}`);
  }
  return response.json();
}

export async function extractPdfAndExecute(
  file: File,
  patientId: string,
  workflowId: string,
): Promise<ExtractPdfAndExecuteResult> {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("patient_id", patientId);
  formData.append("workflow_id", workflowId);

  const response = await fetch(`${API_URL}/api/pdf/extract-and-execute`, {
    method: "POST",
    body: formData,
  });
  if (!response.ok) {
    const detail = await response.text().catch(() => response.statusText);
    throw new Error(
      `PDF extract & execute failed (${response.status}): ${detail}`,
    );
  }
  return response.json() as Promise<ExtractPdfAndExecuteResult>;
}

export async function listPdfDocuments(patientId?: string) {
  const params = new URLSearchParams();
  if (patientId) params.set("patient_id", patientId);
  const qs = params.toString();
  const response = await fetch(
    `${API_URL}/api/pdf/documents${qs ? `?${qs}` : ""}`,
  );
  return response.json();
}

export async function getPdfDocument(docId: string) {
  const response = await fetch(`${API_URL}/api/pdf/documents/${docId}`);
  if (!response.ok)
    throw new Error(`Failed to fetch PDF document (${response.status})`);
  return response.json();
}

export async function deletePdfDocument(docId: string) {
  return fetch(`${API_URL}/api/pdf/documents/${docId}`, { method: "DELETE" });
}

// ---------------------------------------------------------------------------
// Notifications
// ---------------------------------------------------------------------------

export async function listNotifications(patientId?: string) {
  const params = new URLSearchParams();
  if (patientId) params.set("patient_id", patientId);
  const qs = params.toString();
  const response = await fetch(
    `${API_URL}/api/notifications${qs ? `?${qs}` : ""}`,
  );
  return response.json();
}

// ---------------------------------------------------------------------------
// Lab orders
// ---------------------------------------------------------------------------

export async function listLabOrders(patientId?: string) {
  const params = new URLSearchParams();
  if (patientId) params.set("patient_id", patientId);
  const qs = params.toString();
  const response = await fetch(
    `${API_URL}/api/lab-orders${qs ? `?${qs}` : ""}`,
  );
  return response.json();
}

// ---------------------------------------------------------------------------
// Referrals
// ---------------------------------------------------------------------------

export async function listReferrals(patientId?: string) {
  const params = new URLSearchParams();
  if (patientId) params.set("patient_id", patientId);
  const qs = params.toString();
  const response = await fetch(`${API_URL}/api/referrals${qs ? `?${qs}` : ""}`);
  return response.json();
}

// ---------------------------------------------------------------------------
// Staff assignments
// ---------------------------------------------------------------------------

export async function listStaffAssignments(
  patientId?: string,
  staffId?: string,
) {
  const params = new URLSearchParams();
  if (patientId) params.set("patient_id", patientId);
  if (staffId) params.set("staff_id", staffId);
  const qs = params.toString();
  const response = await fetch(
    `${API_URL}/api/staff-assignments${qs ? `?${qs}` : ""}`,
  );
  return response.json();
}

// ---------------------------------------------------------------------------
// Reports
// ---------------------------------------------------------------------------

export async function listReports(patientId?: string, workflowId?: string) {
  const params = new URLSearchParams();
  if (patientId) params.set("patient_id", patientId);
  if (workflowId) params.set("workflow_id", workflowId);
  const qs = params.toString();
  const response = await fetch(`${API_URL}/api/reports${qs ? `?${qs}` : ""}`);
  return response.json() as Promise<ReportItem[]>;
}

export async function getReport(reportId: string) {
  const response = await fetch(`${API_URL}/api/reports/${reportId}`);
  if (!response.ok)
    throw new Error(`Failed to fetch report (${response.status})`);
  return response.json();
}

// ---------------------------------------------------------------------------
// Blood campaigns
// ---------------------------------------------------------------------------

export interface BloodDonorItem {
  id: string;
  doctor_id: string;
  name: string;
  gender: string;
  phone_number: string;
  location: string;
  latitude?: number | null;
  longitude?: number | null;
  last_donated_date: string;
  blood_type: string;
  created_at: string;
  updated_at: string;
}

export interface BloodNgoItem {
  id: string;
  doctor_id: string;
  ngo_name: string;
  phone_number: string;
  location: string;
  latitude?: number | null;
  longitude?: number | null;
  created_at: string;
  updated_at: string;
}

export interface BloodCampaignAttempt {
  id: string;
  campaign_id: string;
  donor_id: string;
  worker_pool_id?: string | null;
  worker_name?: string | null;
  status: string;
  outcome?: string | null;
  message?: string | null;
  conversation_id?: string | null;
  call_sid?: string | null;
  created_at: string;
  updated_at: string;
  started_at?: string | null;
  completed_at?: string | null;
  donor_name?: string;
  donor_phone_number?: string;
  donor_blood_type?: string;
  donor_location?: string;
  donor_latitude?: number | null;
  donor_longitude?: number | null;
}

export interface BloodCampaignSummary {
  active: number;
  completed: number;
  accepted: boolean;
}

export interface BloodCampaignDetail {
  campaign: Record<string, unknown>;
  attempts: BloodCampaignAttempt[];
  summary: BloodCampaignSummary;
}

export interface BloodCampaignMapPoint {
  id: string;
  name: string;
  location: string;
  latitude?: number | null;
  longitude?: number | null;
  blood_type?: string;
  status?: string;
}

export interface BloodCampaignMapPayload {
  campaign_id: string;
  patient: {
    location?: string | null;
    latitude?: number | null;
    longitude?: number | null;
  };
  donors: BloodCampaignMapPoint[];
  ngos: BloodCampaignMapPoint[];
}

export async function uploadBloodCampaignSheet(file: File, doctorId: string) {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("doctor_id", doctorId);

  const response = await fetch(`${API_URL}/api/blood-campaigns/upload`, {
    method: "POST",
    body: formData,
  });

  if (!response.ok) {
    const detail = await response.text().catch(() => response.statusText);
    throw new Error(`Blood upload failed (${response.status}): ${detail}`);
  }
  return response.json();
}

export async function listBloodCampaignDonors(doctorId: string) {
  const response = await fetch(
    `${API_URL}/api/blood-campaigns/donors?doctor_id=${encodeURIComponent(doctorId)}`,
  );
  if (!response.ok) {
    const detail = await response.text().catch(() => response.statusText);
    throw new Error(`Failed to fetch blood donors (${response.status}): ${detail}`);
  }
  return response.json() as Promise<BloodDonorItem[]>;
}

export async function listBloodCampaignNgos(doctorId: string) {
  const response = await fetch(
    `${API_URL}/api/blood-campaigns/ngos?doctor_id=${encodeURIComponent(doctorId)}`,
  );
  if (!response.ok) {
    const detail = await response.text().catch(() => response.statusText);
    throw new Error(`Failed to fetch blood NGOs (${response.status}): ${detail}`);
  }
  return response.json() as Promise<BloodNgoItem[]>;
}

export async function startBloodCampaign(payload: {
  doctor_id: string;
  blood_type: string;
  recipient_name: string;
  reason?: string | null;
  patient_location?: string | null;
  batch_size?: number;
}) {
  const response = await fetch(`${API_URL}/api/blood-campaigns/start`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    const detail = await response.text().catch(() => response.statusText);
    throw new Error(`Failed to start blood campaign (${response.status}): ${detail}`);
  }
  return response.json() as Promise<{ campaign_id: string; status: string }>;
}

export async function getBloodCampaignStatus(campaignId: string) {
  const response = await fetch(`${API_URL}/api/blood-campaigns/${campaignId}`);
  if (!response.ok) {
    const detail = await response.text().catch(() => response.statusText);
    throw new Error(
      `Failed to fetch blood campaign status (${response.status}): ${detail}`,
    );
  }
  return response.json() as Promise<BloodCampaignDetail>;
}

export async function getBloodCampaignMap(campaignId: string) {
  const response = await fetch(
    `${API_URL}/api/blood-campaigns/${campaignId}/map`,
  );
  if (!response.ok) {
    const detail = await response.text().catch(() => response.statusText);
    throw new Error(
      `Failed to fetch blood campaign map (${response.status}): ${detail}`,
    );
  }
  return response.json() as Promise<BloodCampaignMapPayload>;
}
