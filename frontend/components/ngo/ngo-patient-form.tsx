"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { listDoctors, type DoctorListItem } from "@/services/api";
import { NgoApiError } from "@/services/ngo-api";
import { validateNgoPatient, type NgoFieldErrors, type NgoPatientFormValues } from "@/lib/ngo-validation";
import { ErrorBanner, inputClass } from "@/components/ngo/ui";
import type { NgoPatientCreateResult, NgoPatientInput } from "@/types/ngo";

const EMPTY: NgoPatientFormValues = { name: "", phone: "", dob: "", mrn: "", insurance: "", notes: "", doctor_id: "" };

type Props = {
  onSubmit: (payload: NgoPatientInput, idempotencyKey: string) => Promise<NgoPatientCreateResult>;
  onSuccess: (result: NgoPatientCreateResult) => void;
  onError: (err: unknown) => string;
};

function Field({
  id,
  label,
  required,
  error,
  hint,
  children,
}: {
  id: string;
  label: string;
  required?: boolean;
  error?: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label htmlFor={id} className="mb-1 block text-xs font-medium text-muted-foreground">
        {label}
        {required && <span aria-hidden="true"> *</span>}
      </label>
      {children}
      {hint && !error && <p id={`${id}-hint`} className="mt-1 text-[11px] text-muted-foreground">{hint}</p>}
      {error && <p id={`${id}-error`} className="mt-1 text-xs text-destructive">{error}</p>}
    </div>
  );
}

export function NgoPatientForm({ onSubmit, onSuccess, onError }: Props) {
  const [values, setValues] = useState<NgoPatientFormValues>(EMPTY);
  const [errors, setErrors] = useState<NgoFieldErrors>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [duplicateWarning, setDuplicateWarning] = useState<string | null>(null);
  const [existingPatientId, setExistingPatientId] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [doctors, setDoctors] = useState<DoctorListItem[]>([]);
  const [doctorsError, setDoctorsError] = useState<string | null>(null);
  // One key per form instance: double clicks / retries cannot create two patients.
  const idempotencyKey = useRef<string>(crypto.randomUUID());

  useEffect(() => {
    listDoctors()
      .then(setDoctors)
      .catch(() => setDoctorsError("Could not load doctors. Refresh to try again."));
  }, []);

  const set = (field: keyof NgoPatientFormValues) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) => {
    setValues((v) => ({ ...v, [field]: e.target.value }));
    setErrors((prev) => ({ ...prev, [field]: undefined }));
    setDuplicateWarning(null);
    setExistingPatientId(null);
  };

  const submit = async (confirmPossibleDuplicate: boolean) => {
    if (submitting) return;
    const clientErrors = validateNgoPatient(values);
    setErrors(clientErrors);
    setFormError(null);
    if (Object.keys(clientErrors).length > 0) return;

    setSubmitting(true);
    try {
      const result = await onSubmit(
        {
          name: values.name.trim(),
          phone: values.phone.trim(),
          doctor_id: values.doctor_id,
          dob: values.dob || null,
          mrn: values.mrn.trim() || null,
          insurance: values.insurance.trim() || null,
          notes: values.notes.trim() || null,
          confirm_possible_duplicate: confirmPossibleDuplicate,
        },
        idempotencyKey.current,
      );
      onSuccess(result);
    } catch (err) {
      const message = onError(err);
      if (err instanceof NgoApiError) {
        if (err.detail.field_errors) setErrors(err.detail.field_errors as NgoFieldErrors);
        if (err.detail.code === "possible_duplicate") {
          setDuplicateWarning(message);
          return;
        }
        if (err.detail.code === "duplicate_patient") setExistingPatientId(err.detail.patient_id || null);
      }
      setFormError(message);
    } finally {
      setSubmitting(false);
    }
  };

  const describedBy = (id: keyof NgoPatientFormValues) => (errors[id] ? `${id}-error` : undefined);

  return (
    <form
      noValidate
      onSubmit={(e) => {
        e.preventDefault();
        submit(false);
      }}
      className="space-y-5 rounded-xl border border-border bg-card p-6"
    >
      <ErrorBanner message={formError} />
      {existingPatientId && (
        <p className="text-sm">
          <Link href={`/ngo/patients/${existingPatientId}`} className="text-primary underline">View the existing patient</Link>
        </p>
      )}

      <div className="grid gap-4 sm:grid-cols-2">
        <Field id="name" label="Full name" required error={errors.name}>
          <input id="name" value={values.name} onChange={set("name")} maxLength={200} autoComplete="off"
            aria-invalid={!!errors.name} aria-describedby={describedBy("name")} className={inputClass} />
        </Field>
        <Field id="phone" label="Phone number" required error={errors.phone} hint="10-digit mobile number; +91 is added automatically">
          <input id="phone" type="tel" inputMode="tel" value={values.phone} onChange={set("phone")} maxLength={20} autoComplete="off"
            aria-invalid={!!errors.phone} aria-describedby={describedBy("phone") || "phone-hint"} className={inputClass} />
        </Field>
        <Field id="dob" label="Date of birth" error={errors.dob}>
          <input id="dob" type="date" value={values.dob} onChange={set("dob")} max={new Date().toISOString().slice(0, 10)}
            aria-invalid={!!errors.dob} aria-describedby={describedBy("dob")} className={inputClass} />
        </Field>
        <Field id="doctor_id" label="Assigned doctor" required error={errors.doctor_id || doctorsError || undefined}>
          <select id="doctor_id" value={values.doctor_id} onChange={set("doctor_id")}
            aria-invalid={!!errors.doctor_id} aria-describedby={describedBy("doctor_id")} className={inputClass}>
            <option value="">Select a doctor…</option>
            {doctors.map((d) => (
              <option key={d.id} value={d.id}>{d.name} — {d.specialty}</option>
            ))}
          </select>
        </Field>
        <Field id="mrn" label="MRN / health ID" error={errors.mrn}>
          <input id="mrn" value={values.mrn} onChange={set("mrn")} maxLength={64} autoComplete="off"
            aria-invalid={!!errors.mrn} aria-describedby={describedBy("mrn")} className={inputClass} />
        </Field>
        <Field id="insurance" label="Insurance / scheme" error={errors.insurance}>
          <input id="insurance" value={values.insurance} onChange={set("insurance")} maxLength={200} autoComplete="off"
            aria-invalid={!!errors.insurance} aria-describedby={describedBy("insurance")} className={inputClass} />
        </Field>
      </div>

      <Field id="notes" label="Care coordination notes" error={errors.notes} hint="Non-clinical context for the care team (max 1000 characters)">
        <textarea id="notes" value={values.notes} onChange={set("notes")} rows={3} maxLength={1000}
          aria-invalid={!!errors.notes} aria-describedby={describedBy("notes") || "notes-hint"} className={inputClass} />
      </Field>

      {duplicateWarning && (
        <div role="alert" className="space-y-3 rounded-lg border border-warning/40 bg-warning/5 px-4 py-3 text-sm">
          <p><strong>Possible duplicate:</strong> {duplicateWarning}</p>
          <p className="text-muted-foreground">Register anyway only if you have verified this is a different person.</p>
          <div className="flex gap-2">
            <Button type="button" size="sm" disabled={submitting} onClick={() => submit(true)}>
              It&apos;s a different person — register
            </Button>
            <Button type="button" size="sm" variant="outline" onClick={() => setDuplicateWarning(null)}>Cancel</Button>
          </div>
        </div>
      )}

      <div className="flex justify-end gap-2">
        <Link href="/ngo/patients" className="inline-flex h-8 items-center rounded-lg border border-border px-2.5 text-sm hover:bg-muted">
          Cancel
        </Link>
        <Button type="submit" disabled={submitting || !!duplicateWarning}>
          {submitting ? "Registering…" : "Register patient"}
        </Button>
      </div>
    </form>
  );
}
