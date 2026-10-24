"use client";

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { useLocalAuth } from "@/lib/local-auth";
import {
  listDoctorAppointments,
  updateDoctorAppointment,
  type DoctorAppointmentItem,
} from "@/services/api";

import { cn } from "@/lib/utils";
import {
  Calendar,
  CheckCircle2,
  Clock,
  AlertCircle,
  FileText,
  Phone,
} from "lucide-react";

export default function AppointmentsPage() {
  const { user } = useLocalAuth();
  const doctorId = user?.doctor_id || user?.sub;

  const [appointments, setAppointments] = useState<DoctorAppointmentItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [savingId, setSavingId] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const fetchAppointments = useCallback(async () => {
    if (!doctorId) {
      setAppointments([]);
      setLoading(false);
      return;
    }

    setLoading(true);
    try {
      const data = await listDoctorAppointments(doctorId);
      setAppointments(Array.isArray(data) ? data : []);
    } catch {
      setAppointments([]);
    } finally {
      setLoading(false);
    }
  }, [doctorId]);

  useEffect(() => {
    fetchAppointments();
  }, [fetchAppointments]);

  const handleAppointmentUpdate = useCallback(
    async (
      appointmentId: string,
      payload: { status?: string; notes?: string },
    ) => {
      if (!doctorId) return;
      setSavingId(appointmentId);
      setMessage(null);
      try {
        await updateDoctorAppointment(appointmentId, {
          doctor_id: doctorId,
          ...payload,
        });
        await fetchAppointments();
        setMessage("Appointment updated.");
      } catch (err) {
        const text = err instanceof Error ? err.message : "Update failed.";
        setMessage(text);
      } finally {
        setSavingId(null);
      }
    },
    [doctorId, fetchAppointments],
  );

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Appointments</h1>
        <p className="text-sm text-muted-foreground">
          Appointments booked by patients.
          {!loading &&
            ` ${appointments.length} appointment${appointments.length !== 1 ? "s" : ""} found.`}
        </p>
      </div>

      {loading ? (
        <div className="rounded-xl border border-border bg-card p-12 text-center text-sm text-muted-foreground">
          Loading appointments…
        </div>
      ) : appointments.length === 0 ? (
        <div className="rounded-xl border border-border bg-card p-12 text-center">
          <Calendar className="size-10 text-muted-foreground/40 mx-auto mb-3" />
          <p className="text-sm text-muted-foreground">
            No appointments yet. Booked appointments will appear here.
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {appointments.map((apt) => {
            const StatusIcon =
              apt.status === "booked" || apt.status === "confirmed"
                ? CheckCircle2
                : apt.status === "cancelled"
                  ? AlertCircle
                  : Clock;
            const statusStyle =
              apt.status === "booked" || apt.status === "confirmed"
                ? "bg-success/10 text-success"
                : apt.status === "cancelled"
                  ? "bg-destructive/10 text-destructive"
                  : "bg-muted text-muted-foreground";

            return (
              <div
                key={apt.id}
                className="rounded-xl border border-border bg-card p-5"
              >
                <div className="flex items-start gap-4">
                  <div className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                    <Calendar className="size-5" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span
                        className={cn(
                          "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold capitalize",
                          statusStyle,
                        )}
                      >
                        <StatusIcon className="size-3" />
                        {apt.status}
                      </span>
                      <span className="text-xs text-muted-foreground">
                        {apt.consultation_type}
                      </span>
                    </div>
                    <div className="flex items-center gap-4 mt-2 text-xs text-muted-foreground">
                      <span>
                        Date:{" "}
                        <strong className="text-foreground">
                          {apt.slot_start
                            ? new Date(apt.slot_start).toLocaleDateString()
                            : "—"}
                        </strong>
                      </span>
                      <span>
                        Time:{" "}
                        <strong className="text-foreground">
                          {apt.slot_start
                            ? new Date(apt.slot_start).toLocaleTimeString()
                            : "—"}
                        </strong>
                      </span>
                      <span>
                        Patient:{" "}
                        <strong className="text-foreground">
                          {apt.patient_name || apt.patient_id?.slice(0, 8)}
                        </strong>
                      </span>
                    </div>
                    <div className="flex items-center gap-3 mt-1 text-[10px] text-muted-foreground">
                      <span>Phone: {apt.patient_phone || "—"}</span>
                      <span>
                        Created: {new Date(apt.created_at).toLocaleString()}
                      </span>
                    </div>
                    <div className="flex flex-wrap items-center gap-2 mt-2">
                      {apt.report_id && (
                        <span className="inline-flex items-center gap-1 text-[10px] bg-blue-50 text-blue-600 border border-blue-200 px-2 py-0.5 rounded-full">
                          <FileText className="size-2.5" />
                          {apt.report_title || "Linked Report"}
                          {apt.report_date && (
                            <span className="text-blue-400">
                              · {apt.report_date}
                            </span>
                          )}
                        </span>
                      )}
                      {apt.call_log_id && (
                        <span className="inline-flex items-center gap-1 text-[10px] bg-violet-50 text-violet-600 border border-violet-200 px-2 py-0.5 rounded-full">
                          <Phone className="size-2.5" />
                          Booked via call
                        </span>
                      )}
                    </div>
                    <div className="mt-3 grid gap-2 md:grid-cols-3">
                      <select
                        defaultValue={apt.status}
                        className="rounded-md border border-border bg-background px-2 py-1.5 text-xs"
                        onChange={(e) => {
                          void handleAppointmentUpdate(apt.id, {
                            status: e.target.value,
                          });
                        }}
                        disabled={savingId === apt.id}
                      >
                        <option value="booked">booked</option>
                        <option value="confirmed">confirmed</option>
                        <option value="in_progress">in_progress</option>
                        <option value="completed">completed</option>
                        <option value="no_show">no_show</option>
                        <option value="cancelled">cancelled</option>
                      </select>
                      <div className="flex items-center">
                        <Link
                          href={`/consultation/${apt.id}`}
                          className="w-full"
                        >
                          <button className="w-full rounded-md border border-primary/30 bg-primary/10 px-2 py-1.5 text-xs text-primary hover:bg-primary/15">
                            {apt.consultation_type === "video" ? "Open Video" : "Open Chat"}
                          </button>
                        </Link>
                      </div>
                      <ButtonRow
                        disabled={savingId === apt.id}
                        onConfirm={() =>
                          handleAppointmentUpdate(apt.id, {
                            status: "confirmed",
                          })
                        }
                        onComplete={() =>
                          handleAppointmentUpdate(apt.id, {
                            status: "completed",
                          })
                        }
                        onCancel={() =>
                          handleAppointmentUpdate(apt.id, {
                            status: "cancelled",
                          })
                        }
                      />
                    </div>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {message && (
        <div className="rounded-lg border border-border bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
          {message}
        </div>
      )}
    </div>
  );
}

function ButtonRow({
  onConfirm,
  onComplete,
  onCancel,
  disabled,
}: {
  onConfirm: () => void;
  onComplete: () => void;
  onCancel: () => void;
  disabled: boolean;
}) {
  return (
    <div className="md:col-span-2 flex flex-wrap gap-2">
      <button
        className="rounded-md border border-border px-2 py-1 text-xs hover:bg-muted disabled:opacity-50"
        disabled={disabled}
        onClick={() => void onConfirm()}
      >
        Confirm
      </button>
      <button
        className="rounded-md border border-border px-2 py-1 text-xs hover:bg-muted disabled:opacity-50"
        disabled={disabled}
        onClick={() => void onComplete()}
      >
        Complete
      </button>
      <button
        className="rounded-md border border-destructive/40 px-2 py-1 text-xs text-destructive hover:bg-destructive/10 disabled:opacity-50"
        disabled={disabled}
        onClick={() => void onCancel()}
      >
        Cancel
      </button>
    </div>
  );
}
