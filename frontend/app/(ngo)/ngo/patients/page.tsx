"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { ArrowRight, FileUp, Search, UserPlus, X } from "lucide-react";
import { Button, buttonVariants } from "@/components/ui/button";
import { useNgoSession } from "@/components/ngo/use-ngo-session";
import {
  EmptyState,
  ErrorBanner,
  FollowUpBadge,
  PageHeader,
  SourceBadge,
  formatDate,
  inputClass,
} from "@/components/ngo/ui";
import { listNgoPatients, type NgoPatientQuery } from "@/services/ngo-api";
import type { FollowUpFilter, NgoPatientListItem, Paginated, RegistrationSource } from "@/types/ngo";

const PAGE_SIZE = 20;

function NgoPatientsList() {
  const { token, handleError } = useNgoSession();
  const searchParams = useSearchParams();
  const importId = searchParams.get("import_id") || "";

  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [source, setSource] = useState<RegistrationSource | "">("");
  const [followUp, setFollowUp] = useState<FollowUpFilter | "">("");
  const [registeredFrom, setRegisteredFrom] = useState("");
  const [registeredTo, setRegisteredTo] = useState("");
  const [page, setPage] = useState(1);
  const [data, setData] = useState<Paginated<NgoPatientListItem> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Debounce the search box.
  useEffect(() => {
    const timer = setTimeout(() => {
      setSearch(searchInput.trim());
      setPage(1);
    }, 300);
    return () => clearTimeout(timer);
  }, [searchInput]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    const query: NgoPatientQuery = {
      search,
      source,
      follow_up: followUp,
      registered_from: registeredFrom,
      registered_to: registeredTo,
      import_id: importId,
      page,
      page_size: PAGE_SIZE,
    };
    try {
      setData(await listNgoPatients(token, query));
    } catch (err) {
      setError(handleError(err));
    } finally {
      setLoading(false);
    }
  }, [token, handleError, search, source, followUp, registeredFrom, registeredTo, importId, page]);

  useEffect(() => {
    load();
  }, [load]);

  const hasFilters = !!(search || source || followUp || registeredFrom || registeredTo);
  const resetFilters = () => {
    setSearchInput("");
    setSearch("");
    setSource("");
    setFollowUp("");
    setRegisteredFrom("");
    setRegisteredTo("");
    setPage(1);
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Patients"
        description={
          importId ? (
            <>Showing patients from one CSV import. <Link href="/ngo/patients" className="underline">Show all</Link></>
          ) : data ? `${data.total} patient${data.total === 1 ? "" : "s"} registered by your NGO.` : undefined
        }
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

      <div className="flex flex-wrap items-end gap-3">
        <label className="relative block w-full max-w-xs">
          <span className="sr-only">Search by name or phone</span>
          <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <input
            type="search"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            placeholder="Search name or phone…"
            maxLength={100}
            className={`${inputClass} pl-9`}
          />
        </label>
        <label className="block">
          <span className="mb-1 block text-xs font-medium text-muted-foreground">Source</span>
          <select value={source} onChange={(e) => { setSource(e.target.value as RegistrationSource | ""); setPage(1); }} className={inputClass}>
            <option value="">All</option>
            <option value="manual">Manual</option>
            <option value="csv">CSV</option>
          </select>
        </label>
        <label className="block">
          <span className="mb-1 block text-xs font-medium text-muted-foreground">Follow-up</span>
          <select value={followUp} onChange={(e) => { setFollowUp(e.target.value as FollowUpFilter | ""); setPage(1); }} className={inputClass}>
            <option value="">All</option>
            <option value="pending">Follow-up pending</option>
            <option value="none">No pending follow-up</option>
          </select>
        </label>
        <label className="block">
          <span className="mb-1 block text-xs font-medium text-muted-foreground">Registered from</span>
          <input type="date" value={registeredFrom} onChange={(e) => { setRegisteredFrom(e.target.value); setPage(1); }} className={inputClass} />
        </label>
        <label className="block">
          <span className="mb-1 block text-xs font-medium text-muted-foreground">Registered to</span>
          <input type="date" value={registeredTo} onChange={(e) => { setRegisteredTo(e.target.value); setPage(1); }} className={inputClass} />
        </label>
        {hasFilters && (
          <Button variant="ghost" onClick={resetFilters}>
            <X className="size-3.5" />
            Clear
          </Button>
        )}
      </div>

      <ErrorBanner message={error} />

      {loading && !data ? (
        <EmptyState>Loading patients…</EmptyState>
      ) : data && data.items.length === 0 ? (
        <EmptyState>
          {hasFilters || importId ? "No patients match these filters." : "No patients registered yet. Add a patient or import a CSV."}
        </EmptyState>
      ) : data ? (
        <div className="overflow-hidden rounded-xl border border-border bg-card">
          <div className="overflow-x-auto">
            <table className="w-full text-sm" aria-busy={loading}>
              <thead>
                <tr className="border-b border-border bg-muted/30 text-left text-xs uppercase tracking-wider text-muted-foreground">
                  <th className="px-5 py-3 font-semibold">Patient</th>
                  <th className="px-5 py-3 font-semibold">Phone</th>
                  <th className="px-5 py-3 font-semibold">Doctor</th>
                  <th className="px-5 py-3 font-semibold">Source</th>
                  <th className="px-5 py-3 font-semibold">Follow-up</th>
                  <th className="px-5 py-3 font-semibold">Next appointment</th>
                  <th className="px-5 py-3 font-semibold">Registered</th>
                  <th className="px-5 py-3"><span className="sr-only">Actions</span></th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((p) => (
                  <tr key={p.id} className="border-b border-border/50 last:border-0 hover:bg-muted/30">
                    <td className="px-5 py-3">
                      <Link href={`/ngo/patients/${p.id}`} className="font-medium hover:text-primary">{p.name}</Link>
                      {p.dob && <p className="text-[10px] text-muted-foreground">DOB: {p.dob}</p>}
                    </td>
                    <td className="px-5 py-3 text-muted-foreground">{p.phone}</td>
                    <td className="px-5 py-3 text-muted-foreground">{p.doctor_name || "—"}</td>
                    <td className="px-5 py-3"><SourceBadge source={p.source} /></td>
                    <td className="px-5 py-3"><FollowUpBadge pending={p.follow_up_pending} /></td>
                    <td className="px-5 py-3 text-muted-foreground">{formatDate(p.next_appointment_at, true)}</td>
                    <td className="px-5 py-3 text-muted-foreground">{formatDate(p.registered_at)}</td>
                    <td className="px-5 py-3 text-right">
                      <Link href={`/ngo/patients/${p.id}`} className={buttonVariants({ variant: "ghost", size: "sm" })}>
                        View
                        <ArrowRight className="size-3" />
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="flex items-center justify-between border-t border-border px-5 py-3 text-xs text-muted-foreground">
            <span>
              Page {data.page} of {data.total_pages} · {data.total} total
            </span>
            <div className="flex gap-2">
              <Button size="sm" variant="outline" disabled={page <= 1 || loading} onClick={() => setPage((p) => p - 1)}>
                Previous
              </Button>
              <Button size="sm" variant="outline" disabled={page >= data.total_pages || loading} onClick={() => setPage((p) => p + 1)}>
                Next
              </Button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

export default function NgoPatientsPage() {
  return (
    <Suspense fallback={<EmptyState>Loading patients…</EmptyState>}>
      <NgoPatientsList />
    </Suspense>
  );
}
