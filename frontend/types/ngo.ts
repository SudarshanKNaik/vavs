export type RegistrationSource = "manual" | "csv";
export type FollowUpFilter = "pending" | "none";

export interface Paginated<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export interface NgoPatientListItem {
  id: string;
  name: string;
  phone: string;
  dob: string | null;
  doctor_id: string;
  doctor_name: string | null;
  source: RegistrationSource;
  import_id: string | null;
  registered_at: string;
  follow_up_pending: boolean;
  next_appointment_at: string | null;
}

export interface NgoPatientAppointment {
  id: string;
  status: string;
  consultation_type: string | null;
  slot_start: string;
  slot_end: string;
  doctor_name: string | null;
}

export interface NgoPatientFollowUp {
  status: string;
  scheduled_for: string;
  attempt_count: number;
  created_at: string;
}

export interface NgoPatientDetail {
  id: string;
  name: string;
  phone: string;
  dob: string | null;
  mrn: string | null;
  insurance: string | null;
  notes: string | null;
  doctor_id: string;
  doctor_name: string | null;
  doctor_specialty: string | null;
  source: RegistrationSource;
  import_id: string | null;
  registered_at: string;
  registered_by: string | null;
  follow_up_pending: boolean;
  appointments: NgoPatientAppointment[];
  follow_ups: NgoPatientFollowUp[];
}

export interface NgoPatientInput {
  name: string;
  phone: string;
  doctor_id: string;
  dob?: string | null;
  mrn?: string | null;
  insurance?: string | null;
  notes?: string | null;
  confirm_possible_duplicate?: boolean;
}

export interface NgoPatientCreateResult {
  patient_id: string;
  replayed: boolean;
}

export type ImportStatus = "previewed" | "processing" | "completed" | "failed";

export interface NgoImportSummary {
  id: string;
  file_name: string | null;
  status: ImportStatus;
  total_rows: number;
  valid_rows: number;
  invalid_rows: number;
  duplicate_rows: number;
  review_rows: number;
  inserted_count: number;
  skipped_count: number;
  failed_count: number;
  created_at: string;
  confirmed_at: string | null;
  completed_at: string | null;
  created_by: string | null;
}

export type ImportRowStatus =
  | "valid"
  | "invalid"
  | "duplicate"
  | "review"
  | "inserted"
  | "skipped"
  | "failed";

export interface ImportRowError {
  field: string | null;
  message: string;
}

export type PatientField = "name" | "phone" | "dob" | "mrn" | "insurance" | "notes" | "doctor_id";

export interface ImportPreviewRow {
  row_number: number;
  raw_data: Partial<Record<PatientField, string>>;
  normalized: Partial<Record<PatientField, string | null>> | null;
  status: ImportRowStatus;
  errors: ImportRowError[];
}

export interface ImportPreview {
  import_id: string;
  file_name: string;
  headers: string[];
  mapping: Partial<Record<PatientField, string>>;
  ignored_columns: string[];
  empty_rows_skipped: number;
  total_rows: number;
  valid_rows: number;
  invalid_rows: number;
  duplicate_rows: number;
  review_rows: number;
  rows: ImportPreviewRow[];
}

export interface ImportConfirmResult extends NgoImportSummary {
  already_processed: boolean;
}

export interface NgoImportDetail extends NgoImportSummary {
  column_mapping: Partial<Record<PatientField, string>>;
  rows: {
    row_number: number;
    status: ImportRowStatus;
    raw_data: Partial<Record<PatientField, string>>;
    errors: ImportRowError[];
    patient_id: string | null;
  }[];
}

export interface NgoDashboard {
  total_patients: number;
  manual_patients: number;
  csv_patients: number;
  follow_up_pending: number;
  upcoming_appointments: number;
  upcoming: {
    id: string;
    status: string;
    slot_start: string;
    patient_id: string;
    patient_name: string;
    doctor_name: string | null;
  }[];
  recent_registrations: { id: string; name: string; source: RegistrationSource; registered_at: string }[];
  imports: { total: number; successful: number; with_failures: number };
  recent_imports: NgoImportSummary[];
}

export interface NgoErrorDetail {
  code: string;
  message: string;
  field_errors?: Record<string, string>;
  headers?: string[];
  mapping?: Partial<Record<PatientField, string>>;
  missing?: PatientField[];
  patient_id?: string;
  requires_confirmation?: boolean;
}
