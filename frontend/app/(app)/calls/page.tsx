"use client";

import { useState, useEffect, useCallback } from "react";
import { useLocalAuth } from "@/lib/local-auth";
import { listCallLogs, checkCallStatus } from "@/services/api";

import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import {
  ChevronDown,
  ChevronRight,
  Search,
  X,
  FileText,
  CheckCircle2,
  XCircle,
  Clock,
  Loader2,
  Mic,
} from "lucide-react";

const statusConfig: Record<
  string,
  {
    label: string;
    icon: React.ComponentType<{ className?: string }>;
    color: string;
  }
> = {
  completed: {
    label: "Completed",
    icon: CheckCircle2,
    color: "bg-success/10 text-success",
  },
  failed: {
    label: "Failed",
    icon: XCircle,
    color: "bg-destructive/10 text-destructive",
  },
  running: {
    label: "Running",
    icon: Loader2,
    color: "bg-primary/10 text-primary",
  },
  initiated: {
    label: "Initiated",
    icon: Clock,
    color: "bg-muted text-muted-foreground",
  },
};

export default function CallsPage() {
  const { user } = useLocalAuth();
  const doctorId = user?.doctor_id || user?.sub;

  const [callLogs, setCallLogs] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [filterStatus, setFilterStatus] = useState<string>("all");
  const [checkingById, setCheckingById] = useState<Record<string, boolean>>({});
  const [checkMessageById, setCheckMessageById] = useState<Record<string, string>>({});

  const fetchCallLogs = useCallback(async () => {
    if (!doctorId) return;
    setLoading(true);
    try {
      const data = await listCallLogs(undefined, doctorId);
      setCallLogs(Array.isArray(data) ? data : []);
    } catch {
      setCallLogs([]);
    } finally {
      setLoading(false);
    }
  }, [doctorId]);

  useEffect(() => {
    fetchCallLogs();
  }, [fetchCallLogs]);

  const filtered = callLogs.filter((cl) => {
    if (filterStatus !== "all" && cl.status !== filterStatus) return false;
    if (search) {
      const q = search.toLowerCase();
      return (
        cl.id?.toLowerCase().includes(q) ||
        cl.workflow_id?.toLowerCase().includes(q) ||
        cl.patient_id?.toLowerCase().includes(q) ||
        cl.outcome?.toLowerCase().includes(q) ||
        cl.status?.toLowerCase().includes(q)
      );
    }
    return true;
  });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Call Log</h1>
        <p className="text-sm text-muted-foreground">
          All workflow executions with outcomes and details.
          {!loading &&
            ` ${callLogs.length} total execution${callLogs.length !== 1 ? "s" : ""}.`}
        </p>
      </div>

      {/* Filters */}
      <div className="flex items-center gap-3">
        <div className="relative flex-1 max-w-xs">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-muted-foreground" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search by ID, outcome…"
            className="w-full pl-9 pr-3 py-2 rounded-lg border border-border bg-background text-sm placeholder-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary"
          />
          {search && (
            <button
              onClick={() => setSearch("")}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
            >
              <X className="size-3.5" />
            </button>
          )}
        </div>
        <div className="flex items-center rounded-lg border border-border overflow-hidden">
          {["all", "completed", "running", "failed", "initiated"].map((s) => (
            <button
              key={s}
              onClick={() => setFilterStatus(s)}
              className={cn(
                "px-3 py-1.5 text-xs font-medium transition-colors capitalize",
                filterStatus === s
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground hover:bg-muted",
              )}
            >
              {s === "all" ? "All" : s}
            </button>
          ))}
        </div>
        <Button size="sm" variant="outline" onClick={fetchCallLogs}>
          Refresh
        </Button>
      </div>

      {/* Call log list */}
      {loading ? (
        <div className="rounded-xl border border-border bg-card p-12 text-center text-sm text-muted-foreground">
          Loading call logs…
        </div>
      ) : filtered.length === 0 ? (
        <div className="rounded-xl border border-border bg-card p-12 text-center">
          <FileText className="size-10 text-muted-foreground/40 mx-auto mb-3" />
          <p className="text-sm text-muted-foreground">
            {callLogs.length === 0
              ? "No call logs yet. Execute a workflow to see logs here."
              : "No logs match your filters."}
          </p>
        </div>
      ) : (
        <div className="space-y-2">
          {filtered.map((cl) => {
            const isExpanded = expandedId === cl.id;
            const config = statusConfig[cl.status] || statusConfig.initiated;
            const StatusIcon = config.icon;
            const execLog: any[] = Array.isArray(cl.execution_log)
              ? cl.execution_log
              : [];
            const latestCallRefStep = [...execLog]
              .reverse()
              .find((s) => s?.conversation_id || s?.call_sid || s?.callSid);
            const conversationId = latestCallRefStep?.conversation_id || "";
            const callSid =
              latestCallRefStep?.call_sid || latestCallRefStep?.callSid || "";

            return (
              <div
                key={cl.id}
                className="rounded-xl border border-border bg-card overflow-hidden"
              >
                <button
                  onClick={() => setExpandedId(isExpanded ? null : cl.id)}
                  className="w-full flex items-center gap-4 px-5 py-4 text-left hover:bg-muted/30 transition-colors"
                >
                  <div className="shrink-0">
                    {isExpanded ? (
                      <ChevronDown className="size-4 text-muted-foreground" />
                    ) : (
                      <ChevronRight className="size-4 text-muted-foreground" />
                    )}
                  </div>
                  <div className="flex items-center gap-2 min-w-0 flex-1">
                    <span
                      className={cn(
                        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold",
                        config.color,
                      )}
                    >
                      <StatusIcon className="size-3" />
                      {config.label}
                    </span>
                    {cl.outcome && (
                      <span className="text-xs text-muted-foreground capitalize">
                        {cl.outcome}
                      </span>
                    )}
                    {cl.trigger_node && (
                      <span className="text-[10px] bg-muted text-muted-foreground px-2 py-0.5 rounded-full">
                        {cl.trigger_node}
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-4 shrink-0 text-[11px] text-muted-foreground">
                    <span>Workflow: {cl.workflow_id?.slice(0, 8) ?? "—"}…</span>
                    <span>Patient: {cl.patient_id?.slice(0, 8) ?? "—"}…</span>
                    <span>{new Date(cl.created_at).toLocaleString()}</span>
                  </div>
                </button>

                {isExpanded && (
                  <div className="border-t border-border px-5 py-4 bg-muted/10">
                    <div className="grid grid-cols-2 gap-4 mb-4 text-xs">
                      <div>
                        <span className="text-muted-foreground">
                          Call Log ID:
                        </span>
                        <code className="ml-2 rounded bg-muted px-2 py-0.5 font-mono text-xs">
                          {cl.id}
                        </code>
                      </div>
                      <div>
                        <span className="text-muted-foreground">
                          Workflow ID:
                        </span>
                        <code className="ml-2 rounded bg-muted px-2 py-0.5 font-mono text-xs">
                          {cl.workflow_id ?? "—"}
                        </code>
                      </div>
                      <div>
                        <span className="text-muted-foreground">
                          Patient ID:
                        </span>
                        <code className="ml-2 rounded bg-muted px-2 py-0.5 font-mono text-xs">
                          {cl.patient_id ?? "—"}
                        </code>
                      </div>
                      <div>
                        <span className="text-muted-foreground">Keypress:</span>
                        <span className="ml-2">{cl.keypress || "—"}</span>
                      </div>
                      <div>
                        <span className="text-muted-foreground">
                          Conversation:
                        </span>
                        <code className="ml-2 rounded bg-muted px-2 py-0.5 font-mono text-xs">
                          {conversationId ? `${conversationId.slice(0, 16)}…` : "—"}
                        </code>
                      </div>
                      <div>
                        <span className="text-muted-foreground">Call SID:</span>
                        <code className="ml-2 rounded bg-muted px-2 py-0.5 font-mono text-xs">
                          {callSid ? `${callSid.slice(0, 16)}…` : "—"}
                        </code>
                      </div>
                    </div>

                    {execLog.length > 0 ? (
                      <div>
                        <h4 className="text-xs font-semibold mb-2">
                          Execution Steps
                        </h4>
                        <div className="space-y-1.5">
                          {execLog.map((step: any, i: number) => (
                            <div
                              key={i}
                              className="flex items-start gap-2 rounded-lg bg-card border border-border px-3 py-2"
                            >
                              <span
                                className="mt-1 size-2 rounded-full shrink-0"
                                style={{
                                  backgroundColor:
                                    step.status === "ok"
                                      ? "#10b981"
                                      : step.status === "error"
                                        ? "#ef4444"
                                        : "#6b7280",
                                }}
                              />
                              <div className="min-w-0 flex-1">
                                <p className="text-xs font-medium">
                                  {step.label || step.node_type}
                                </p>
                                <p className="text-[11px] text-muted-foreground">
                                  {step.message}
                                </p>
                              </div>
                              <span className="text-[10px] text-muted-foreground capitalize shrink-0">
                                {step.status}
                              </span>
                            </div>
                          ))}
                        </div>
                      </div>
                    ) : (
                      <p className="text-xs text-muted-foreground">
                        No execution steps recorded.
                      </p>
                    )}

                    {/* Transcript view */}
                    {(() => {
                      const transcriptStep = execLog.find(
                        (s) => s.transcript && s.transcript.length > 0,
                      );
                      const transcriptText =
                        transcriptStep?.transcript || cl.transcript;
                      if (!transcriptText) return null;
                      return (
                        <div className="mt-3">
                          <h4 className="text-xs font-semibold mb-1 flex items-center gap-1">
                            <Mic className="size-3" /> Transcript
                          </h4>
                          <details>
                            <summary className="cursor-pointer text-xs text-muted-foreground">
                              View call transcript
                            </summary>
                            <pre className="mt-2 text-[11px] whitespace-pre-wrap bg-background rounded-lg border border-border p-3 max-h-48 overflow-y-auto">
                              {transcriptText}
                            </pre>
                          </details>
                        </div>
                      );
                    })()}

                    {/* Booked appointment info */}
                    {(() => {
                      const apptStep = execLog.find((s) => s.appointment_id);
                      if (!apptStep) return null;
                      return (
                        <div className="mt-3 rounded-lg border border-success/30 bg-success/5 px-3 py-2">
                          <div className="flex items-center gap-2 text-xs text-success font-semibold">
                            <CheckCircle2 className="size-3" />
                            Appointment Booked
                          </div>
                          <p className="text-[11px] text-muted-foreground mt-0.5">
                            ID:{" "}
                            <code className="font-mono">
                              {apptStep.appointment_id?.slice(0, 8)}…
                            </code>
                          </p>
                        </div>
                      );
                    })()}

                    {/* Poll status button for running calls */}
                    {cl.status === "running" && (
                      <div className="mt-3">
                        <button
                          onClick={async () => {
                            setCheckingById((prev) => ({ ...prev, [cl.id]: true }));
                            setCheckMessageById((prev) => ({
                              ...prev,
                              [cl.id]: "Checking latest call status...",
                            }));
                            try {
                              const result = await checkCallStatus(cl.id);
                              const nextMessage =
                                result.message ||
                                (result.status === "completed"
                                  ? "Call processed and synced."
                                  : result.status === "in_progress"
                                    ? "Call is still in progress."
                                    : result.status === "waiting"
                                      ? "Call initialized. Waiting for conversation link."
                                      : "Status updated.");
                              setCheckMessageById((prev) => ({
                                ...prev,
                                [cl.id]: nextMessage,
                              }));
                              await fetchCallLogs();
                            } catch (error) {
                              const msg =
                                error instanceof Error
                                  ? error.message
                                  : "Failed to check status.";
                              setCheckMessageById((prev) => ({
                                ...prev,
                                [cl.id]: msg,
                              }));
                            } finally {
                              setCheckingById((prev) => ({
                                ...prev,
                                [cl.id]: false,
                              }));
                            }
                          }}
                          className="text-xs text-primary hover:underline"
                          disabled={Boolean(checkingById[cl.id])}
                        >
                          {checkingById[cl.id] ? "Checking..." : "↻ Check Status Now"}
                        </button>
                        {checkMessageById[cl.id] && (
                          <p className="mt-1 text-[11px] text-muted-foreground">
                            {checkMessageById[cl.id]}
                          </p>
                        )}
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
