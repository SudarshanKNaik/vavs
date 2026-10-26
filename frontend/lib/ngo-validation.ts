// Client-side checks for NGO patient registration. They mirror
// backend/app/services/ngo_service.validate_patient_fields so users see errors
// early; the backend remains the source of truth.

export type NgoPatientFormValues = {
  name: string;
  phone: string;
  dob: string;
  mrn: string;
  insurance: string;
  notes: string;
  doctor_id: string;
};

export type NgoFieldErrors = Partial<Record<keyof NgoPatientFormValues, string>>;

const MAX_LENGTHS = { name: 200, mrn: 64, insurance: 200, notes: 1000 } as const;

export function normalizeIndianPhone(raw: string): string | null {
  const digits = raw.replace(/\D/g, "");
  const valid =
    digits.length === 10 ||
    (digits.length === 11 && digits.startsWith("0")) ||
    (digits.length === 12 && digits.startsWith("91"));
  return valid ? `+91${digits.slice(-10)}` : null;
}

export function validateNgoPatient(values: NgoPatientFormValues, today: Date = new Date()): NgoFieldErrors {
  const errors: NgoFieldErrors = {};
  const name = values.name.trim().replace(/\s+/g, " ");

  if (!name) errors.name = "Full name is required";
  else if (name.length < 2) errors.name = "Full name must be at least 2 characters";
  else if (name.length > MAX_LENGTHS.name) errors.name = `Full name must be at most ${MAX_LENGTHS.name} characters`;
  else if (!/^\p{L}/u.test(name)) errors.name = "Full name must start with a letter";

  if (!values.phone.trim()) errors.phone = "Phone number is required";
  else if (!normalizeIndianPhone(values.phone)) {
    errors.phone = "Phone number must be a 10-digit number, optionally with +91 or 0 prefix";
  }

  if (values.dob) {
    // <input type="date"> yields YYYY-MM-DD
    const dob = new Date(`${values.dob}T00:00:00`);
    if (Number.isNaN(dob.getTime())) errors.dob = "Enter a valid date of birth";
    else if (dob > today) errors.dob = "Date of birth cannot be in the future";
    else if (dob.getFullYear() < 1900) errors.dob = "Date of birth must be after 1900";
  }

  if (values.mrn.trim().length > MAX_LENGTHS.mrn) errors.mrn = `Must be at most ${MAX_LENGTHS.mrn} characters`;
  if (values.insurance.trim().length > MAX_LENGTHS.insurance) {
    errors.insurance = `Must be at most ${MAX_LENGTHS.insurance} characters`;
  }
  if (values.notes.trim().length > MAX_LENGTHS.notes) errors.notes = `Must be at most ${MAX_LENGTHS.notes} characters`;
  if (!values.doctor_id) errors.doctor_id = "An assigned doctor is required";

  return errors;
}

export type NgoAccess = "loading" | "allow" | "signin" | "forbidden";

/** Route-guard decision for /ngo/* pages. */
export function ngoAccessDecision(isLoading: boolean, role: string | undefined, hasToken: boolean): NgoAccess {
  if (isLoading) return "loading";
  if (!role || !hasToken) return "signin";
  return role === "ngo" ? "allow" : "forbidden";
}

export const MAX_CSV_BYTES = 2 * 1024 * 1024;

/** Pre-upload file check; the backend enforces the configured limits. */
export function checkCsvFile(file: { name: string; size: number }): string | null {
  if (!file.name.toLowerCase().endsWith(".csv")) return "Only .csv files are accepted";
  if (file.size === 0) return "The selected file is empty";
  if (file.size > MAX_CSV_BYTES) return `The file exceeds the ${MAX_CSV_BYTES / 1024} KB limit`;
  return null;
}
