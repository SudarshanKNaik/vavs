"use client";

import { useLocalAuth } from "@/lib/local-auth";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  createBloodRequest,
  listBloodRequests,
  listPatients,
  type BloodComponent,
  type BloodRequestItem,
  type BloodUrgency,
} from "@/services/api";
import { Button } from "@/components/ui/button";
import { Droplet, Loader2, RefreshCw } from "lucide-react";

const BLOOD_GROUPS = ["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"];

const COMPONENTS: { value: BloodComponent; label: string }[] = [
  { value: "whole_blood", label: "Whole blood" },
  { value: "packed_rbc", label: "Packed red cells (PRBC)" },
  { value: "platelets", label: "Platelets" },
  { value: "plasma", label: "Plasma (FFP)" },
];

const URGENCIES: { value: BloodUrgency; label: string; hint: string }[] = [
  { value: "emergency", label: "Emergency", hint: "Needed within hours" },
  { value: "urgent", label: "Urgent", hint: "Needed today" },
  { value: "planned", label: "Planned", hint: "Scheduled surgery or transfusion" },
];

// Hospital and contact details rarely change between requests, so remember
// them per doctor in this browser to save retyping. Best-effort only.
const DEFAULTS_KEY = "caresync_blood_request_defaults";

type SavedDefaults = {
  hospital_name?: string;
  ward?: string;
  hospital_location?: string;
  contact_name?: string;
  contact_phone?: string;
};

function loadDefaults(doctorId: string): SavedDefaults {
  try {
    const raw = window.localStorage.getItem(`${DEFAULTS_KEY}:${doctorId}`);
    return raw ? (JSON.parse(raw) as SavedDefaults) : {};
  } catch {
    return {};
  }
}

function saveDefaults(doctorId: string, value: SavedDefaults) {
  try {
    window.localStorage.setItem(`${DEFAULTS_KEY}:${doctorId}`, JSON.stringify(value));
  } catch {
    // Storage unavailable (private mode etc.); nothing to do.
  }
}

type PatientOption = { id: string; name: string };

const emptyForm = {
  blood_type: "",
  component: "whole_blood" as BloodComponent,
  units_needed: 1,
  urgency: "urgent" as BloodUrgency,
  required_by: "",
  recipient_name: "",
  patient_id: "",
  reason: "",
  hospital_name: "",
  ward: "",
  hospital_location: "",
  contact_name: "",
  contact_phone: "",
};

function componentLabel(value: string) {
  return COMPONENTS.find((c) => c.value === value)?.label || value;
}

function formatDateTime(value?: string | null) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

function requestStatus(req: BloodRequestItem): { label: string; tone: string; live: boolean } {
  const confirmed = `${req.donors_accepted} of ${req.units_needed} donor(s) confirmed`;
  if (req.status === "draft" || req.status === "running") {
    return {
      label: `Calling donors · ${confirmed}${req.calls_in_progress ? ` · ${req.calls_in_progress} call(s) live` : ""}`,
      tone: "border-warning/40 bg-warning/10 text-warning",
      live: true,
    };
  }
  if (req.status === "stopped" || req.donors_accepted >= req.units_needed) {
    return { label: `Fulfilled · ${confirmed}`, tone: "border-success/40 bg-success/10 text-success", live: false };
  }
  if (req.status === "failed") {
    return {
      label: "Couldn't start calls: voice calling isn't configured (ElevenLabs keys)",
      tone: "border-destructive/40 bg-destructive/10 text-destructive",
      live: false,
    };
  }
  if (req.donors_contacted === 0) {
    return {
      label: "No eligible donors found (blood group, cooldown or empty donor list)",
      tone: "border-destructive/40 bg-destructive/10 text-destructive",
      live: false,
    };
  }
  return {
    label: `All eligible donors called · ${confirmed}`,
    tone: "border-destructive/40 bg-destructive/10 text-destructive",
    live: false,
  };
}

const inputClass =
  "w-full rounded-lg border border-border bg-background px-3 py-2 text-sm focus:border-primary/30 focus:outline-none focus:ring-2 focus:ring-primary/20";

function Field({
  label,
  required,
  hint,
  children,
  className = "",
}: {
  label: string;
  required?: boolean;
  hint?: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <label className={`block space-y-1 text-xs ${className}`}>
      <span className="font-medium text-foreground">
        {label}
        {required && <span className="text-destructive"> *</span>}
      </span>
      {children}
      {hint && <span className="block text-[11px] text-muted-foreground">{hint}</span>}
    </label>
  );
}

export default function BloodRequestsPage() {
  const { user } = useLocalAuth();
  const doctorId = user?.doctor_id || user?.sub;

  const [form, setForm] = useState(emptyForm);
  const [patients, setPatients] = useState<PatientOption[]>([]);
  const [requests, setRequests] = useState<BloodRequestItem[]>([]);
  const [loadingRequests, setLoadingRequests] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);

  const update = <K extends keyof typeof emptyForm>(key: K, value: (typeof emptyForm)[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  const fetchRequests = useCallback(async () => {
    if (!doctorId) return;
    try {
      setRequests(await listBloodRequests(doctorId));
    } catch (err) {
      setMessage({ type: "error", text: err instanceof Error ? err.message : "Failed to load requests." });
    } finally {
      setLoadingRequests(false);
    }
  }, [doctorId]);

  useEffect(() => {
    if (!doctorId) return;
    const saved = loadDefaults(doctorId);
    setForm((prev) => ({
      ...prev,
      ...saved,
      contact_name: saved.contact_name || user?.name || "",
      contact_phone: saved.contact_phone || user?.mobile || "",
    }));
    fetchRequests();
    listPatients(doctorId)
      .then((rows: { id: string; name: string }[]) =>
        setPatients(Array.isArray(rows) ? rows.map((p) => ({ id: p.id, name: p.name })) : []),
      )
      .catch(() => setPatients([]));
  }, [doctorId, fetchRequests, user?.mobile, user?.name]);

  // Refresh while any request is still calling donors.
  const hasLive = useMemo(() => requests.some((r) => requestStatus(r).live), [requests]);
  useEffect(() => {
    if (!hasLive) return;
    const timer = window.setInterval(fetchRequests, 5000);
    return () => window.clearInterval(timer);
  }, [hasLive, fetchRequests]);

  const handleSelectPatient = (patientId: string) => {
    const patient = patients.find((p) => p.id === patientId);
    setForm((prev) => ({
      ...prev,
      patient_id: patientId,
      recipient_name: patient ? patient.name : prev.recipient_name,
    }));
  };

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!doctorId) return;
    if (!form.blood_type) {
      setMessage({ type: "error", text: "Choose the patient's blood group." });
      return;
    }
    if (form.urgency === "planned" && !form.required_by) {
      setMessage({ type: "error", text: "Planned requests need a 'Required by' date and time." });
      return;
    }

    setSubmitting(true);
    setMessage(null);
    try {
      await createBloodRequest({
        doctor_id: doctorId,
        blood_type: form.blood_type,
        component: form.component,
        units_needed: Number(form.units_needed) || 1,
        urgency: form.urgency,
        required_by: form.required_by ? new Date(form.required_by).toISOString() : null,
        recipient_name: form.recipient_name.trim(),
        patient_id: form.patient_id || null,
        reason: form.reason.trim() || null,
        hospital_name: form.hospital_name.trim(),
        ward: form.ward.trim() || null,
        hospital_location: form.hospital_location.trim(),
        contact_name: form.contact_name.trim(),
        contact_phone: form.contact_phone.trim(),
      });
      saveDefaults(doctorId, {
        hospital_name: form.hospital_name.trim(),
        ward: form.ward.trim(),
        hospital_location: form.hospital_location.trim(),
        contact_name: form.contact_name.trim(),
        contact_phone: form.contact_phone.trim(),
      });
      setMessage({
        type: "success",
        text: `Request sent. Calling compatible ${form.blood_type} donors nearest first until ${form.units_needed} confirm.`,
      });
      // Keep hospital/contact details; clear the patient-specific fields.
      setForm((prev) => ({
        ...prev,
        blood_type: "",
        component: "whole_blood",
        units_needed: 1,
        urgency: "urgent",
        required_by: "",
        recipient_name: "",
        patient_id: "",
        reason: "",
      }));
      await fetchRequests();
    } catch (err) {
      setMessage({ type: "error", text: err instanceof Error ? err.message : "Could not send the request." });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Blood Requests</h1>
        <p className="text-sm text-muted-foreground">
          Tell us what the patient needs. CareSync calls compatible donors, nearest first, until enough confirm.
        </p>
      </div>

      <form onSubmit={handleSubmit} className="space-y-4">
        <section className="rounded-xl border border-border bg-card p-4">
          <h2 className="mb-3 text-sm font-semibold">1. Patient</h2>
          <div className="grid gap-4 md:grid-cols-2">
            <Field label="Existing patient" hint="Optional. Picks the name for you.">
              <select
                value={form.patient_id}
                onChange={(e) => handleSelectPatient(e.target.value)}
                className={inputClass}
              >
                <option value="">Not in my patient list</option>
                {patients.map((p) => (
                  <option key={p.id} value={p.id}>{p.name}</option>
                ))}
              </select>
            </Field>
            <Field label="Patient name" required>
              <input
                required
                value={form.recipient_name}
                onChange={(e) => update("recipient_name", e.target.value)}
                placeholder="e.g. Rahul Patil"
                className={inputClass}
              />
            </Field>
            <Field label="Clinical reason" hint="Shared with donors in general terms only." className="md:col-span-2">
              <textarea
                value={form.reason}
                onChange={(e) => update("reason", e.target.value)}
                rows={2}
                placeholder="e.g. Surgery, post-partum haemorrhage, dengue with low platelets"
                className={inputClass}
              />
            </Field>
          </div>
        </section>

        <section className="rounded-xl border border-border bg-card p-4">
          <h2 className="mb-3 text-sm font-semibold">2. What&apos;s needed</h2>
          <div className="grid gap-4 md:grid-cols-3">
            <Field label="Blood group" required>
              <select
                required
                value={form.blood_type}
                onChange={(e) => update("blood_type", e.target.value)}
                className={inputClass}
              >
                <option value="" disabled>Select</option>
                {BLOOD_GROUPS.map((g) => (
                  <option key={g} value={g}>{g}</option>
                ))}
              </select>
            </Field>
            <Field label="Component" required>
              <select
                value={form.component}
                onChange={(e) => update("component", e.target.value as BloodComponent)}
                className={inputClass}
              >
                {COMPONENTS.map((c) => (
                  <option key={c.value} value={c.value}>{c.label}</option>
                ))}
              </select>
            </Field>
            <Field label="Units needed" required hint="We keep calling until this many donors confirm.">
              <input
                type="number"
                min={1}
                max={20}
                required
                value={form.units_needed}
                onChange={(e) => update("units_needed", Math.max(1, Math.min(20, Number(e.target.value) || 1)))}
                className={inputClass}
              />
            </Field>
          </div>

          <div className="mt-4">
            <span className="text-xs font-medium">Urgency <span className="text-destructive">*</span></span>
            <div className="mt-1 grid gap-2 sm:grid-cols-3" role="radiogroup" aria-label="Urgency">
              {URGENCIES.map((u) => {
                const selected = form.urgency === u.value;
                return (
                  <button
                    key={u.value}
                    type="button"
                    role="radio"
                    aria-checked={selected}
                    onClick={() => update("urgency", u.value)}
                    className={`rounded-lg border px-3 py-2 text-left text-sm transition-colors ${
                      selected
                        ? u.value === "emergency"
                          ? "border-destructive bg-destructive/10 text-destructive"
                          : "border-primary bg-primary/10 text-foreground"
                        : "border-border bg-background text-muted-foreground hover:border-primary/40"
                    }`}
                  >
                    <span className="block font-medium">{u.label}</span>
                    <span className="block text-[11px] opacity-80">{u.hint}</span>
                  </button>
                );
              })}
            </div>
          </div>

          <Field
            label="Required by"
            required={form.urgency === "planned"}
            hint="When the blood must be at the hospital."
            className="mt-4 md:max-w-xs"
          >
            <input
              type="datetime-local"
              required={form.urgency === "planned"}
              value={form.required_by}
              onChange={(e) => update("required_by", e.target.value)}
              className={inputClass}
            />
          </Field>
        </section>

        <section className="rounded-xl border border-border bg-card p-4">
          <h2 className="mb-1 text-sm font-semibold">3. Where and who to contact</h2>
          <p className="mb-3 text-xs text-muted-foreground">Remembered for your next request.</p>
          <div className="grid gap-4 md:grid-cols-2">
            <Field label="Hospital" required>
              <input
                required
                value={form.hospital_name}
                onChange={(e) => update("hospital_name", e.target.value)}
                placeholder="e.g. KIMS Hubli"
                className={inputClass}
              />
            </Field>
            <Field label="Ward / unit">
              <input
                value={form.ward}
                onChange={(e) => update("ward", e.target.value)}
                placeholder="e.g. ICU 2, Labour room"
                className={inputClass}
              />
            </Field>
            <Field
              label="Hospital address or map coordinates"
              required
              hint='Used to call the nearest donors first. An address, or "lat,lng" like 15.3647,75.1240.'
              className="md:col-span-2"
            >
              <input
                required
                value={form.hospital_location}
                onChange={(e) => update("hospital_location", e.target.value)}
                placeholder="e.g. Vidyanagar, Hubli, Karnataka"
                className={inputClass}
              />
            </Field>
            <Field label="Contact person" required hint="Who the donor should reach on arrival.">
              <input
                required
                value={form.contact_name}
                onChange={(e) => update("contact_name", e.target.value)}
                placeholder="e.g. Nurse Asha"
                className={inputClass}
              />
            </Field>
            <Field label="Contact phone" required>
              <input
                required
                type="tel"
                minLength={6}
                value={form.contact_phone}
                onChange={(e) => update("contact_phone", e.target.value)}
                placeholder="+91 ..."
                className={inputClass}
              />
            </Field>
          </div>
        </section>

        {message && (
          <div
            className={`rounded-lg border px-3 py-2 text-sm ${
              message.type === "success"
                ? "border-success/40 bg-success/10 text-success"
                : "border-destructive/40 bg-destructive/10 text-destructive"
            }`}
          >
            {message.text}
          </div>
        )}

        <div className="flex justify-end">
          <Button type="submit" disabled={submitting || !doctorId}>
            {submitting ? <Loader2 className="mr-2 size-4 animate-spin" /> : <Droplet className="mr-2 size-4" />}
            {submitting ? "Sending..." : "Send request and start calling donors"}
          </Button>
        </div>
      </form>

      <section className="rounded-xl border border-border bg-card p-4">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold">Your requests</h2>
          <Button variant="ghost" size="sm" onClick={fetchRequests} disabled={loadingRequests}>
            <RefreshCw className="mr-2 size-4" />Refresh
          </Button>
        </div>

        {loadingRequests ? (
          <div className="inline-flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="size-4 animate-spin" />Loading requests...
          </div>
        ) : requests.length === 0 ? (
          <p className="text-sm text-muted-foreground">No blood requests yet.</p>
        ) : (
          <ul className="space-y-3">
            {requests.map((req) => {
              const status = requestStatus(req);
              return (
                <li key={req.id} className="rounded-lg border border-border p-3">
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div>
                      <p className="text-sm font-semibold">
                        {req.blood_type} · {componentLabel(req.component)} · {req.units_needed} unit(s)
                        <span
                          className={`ml-2 rounded-full border px-2 py-0.5 text-[10px] uppercase tracking-wide ${
                            req.urgency === "emergency"
                              ? "border-destructive/40 text-destructive"
                              : "border-border text-muted-foreground"
                          }`}
                        >
                          {req.urgency}
                        </span>
                      </p>
                      <p className="mt-1 text-xs text-muted-foreground">
                        For {req.recipient_name}
                        {req.hospital_name ? ` at ${req.hospital_name}` : ""}
                        {req.ward ? ` (${req.ward})` : ""}
                        {req.required_by ? ` · needed by ${formatDateTime(req.required_by)}` : ""}
                      </p>
                      <p className="mt-0.5 text-[11px] text-muted-foreground">Raised {formatDateTime(req.created_at)}</p>
                    </div>
                    <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-1 text-[11px] ${status.tone}`}>
                      {status.live && <Loader2 className="size-3 animate-spin" />}
                      {status.label}
                    </span>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </section>
    </div>
  );
}
