"use client";

import { AlertTriangle, CheckCircle2 } from "lucide-react";
import { cn } from "@/lib/utils";
import type { ImportRowStatus, ImportStatus, RegistrationSource } from "@/types/ngo";

export const inputClass =
  "w-full rounded-lg border border-border bg-background px-3 py-2 text-sm placeholder-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary aria-invalid:border-destructive";

export function formatDate(value: string | null | undefined, withTime = false) {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return withTime ? d.toLocaleString() : d.toLocaleDateString();
}

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description?: React.ReactNode;
  actions?: React.ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h1 className="text-2xl font-semibold">{title}</h1>
        {description && <p className="text-sm text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function StatCard({ label, value, hint }: { label: string; value: number | string; hint?: string }) {
  return (
    <div className="rounded-xl border border-border bg-card p-5">
      <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">{label}</p>
      <p className="mt-2 text-3xl font-semibold tabular-nums">{value}</p>
      {hint && <p className="mt-1 text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
}

export function Panel({ title, children, action }: { title: string; children: React.ReactNode; action?: React.ReactNode }) {
  return (
    <section className="rounded-xl border border-border bg-card">
      <div className="flex items-center justify-between border-b border-border px-5 py-3">
        <h2 className="text-sm font-semibold">{title}</h2>
        {action}
      </div>
      <div className="p-5">{children}</div>
    </section>
  );
}

export function ErrorBanner({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <div role="alert" className="flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive">
      <AlertTriangle className="mt-0.5 size-4 shrink-0" />
      <span>{message}</span>
    </div>
  );
}

export function SuccessBanner({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <div role="status" className="flex items-start gap-2 rounded-lg border border-success/30 bg-success/5 px-4 py-3 text-sm text-success">
      <CheckCircle2 className="mt-0.5 size-4 shrink-0" />
      <span>{message}</span>
    </div>
  );
}

export function EmptyState({ children }: { children: React.ReactNode }) {
  return <div className="rounded-xl border border-border bg-card p-12 text-center text-sm text-muted-foreground">{children}</div>;
}

export function SourceBadge({ source }: { source: RegistrationSource }) {
  return (
    <span
      className={cn(
        "inline-flex rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide",
        source === "csv" ? "bg-primary/10 text-primary" : "bg-muted text-muted-foreground",
      )}
    >
      {source === "csv" ? "CSV" : "Manual"}
    </span>
  );
}

const ROW_STATUS_STYLES: Record<ImportRowStatus | ImportStatus, string> = {
  valid: "bg-success/10 text-success",
  inserted: "bg-success/10 text-success",
  completed: "bg-success/10 text-success",
  invalid: "bg-destructive/10 text-destructive",
  failed: "bg-destructive/10 text-destructive",
  duplicate: "bg-muted text-muted-foreground",
  skipped: "bg-muted text-muted-foreground",
  review: "bg-warning/10 text-warning",
  previewed: "bg-warning/10 text-warning",
  processing: "bg-primary/10 text-primary",
};

const STATUS_LABELS: Partial<Record<ImportRowStatus | ImportStatus, string>> = {
  review: "Needs review",
  previewed: "Not confirmed",
};

export function StatusBadge({ status }: { status: ImportRowStatus | ImportStatus }) {
  return (
    <span className={cn("inline-flex rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide", ROW_STATUS_STYLES[status])}>
      {STATUS_LABELS[status] || status}
    </span>
  );
}

export function FollowUpBadge({ pending }: { pending: boolean }) {
  return pending ? (
    <span className="inline-flex rounded-full bg-warning/10 px-2 py-0.5 text-[10px] font-semibold text-warning">Follow-up pending</span>
  ) : (
    <span className="text-xs text-muted-foreground">None</span>
  );
}
