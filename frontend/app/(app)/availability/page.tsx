"use client";

import { useLocalAuth } from "@/lib/local-auth";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  cancelDoctorSlots,
  getDoctorAvailabilitySettings,
  listDoctorAppointments,
  listDoctorSlots,
  reopenDoctorSlots,
  updateDoctorAvailabilitySettings,
  type DoctorAppointmentItem,
  type DoctorAvailabilitySettings,
  type DoctorManagedSlot,
} from "@/services/api";
import { Button } from "@/components/ui/button";
import { ScheduleRulesCard } from "@/components/app/schedule-rules-card";
import { CalendarClock, CalendarX, ChevronLeft, ChevronRight, Loader2, RefreshCw, RotateCcw, X } from "lucide-react";

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

// Monday (YYYY-MM-DD) of the week a calendar date key falls in.
function weekStartOf(dateKey: string) {
  const d = new Date(`${dateKey}T00:00:00Z`);
  const offset = (d.getUTCDay() + 6) % 7;
  d.setUTCDate(d.getUTCDate() - offset);
  return d.toISOString().slice(0, 10);
}

function slotTone(status: string) {
  if (status === "available") return "border-success/40 bg-success/10 text-success";
  if (status === "reserved") return "border-warning/40 bg-warning/10 text-warning";
  if (status === "completed") return "border-emerald-400/50 bg-emerald-50 text-emerald-700";
  if (status === "booked") return "border-primary/40 bg-primary/10 text-primary";
  return "border-border bg-muted/40 text-muted-foreground";
}

function SlotAction({
  slot,
  displayStatus,
  busy,
  disabled,
  nowMs,
  onRemove,
  onReopen,
}: {
  slot: DoctorManagedSlot;
  displayStatus: string;
  busy: boolean;
  disabled: boolean;
  nowMs: number;
  onRemove: (slot: DoctorManagedSlot) => void;
  onReopen: (slot: DoctorManagedSlot) => void;
}) {
  if (displayStatus === "completed") return null;
  const isFuture = new Date(slot.slot_start).getTime() > nowMs;
  if (!isFuture) return null;

  const base =
    "mt-1.5 inline-flex items-center gap-1 rounded px-1 py-0.5 text-[10px] font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50";

  if (displayStatus === "cancelled") {
    return (
      <button type="button" disabled={disabled} onClick={() => onReopen(slot)} className={`${base} hover:bg-background/70`}>
        {busy ? <Loader2 className="size-3 animate-spin" /> : <RotateCcw className="size-3" />}
        Reopen
      </button>
    );
  }

  const hasPatient = displayStatus === "booked" || displayStatus === "reserved";
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={() => onRemove(slot)}
      className={`${base} text-destructive hover:bg-destructive/10`}
    >
      {busy ? <Loader2 className="size-3 animate-spin" /> : <X className="size-3" />}
      {hasPatient ? "Cancel appointment" : "Remove"}
    </button>
  );
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
  const [cancellingDay, setCancellingDay] = useState<string | null>(null);
  const [weekIndex, setWeekIndex] = useState(0);
  // Slot (or "day:<date>") with an action in flight, to disable its button.
  const [busyKey, setBusyKey] = useState<string | null>(null);
  // When slots were last loaded; decides which slots count as future.
  const [nowMs, setNowMs] = useState(() => Date.now());

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
      setNowMs(Date.now());

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

    const allDates = Array.from(byDate.keys()).sort((a, b) => a.localeCompare(b));
    const times = Array.from(allTimes).sort((a, b) => a.localeCompare(b));

    // A month of slots is too wide for one table: page through it a week
    // (Monday to Saturday) at a time.
    const weekStarts = Array.from(new Set(allDates.map(weekStartOf))).sort();
    const weekCount = Math.max(1, weekStarts.length);
    const currentWeek = weekStarts[Math.min(weekIndex, weekCount - 1)];
    const dates = allDates.filter((d) => weekStartOf(d) === currentWeek);

    return { dates, times, byDate, weekCount, currentWeek };
  }, [filteredSlots, weekIndex]);

  // Slots a "Cancel day" would touch, from all slots (not just the filtered view),
  // keyed the same way as the calendar columns. Completed visits are left alone.
  const cancellableSlotsByDay = useMemo(() => {
    const byDay = new Map<string, DoctorManagedSlot[]>();
    for (const slot of slots) {
      const start = new Date(slot.slot_start);
      if (Number.isNaN(start.getTime())) continue;
      const status = getDisplayStatus(slot);
      if (status === "cancelled" || status === "completed") continue;
      const dateKey = start.toISOString().slice(0, 10);
      if (!byDay.has(dateKey)) byDay.set(dateKey, []);
      byDay.get(dateKey)?.push(slot);
    }
    return byDay;
  }, [slots, getDisplayStatus]);

  const handleCancelDay = useCallback(async (day: string) => {
    if (!doctorId) return;
    const daySlots = cancellableSlotsByDay.get(day) || [];
    if (daySlots.length === 0) return;

    const bookedCount = daySlots.filter((slot) => slot.status === "booked" || slot.status === "reserved").length;
    const reason = window.prompt(
      `Cancel ${formatDayLabel(day)}?\n\n` +
        `${daySlots.length} slot(s) will be closed so no one can book them.` +
        (bookedCount > 0
          ? `\n${bookedCount} booked appointment(s) will be cancelled and those patients notified.`
          : "\nNo patients are booked on this day.") +
        "\n\nOptional reason to show patients (press OK to continue, Cancel to stop):",
      "",
    );
    if (reason === null) return;

    setCancellingDay(day);
    setMessage(null);
    try {
      const result = await cancelDoctorSlots(doctorId, {
        slot_ids: daySlots.map((slot) => slot.id),
        reason: reason.trim() || undefined,
      });
      setMessage(
        `${formatDayLabel(day)} cancelled: ${result.cancelled_slots} slot(s) closed, ` +
          `${result.cancelled_appointments} appointment(s) cancelled` +
          (result.cancelled_appointments > 0 ? " and patients notified." : "."),
      );
      await fetchAvailabilityContext();
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Could not cancel the day.");
    } finally {
      setCancellingDay(null);
    }
  }, [cancellableSlotsByDay, doctorId, fetchAvailabilityContext]);

  // Future cancelled slots per day, for "Reopen day".
  const reopenableSlotsByDay = useMemo(() => {
    const byDay = new Map<string, DoctorManagedSlot[]>();
    for (const slot of slots) {
      const start = new Date(slot.slot_start);
      if (Number.isNaN(start.getTime()) || slot.status !== "cancelled" || start.getTime() <= nowMs) continue;
      const dateKey = start.toISOString().slice(0, 10);
      if (!byDay.has(dateKey)) byDay.set(dateKey, []);
      byDay.get(dateKey)?.push(slot);
    }
    return byDay;
  }, [slots, nowMs]);

  const handleRemoveSlot = useCallback(async (slot: DoctorManagedSlot) => {
    if (!doctorId) return;
    const when = formatDateTime(slot.slot_start);
    const hasPatient = slot.status === "booked" || slot.status === "reserved";
    let reason: string | null = "";
    if (hasPatient) {
      reason = window.prompt(
        `Cancel the appointment at ${when}?\n\nThe patient will be notified and the slot closed.` +
          "\n\nOptional reason to show the patient:",
        "",
      );
      if (reason === null) return;
    } else if (!window.confirm(`Remove the ${when} slot? Patients and the call agent won't be able to book it.`)) {
      return;
    }

    setBusyKey(slot.id);
    setMessage(null);
    try {
      const result = await cancelDoctorSlots(doctorId, {
        slot_ids: [slot.id],
        reason: reason?.trim() || undefined,
      });
      setMessage(
        result.cancelled_appointments > 0
          ? `Appointment at ${when} cancelled and the patient notified.`
          : `Slot at ${when} removed.`,
      );
      await fetchAvailabilityContext();
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Could not remove the slot.");
    } finally {
      setBusyKey(null);
    }
  }, [doctorId, fetchAvailabilityContext]);

  const handleReopen = useCallback(async (slotIds: string[], label: string, key: string) => {
    if (!doctorId || slotIds.length === 0) return;
    setBusyKey(key);
    setMessage(null);
    try {
      const result = await reopenDoctorSlots(doctorId, slotIds);
      setMessage(`${label} reopened: ${result.reopened_slots} slot(s) bookable again.`);
      await fetchAvailabilityContext();
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Could not reopen.");
    } finally {
      setBusyKey(null);
    }
  }, [doctorId, fetchAvailabilityContext]);

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
          Set your working hours and slot length. Open slots are kept up to date automatically.
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
        <ScheduleRulesCard doctorId={doctorId} onSaved={fetchAvailabilityContext} />
      </div>

      {message && (
        <div className="rounded-lg border border-border bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
          {message}
        </div>
      )}

      <div className="rounded-xl border border-border bg-card p-4">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <div>
            <h2 className="text-sm font-semibold">Calendar Slots</h2>
            <p className="text-xs text-muted-foreground">
              {calendarData.currentWeek
                ? `Week of ${formatDayLabel(calendarData.currentWeek)} · week ${Math.min(weekIndex, calendarData.weekCount - 1) + 1} of ${calendarData.weekCount}`
                : "Table view by day and time."}
            </p>
            <div className="mt-2 flex items-center gap-1">
              <button
                type="button"
                onClick={() => setWeekIndex((w) => Math.max(0, w - 1))}
                disabled={weekIndex === 0}
                className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-xs disabled:opacity-40"
              >
                <ChevronLeft className="size-3.5" />Previous week
              </button>
              <button
                type="button"
                onClick={() => setWeekIndex((w) => Math.min(calendarData.weekCount - 1, w + 1))}
                disabled={weekIndex >= calendarData.weekCount - 1}
                className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-xs disabled:opacity-40"
              >
                Next week<ChevronRight className="size-3.5" />
              </button>
              {weekIndex > 0 && (
                <button type="button" onClick={() => setWeekIndex(0)} className="px-2 py-1 text-xs text-muted-foreground hover:text-foreground">
                  This week
                </button>
              )}
            </div>
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
                  {calendarData.dates.map((day) => {
                    const cancellableCount = cancellableSlotsByDay.get(day)?.length || 0;
                    const isCancelling = cancellingDay === day;
                    return (
                      <th key={day} className="border-b border-border px-3 py-2 text-left font-semibold">
                        <div className="flex items-center justify-between gap-2">
                          <span>{formatDayLabel(day)}</span>
                          {cancellableCount > 0 ? (
                            <button
                              type="button"
                              onClick={() => handleCancelDay(day)}
                              disabled={cancellingDay !== null || loading}
                              title={`Cancel all ${cancellableCount} open or booked slot(s) on this day`}
                              className="inline-flex shrink-0 items-center gap-1 rounded-md border border-destructive/30 px-1.5 py-0.5 text-[10px] font-medium text-destructive transition-colors hover:bg-destructive/10 disabled:cursor-not-allowed disabled:opacity-50"
                            >
                              {isCancelling ? <Loader2 className="size-3 animate-spin" /> : <CalendarX className="size-3" />}
                              {isCancelling ? "Cancelling" : "Cancel day"}
                            </button>
                          ) : (reopenableSlotsByDay.get(day)?.length || 0) > 0 ? (
                            <button
                              type="button"
                              onClick={() =>
                                handleReopen(
                                  (reopenableSlotsByDay.get(day) || []).map((s) => s.id),
                                  formatDayLabel(day),
                                  `day:${day}`,
                                )
                              }
                              disabled={busyKey !== null || loading}
                              title="Make this day's cancelled slots bookable again"
                              className="inline-flex shrink-0 items-center gap-1 rounded-md border border-border px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground transition-colors hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50"
                            >
                              {busyKey === `day:${day}` ? <Loader2 className="size-3 animate-spin" /> : <RotateCcw className="size-3" />}
                              Reopen day
                            </button>
                          ) : (
                            <span className="shrink-0 text-[10px] font-normal text-muted-foreground">Day closed</span>
                          )}
                        </div>
                      </th>
                    );
                  })}
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
                              <SlotAction
                                slot={slot}
                                displayStatus={displayStatus || slot.status}
                                busy={busyKey === slot.id}
                                disabled={busyKey !== null || cancellingDay !== null}
                                nowMs={nowMs}
                                onRemove={handleRemoveSlot}
                                onReopen={(s) => handleReopen([s.id], formatDateTime(s.slot_start), s.id)}
                              />
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
    </div>
  );
}
