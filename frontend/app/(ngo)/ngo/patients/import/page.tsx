"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Download, FileUp, Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useNgoSession } from "@/components/ngo/use-ngo-session";
import { EmptyState, ErrorBanner, PageHeader, Panel, StatCard, StatusBadge, inputClass } from "@/components/ngo/ui";
import { checkCsvFile } from "@/lib/ngo-validation";
import { listDoctors, type DoctorListItem } from "@/services/api";
import { NgoApiError, confirmNgoImport, ngoImportTemplateUrl, previewNgoImport } from "@/services/ngo-api";
import type { ImportPreview, ImportRowStatus, PatientField } from "@/types/ngo";

const FIELD_LABELS: Record<PatientField, string> = {
  name: "Full name *",
  phone: "Phone number *",
  dob: "Date of birth",
  mrn: "MRN / health ID",
  insurance: "Insurance / scheme",
  notes: "Notes",
  doctor_id: "Doctor ID (overrides default)",
};
const FIELDS = Object.keys(FIELD_LABELS) as PatientField[];
const ROWS_PER_PAGE = 50;

type Mapping = Partial<Record<PatientField, string>>;
type RowFilter = "all" | Extract<ImportRowStatus, "valid" | "invalid" | "duplicate" | "review">;

export default function NgoImportPage() {
  const router = useRouter();
  const { token, handleError } = useNgoSession();
  const fileInput = useRef<HTMLInputElement>(null);

  const [doctors, setDoctors] = useState<DoctorListItem[]>([]);
  const [defaultDoctorId, setDefaultDoctorId] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [headers, setHeaders] = useState<string[] | null>(null);
  const [mapping, setMapping] = useState<Mapping>({});
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [approved, setApproved] = useState<Set<number>>(new Set());
  const [filter, setFilter] = useState<RowFilter>("all");
  const [visibleRows, setVisibleRows] = useState(ROWS_PER_PAGE);
  const [busy, setBusy] = useState<"preview" | "confirm" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirmChecked, setConfirmChecked] = useState(false);

  useEffect(() => {
    listDoctors().then(setDoctors).catch(() => setError("Could not load doctors. Refresh to try again."));
  }, []);

  const reset = () => {
    setFile(null);
    setHeaders(null);
    setMapping({});
    setPreview(null);
    setApproved(new Set());
    setConfirmChecked(false);
    setError(null);
    if (fileInput.current) fileInput.current.value = "";
  };

  const runPreview = async (selected: File, mappingOverride?: Mapping) => {
    const fileProblem = checkCsvFile(selected);
    if (fileProblem) {
      setError(fileProblem);
      return;
    }
    setBusy("preview");
    setError(null);
    setPreview(null);
    setApproved(new Set());
    setConfirmChecked(false);
    try {
      const result = await previewNgoImport(token, selected, defaultDoctorId, mappingOverride);
      setPreview(result);
      setHeaders(result.headers);
      setMapping(result.mapping);
      setFilter("all");
      setVisibleRows(ROWS_PER_PAGE);
    } catch (err) {
      const message = handleError(err);
      if (err instanceof NgoApiError && err.detail.code === "missing_required_columns") {
        setHeaders(err.detail.headers || []);
        setMapping(err.detail.mapping || {});
      }
      setError(message);
    } finally {
      setBusy(null);
    }
  };

  const confirm = async () => {
    if (!preview || busy) return;
    setBusy("confirm");
    setError(null);
    try {
      const result = await confirmNgoImport(token, preview.import_id, [...approved]);
      router.push(`/ngo/imports/${result.id}?done=1`);
    } catch (err) {
      setError(handleError(err));
      setBusy(null);
    }
  };

  const rows = useMemo(
    () => (preview ? preview.rows.filter((r) => filter === "all" || r.status === filter) : []),
    [preview, filter],
  );
  const toImport = preview ? preview.valid_rows + approved.size : 0;
  const mappingValid = !!mapping.name && !!mapping.phone;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Import patients from CSV"
        description="Nothing is saved until you review the preview and confirm. No calls or messages are sent automatically."
        actions={
          <a href={ngoImportTemplateUrl()} className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-border px-2.5 text-sm hover:bg-muted">
            <Download className="size-4" /> Download template
          </a>
        }
      />

      <Panel title="1. Upload">
        <div className="grid gap-4 md:grid-cols-[1fr_1fr_auto] md:items-end">
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-muted-foreground">CSV file (UTF-8, max 2 MB)</span>
            <input
              ref={fileInput}
              type="file"
              accept=".csv,text/csv"
              onChange={(e) => {
                setPreview(null);
                setHeaders(null);
                setError(null);
                setFile(e.target.files?.[0] || null);
              }}
              className={inputClass}
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-muted-foreground">Default assigned doctor</span>
            <select value={defaultDoctorId} onChange={(e) => setDefaultDoctorId(e.target.value)} className={inputClass}>
              <option value="">Select a doctor…</option>
              {doctors.map((d) => (
                <option key={d.id} value={d.id}>{d.name} — {d.specialty}</option>
              ))}
            </select>
          </label>
          <Button disabled={!file || busy !== null} onClick={() => file && runPreview(file)}>
            <Upload className="size-4" />
            {busy === "preview" ? "Validating…" : "Validate file"}
          </Button>
        </div>
        <p className="mt-3 text-xs text-muted-foreground">
          Required columns: name, phone. Optional: dob (YYYY-MM-DD or DD/MM/YYYY), mrn, insurance, notes, doctor_id.
          Rows without a doctor_id use the default doctor.
        </p>
      </Panel>

      <ErrorBanner message={error} />

      {headers && file && (
        <Panel title="2. Map columns">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {FIELDS.map((field) => (
              <label key={field} className="block">
                <span className="mb-1 block text-xs font-medium text-muted-foreground">{FIELD_LABELS[field]}</span>
                <select
                  value={mapping[field] || ""}
                  onChange={(e) => setMapping((m) => ({ ...m, [field]: e.target.value || undefined }))}
                  className={inputClass}
                >
                  <option value="">— Not in file —</option>
                  {headers.map((h) => (
                    <option key={h} value={h}>{h}</option>
                  ))}
                </select>
              </label>
            ))}
          </div>
          {preview && preview.ignored_columns.length > 0 && (
            <p className="mt-3 text-xs text-muted-foreground">Ignored columns: {preview.ignored_columns.join(", ")}</p>
          )}
          <Button className="mt-4" variant="outline" disabled={!mappingValid || busy !== null} onClick={() => runPreview(file, mapping)}>
            Re-validate with this mapping
          </Button>
        </Panel>
      )}

      {busy === "preview" && <EmptyState>Validating rows…</EmptyState>}

      {preview && (
        <Panel title="3. Review">
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
            <StatCard label="Rows detected" value={preview.total_rows} hint={preview.empty_rows_skipped ? `${preview.empty_rows_skipped} empty rows ignored` : undefined} />
            <StatCard label="Valid" value={preview.valid_rows} />
            <StatCard label="Invalid" value={preview.invalid_rows} />
            <StatCard label="Duplicates (skipped)" value={preview.duplicate_rows} />
            <StatCard label="Need review" value={preview.review_rows} hint="Tick to import as a new patient" />
          </div>

          <div className="mt-5 flex flex-wrap gap-2" role="tablist" aria-label="Filter rows">
            {(["all", "valid", "invalid", "duplicate", "review"] as RowFilter[]).map((f) => (
              <Button key={f} size="sm" role="tab" aria-selected={filter === f} variant={filter === f ? "default" : "outline"}
                onClick={() => { setFilter(f); setVisibleRows(ROWS_PER_PAGE); }}>
                {f === "all" ? "All" : f === "review" ? "Needs review" : f[0].toUpperCase() + f.slice(1)}
              </Button>
            ))}
          </div>

          <div className="mt-4 overflow-x-auto rounded-lg border border-border">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border bg-muted/30 text-left text-xs uppercase tracking-wider text-muted-foreground">
                  <th className="px-3 py-2 font-semibold">Row</th>
                  <th className="px-3 py-2 font-semibold">Status</th>
                  <th className="px-3 py-2 font-semibold">Name</th>
                  <th className="px-3 py-2 font-semibold">Phone</th>
                  <th className="px-3 py-2 font-semibold">DOB</th>
                  <th className="px-3 py-2 font-semibold">Issues</th>
                  <th className="px-3 py-2 font-semibold">Import?</th>
                </tr>
              </thead>
              <tbody>
                {rows.slice(0, visibleRows).map((r) => (
                  <tr key={r.row_number} className="border-b border-border/50 align-top last:border-0">
                    <td className="px-3 py-2 tabular-nums text-muted-foreground">{r.row_number}</td>
                    <td className="px-3 py-2"><StatusBadge status={r.status} /></td>
                    <td className="px-3 py-2">{r.normalized?.name || r.raw_data.name || "—"}</td>
                    <td className="px-3 py-2 text-muted-foreground">{r.normalized?.phone || r.raw_data.phone || "—"}</td>
                    <td className="px-3 py-2 text-muted-foreground">{r.normalized?.dob || r.raw_data.dob || "—"}</td>
                    <td className="px-3 py-2 text-xs">
                      {r.errors.length === 0 ? (
                        <span className="text-muted-foreground">—</span>
                      ) : (
                        <ul className="space-y-0.5">
                          {r.errors.map((e, i) => (
                            <li key={i} className={r.status === "invalid" ? "text-destructive" : "text-muted-foreground"}>
                              {e.field ? <strong>{e.field}: </strong> : null}{e.message}
                            </li>
                          ))}
                        </ul>
                      )}
                    </td>
                    <td className="px-3 py-2">
                      {r.status === "valid" ? (
                        <span className="text-xs text-success">Yes</span>
                      ) : r.status === "review" ? (
                        <label className="inline-flex items-center gap-1.5 text-xs">
                          <input
                            type="checkbox"
                            checked={approved.has(r.row_number)}
                            onChange={(e) =>
                              setApproved((prev) => {
                                const next = new Set(prev);
                                if (e.target.checked) next.add(r.row_number);
                                else next.delete(r.row_number);
                                return next;
                              })
                            }
                          />
                          Different person
                        </label>
                      ) : (
                        <span className="text-xs text-muted-foreground">No</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {rows.length === 0 && <p className="p-4 text-center text-sm text-muted-foreground">No rows in this view.</p>}
          </div>
          {rows.length > visibleRows && (
            <Button className="mt-3" variant="ghost" size="sm" onClick={() => setVisibleRows((v) => v + ROWS_PER_PAGE)}>
              Show more ({rows.length - visibleRows} remaining)
            </Button>
          )}

          <div className="mt-6 space-y-3 rounded-lg border border-border bg-muted/20 p-4">
            <p className="text-sm">
              <strong>{toImport}</strong> patient{toImport === 1 ? "" : "s"} will be registered.{" "}
              {preview.total_rows - toImport} row{preview.total_rows - toImport === 1 ? "" : "s"} will be skipped or rejected
              and listed in the downloadable error file.
            </p>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={confirmChecked} onChange={(e) => setConfirmChecked(e.target.checked)} />
              I have reviewed the preview and want to register these patients.
            </label>
            <div className="flex gap-2">
              <Button disabled={!confirmChecked || toImport === 0 || busy !== null} onClick={confirm}>
                <FileUp className="size-4" />
                {busy === "confirm" ? "Importing…" : `Confirm import of ${toImport}`}
              </Button>
              <Button variant="outline" disabled={busy !== null} onClick={reset}>Start over</Button>
            </div>
          </div>
        </Panel>
      )}
    </div>
  );
}
