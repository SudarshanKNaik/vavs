"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useLocalAuth } from "@/lib/local-auth";
import {
  getFollowUpCronConfig,
  listFollowUpCronJobLogs,
  listFollowUpCronJobs,
  runFollowUpCronJobNow,
  type FollowUpCronConfig,
  type FollowUpJob,
  type FollowUpJobLog,
} from "@/services/api";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import {
  AlertTriangle,
  ChevronDown,
  ChevronRight,
  Clock,
  Loader2,
  Play,
  RefreshCw,
} from "lucide-react";

const statusColor: Record<string, string> = {
  queued: "bg-primary/10 text-primary",
  running: "bg-warning/10 text-warning",
  completed: "bg-success/10 text-success",
  failed: "bg-destructive/10 text-destructive",
  skipped: "bg-muted text-muted-foreground",
  cancelled: "bg-muted text-muted-foreground",
};

export default function FollowUpsPage() {
  const { user } = useLocalAuth();
  const doctorId = user?.doctor_id || user?.sub;

  const [config, setConfig] = useState<FollowUpCronConfig | null>(null);
  const [jobs, setJobs] = useState<FollowUpJob[]>([]);
  const [logsByJob, setLogsByJob] = useState<Record<string, FollowUpJobLog[]>>({});
  const [expandedJobId, setExpandedJobId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [runningNowById, setRunningNowById] = useState<Record<string, boolean>>({});
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [accessMessage, setAccessMessage] = useState<string | null>(null);

  const loadJobs = useCallback(async () => {
    if (!doctorId) return;
    const [cfg, rows] = await Promise.all([
      getFollowUpCronConfig(),
      listFollowUpCronJobs({ doctor_id: doctorId, limit: 200 }),
    ]);
    setConfig(cfg);
    setJobs(Array.isArray(rows) ? rows : []);
  }, [doctorId]);

  useEffect(() => {
    let mounted = true;
    (async () => {
      if (!doctorId) {
        setAccessMessage("Doctor profile not found in session. Please sign in as a doctor.");
        setLoading(false);
        return;
      }

      setAccessMessage(null);
      setLoading(true);
      try {
        await loadJobs();
      } finally {
        if (mounted) setLoading(false);
      }
    })();

    return () => {
      mounted = false;
    };
  }, [doctorId, loadJobs]);

  const handleRefresh = useCallback(async () => {
    setRefreshing(true);
    try {
      await loadJobs();
    } finally {
      setRefreshing(false);
    }
  }, [loadJobs]);

  const visibleJobs = useMemo(() => {
    if (statusFilter === "all") return jobs;
    return jobs.filter((j) => j.status === statusFilter);
  }, [jobs, statusFilter]);

  const handleToggleExpand = useCallback(async (jobId: string) => {
    setExpandedJobId((prev) => (prev === jobId ? null : jobId));

    if (logsByJob[jobId]) return;

    try {
      const logs = await listFollowUpCronJobLogs(jobId, 200);
      setLogsByJob((prev) => ({ ...prev, [jobId]: logs }));
    } catch {
      setLogsByJob((prev) => ({ ...prev, [jobId]: [] }));
    }
  }, [logsByJob]);

  const handleRunNow = useCallback(async (jobId: string) => {
    setRunningNowById((prev) => ({ ...prev, [jobId]: true }));
    try {
      await runFollowUpCronJobNow(jobId);
      await loadJobs();
      const logs = await listFollowUpCronJobLogs(jobId, 200);
      setLogsByJob((prev) => ({ ...prev, [jobId]: logs }));
      setExpandedJobId(jobId);
    } finally {
      setRunningNowById((prev) => ({ ...prev, [jobId]: false }));
    }
  }, [loadJobs]);

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">Follow-up Cron Monitor</h1>
          <p className="text-sm text-muted-foreground">
            Delayed follow-up workflow queue and execution logs for missed or unbooked calls.
          </p>
        </div>
        <Button variant="outline" onClick={handleRefresh} disabled={refreshing || loading}>
          <RefreshCw className={cn("size-4", refreshing && "animate-spin")} />
          Refresh
        </Button>
      </div>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="Scheduler"
          value={config?.running ? "Running" : "Stopped"}
          tone={config?.running ? "success" : "danger"}
        />
        <StatCard label="Enabled" value={config?.enabled ? "Yes" : "No"} tone={config?.enabled ? "success" : "muted"} />
        <StatCard
          label="Follow-up Delay"
          value={config ? `${config.delay_minutes} min` : "-"}
          tone="muted"
        />
        <StatCard
          label="Poll Interval"
          value={config ? `${config.poll_interval_seconds} sec` : "-"}
          tone="muted"
        />
      </div>

      <div className="rounded-xl border border-border bg-card p-4">
        <div className="flex flex-wrap items-center gap-2">
          {["all", "queued", "running", "completed", "failed", "skipped"].map((s) => (
            <button
              key={s}
              onClick={() => setStatusFilter(s)}
              className={cn(
                "rounded-full px-3 py-1 text-xs font-medium capitalize transition-colors",
                statusFilter === s ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground hover:bg-muted/70",
              )}
            >
              {s}
            </button>
          ))}
        </div>
      </div>

      {accessMessage && (
        <div className="rounded-xl border border-warning/50 bg-warning/10 p-4 text-sm text-warning">
          {accessMessage}
        </div>
      )}

      {loading ? (
        <div className="rounded-xl border border-border bg-card p-12 text-center text-sm text-muted-foreground">
          Loading follow-up jobs...
        </div>
      ) : visibleJobs.length === 0 ? (
        <div className="rounded-xl border border-border bg-card p-12 text-center">
          <Clock className="mx-auto mb-3 size-10 text-muted-foreground/40" />
          <p className="text-sm text-muted-foreground">No follow-up cron jobs found for this doctor.</p>
        </div>
      ) : (
        <div className="space-y-2">
          {visibleJobs.map((job) => {
            const isExpanded = expandedJobId === job.id;
            const logs = logsByJob[job.id] || [];
            const runDisabled = runningNowById[job.id] || job.status === "running";
            return (
              <div key={job.id} className="overflow-hidden rounded-xl border border-border bg-card">
                <div className="flex items-center gap-3 px-4 py-3">
                  <button
                    onClick={() => handleToggleExpand(job.id)}
                    className="shrink-0 text-muted-foreground hover:text-foreground"
                    aria-label="Toggle logs"
                  >
                    {isExpanded ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
                  </button>

                  <span
                    className={cn(
                      "inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-semibold capitalize",
                      statusColor[job.status] || "bg-muted text-muted-foreground",
                    )}
                  >
                    {job.status}
                  </span>

                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium">{job.reason || "Follow-up required"}</p>
                    <p className="text-xs text-muted-foreground">
                      Due: {new Date(job.scheduled_for).toLocaleString()} • Attempts: {job.attempt_count}/{job.max_attempts}
                    </p>
                  </div>

                  <Button
                    size="sm"
                    variant="outline"
                    disabled={runDisabled}
                    onClick={() => handleRunNow(job.id)}
                  >
                    {runningNowById[job.id] ? (
                      <Loader2 className="size-3.5 animate-spin" />
                    ) : (
                      <Play className="size-3.5" />
                    )}
                    Run Now
                  </Button>
                </div>

                {job.last_error && (
                  <div className="border-t border-border bg-destructive/5 px-4 py-2 text-xs text-destructive">
                    <div className="inline-flex items-center gap-1">
                      <AlertTriangle className="size-3.5" />
                      {job.last_error}
                    </div>
                  </div>
                )}

                {isExpanded && (
                  <div className="border-t border-border bg-muted/20 px-4 py-3">
                    <p className="mb-2 text-xs font-semibold text-muted-foreground">Job Logs</p>
                    {logs.length === 0 ? (
                      <p className="text-xs text-muted-foreground">No log entries yet.</p>
                    ) : (
                      <div className="space-y-2">
                        {logs.map((entry) => (
                          <div key={entry.id} className="rounded-lg border border-border bg-background p-2.5">
                            <div className="flex items-center justify-between gap-2">
                              <span className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                                {entry.level}
                              </span>
                              <span className="text-[11px] text-muted-foreground">
                                {new Date(entry.created_at).toLocaleString()}
                              </span>
                            </div>
                            <p className="mt-1 text-xs">{entry.message}</p>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function StatCard({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone: "success" | "danger" | "muted";
}) {
  const toneClass =
    tone === "success"
      ? "text-success"
      : tone === "danger"
      ? "text-destructive"
      : "text-foreground";

  return (
    <div className="rounded-xl border border-border bg-card p-4">
      <p className="text-xs uppercase tracking-wider text-muted-foreground">{label}</p>
      <p className={cn("mt-2 text-xl font-semibold", toneClass)}>{value}</p>
    </div>
  );
}
