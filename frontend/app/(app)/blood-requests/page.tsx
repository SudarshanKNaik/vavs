"use client";

import { useLocalAuth } from "@/lib/local-auth";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  createBloodRequest,
  getBloodCampaignStatus,
  listBloodRequests,
  listPatients,
  type BloodCampaignAttempt,
  type BloodCampaignMessage,
  type BloodComponent,
  type BloodRequestItem,
  type BloodSource,
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

const SOURCES: { value: BloodSource; label: string; hint: string }[] = [
  { value: "donors", label: "Donors", hint: "Individual donors, nearest first" },
  { value: "orgs", label: "Organizations", hint: "Blood banks and hospitals that store blood" },
  { value: "any", label: "Any", hint: "Whoever is nearest, donor or organization" },
];

const RADIUS_KM = 20;

const ATTEMPT_LABELS: Record<string, { label: string; tone: string }> = {
  queued: { label: "Queued", tone: "text-muted-foreground" },
  active: { label: "Calling…", tone: "text-warning" },
  accepted: { label: "Accepted", tone: "text-success" },
  declined: { label: "No stock", tone: "text-destructive" },
  completed: { label: "Declined", tone: "text-destructive" },
  hangup: { label: "Hung up", tone: "text-warning" },
  failed: { label: "Failed", tone: "text-destructive" },
};

const MESSAGE_LABELS: Record<BloodCampaignMessage["kind"], string> = {
  donor_accepted: "Details texted",
  org_accepted: "Details texted",
  donor_missed: "Missed call: appeal texted",
  contact_update: "Contact person texted",
  contact_summary: "Contact person texted: nobody confirmed",
  doctor_summary: "Summary emailed to you",
};

const MESSAGE_TONES: Record<BloodCampaignMessage["status"], string> = {
  pending: "text-muted-foreground",
  sent: "text-success",
  failed: "text-destructive",
  skipped: "text-muted-foreground",
};

function MessageBadge({ message }: { message: BloodCampaignMessage }) {
  const status =
    message.status === "sent" ? "" : message.status === "pending" ? " (sending…)" : ` (${message.status})`;
  return (
    <span
      className={`text-[10px] ${MESSAGE_TONES[message.status]}`}
      title={message.detail ? `${message.recipient}: ${message.detail}` : message.recipient}
    >
      {message.channel === "email" ? "✉" : "💬"} {MESSAGE_LABELS[message.kind] || message.kind}
      {status}
    </span>
  );
}

// Hospital and contact details rarely change between requests, so remember
// them per doctor in this browser to save retyping. Best-effort only.
const DEFAULTS_KEY = "caresync_blood_request_defaults_v2";

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
  source: "orgs" as BloodSource,
  required_by: "",
  recipient_name: "",
  patient_id: "",
  reason: "",
  hospital_name: "KIMS Hubli",
  ward: "",
  hospital_location: "KIMS Hospital, Vidyanagar, Hubli, Karnataka",
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
  const orgOnly = req.source === "orgs";
  const confirmed = orgOnly
    ? `${req.donors_accepted ? "stock confirmed" : "no stock confirmed yet"}`
    : `${req.donors_accepted} of ${req.units_needed} donor(s) confirmed`;
  if (req.status === "draft" || req.status === "running") {
    return {
      label: `Calling ${orgOnly ? "organizations" : req.source === "any" ? "donors and organizations" : "donors"} · ${confirmed}${req.calls_in_progress ? ` · ${req.calls_in_progress} call(s) live` : ""}`,
      tone: "border-warning/40 bg-warning/10 text-warning",
      live: true,
    };
  }
  if (req.status === "stopped" || (!orgOnly && req.donors_accepted >= req.units_needed)) {
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
      label: `No one eligible within ${req.radius_km ?? RADIUS_KM} km (blood group, cooldown, radius or empty list)`,
      tone: "border-destructive/40 bg-destructive/10 text-destructive",
      live: false,
    };
  }
  return {
    label: `Everyone within ${req.radius_km ?? RADIUS_KM} km called · ${confirmed}`,
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

function RequestCalls({ requestId, live }: { requestId: string; live: boolean }) {
  const [attempts, setAttempts] = useState<BloodCampaignAttempt[]>([]);
  const [messages, setMessages] = useState<BloodCampaignMessage[]>([]);

  useEffect(() => {
    let cancelled = false;
    const load = () =>
      getBloodCampaignStatus(requestId)
        .then((detail) => {
          if (cancelled) return;
          setAttempts(detail.attempts);
          setMessages(detail.messages || []);
        })
        .catch(() => undefined);
    load();
    if (!live) return () => { cancelled = true; };
    const timer = window.setInterval(load, 4000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [requestId, live]);

  if (attempts.length === 0) return null;
  const requestMessages = messages.filter((m) => !m.attempt_id);
  return (
    <>
      <ul className="mt-3 divide-y divide-border rounded-md border border-border text-xs">
        {attempts.map((a) => {
          const state = ATTEMPT_LABELS[a.status] || { label: a.status, tone: "text-muted-foreground" };
          const attemptMessages = messages.filter((m) => m.attempt_id === a.id);
          return (
            <li key={a.id} className="px-3 py-1.5">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span>
                  {a.donor_name || "Unknown"}
                  <span className="ml-2 text-[10px] uppercase text-muted-foreground">
                    {a.target_type === "org" ? "organization" : "donor"}
                    {a.attempt_number && a.attempt_number > 1 ? ` · retry` : ""}
                  </span>
                </span>
                <span className={state.tone}>
                  {state.label}
                  {a.units_confirmed ? ` · ${a.units_confirmed} unit(s)` : ""}
                </span>
              </div>
              {attemptMessages.length > 0 && (
                <div className="mt-0.5 flex flex-wrap gap-x-3">
                  {attemptMessages.map((m) => (
                    <MessageBadge key={m.id} message={m} />
                  ))}
                </div>
              )}
            </li>
          );
        })}
      </ul>
      {requestMessages.length > 0 && (
        <div className="mt-1.5 flex flex-wrap gap-x-3 px-1">
          {requestMessages.map((m) => (
            <MessageBadge key={m.id} message={m} />
          ))}
        </div>
      )}
    </>
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
    // Links such as Outbreak Watch's platelet forecast pre-fill the request.
    const params = new URLSearchParams(window.location.search);
    const component = COMPONENTS.find((c) => c.value === params.get("component"))?.value;
    const urgency = URGENCIES.find((u) => u.value === params.get("urgency"))?.value;
    setForm((prev) => ({
      ...prev,
      ...(component && { component }),
      ...(urgency && { urgency }),
      ...(params.get("reason") && { reason: params.get("reason") as string }),
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
        source: form.source,
        radius_km: RADIUS_KM,
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
        text:
          form.source === "orgs"
            ? `Request sent. Calling blood-storing organizations within ${RADIUS_KM} km, nearest first, until one confirms.`
            : form.source === "any"
              ? `Request sent. Calling the nearest donors and organizations within ${RADIUS_KM} km until one confirms.`
              : `Request sent. Calling compatible ${form.blood_type} donors nearest first until ${form.units_needed} confirm.`,
      });
      // Keep hospital/contact details; clear the patient-specific fields.
      setForm((prev) => ({
        ...prev,
        blood_type: "",
        component: "whole_blood",
        units_needed: 1,
        urgency: "urgent",
        source: "orgs",
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
          Tell us what the patient needs. CareSync calls donors or blood-storing organizations within {RADIUS_KM} km, nearest first, until enough confirm.
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

          <div className="mt-4">
            <span className="text-xs font-medium">Get blood from <span className="text-destructive">*</span></span>
            <div className="mt-1 grid gap-2 sm:grid-cols-3" role="radiogroup" aria-label="Blood source">
              {SOURCES.map((src) => {
                const selected = form.source === src.value;
                return (
                  <button
                    key={src.value}
                    type="button"
                    role="radio"
                    aria-checked={selected}
                    onClick={() => update("source", src.value)}
                    className={`rounded-lg border px-3 py-2 text-left text-sm transition-colors ${
                      selected
                        ? "border-primary bg-primary/10 text-foreground"
                        : "border-border bg-background text-muted-foreground hover:border-primary/40"
                    }`}
                  >
                    <span className="block font-medium">{src.label}</span>
                    <span className="block text-[11px] opacity-80">{src.hint}</span>
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
          <h2 className="mb-1 text-sm font-semibold">3. Requesting body details</h2>
          <p className="mb-3 text-xs text-muted-foreground">
            The hospital or body making this request. Its address sets the {RADIUS_KM} km search area. Remembered for
            your next request.
          </p>
          <div className="grid gap-4 md:grid-cols-2">
            <Field label="Requesting hospital / body" required>
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
              label="Address or map coordinates"
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
            <Field label="Contact person" required hint="Who donors and organizations should reach.">
              <input
                required
                value={form.contact_name}
                onChange={(e) => update("contact_name", e.target.value)}
                placeholder="e.g. Nurse Asha"
                className={inputClass}
              />
            </Field>
            <Field label="Contact phone" required hint="Texted whenever someone says yes; shared with donors who agree.">

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
            {submitting ? "Sending..." : "Send request and start calling"}
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
                  <RequestCalls requestId={req.id} live={status.live} />
                </li>
              );
            })}
          </ul>
        )}
      </section>
    </div>
  );
}
