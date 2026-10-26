"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { FileUp, UserPlus } from "lucide-react";
import { buttonVariants } from "@/components/ui/button";
import { useNgoSession } from "@/components/ngo/use-ngo-session";
import {
  EmptyState,
  ErrorBanner,
  PageHeader,
  Panel,
  SourceBadge,
  StatCard,
  formatDate,
} from "@/components/ngo/ui";
import { getNgoDashboard } from "@/services/ngo-api";
import type { NgoDashboard } from "@/types/ngo";

export default function NgoDashboardPage() {
  const { token, user, handleError } = useNgoSession();
  const [data, setData] = useState<NgoDashboard | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getNgoDashboard(token)
      .then((d) => !cancelled && setData(d))
      .catch((err) => !cancelled && setError(handleError(err)));
    return () => {
      cancelled = true;
    };
  }, [token, handleError]);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Dashboard"
        description={`Patients registered by ${user?.ngo_name || "your NGO"}.`}
        actions={
          <>
            <Link href="/ngo/patients/import" className={buttonVariants({ variant: "outline" })}>
              <FileUp className="size-4" />
              Import CSV
            </Link>
            <Link href="/ngo/patients/new" className={buttonVariants()}>
              <UserPlus className="size-4" />
              Add Patient
            </Link>
          </>
        }
      />

      <ErrorBanner message={error} />

      {!data && !error ? (
        <EmptyState>Loading dashboard…</EmptyState>
      ) : data ? (
        <>
          <div className="grid gap-4 sm:grid-cols-3">
            <StatCard label="Total patients" value={data.total_patients} />
            <StatCard label="Registered manually" value={data.manual_patients} />
            <StatCard label="Imported via CSV" value={data.csv_patients} />
          </div>

          <Panel
            title="Recent registrations"
            action={<Link href="/ngo/patients" className="text-xs text-primary hover:underline">View all</Link>}
          >
            {data.recent_registrations.length === 0 ? (
              <p className="text-sm text-muted-foreground">No patients registered yet.</p>
            ) : (
              <ul className="divide-y divide-border/60">
                {data.recent_registrations.map((p) => (
                  <li key={p.id} className="flex items-center justify-between gap-3 py-2.5 text-sm">
                    <Link href={`/ngo/patients/${p.id}`} className="font-medium hover:text-primary">{p.name}</Link>
                    <span className="flex items-center gap-2 text-xs text-muted-foreground">
                      <SourceBadge source={p.source} />
                      {formatDate(p.registered_at)}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </Panel>
        </>
      ) : null}
    </div>
  );
}
