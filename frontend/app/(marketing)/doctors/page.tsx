"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  listDoctors,
  listDoctorAvailability,
  reserveSlot,
  type DoctorListItem,
  type DoctorAvailabilitySlot,
} from "@/services/api";
import { Button } from "@/components/ui/button";
import { CalendarClock, CircleDollarSign, Languages, Loader2, Stethoscope, User } from "lucide-react";

type AvailabilityMap = Record<string, DoctorAvailabilitySlot[]>;

function formatDateTime(value: string | null | undefined) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

export default function DoctorsPage() {
  const [doctors, setDoctors] = useState<DoctorListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [specialty, setSpecialty] = useState("");
  const [language, setLanguage] = useState("");
  const [consultationType, setConsultationType] = useState("");
  const [availableNowOnly, setAvailableNowOnly] = useState(false);

  const [patientId, setPatientId] = useState("");
  const [expandedDoctorId, setExpandedDoctorId] = useState<string | null>(null);
  const [availabilityByDoctor, setAvailabilityByDoctor] = useState<AvailabilityMap>({});
  const [availabilityLoadingFor, setAvailabilityLoadingFor] = useState<string | null>(null);
  const [reserveLoadingFor, setReserveLoadingFor] = useState<string | null>(null);
  const [actionMessage, setActionMessage] = useState<string | null>(null);

  const fetchDoctors = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await listDoctors({
        specialty: specialty || undefined,
        language: language || undefined,
        consultation_type: consultationType || undefined,
        available_now: availableNowOnly || undefined,
      });
      setDoctors(Array.isArray(data) ? data : []);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to load doctors.";
      setError(message);
      setDoctors([]);
    } finally {
      setLoading(false);
    }
  }, [availableNowOnly, consultationType, language, specialty]);

  useEffect(() => {
    fetchDoctors();
  }, [fetchDoctors]);

  const specialtyOptions = useMemo(
    () => Array.from(new Set(doctors.map((d) => d.specialty).filter(Boolean))).sort(),
    [doctors],
  );
  const languageOptions = useMemo(
    () => Array.from(new Set(doctors.map((d) => d.language).filter(Boolean))).sort(),
    [doctors],
  );

  const handleLoadAvailability = useCallback(
    async (doctorId: string) => {
      const isAlreadyOpen = expandedDoctorId === doctorId;
      if (isAlreadyOpen) {
        setExpandedDoctorId(null);
        return;
      }

      setExpandedDoctorId(doctorId);
      setActionMessage(null);

      if (availabilityByDoctor[doctorId]) return;

      setAvailabilityLoadingFor(doctorId);
      try {
        const slots = await listDoctorAvailability(doctorId);
        setAvailabilityByDoctor((prev) => ({ ...prev, [doctorId]: slots }));
      } catch (err) {
        const message = err instanceof Error ? err.message : "Could not load availability.";
        setActionMessage(message);
      } finally {
        setAvailabilityLoadingFor(null);
      }
    },
    [availabilityByDoctor, expandedDoctorId],
  );

  const handleReserveSlot = useCallback(
    async (slotId: string, doctorId: string) => {
      if (!patientId.trim()) {
        setActionMessage("Enter your Patient ID before reserving a slot.");
        return;
      }

      setReserveLoadingFor(slotId);
      setActionMessage(null);
      try {
        await reserveSlot(slotId, { patient_id: patientId.trim(), hold_minutes: 10 });
        setActionMessage("Slot reserved successfully for 10 minutes.");

        const [updatedDoctors, updatedSlots] = await Promise.all([
          listDoctors({
            specialty: specialty || undefined,
            language: language || undefined,
            consultation_type: consultationType || undefined,
            available_now: availableNowOnly || undefined,
          }),
          listDoctorAvailability(doctorId),
        ]);

        setDoctors(Array.isArray(updatedDoctors) ? updatedDoctors : []);
        setAvailabilityByDoctor((prev) => ({ ...prev, [doctorId]: updatedSlots }));
      } catch (err) {
        const message = err instanceof Error ? err.message : "Could not reserve slot.";
        setActionMessage(message);
      } finally {
        setReserveLoadingFor(null);
      }
    },
    [availableNowOnly, consultationType, language, patientId, specialty],
  );

  return (
    <section className="mx-auto max-w-7xl px-6 py-14 md:py-16">
      <div className="mb-8">
        <p className="text-xs font-medium uppercase tracking-[0.18em] text-muted-foreground">Doctor Directory</p>
        <h1 className="mt-3 font-serif text-4xl tracking-tight md:text-5xl">Find available doctors quickly</h1>
        <p className="mt-3 max-w-2xl text-sm text-muted-foreground">
          Filter by specialty, language, and consultation type. You can reserve a slot for a short booking hold.
        </p>
      </div>

      <div className="mb-5 grid gap-3 rounded-xl border border-border bg-card p-4 md:grid-cols-5">
        <input
          value={specialty}
          onChange={(e) => setSpecialty(e.target.value)}
          list="doctor-specialties"
          placeholder="Specialty"
          className="rounded-lg border border-border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
        />
        <datalist id="doctor-specialties">
          {specialtyOptions.map((opt) => (
            <option key={opt} value={opt} />
          ))}
        </datalist>

        <input
          value={language}
          onChange={(e) => setLanguage(e.target.value)}
          list="doctor-languages"
          placeholder="Language"
          className="rounded-lg border border-border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
        />
        <datalist id="doctor-languages">
          {languageOptions.map((opt) => (
            <option key={opt} value={opt} />
          ))}
        </datalist>

        <select
          value={consultationType}
          onChange={(e) => setConsultationType(e.target.value)}
          className="rounded-lg border border-border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
        >
          <option value="">Consultation Type</option>
          <option value="video">Video</option>
          <option value="chat">Chat</option>
          <option value="in_person">In-person</option>
          <option value="hybrid">Hybrid</option>
        </select>

        <input
          value={patientId}
          onChange={(e) => setPatientId(e.target.value)}
          placeholder="Patient ID (for reserve)"
          className="rounded-lg border border-border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
        />

        <div className="flex items-center gap-2">
          <label className="inline-flex items-center gap-2 text-sm text-muted-foreground">
            <input
              type="checkbox"
              checked={availableNowOnly}
              onChange={(e) => setAvailableNowOnly(e.target.checked)}
              className="h-4 w-4 rounded border-border"
            />
            Available now
          </label>
          <Button size="sm" onClick={fetchDoctors}>Apply</Button>
        </div>
      </div>

      {actionMessage && (
        <div className="mb-4 rounded-lg border border-border bg-muted/30 px-3 py-2 text-xs text-muted-foreground">{actionMessage}</div>
      )}

      {loading ? (
        <div className="rounded-xl border border-border bg-card p-10 text-center text-sm text-muted-foreground">
          <Loader2 className="mx-auto mb-2 size-4 animate-spin" />
          Loading doctors...
        </div>
      ) : error ? (
        <div className="rounded-xl border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
          {error}
        </div>
      ) : doctors.length === 0 ? (
        <div className="rounded-xl border border-border bg-card p-10 text-center text-sm text-muted-foreground">
          No doctors found for the selected filters.
        </div>
      ) : (
        <div className="space-y-3">
          {doctors.map((doctor) => {
            const isExpanded = expandedDoctorId === doctor.id;
            const slots = availabilityByDoctor[doctor.id] || [];
            const isSlotsLoading = availabilityLoadingFor === doctor.id;

            return (
              <article key={doctor.id} className="rounded-xl border border-border bg-card p-4">
                <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                  <div className="space-y-1">
                    <h2 className="text-base font-semibold">{doctor.name}</h2>
                    <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
                      <span className="inline-flex items-center gap-1"><Stethoscope className="size-3.5" />{doctor.specialty}</span>
                      <span className="inline-flex items-center gap-1"><Languages className="size-3.5" />{doctor.language}</span>
                      <span className="inline-flex items-center gap-1"><CircleDollarSign className="size-3.5" />${doctor.fee}</span>
                      <span className="inline-flex items-center gap-1"><User className="size-3.5" />{doctor.consultation_type}</span>
                      <span className="inline-flex items-center gap-1">
                        <span className="text-yellow-400">★</span>
                        {doctor.rating_avg?.toFixed(1) || "0.0"} ({doctor.rating_count || 0})
                      </span>
                    </div>
                  </div>

                  <div className="flex items-center gap-2">
                    <span
                      className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${doctor.available_now ? "bg-success/10 text-success" : "bg-muted text-muted-foreground"}`}
                    >
                      {doctor.available_now ? "Available now" : `Next: ${formatDateTime(doctor.next_slot_start)}`}
                    </span>
                    <Button size="sm" variant="outline" onClick={() => handleLoadAvailability(doctor.id)}>
                      {isExpanded ? "Hide Slots" : "View Slots"}
                    </Button>
                  </div>
                </div>

                {isExpanded && (
                  <div className="mt-4 rounded-lg border border-border/70 bg-background p-3">
                    {isSlotsLoading ? (
                      <div className="text-xs text-muted-foreground">Loading slots...</div>
                    ) : slots.length === 0 ? (
                      <div className="text-xs text-muted-foreground">No upcoming slots.</div>
                    ) : (
                      <div className="space-y-2">
                        {slots.map((slot) => (
                          <div
                            key={slot.id}
                            className="flex flex-col gap-2 rounded-md border border-border px-3 py-2 md:flex-row md:items-center md:justify-between"
                          >
                            <div className="text-xs text-muted-foreground">
                              <span className="inline-flex items-center gap-1 font-medium text-foreground">
                                <CalendarClock className="size-3.5" />
                                {formatDateTime(slot.slot_start)}
                              </span>
                              <span className="mx-1">to</span>
                              <span>{formatDateTime(slot.slot_end)}</span>
                            </div>
                            <Button
                              size="sm"
                              disabled={reserveLoadingFor === slot.id}
                              onClick={() => handleReserveSlot(slot.id, doctor.id)}
                            >
                              {reserveLoadingFor === slot.id ? "Reserving..." : "Reserve"}
                            </Button>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </article>
            );
          })}

        </div>
      )}
    </section>
  );
}
