"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { ArrowRight, CalendarCheck, CalendarClock, CalendarX, Loader2 } from "lucide-react";
import {
  listDoctorAppointmentActivity,
  listDoctorUpcomingAppointments,
  type AppointmentActivityItem,
  type DoctorAppointmentItem,
} from "@/services/api";

// How often doctor pages re-check for new bookings and call results.
const REFRESH_MS = 10_000;

export function formatSlotTime(value?: string | null) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(undefined, { weekday: "short", day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });
}

export function timeAgo(value?: string | null) {
  if (!value) return "";
  const diff = Date.now() - new Date(value).getTime();
  if (Number.isNaN(diff)) return "";
  const minutes = Math.round(diff / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  return `${Math.round(hours / 24)} d ago`;
}

/** One readable line per event, shared by the dashboard and the bell. */
export function describeActivity(item: AppointmentActivityItem) {
  const who = item.patient_name || "A patient";
  if (item.kind === "rescheduled") {
    return {
      icon: CalendarClock,
      tone: "text-warning",
      text: `${who} rescheduled ${formatSlotTime(item.slot_start)} → ${formatSlotTime(item.new_slot_start)}`,
    };
  }
  if (item.kind === "cancelled") {
    const by = item.actor === "patient" ? "cancelled" : item.actor === "doctor" ? "appointment cancelled by you" : "appointment cancelled";
    return {
      icon: CalendarX,
      tone: "text-destructive",
      text: item.actor === "patient" ? `${who} cancelled ${formatSlotTime(item.slot_start)}` : `${who}: ${by} (${formatSlotTime(item.slot_start)})`,
    };
  }
  return { icon: CalendarCheck, tone: "text-success", text: `${who} booked ${formatSlotTime(item.slot_start)}` };
}

/** Re-run `load` on an interval and whenever the tab regains focus. */
export function useLiveRefresh(load: () => void | Promise<void>, intervalMs = REFRESH_MS) {
  useEffect(() => {
    const timer = window.setInterval(load, intervalMs);
    const onFocus = () => load();
    window.addEventListener("focus", onFocus);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener("focus", onFocus);
    };
  }, [load, intervalMs]);
}

/** Dashboard panel: next appointments plus recent patient changes. */
export function AppointmentsOverview({ doctorId }: { doctorId?: string }) {
  const [upcoming, setUpcoming] = useState<DoctorAppointmentItem[]>([]);
  const [activity, setActivity] = useState<AppointmentActivityItem[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    if (!doctorId) return;
    try {
      const [rows, events] = await Promise.all([
        listDoctorUpcomingAppointments(doctorId).catch(() => []),
        listDoctorAppointmentActivity(doctorId).catch(() => []),
      ]);
      setUpcoming(
        rows
          .filter((a) => a.status === "booked" || a.status === "confirmed")
          .sort((a, b) => new Date(a.slot_start || 0).getTime() - new Date(b.slot_start || 0).getTime()),
      );
      setActivity(events);
    } finally {
      setLoading(false);
    }
  }, [doctorId]);

  useEffect(() => {
    load();
  }, [load]);
  useLiveRefresh(load);

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <section className="rounded-xl border border-border bg-card">
        <div className="flex items-center justify-between border-b border-border px-5 py-4">
          <div>
            <h3 className="text-sm font-semibold">Upcoming appointments</h3>
            <p className="mt-0.5 text-xs text-muted-foreground">{loading ? "Loading…" : `${upcoming.length} booked`}</p>
          </div>
          <Link href="/appointments" className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
            View all <ArrowRight className="size-3" />
          </Link>
        </div>
        {loading ? (
          <div className="flex items-center gap-2 px-5 py-6 text-sm text-muted-foreground"><Loader2 className="size-4 animate-spin" />Loading…</div>
        ) : upcoming.length === 0 ? (
          <p className="px-5 py-6 text-sm text-muted-foreground">No upcoming appointments.</p>
        ) : (
          <ul className="divide-y divide-border">
            {upcoming.slice(0, 6).map((a) => (
              <li key={a.id} className="flex items-center justify-between gap-3 px-5 py-3 text-sm">
                <div className="min-w-0">
                  <p className="truncate font-medium">{a.patient_name || "Patient"}</p>
                  <p className="text-xs text-muted-foreground">{a.consultation_type}{a.report_title ? ` · ${a.report_title}` : ""}</p>
                </div>
                <span className="shrink-0 text-xs text-muted-foreground">{formatSlotTime(a.slot_start)}</span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="rounded-xl border border-border bg-card">
        <div className="border-b border-border px-5 py-4">
          <h3 className="text-sm font-semibold">Recent appointment changes</h3>
          <p className="mt-0.5 text-xs text-muted-foreground">Bookings, cancellations and reschedules, last 14 days</p>
        </div>
        {loading ? (
          <div className="flex items-center gap-2 px-5 py-6 text-sm text-muted-foreground"><Loader2 className="size-4 animate-spin" />Loading…</div>
        ) : activity.length === 0 ? (
          <p className="px-5 py-6 text-sm text-muted-foreground">No recent changes.</p>
        ) : (
          <ul className="divide-y divide-border">
            {activity.slice(0, 6).map((item) => {
              const d = describeActivity(item);
              return (
                <li key={`${item.kind}-${item.appointment_id}`} className="flex items-start gap-3 px-5 py-3 text-sm">
                  <d.icon className={`mt-0.5 size-4 shrink-0 ${d.tone}`} aria-hidden />
                  <span className="min-w-0 flex-1">{d.text}</span>
                  <span className="shrink-0 text-xs text-muted-foreground">{timeAgo(item.happened_at)}</span>
                </li>
              );
            })}
          </ul>
        )}
      </section>
    </div>
  );
}
