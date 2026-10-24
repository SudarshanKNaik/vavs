"use client";

import { useLocalAuth } from "@/lib/local-auth";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  getDoctorAvailabilitySettings,
  listDoctorAppointments,
  listDoctorSlots,
  updateDoctorAvailabilitySettings,
  type DoctorAppointmentItem,
  type DoctorAvailabilitySettings,
  type DoctorManagedSlot,
} from "@/services/api";
import { Button } from "@/components/ui/button";
import { CalendarClock, Loader2, RefreshCw } from "lucide-react";

function formatDateTime(value?: string | null) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

function formatDayLabel(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
}

function formatTimeLabel(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

function slotTone(status: string) {
  if (status === "available") return "border-success/40 bg-success/10 text-success";
  if (status === "reserved") return "border-warning/40 bg-warning/10 text-warning";
  if (status === "completed") return "border-emerald-400/50 bg-emerald-50 text-emerald-700";
  if (status === "booked") return "border-primary/40 bg-primary/10 text-primary";
  return "border-border bg-muted/40 text-muted-foreground";
}

export default function AvailabilityPage() {
  const { user } = useLocalAuth();
  const doctorId = user?.doctor_id || user?.sub;

  const [loading, setLoading] = useState(true);
  const [settings, setSettings] = useState<DoctorAvailabilitySettings | null>(null);
  const [slots, setSlots] = useState<DoctorManagedSlot[]>([]);
  const [appointmentStatusBySlotId, setAppointmentStatusBySlotId] = useState<Record<string, string>>({});
  const [statusFilter, setStatusFilter] = useState("all");
  const [toggling, setToggling] = useState(false);

  const [message, setMessage] = useState<string | null>(null);

  const fetchAvailabilityContext = useCallback(async () => {
    if (!doctorId) {
      setSettings(null);
      setSlots([]);
      setLoading(false);
      return;
    }

    setLoading(true);
    try {
      const [settingsData, slotsData, appointmentsData] = await Promise.all([
        getDoctorAvailabilitySettings(doctorId),
        listDoctorSlots(doctorId, { includePast: false }),
        listDoctorAppointments(doctorId),
      ]);
      setSettings(settingsData);
      setSlots(slotsData);

      const statusBySlot: Record<string, string> = {};
      for (const appt of (appointmentsData as DoctorAppointmentItem[])) {
        if (appt?.slot_id) {
          statusBySlot[appt.slot_id] = appt.status;
        }
      }
      setAppointmentStatusBySlotId(statusBySlot);
    } catch (err) {
      const text = err instanceof Error ? err.message : "Failed to load availability.";
      setMessage(text);
      setSettings(null);
      setSlots([]);
      setAppointmentStatusBySlotId({});
    } finally {
      setLoading(false);
    }
  }, [doctorId]);

  const getDisplayStatus = useCallback((slot: DoctorManagedSlot) => {
    const appointmentStatus = appointmentStatusBySlotId[slot.id];
    if (slot.status === "booked" && appointmentStatus === "completed") {
      return "completed";
    }
    return slot.status;
  }, [appointmentStatusBySlotId]);

  useEffect(() => {
    fetchAvailabilityContext();
  }, [fetchAvailabilityContext]);

  const filteredSlots = useMemo(() => {
    if (statusFilter === "all") return slots;
    return slots.filter((slot) => getDisplayStatus(slot) === statusFilter);
  }, [slots, statusFilter, getDisplayStatus]);

  const calendarData = useMemo(() => {
    const byDate = new Map<string, Map<string, DoctorManagedSlot>>();
    const allTimes = new Set<string>();

    for (const slot of filteredSlots) {
      const start = new Date(slot.slot_start);
      if (Number.isNaN(start.getTime())) continue;

      const dateKey = start.toISOString().slice(0, 10);
      const timeKey = start.toISOString().slice(11, 16);

      allTimes.add(timeKey);
      if (!byDate.has(dateKey)) byDate.set(dateKey, new Map<string, DoctorManagedSlot>());
      byDate.get(dateKey)?.set(timeKey, slot);
    }

    const dates = Array.from(byDate.keys()).sort((a, b) => a.localeCompare(b));
    const times = Array.from(allTimes).sort((a, b) => a.localeCompare(b));

    return { dates, times, byDate };
  }, [filteredSlots]);

  const handleToggleAvailability = useCallback(async (nextValue: boolean) => {
    if (!doctorId) return;
    setToggling(true);
    setMessage(null);

    try {
      const updated = await updateDoctorAvailabilitySettings(doctorId, {
        is_available: nextValue,
        confirm_reschedule_today: false,
      });
      setSettings(updated);
      setMessage(nextValue ? "Doctor marked available. Rolling slots regenerated." : "Doctor marked unavailable.");
      const refreshedSlots = await listDoctorSlots(doctorId, { includePast: false });
      setSlots(refreshedSlots);
      return;
    } catch (err) {
      const knownErr = err as Error & {
        status?: number;
        detail?: { detail?: { code?: string; pending_today_appointments?: number } };
      };
      const maybeCode = knownErr.detail?.detail?.code;
      const pendingCount = knownErr.detail?.detail?.pending_today_appointments || 0;

      if (knownErr.status === 409 && maybeCode === "CONFIRM_REQUIRED") {
        const proceed = window.confirm(
          `${pendingCount} appointment(s) for today will be moved to the next working day. Continue?`,
        );
        if (!proceed) {
          setMessage("Toggle cancelled. No appointments were moved.");
          return;
        }

        const confirmed = await updateDoctorAvailabilitySettings(doctorId, {
          is_available: nextValue,
          confirm_reschedule_today: true,
        });
        setSettings(confirmed);
        setMessage(
          `Doctor marked unavailable. ${confirmed.rescheduled_appointments || 0} appointment(s) moved to next working day.`,
        );
        const refreshedSlots = await listDoctorSlots(doctorId, { includePast: false });
        setSlots(refreshedSlots);
        return;
      }

      const text = err instanceof Error ? err.message : "Could not update availability status.";
      setMessage(text);
    } finally {
      setToggling(false);
    }
  }, [doctorId]);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Manage Availability</h1>
        <p className="text-sm text-muted-foreground">
          Toggle your day planning and keep an auto-managed 3-day rolling slot window.
        </p>
      </div>

      <div className="rounded-xl border border-border bg-card p-4">
        <h2 className="mb-3 text-sm font-semibold">Doctor Toggle</h2>
        <div className="flex flex-wrap items-center gap-3">
          <Button
            disabled={loading || toggling || settings?.is_available === true}
            onClick={() => handleToggleAvailability(true)}
          >
            {toggling && settings?.is_available === false ? "Updating..." : "Set Available"}
          </Button>
          <Button
            variant="outline"
            disabled={loading || toggling || settings?.is_available === false}
            onClick={() => handleToggleAvailability(false)}
          >
            {toggling && settings?.is_available === true ? "Updating..." : "Set Not Available"}
          </Button>
          <Button variant="ghost" disabled={loading || toggling} onClick={fetchAvailabilityContext}>
            <RefreshCw className="mr-2 size-4" />Refresh
          </Button>
          <span className="rounded-full border border-border px-2 py-1 text-xs text-muted-foreground">
            Current: {settings?.is_available ? "Available" : "Not Available"}
          </span>
          <span className="rounded-full border border-border px-2 py-1 text-xs text-muted-foreground">
            Pending today: {settings?.pending_today_appointments || 0}
          </span>
        </div>
        <p className="mt-3 text-xs text-muted-foreground">
          Rule set: 10:30 AM to 4:30 PM, 30-minute slots, 1:30 PM to 2:30 PM break, Sundays closed, rolling 3-day window.
        </p>
      </div>

      <div className="rounded-xl border border-border bg-card p-4">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <div>
            <h2 className="text-sm font-semibold">Calendar Slots</h2>
            <p className="text-xs text-muted-foreground">Table view by day and time.</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="rounded-lg border border-border bg-background px-3 py-2 text-xs"
            >
              <option value="all">All</option>
              <option value="available">Available</option>
              <option value="reserved">Reserved</option>
              <option value="completed">Completed</option>
              <option value="booked">Booked</option>
              <option value="cancelled">Cancelled</option>
            </select>
            <span className="rounded-full border border-success/30 bg-success/10 px-2 py-1 text-[11px] text-success">Available</span>
            <span className="rounded-full border border-warning/30 bg-warning/10 px-2 py-1 text-[11px] text-warning">Reserved</span>
            <span className="rounded-full border border-emerald-400/50 bg-emerald-50 px-2 py-1 text-[11px] text-emerald-700">Completed</span>
            <span className="rounded-full border border-primary/30 bg-primary/10 px-2 py-1 text-[11px] text-primary">Booked</span>
            <span className="rounded-full border border-border bg-muted/30 px-2 py-1 text-[11px] text-muted-foreground">Cancelled</span>
          </div>
        </div>

        {loading ? (
          <div className="inline-flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="size-4 animate-spin" />
            Loading slots...
          </div>
        ) : filteredSlots.length === 0 ? (
          <p className="text-sm text-muted-foreground">No slots found.</p>
        ) : (
          <div className="overflow-x-auto rounded-lg border border-border">
            <table className="min-w-full border-collapse text-xs">
              <thead>
                <tr className="bg-muted/40">
                  <th className="sticky left-0 z-10 border-b border-r border-border bg-muted/60 px-3 py-2 text-left font-semibold">Time</th>
                  {calendarData.dates.map((day) => (
                    <th key={day} className="border-b border-border px-3 py-2 text-left font-semibold">
                      {formatDayLabel(day)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {calendarData.times.map((timeKey) => (
                  <tr key={timeKey} className="align-top">
                    <td className="sticky left-0 z-10 border-r border-border bg-card px-3 py-3 font-medium text-foreground">
                      {formatTimeLabel(`1970-01-01T${timeKey}:00Z`)}
                    </td>
                    {calendarData.dates.map((day) => {
                      const slot = calendarData.byDate.get(day)?.get(timeKey);
                      const displayStatus = slot ? getDisplayStatus(slot) : null;
                      return (
                        <td key={`${day}-${timeKey}`} className="border-l border-border px-2 py-2">
                          {slot ? (
                            <div className={`rounded-md border px-2 py-2 ${slotTone(displayStatus || slot.status)}`}>
                              <p className="inline-flex items-center gap-1 text-[11px] font-semibold uppercase tracking-wide">
                                <CalendarClock className="size-3.5" />
                                {displayStatus || slot.status}
                              </p>
                              <p className="mt-1 text-[11px] leading-tight opacity-90">
                                {formatDateTime(slot.slot_start)}
                              </p>
                            </div>
                          ) : (
                            <div className="rounded-md border border-dashed border-border px-2 py-4 text-center text-[11px] text-muted-foreground">
                              -
                            </div>
                          )}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {message && (
        <div className="rounded-lg border border-border bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
          {message}
        </div>
      )}
    </div>
  );
}
