"use client";

import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { ArrowLeft } from "lucide-react";
import { useNgoSession } from "@/components/ngo/use-ngo-session";
import {
  EmptyState,
  ErrorBanner,
  FollowUpBadge,
  PageHeader,
  Panel,
  SourceBadge,
  SuccessBanner,
  formatDate,
} from "@/components/ngo/ui";
import { getNgoPatient } from "@/services/ngo-api";
import type { NgoPatientDetail } from "@/types/ngo";

function Detail({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs font-medium text-muted-foreground">{label}</dt>
      <dd className="mt-0.5 text-sm">{children || "—"}</dd>
    </div>
  );
}

function PatientDetail() {
  const { patientId } = useParams<{ patientId: string }>();
  const justRegistered = useSearchParams().get("registered") === "1";
  const { token, handleError } = useNgoSession();
  const [patient, setPatient] = useState<NgoPatientDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getNgoPatient(token, patientId)
      .then((p) => !cancelled && setPatient(p))
      .catch((err) => !cancelled && setError(handleError(err)));
    return () => {
      cancelled = true;
    };
  }, [token, patientId, handleError]);

  return (
    <div className="space-y-6">
      <Link href="/ngo/patients" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
        <ArrowLeft className="size-4" /> Back to patients
      </Link>
      {justRegistered && <SuccessBanner message="Patient registered successfully." />}
      <ErrorBanner message={error} />

      {!patient && !error && <EmptyState>Loading patient…</EmptyState>}
      {patient && (
        <>
          <PageHeader title={patient.name} description={<>Registered {formatDate(patient.registered_at)} <SourceBadge source={patient.source} /></>} />

          <div className="grid gap-6 lg:grid-cols-3">
            <Panel title="Patient details">
              <dl className="grid gap-4">
                <Detail label="Phone">{patient.phone}</Detail>
                <Detail label="Date of birth">{patient.dob}</Detail>
                <Detail label="MRN / health ID">{patient.mrn}</Detail>
                <Detail label="Insurance / scheme">{patient.insurance}</Detail>
                <Detail label="Notes"><span className="whitespace-pre-wrap">{patient.notes}</span></Detail>
              </dl>
            </Panel>

            <Panel title="Care coordination">
              <dl className="grid gap-4">
                <Detail label="Assigned doctor">
                  {patient.doctor_name ? `${patient.doctor_name}${patient.doctor_specialty ? ` · ${patient.doctor_specialty}` : ""}` : null}
                </Detail>
                <Detail label="Follow-up status"><FollowUpBadge pending={patient.follow_up_pending} /></Detail>
                <Detail label="Registered by">{patient.registered_by}</Detail>
                <Detail label="Registration source">
                  {patient.source === "csv" && patient.import_id ? (
                    <Link href={`/ngo/imports/${patient.import_id}`} className="text-primary underline">CSV import</Link>
                  ) : (
                    "Manual registration"
                  )}
                </Detail>
              </dl>
            </Panel>

            <Panel title="Appointments">
              {patient.appointments.length === 0 ? (
                <p className="text-sm text-muted-foreground">No appointments yet.</p>
              ) : (
                <ul className="divide-y divide-border/60 text-sm">
                  {patient.appointments.map((a) => (
                    <li key={a.id} className="py-2">
                      <p className="font-medium">{formatDate(a.slot_start, true)}</p>
                      <p className="text-xs text-muted-foreground">{a.status}{a.doctor_name ? ` · ${a.doctor_name}` : ""}</p>
                    </li>
                  ))}
                </ul>
              )}
            </Panel>
          </div>
        </>
      )}
    </div>
  );
}

export default function NgoPatientDetailPage() {
  return (
    <Suspense fallback={<EmptyState>Loading patient…</EmptyState>}>
      <PatientDetail />
    </Suspense>
  );
}
