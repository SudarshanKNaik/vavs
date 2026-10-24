"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { useLocalAuth } from "@/lib/local-auth";
import {
  bookPatientPortalSlot,
  getPatientPortalMe,
  listDoctorAvailability,
  listDoctors,
  reschedulePatientPortalAppointment,
  type DoctorAvailabilitySlot,
  type DoctorListItem,
} from "@/services/api";
import { Button } from "@/components/ui/button";
import { CalendarClock, Loader2, Stethoscope } from "lucide-react";

type DoctorSlotsMap = Record<string, DoctorAvailabilitySlot[]>;

function formatDateTime(value?: string | null) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

export default function BookingClient() {
  const { user, isAuthenticated, isLoading } = useLocalAuth();
  const searchParams = useSearchParams();
  const authUserId = user?.sub ?? "";
  const appointmentId = searchParams.get("appointmentId") || "";

  const [loading, setLoading] = useState(true);
  const [doctors, setDoctors] = useState<DoctorListItem[]>([]);
  const [doctorSlots, setDoctorSlots] = useState<DoctorSlotsMap>({});
  const [expandedDoctorId, setExpandedDoctorId] = useState<string | null>(null);
  const [slotsLoadingDoctorId, setSlotsLoadingDoctorId] = useState<string | null>(null);
  const [consultationType, setConsultationType] = useState("video");
  const [bookingSlotId, setBookingSlotId] = useState<string | null>(null);
  const [status, setStatus] = useState<{ type: "success" | "error" | "info"; text: string } | null>(null);

  useEffect(() => {
    if (!isAuthenticated || !authUserId) {
      setLoading(false);
      return;
    }

    let active = true;
    setLoading(true);

    Promise.all([getPatientPortalMe(authUserId), listDoctors()])
      .then(async ([profile, doctorRows]) => {
        if (!active) return;

        if (!profile) {
          setStatus({ type: "info", text: "Complete patient registration first in the portal." });
          setDoctors(doctorRows);
          return;
        }

        setDoctors(doctorRows);
      })
      .catch((err) => {
        const text = err instanceof Error ? err.message : "Failed to load booking data.";
        if (active) setStatus({ type: "error", text });
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
    };
  }, [authUserId, isAuthenticated]);

  const availableDoctors = doctors;

  const handleSeeSlots = useCallback(async (doctorId: string) => {
    const isAlreadyOpen = expandedDoctorId === doctorId;
    setExpandedDoctorId(isAlreadyOpen ? null : doctorId);
    if (isAlreadyOpen || doctorSlots[doctorId]) return;

    setSlotsLoadingDoctorId(doctorId);
    setStatus(null);
    try {
      const rows = await listDoctorAvailability(doctorId);
      setDoctorSlots((prev) => ({ ...prev, [doctorId]: rows }));
    } catch (err) {
      const text = err instanceof Error ? err.message : "Failed to load slots.";
      setStatus({ type: "error", text });
    } finally {
      setSlotsLoadingDoctorId(null);
    }
  }, [doctorSlots, expandedDoctorId]);

  const handleBook = useCallback(async (slotId: string, doctorId: string) => {
    if (!authUserId) return;

    setBookingSlotId(slotId);
    setStatus(null);
    try {
      if (appointmentId) {
        await reschedulePatientPortalAppointment(appointmentId, {
          auth_user_id: authUserId,
          new_slot_id: slotId,
          consultation_type: consultationType,
        });
        setStatus({ type: "success", text: "Appointment rescheduled successfully." });
      } else {
        await bookPatientPortalSlot(slotId, {
          auth_user_id: authUserId,
          consultation_type: consultationType,
        });
        setStatus({ type: "success", text: "Appointment booked. Confirmation notification created." });
      }
      const refreshed = await listDoctorAvailability(doctorId);
      setDoctorSlots((prev) => ({ ...prev, [doctorId]: refreshed }));
    } catch (err) {
      const text = err instanceof Error ? err.message : "Booking failed.";
      setStatus({ type: "error", text });
    } finally {
      setBookingSlotId(null);
    }
  }, [appointmentId, authUserId, consultationType]);

  if (isLoading || loading) {
    return (
      <div className="mx-auto flex min-h-screen max-w-5xl items-center justify-center px-6">
        <div className="inline-flex items-center gap-2 text-sm text-[#6E6057]">
          <Loader2 className="size-4 animate-spin" />
          Loading booking flow...
        </div>
      </div>
    );
  }

  if (!isAuthenticated) {
    return (
      <div className="mx-auto flex min-h-screen max-w-3xl flex-col items-center justify-center gap-4 px-6 text-center">
        <h1 className="font-serif text-4xl tracking-tight md:text-5xl">Book Appointment</h1>
        <p className="text-sm text-[#6E6057]">Login to continue your booking.</p>
        <Link href="/patient-signIn"><Button>Patient Login</Button></Link>
      </div>
    );
  }

  return (
    <div className="mx-auto min-h-screen max-w-5xl px-6 py-10">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <p className="text-xs uppercase tracking-[0.18em] text-[#6E6057]">Phase 2</p>
          <h1 className="mt-2 font-serif text-4xl tracking-tight">Self-service Appointment Booking</h1>
          <p className="mt-2 text-sm text-[#6E6057]">
            {appointmentId
              ? "Choose a new slot to reschedule your appointment."
              : "Select a doctor and book any available slot."}
          </p>
        </div>
        <Link href="/patient"><Button variant="outline">Back to Portal</Button></Link>
      </div>

      <div className="grid gap-4 rounded-2xl border border-border/80 bg-card p-4 shadow-sm md:grid-cols-1">
        <select
          value={consultationType}
          onChange={(e) => setConsultationType(e.target.value)}
          className="rounded-lg border border-border/80 bg-background px-3 py-2 text-sm focus:border-primary/30 focus:outline-none focus:ring-2 focus:ring-primary/20"
        >
          <option value="video">Video</option>
          <option value="chat">Chat</option>
          <option value="in_person">In-person</option>
        </select>
      </div>

      {status && (
        <div className={`mt-4 rounded-lg px-3 py-2 text-sm ${status.type === "success" ? "border border-emerald-300 bg-emerald-50 text-emerald-700" : status.type === "error" ? "border border-destructive/40 bg-destructive/10 text-destructive" : "border border-border/80 bg-muted/40 text-[#5E5149]"}`}>
          {status.text}
        </div>
      )}

      <div className="mt-6 space-y-4">
        {availableDoctors.length === 0 ? (
          <article className="rounded-2xl border border-border/80 bg-card p-4 shadow-sm">
            <p className="text-sm text-[#6E6057]">No doctors found right now.</p>
          </article>
        ) : availableDoctors.map((doctor) => {
          const isExpanded = expandedDoctorId === doctor.id;
          const isSlotsLoading = slotsLoadingDoctorId === doctor.id;
          const slots = doctorSlots[doctor.id] || [];

          return (
            <article key={doctor.id} className="rounded-2xl border border-border/80 bg-card p-4 shadow-sm">
              <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
                <div>
                  <p className="text-sm font-semibold">{doctor.name}</p>
                  <div className="mt-1 flex flex-wrap gap-3 text-xs text-[#6E6057]">
                    <span className="inline-flex items-center gap-1"><Stethoscope className="size-3.5" />{doctor.specialty}</span>
                  </div>
                </div>
                <Button variant="outline" size="sm" onClick={() => handleSeeSlots(doctor.id)}>
                  {isExpanded ? "Hide Slots" : "See Available Slots"}
                </Button>
              </div>

              {isExpanded && (
                <div className="mt-3 space-y-2">
                  {isSlotsLoading ? (
                    <div className="inline-flex items-center gap-2 text-sm text-[#6E6057]">
                      <Loader2 className="size-4 animate-spin" />
                      Loading slots...
                    </div>
                  ) : (
                    <>
                      {slots.length === 0 ? (
                        <p className="text-sm text-[#6E6057]">No slots available for this doctor.</p>
                      ) : (
                        slots.map((slot) => (
                          <div key={slot.id} className="flex flex-col gap-2 rounded-md border border-border px-3 py-2 md:flex-row md:items-center md:justify-between">
                            <span className="inline-flex items-center gap-1 text-sm text-[#6E6057]">
                              <CalendarClock className="size-4" />
                              {formatDateTime(slot.slot_start)}
                            </span>
                            <Button
                              size="sm"
                              disabled={bookingSlotId === slot.id}
                              onClick={() => handleBook(slot.id, doctor.id)}
                            >
                              {bookingSlotId === slot.id ? "Saving..." : appointmentId ? "Reschedule Here" : "Confirm Booking"}
                            </Button>
                          </div>
                        ))
                      )}
                    </>
                  )}
                </div>
              )}
            </article>
          );
        })}
      </div>
    </div>
  );
}
