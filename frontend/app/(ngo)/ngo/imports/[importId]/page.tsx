"use client";

import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { ArrowLeft, Download, Users } from "lucide-react";
import { Button, buttonVariants } from "@/components/ui/button";
import { useNgoSession } from "@/components/ngo/use-ngo-session";
import {
  EmptyState,
  ErrorBanner,
  PageHeader,
  Panel,
  StatCard,
  StatusBadge,
  SuccessBanner,
  formatDate,
} from "@/components/ngo/ui";
import { downloadNgoImportErrors, getNgoImport, saveBlob } from "@/services/ngo-api";
import type { NgoImportDetail } from "@/types/ngo";

function ImportResult() {
  const { importId } = useParams<{ importId: string }>();
  const justFinished = useSearchParams().get("done") === "1";
  const { token, handleError } = useNgoSession();
  const [detail, setDetail] = useState<NgoImportDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [downloading, setDownloading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getNgoImport(token, importId)
      .then((d) => !cancelled && setDetail(d))
      .catch((err) => !cancelled && setError(handleError(err)));
    return () => {
      cancelled = true;
    };
  }, [token, importId, handleError]);

  const downloadErrors = async () => {
    setDownloading(true);
    try {
      const { blob, filename } = await downloadNgoImportErrors(token, importId);
      saveBlob(blob, filename);
    } catch (err) {
      setError(handleError(err));
    } finally {
      setDownloading(false);
    }
  };

  const rejected = detail ? detail.rows.filter((r) => !["valid", "inserted"].includes(r.status)) : [];
  const confirmed = detail && detail.status !== "previewed";

  return (
    <div className="space-y-6">
      <Link href="/ngo/patients/import" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
        <ArrowLeft className="size-4" /> Import CSV
      </Link>
      <ErrorBanner message={error} />
      {!detail && !error && <EmptyState>Loading import…</EmptyState>}

      {detail && (
        <>
          {justFinished && (
            <SuccessBanner message={`Import complete: ${detail.inserted_count} registered, ${detail.skipped_count} skipped, ${detail.failed_count} failed.`} />
          )}
          <PageHeader
            title={detail.file_name || "CSV import"}
            description={<>Uploaded {formatDate(detail.created_at, true)}{detail.created_by ? ` by ${detail.created_by}` : ""} · <StatusBadge status={detail.status} /></>}
            actions={
              <>
                {rejected.length > 0 && (
                  <Button variant="outline" disabled={downloading} onClick={downloadErrors}>
                    <Download className="size-4" />
                    {downloading ? "Preparing…" : "Download error CSV"}
                  </Button>
                )}
                {confirmed && detail.inserted_count > 0 && (
                  <Link href={`/ngo/patients?import_id=${detail.id}`} className={buttonVariants()}>
                    <Users className="size-4" /> View imported patients
                  </Link>
                )}
              </>
            }
          />

          {!confirmed && (
            <p className="rounded-lg border border-warning/40 bg-warning/5 px-4 py-3 text-sm">
              This preview was never confirmed, so no patients were registered from it.{" "}
              <Link href="/ngo/patients/import" className="underline">Upload a file</Link> to start a new import.
            </p>
          )}

          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <StatCard label="Rows in file" value={detail.total_rows} />
            <StatCard label="Registered" value={detail.inserted_count} />
            <StatCard label="Skipped" value={confirmed ? detail.skipped_count : detail.duplicate_rows + detail.review_rows} hint="Duplicates and unapproved matches" />
            <StatCard label="Failed" value={confirmed ? detail.failed_count : detail.invalid_rows} hint="Invalid or could not be saved" />
          </div>

          <Panel title={`Rejected and skipped rows (${rejected.length})`}>
            {rejected.length === 0 ? (
              <p className="text-sm text-muted-foreground">Every row was registered.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border text-left text-xs uppercase tracking-wider text-muted-foreground">
                      <th className="py-2 pr-4 font-semibold">Row</th>
                      <th className="py-2 pr-4 font-semibold">Status</th>
                      <th className="py-2 pr-4 font-semibold">Name</th>
                      <th className="py-2 font-semibold">Reason</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rejected.map((r) => (
                      <tr key={r.row_number} className="border-b border-border/50 align-top last:border-0">
                        <td className="py-2 pr-4 tabular-nums text-muted-foreground">{r.row_number}</td>
                        <td className="py-2 pr-4"><StatusBadge status={r.status} /></td>
                        <td className="py-2 pr-4">{r.raw_data.name || "—"}</td>
                        <td className="py-2 text-xs text-muted-foreground">
                          {r.errors.map((e) => (e.field ? `${e.field}: ${e.message}` : e.message)).join("; ") || "Not approved during review"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Panel>
        </>
      )}
    </div>
  );
}

export default function NgoImportDetailPage() {
  return (
    <Suspense fallback={<EmptyState>Loading import…</EmptyState>}>
      <ImportResult />
    </Suspense>
  );
}
