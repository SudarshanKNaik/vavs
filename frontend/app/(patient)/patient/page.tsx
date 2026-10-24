"use client";

import Link from "next/link";
import { useLocalAuth } from "@/lib/local-auth";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  cancelPatientPortalAppointment,
  listDoctors,
  listDoctorFeedback,
  listReports,
  registerPatientPortal,
  getPatientPortalMe,
  listPatientPortalAppointments,
  type DoctorListItem,
  type DoctorFeedbackItem,
  type PatientPortalAppointment,
  type PatientPortalProfile,
  type ReportItem,
} from "@/services/api";
import { Button } from "@/components/ui/button";
import {
  BadgeCheck,
  CalendarClock,
  FileText,
  Loader2,
  Phone,
  Star,
  Stethoscope,
  UserRound,
} from "lucide-react";
import FeedbackForm from "@/components/FeedbackForm";

function formatDateTime(value?: string | null) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

export default function PatientPortalPage() {
  const { user, isLoading, isAuthenticated, logout } = useLocalAuth();

  const [profile, setProfile] = useState<PatientPortalProfile | null>(null);
  const [appointments, setAppointments] = useState<PatientPortalAppointment[]>(
    [],
  );
  const [reports, setReports] = useState<ReportItem[]>([]);
  const [doctors, setDoctors] = useState<DoctorListItem[]>([]);
  const [feedbackByDoctor, setFeedbackByDoctor] = useState<
    Record<string, DoctorFeedbackItem[]>
  >({});
  const [feedbackDoctorId, setFeedbackDoctorId] = useState<string | null>(null);

  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [selectedDoctorId, setSelectedDoctorId] = useState("");

  const [loading, setLoading] = useState(true);
  const [registering, setRegistering] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const authUserId = user?.sub ?? "";

  const loadDoctors = useCallback(async () => {
    const rows = await listDoctors();
    setDoctors(rows);

    if (!selectedDoctorId && rows.length > 0) {
      setSelectedDoctorId(rows[0].id);
    }
  }, [selectedDoctorId]);

  const loadProfileAndAppointments = useCallback(async () => {
    if (!authUserId) return;

    const me = await getPatientPortalMe(authUserId);
    setProfile(me);

    if (me) {
      setName(me.name || "");
      setPhone(me.phone || "");
      const [appts, reportRows] = await Promise.all([
        listPatientPortalAppointments(authUserId),
        listReports(me.id),
      ]);
      setAppointments(appts);
      setReports(reportRows);
    } else {
      setAppointments([]);
      setReports([]);
      setName(user?.name || "");
      setPhone("");
    }
  }, [authUserId, user?.name]);

  useEffect(() => {
    if (!isAuthenticated || !authUserId) {
      setLoading(false);
      return;
    }

    let active = true;
    setLoading(true);

    Promise.all([loadDoctors(), loadProfileAndAppointments()])
      .catch((err) => {
        if (active) {
          const text =
            err instanceof Error
              ? err.message
              : "Failed to load patient portal.";
          setMessage(text);
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
    };
  }, [authUserId, isAuthenticated, loadDoctors, loadProfileAndAppointments]);

  const handleRegister = useCallback(async () => {
    if (!authUserId || !user?.email) return;
    if (!name.trim() || !phone.trim() || !selectedDoctorId) {
      setMessage("Please fill name, phone, and primary doctor.");
      return;
    }

    setRegistering(true);
    setMessage(null);
    try {
      const created = await registerPatientPortal({
        auth_user_id: authUserId,
        email: user.email,
        name: name.trim(),
        phone: phone.trim(),
        doctor_id: selectedDoctorId,
      });
      setProfile(created);
      const [appts, reportRows] = await Promise.all([
        listPatientPortalAppointments(authUserId),
        listReports(created.id),
      ]);
      setAppointments(appts);
      setReports(reportRows);
      setMessage("Patient profile registered successfully.");
    } catch (err) {
      const text = err instanceof Error ? err.message : "Registration failed.";
      setMessage(text);
    } finally {
      setRegistering(false);
    }
  }, [authUserId, name, phone, selectedDoctorId, user?.email]);

  const upcomingAppointments = useMemo(
    () =>
      appointments.filter(
        (appt) => !["cancelled", "completed", "no_show"].includes(appt.status),
      ),
    [appointments],
  );

  const completedAppointmentsCount = useMemo(
    () =>
      appointments.filter(
        (appt) => (appt.status || "").toLowerCase() === "completed",
      ).length,
    [appointments],
  );

  const primaryDoctorName = useMemo(() => {
    if (!profile?.doctor_id) return "Not assigned";
    return (
      doctors.find((doctor) => doctor.id === profile.doctor_id)?.name ||
      "Assigned"
    );
  }, [doctors, profile?.doctor_id]);

  const nextAppointment = useMemo(() => {
    if (upcomingAppointments.length === 0) return null;
    const sorted = [...upcomingAppointments].sort((a, b) => {
      const aTime = new Date(a.slot_start || "").getTime();
      const bTime = new Date(b.slot_start || "").getTime();
      return aTime - bTime;
    });
    return sorted[0];
  }, [upcomingAppointments]);

  const completedDoctorIds = useMemo(() => {
    const ids = new Set<string>();
    for (const appt of appointments) {
      if ((appt.status || "").toLowerCase() === "completed" && appt.doctor_id) {
        ids.add(appt.doctor_id);
      }
    }
    return ids;
  }, [appointments]);

  const feedbackDoctors = useMemo(
    () => doctors.filter((doctor) => completedDoctorIds.has(doctor.id)),
    [doctors, completedDoctorIds],
  );

  useEffect(() => {
    let active = true;

    const run = async () => {
      if (feedbackDoctors.length === 0) {
        if (active) setFeedbackByDoctor({});
        return;
      }

      const feedbackPairs = await Promise.all(
        feedbackDoctors.map(async (doctor) => {
          try {
            const feedbackRows = await listDoctorFeedback(doctor.id, 5);
            return [doctor.id, feedbackRows] as const;
          } catch {
            return [doctor.id, []] as const;
          }
        }),
      );

      if (!active) return;
      setFeedbackByDoctor(Object.fromEntries(feedbackPairs));
    };

    run().catch(() => {
      if (active) setFeedbackByDoctor({});
    });

    return () => {
      active = false;
    };
  }, [feedbackDoctors]);

  const handleCancelAppointment = useCallback(
    async (appointmentId: string) => {
      if (!authUserId) return;
      setMessage(null);
      try {
        await cancelPatientPortalAppointment(appointmentId, {
          auth_user_id: authUserId,
        });
        const appts = await listPatientPortalAppointments(authUserId);
        setAppointments(appts);
        setMessage("Appointment cancelled.");
      } catch (err) {
        const text = err instanceof Error ? err.message : "Cancel failed.";
        setMessage(text);
      }
    },
    [authUserId],
  );

  if (isLoading || loading) {
    return (
      <div className="mx-auto flex min-h-screen max-w-6xl items-center justify-center px-6">
        <div className="inline-flex items-center gap-2 text-sm text-[#6E6057]">
          <Loader2 className="size-4 animate-spin" />
          Loading patient portal...
        </div>
      </div>
    );
  }

  if (!isAuthenticated) {
    return (
      <div className="mx-auto flex min-h-screen max-w-3xl flex-col items-center justify-center gap-4 px-6 text-center">
        <h1 className="font-serif text-4xl tracking-tight md:text-5xl">
          Patient Portal
        </h1>
        <p className="text-sm text-[#6E6057]">
          Sign in to view doctors, register as a patient, and book appointments.
        </p>
        <div className="flex items-center gap-2">
          <Link href="/patient-signIn">
            <Button>Patient Login</Button>
          </Link>
          <Link href="/patient-signUp">
            <Button variant="outline">Create Patient Account</Button>
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-background">
      <header className="sticky top-0 z-20 border-b border-border/80 bg-background/95 backdrop-blur-sm">
        <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-6">
          <div className="flex items-center gap-3">
            <div className="flex size-9 items-center justify-center rounded-full border border-border/80 bg-card">
              <UserRound className="size-4 text-[#5E5149]" />
            </div>
            <div>
              <p className="text-[11px] uppercase tracking-[0.16em] text-[#6E6057]">
                Patient Portal
              </p>
              <h1 className="text-sm font-semibold">
                Welcome, {user?.name || "Patient"}
              </h1>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Link href="/patient/booking">
              <Button size="sm">
                Book Appointment
              </Button>
            </Link>
            <Button
              variant="outline"
              size="sm"
              onClick={() =>
                logout({ logoutParams: { returnTo: window.location.origin } })
              }
            >
              Logout
            </Button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-7xl px-6 py-6">
        <section className="mb-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <div className="rounded-2xl border border-border/80 bg-card px-4 py-3 shadow-sm">
            <p className="text-[11px] uppercase tracking-[0.14em] text-[#6E6057]">
              Upcoming
            </p>
            <p className="mt-1 text-2xl font-semibold leading-none">
              {upcomingAppointments.length}
            </p>
            <p className="mt-2 text-xs text-[#6E6057]">Open appointments</p>
          </div>
          <div className="rounded-2xl border border-border/80 bg-card px-4 py-3 shadow-sm">
            <p className="text-[11px] uppercase tracking-[0.14em] text-[#6E6057]">
              Reports
            </p>
            <p className="mt-1 text-2xl font-semibold leading-none">
              {reports.length}
            </p>
            <p className="mt-2 text-xs text-[#6E6057]">
              Clinical files available
            </p>
          </div>
          <div className="rounded-2xl border border-border/80 bg-card px-4 py-3 shadow-sm">
            <p className="text-[11px] uppercase tracking-[0.14em] text-[#6E6057]">
              Completed
            </p>
            <p className="mt-1 text-2xl font-semibold leading-none">
              {completedAppointmentsCount}
            </p>
            <p className="mt-2 text-xs text-[#6E6057]">Visits completed</p>
          </div>
          <div className="rounded-2xl border border-border/80 bg-card px-4 py-3 shadow-sm">
            <p className="text-[11px] uppercase tracking-[0.14em] text-[#6E6057]">
              Primary Doctor
            </p>
            <p className="mt-1 truncate text-sm font-semibold">
              {primaryDoctorName}
            </p>
            <p className="mt-2 text-xs text-[#6E6057]">Care lead</p>
          </div>
        </section>

        <div className="grid gap-6 md:grid-cols-3">
          <section className="md:col-span-1 space-y-4">
          <div className="rounded-2xl border border-border/80 bg-card p-4 shadow-sm">
            <p className="text-xs uppercase tracking-[0.16em] text-[#6E6057]">
              Quick Actions
            </p>
            <h2 className="mt-2 text-base font-semibold">
              Plan Your Next Visit
            </h2>
            <p className="mt-1 text-xs leading-relaxed text-[#6E6057]">
              Book appointments with available doctors and choose from open
              slots.
            </p>
            {nextAppointment && (
              <div className="mt-3 rounded-lg border border-border/70 bg-background px-3 py-2 text-xs text-[#5E5149]">
                <p className="inline-flex items-center gap-1 font-medium text-foreground">
                  <CalendarClock className="size-3.5" />
                  Next: {nextAppointment.doctor_name || "Doctor"}
                </p>
                <p className="mt-1">{formatDateTime(nextAppointment.slot_start)}</p>
              </div>
            )}
            <Link href="/patient/booking" className="mt-3 block">
              <Button className="w-full">Book Appointment</Button>
            </Link>
          </div>

          <div className="rounded-2xl border border-border/80 bg-card p-4 shadow-sm">
            <h2 className="mb-3 text-sm font-semibold">Patient Registration</h2>

            {profile ? (
              <div className="space-y-2 text-sm">
                <p>
                  <span className="text-[#6E6057]">Name:</span>{" "}
                  {profile.name}
                </p>
                <p>
                  <span className="text-[#6E6057]">Email:</span>{" "}
                  {profile.email}
                </p>
                <p>
                  <span className="text-[#6E6057]">Phone:</span>{" "}
                  {profile.phone}
                </p>
                <p>
                  <span className="text-[#6E6057]">Primary doctor:</span>{" "}
                  {primaryDoctorName}
                </p>
              </div>
            ) : (
              <div className="space-y-3">
                <input
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="Full Name"
                  className="w-full rounded-lg border border-border/80 bg-background px-3 py-2 text-sm placeholder:text-[#8C7B70] focus:border-primary/30 focus:outline-none focus:ring-2 focus:ring-primary/20"
                />
                <input
                  value={phone}
                  onChange={(e) => setPhone(e.target.value)}
                  placeholder="Phone Number"
                  className="w-full rounded-lg border border-border/80 bg-background px-3 py-2 text-sm placeholder:text-[#8C7B70] focus:border-primary/30 focus:outline-none focus:ring-2 focus:ring-primary/20"
                />
                <select
                  value={selectedDoctorId}
                  onChange={(e) => setSelectedDoctorId(e.target.value)}
                  className="w-full rounded-lg border border-border/80 bg-background px-3 py-2 text-sm focus:border-primary/30 focus:outline-none focus:ring-2 focus:ring-primary/20"
                >
                  <option value="">Select primary doctor</option>
                  {doctors.map((doctor) => (
                    <option key={doctor.id} value={doctor.id}>
                      {doctor.name} - {doctor.specialty}
                    </option>
                  ))}
                </select>
                <Button disabled={registering} onClick={handleRegister}>
                  {registering ? "Registering..." : "Register Patient Profile"}
                </Button>
              </div>
            )}
          </div>
        </section>

        <section className="md:col-span-2 space-y-4">
          <div className="rounded-2xl border border-border/80 bg-card p-4 shadow-sm">
            <h2 className="mb-3 inline-flex items-center gap-2 text-sm font-semibold">
              <CalendarClock className="size-4 text-[#5E5149]" />
              Upcoming Appointments
            </h2>
            {upcomingAppointments.length === 0 ? (
              <p className="text-xs text-[#6E6057]">
                No upcoming appointments yet.
              </p>
            ) : (
              <div className="space-y-2">
                {upcomingAppointments.map((appt) => (
                  <div
                    key={appt.id}
                    className="rounded-xl border border-border/70 bg-background p-3 text-xs"
                  >
                    <div className="flex flex-col gap-2 md:flex-row md:items-start md:justify-between">
                      <div>
                        <p className="font-medium">
                          {appt.doctor_name || "Doctor"}
                        </p>
                        <p className="inline-flex items-center gap-1 text-[#6E6057]">
                          <Stethoscope className="size-3.5" />
                          {appt.doctor_specialty || "General Medicine"}
                        </p>
                        <p className="mt-1 text-[#5E5149]">
                          {formatDateTime(appt.slot_start)}
                        </p>
                      </div>
                      <span className="inline-flex w-fit rounded-full border border-border/70 bg-card px-2 py-0.5 text-[11px] font-medium capitalize text-[#5E5149]">
                        {appt.status.replace(/_/g, " ")}
                      </span>
                    </div>
                    {appt.report_title && (
                      <div className="mt-1 flex items-center gap-1 text-xs text-[#6E6057]">
                        <FileText className="size-3" />
                        Reason:{" "}
                        <span className="font-medium">{appt.report_title}</span>
                        {appt.report_date && <span>({appt.report_date})</span>}
                      </div>
                    )}
                    {appt.call_log_id && (
                      <div className="flex items-center gap-1 text-xs text-[#6E6057]">
                        <Phone className="size-3" />
                        Scheduled via AI call
                      </div>
                    )}
                    {appt.status !== "cancelled" &&
                      appt.status !== "completed" &&
                      appt.status !== "no_show" && (
                        <div className="mt-2 flex gap-2">
                          <Link href={`/consultation/${appt.id}`}>
                            <Button size="sm" variant="outline">
                              {appt.consultation_type === "video" ? "Open Video" : "Open Chat"}
                            </Button>
                          </Link>
                          <Link
                            href={`/patient/booking?appointmentId=${appt.id}`}
                          >
                            <Button size="sm" variant="outline">
                              Reschedule
                            </Button>
                          </Link>
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => handleCancelAppointment(appt.id)}
                          >
                            Cancel
                          </Button>
                        </div>
                      )}
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="rounded-2xl border border-border/80 bg-card p-4 shadow-sm">
            <h2 className="mb-3 inline-flex items-center gap-2 text-sm font-semibold">
              <FileText className="size-4 text-[#5E5149]" />
              My Reports
            </h2>
            {reports.length === 0 ? (
              <p className="text-xs text-[#6E6057]">
                No reports available yet.
              </p>
            ) : (
              <div className="space-y-2">
                {reports.slice(0, 12).map((report) => {
                  const reportTitle =
                    (report.report_data?.title as string | undefined) ||
                    (report.report_data?.summary as string | undefined) ||
                    "Clinical Report";

                  return (
                    <div
                      key={report.id}
                      className="rounded-xl border border-border/70 bg-background p-3 text-xs"
                    >
                      <p className="inline-flex items-center gap-1 font-medium">
                        <FileText className="size-3.5" />
                        {reportTitle}
                      </p>
                      <p className="mt-1 text-[#6E6057]">
                        Generated on {formatDateTime(report.created_at)}
                      </p>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          <div className="rounded-2xl border border-border/80 bg-card p-4 shadow-sm">
            <h2 className="mb-3 inline-flex items-center gap-2 text-sm font-semibold">
              <BadgeCheck className="size-4 text-[#5E5149]" />
              Doctors and Feedback
            </h2>
            {feedbackDoctors.length === 0 ? (
              <p className="text-xs text-[#6E6057]">
                Feedback and ratings appear after you complete an appointment with a doctor.
              </p>
            ) : (
              <div className="space-y-3">
                {feedbackDoctors.map((doctor) => {
                  const feedbackRows = feedbackByDoctor[doctor.id] || [];
                  return (
                    <div
                      key={doctor.id}
                      className="rounded-xl border border-border/70 bg-background p-3"
                    >
                      <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
                        <div>
                          <p className="text-sm font-medium">{doctor.name}</p>
                          <p className="text-xs text-[#6E6057]">
                            {doctor.specialty} • {doctor.language}
                          </p>
                          <p className="inline-flex items-center gap-1 text-xs text-[#6E6057]">
                            <Star className="size-3.5 text-amber-500" />
                            {doctor.rating_avg?.toFixed(1) || "0.0"} ({doctor.rating_count || 0})
                          </p>
                        </div>
                        <div className="flex items-center gap-2">
                          <Link href={`/patient/booking?doctorId=${doctor.id}`}>
                            <Button size="sm" variant="outline">
                              See Available Slots
                            </Button>
                          </Link>
                          <Button
                            size="sm"
                            onClick={() => setFeedbackDoctorId(doctor.id)}
                          >
                            Add Feedback
                          </Button>
                        </div>
                      </div>

                      <div className="mt-3 space-y-2">
                        {feedbackRows.length === 0 ? (
                          <p className="text-xs text-[#6E6057]">
                            No feedback yet for this doctor.
                          </p>
                        ) : (
                          feedbackRows.map((item) => (
                            <div
                              key={item.id}
                              className="rounded-md border border-border/70 px-3 py-2 text-xs"
                            >
                              <p className="font-medium">{item.rating}/5</p>
                              <p className="text-[#6E6057]">
                                {item.comment || "No comment"}
                              </p>
                              <p className="mt-1 text-[11px] text-[#6E6057]">
                                {formatDateTime(item.created_at)}
                              </p>
                            </div>
                          ))
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {message && (
            <div className="mt-4 rounded-lg border border-border/80 bg-muted/40 px-3 py-2 text-xs text-[#5E5149]">
              {message}
            </div>
          )}

          {feedbackDoctorId && (
            <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 px-4 backdrop-blur-[2px]">
              <div className="w-full max-w-md rounded-2xl border border-border bg-card p-5 shadow-2xl">
                <div className="mb-3 flex items-center justify-between">
                  <h3 className="text-sm font-semibold">Add Feedback</h3>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => setFeedbackDoctorId(null)}
                  >
                    Close
                  </Button>
                </div>
                <FeedbackForm
                  doctorId={feedbackDoctorId}
                  patientId={profile?.id}
                  onSubmitted={async () => {
                    const rows = await listDoctorFeedback(
                      feedbackDoctorId,
                      5,
                    ).catch(() => []);
                    setFeedbackByDoctor((prev) => ({
                      ...prev,
                      [feedbackDoctorId]: rows,
                    }));
                    await loadDoctors().catch(() => undefined);
                    setFeedbackDoctorId(null);
                  }}
                />
              </div>
            </div>
          )}
        </section>
        </div>
      </main>
    </div>
  );
}
