"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  Check,
  Copy,
  Database,
  Droplets,
  Eye,
  Loader2,
  Mail,
  MapPin,
  PhoneCall,
  Radar,
  ShieldCheck,
  Siren,
  Trash2,
} from "lucide-react";
import { useLocalAuth } from "@/lib/local-auth";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import {
  clearOutbreakDemoData,
  emailOutbreakBrief,
  getOutbreakSummary,
  loadOutbreakDemoData,
  type OutbreakLevel,
  type OutbreakSignal,
  type OutbreakSummary,
  type SyndromeKey,
} from "@/services/api";
import { TrendChart } from "@/components/outbreak/TrendChart";
import { LEVELS, SYNDROME_COLORS, SYNDROME_SHORT } from "@/components/outbreak/theme";

type Filter = "all" | Exclude<SyndromeKey, "fever">;

const FILTERS: { value: Filter; label: string }[] = [
  { value: "all", label: "All syndromes" },
  { value: "dengue_like", label: "Dengue-like" },
  { value: "respiratory", label: "Respiratory" },
  { value: "gastro", label: "Diarrhoea & vomiting" },
];

const LEVEL_ICONS: Record<OutbreakLevel, typeof Siren> = { alert: Siren, watch: Eye, normal: Check };

// Suggestions only; any city name works (it's looked up on OpenStreetMap).
const SAMPLE_CITIES = [
  "Hubli–Dharwad", "Bengaluru", "Mumbai", "Delhi", "Pune", "Hyderabad",
  "Chennai", "Kolkata", "Mysuru", "Belagavi",
];

function SampleCityPicker({
  initial,
  busy,
  onLoad,
  compact,
}: {
  initial: string;
  busy: boolean;
  onLoad: (city: string) => void;
  compact?: boolean;
}) {
  const [city, setCity] = useState(initial);
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (city.trim()) onLoad(city.trim());
      }}
      className="flex flex-wrap items-center gap-2"
    >
      <label className="sr-only" htmlFor={compact ? "ow-city-compact" : "ow-city"}>City</label>
      <div className="relative">
        <MapPin className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" aria-hidden />
        <input
          id={compact ? "ow-city-compact" : "ow-city"}
          list="ow-cities"
          value={city}
          onChange={(e) => setCity(e.target.value)}
          placeholder="Any city, e.g. Pune"
          className={cn(
            "rounded-lg border border-border bg-background pl-8 pr-3 text-sm focus:outline-none focus:ring-2 focus:ring-primary/20",
            compact ? "h-7 w-44" : "h-9 w-56",
          )}
        />
        <datalist id="ow-cities">
          {SAMPLE_CITIES.map((c) => (
            <option key={c} value={c} />
          ))}
        </datalist>
      </div>
      <Button type="submit" size={compact ? "sm" : "default"} variant={compact ? "outline" : "default"} disabled={busy || !city.trim()}>
        {busy ? <Loader2 className="size-3.5 animate-spin" /> : <Database className="size-3.5" />}
        {compact ? "Show this city" : "Load sample data"}
      </Button>
    </form>
  );
}

function LevelPill({ level }: { level: OutbreakLevel }) {
  const meta = LEVELS[level];
  const Icon = LEVEL_ICONS[level];
  return (
    <span className={cn("inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-semibold", meta.tint, meta.text)}>
      <Icon className="size-3" aria-hidden />
      {meta.label}
    </span>
  );
}

function Sparkline({ daily, level }: { daily: number[]; level: OutbreakLevel }) {
  const max = Math.max(1, ...daily);
  const half = daily.length / 2;
  return (
    <div className="flex h-8 items-end gap-[2px]" aria-hidden>
      {daily.map((v, i) => (
        <span
          key={i}
          className="w-1.5 rounded-t-[2px]"
          style={{
            height: `${Math.max(2, (v / max) * 32)}px`,
            background: i >= half ? LEVELS[level === "normal" ? "normal" : level].color : "#D4C9BB",
            opacity: v === 0 ? 0.5 : 1,
          }}
        />
      ))}
    </div>
  );
}

function Kpi({
  label,
  value,
  hint,
  icon: Icon,
  tone,
}: {
  label: string;
  value: React.ReactNode;
  hint?: React.ReactNode;
  icon: typeof Siren;
  tone?: "alert";
}) {
  return (
    <div className="rounded-xl border border-border bg-card p-5">
      <div className="flex items-center justify-between">
        <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">{label}</p>
        <Icon className={cn("size-4", tone === "alert" ? "text-[#d03b3b]" : "text-muted-foreground")} aria-hidden />
      </div>
      <p className="mt-2 text-3xl font-semibold">{value}</p>
      {hint && <p className="mt-1 text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
}

function SignalCard({
  signal,
}: {
  signal: OutbreakSignal;
}) {
  const newCluster = signal.expected < 1;
  return (
    <div className="rounded-xl border border-border bg-background p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <LevelPill level={signal.level} />
            <span className="flex items-center gap-1 text-xs text-muted-foreground">
              <span className="size-2 rounded-full" style={{ background: SYNDROME_COLORS[signal.syndrome] }} />
              {signal.syndrome_label}
            </span>
          </div>
          <p className="mt-2 flex items-center gap-1 truncate font-semibold">
            <MapPin className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
            {signal.locality}
          </p>
        </div>
        <Sparkline daily={signal.daily} level={signal.level} />
      </div>
      <div className="mt-3 flex items-baseline gap-2">
        <span className="text-2xl font-semibold tabular-nums">{signal.observed}</span>
        <span className="text-sm text-muted-foreground">
          cases this week vs {newCluster ? "almost none" : `${signal.expected} usual`}
        </span>
      </div>
      <p className="mt-1 text-xs text-muted-foreground">
        {signal.previous_week} the week before · a rise this large happens by chance {signal.chance}
      </p>
    </div>
  );
}

export default function OutbreakWatchPage() {
  const { user } = useLocalAuth();
  const doctorId = user?.doctor_id || user?.sub;

  const [summary, setSummary] = useState<OutbreakSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [busy, setBusy] = useState<"demo" | "clear" | "email" | null>(null);
  const [copied, setCopied] = useState(false);
  const [emailOpen, setEmailOpen] = useState(false);
  const [emailTo, setEmailTo] = useState("");
  const [notice, setNotice] = useState<{ type: "success" | "error"; text: string } | null>(null);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);

  const refresh = useCallback(async () => {
    if (!doctorId) return;
    try {
      setSummary(await getOutbreakSummary(doctorId));
      setUpdatedAt(new Date());
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load Outbreak Watch.");
    } finally {
      setLoading(false);
    }
  }, [doctorId]);

  useEffect(() => {
    refresh();
    const timer = window.setInterval(refresh, 60_000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  const signals = useMemo(
    () => (summary?.signals || []).filter((s) => filter === "all" || s.syndrome === filter),
    [summary, filter],
  );
  const flagged = signals.filter((s) => s.level !== "normal");
  const quiet = signals.filter((s) => s.level === "normal");
  const alerts = (summary?.signals || []).filter((s) => s.level === "alert");
  const watches = (summary?.signals || []).filter((s) => s.level === "watch");

  const handleDemo = async (action: "demo" | "clear", city?: string) => {
    if (!doctorId) return;
    setBusy(action);
    setNotice(null);
    try {
      if (action === "demo") await loadOutbreakDemoData(doctorId, city);
      else await clearOutbreakDemoData(doctorId);
      await refresh();
    } catch (err) {
      setNotice({ type: "error", text: err instanceof Error ? err.message : "Something went wrong." });
    } finally {
      setBusy(null);
    }
  };

  const handleCopy = async () => {
    if (!summary) return;
    try {
      await navigator.clipboard.writeText(summary.brief);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setNotice({ type: "error", text: "Couldn't copy. Your browser blocked clipboard access." });
    }
  };

  const handleEmail = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!doctorId || !emailTo.trim()) return;
    setBusy("email");
    setNotice(null);
    try {
      const res = await emailOutbreakBrief(doctorId, emailTo.trim());
      setNotice({ type: "success", text: `Situation report sent to ${res.to_email}.` });
      setEmailOpen(false);
    } catch (err) {
      setNotice({ type: "error", text: err instanceof Error ? err.message : "Couldn't send the email." });
    } finally {
      setBusy(null);
    }
  };

  if (loading) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center text-sm text-muted-foreground">
        <Loader2 className="mr-2 size-4 animate-spin" /> Loading Outbreak Watch…
      </div>
    );
  }

  const hasData = !!summary && summary.trend && Object.values(summary.trend).some((series) => series.some((v) => v > 0));
  const p = summary?.platelets;
  const plateletHref = `/blood-requests?${new URLSearchParams({
    component: "platelets",
    urgency: "planned",
    reason: "Expected rise in dengue cases (Outbreak Watch)",
  }).toString()}`;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            <Radar className="size-3.5" aria-hidden /> Public health early warning
          </p>
          <h1 className="mt-1 text-2xl font-semibold">Outbreak Watch</h1>
          <p className="max-w-2xl text-sm text-muted-foreground">
            Symptoms patients mention on AI calls, grouped by area. CareSync flags a neighbourhood when this
            week&apos;s cases are well above its own normal, often days before clinics see the rise.
          </p>
        </div>
        {hasData && (
          <div className="flex flex-wrap items-center gap-2">
            {updatedAt && (
              <span className="mr-1 flex items-center gap-1.5 text-xs text-muted-foreground">
                <span className="relative flex size-2">
                  <span className="absolute inline-flex size-full animate-ping rounded-full bg-success/60" />
                  <span className="relative inline-flex size-2 rounded-full bg-success" />
                </span>
                Updated {updatedAt.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })}
              </span>
            )}
            <Button variant="outline" size="sm" onClick={handleCopy}>
              {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
              {copied ? "Copied" : "Copy report"}
            </Button>
            <Button size="sm" onClick={() => setEmailOpen((v) => !v)}>
              <Mail className="size-3.5" /> Send to health officer
            </Button>
          </div>
        )}
      </div>

      {emailOpen && (
        <form onSubmit={handleEmail} className="flex flex-wrap items-end gap-3 rounded-xl border border-border bg-card p-4">
          <label className="min-w-64 flex-1 space-y-1 text-xs">
            <span className="font-medium">District health officer&apos;s email</span>
            <input
              type="email"
              required
              autoFocus
              value={emailTo}
              onChange={(e) => setEmailTo(e.target.value)}
              placeholder="health.officer@example.org"
              className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/20"
            />
          </label>
          <p className="basis-full text-xs text-muted-foreground sm:order-last">
            The report has area-level counts only: no names, phone numbers or transcripts.
          </p>
          <Button type="submit" disabled={busy === "email"}>
            {busy === "email" ? <Loader2 className="size-3.5 animate-spin" /> : <Mail className="size-3.5" />}
            Send report
          </Button>
        </form>
      )}

      {(notice || error) && (
        <div
          role={notice?.type === "success" ? "status" : "alert"}
          className={cn(
            "rounded-lg border px-4 py-3 text-sm",
            notice?.type === "success"
              ? "border-success/30 bg-success/5 text-success"
              : "border-destructive/30 bg-destructive/5 text-destructive",
          )}
        >
          {notice?.text || error}
        </div>
      )}

      {!hasData ? (
        <div className="grid gap-6 rounded-xl border border-border bg-card p-8 lg:grid-cols-2">
          <div>
            <h2 className="font-semibold">No symptom reports yet</h2>
            <p className="mt-2 text-sm text-muted-foreground">
              Reports appear here automatically as AI calls finish. Patients often mention how they are feeling,
              for example &ldquo;I&apos;ve had fever and joint pain since Monday&rdquo; or &ldquo;bukhar aur badan
              dard hai&rdquo;. Add each patient&apos;s locality on their profile so reports are grouped by area.
            </p>
            <div className="mt-5">
              <SampleCityPicker initial="Hubli–Dharwad" busy={busy === "demo"} onLoad={(city) => handleDemo("demo", city)} />
            </div>
            <p className="mt-2 text-xs text-muted-foreground">
              {busy === "demo"
                ? "Finding the city's neighbourhoods on OpenStreetMap. The first time can take up to 30 seconds."
                : "Five weeks of sample reports for that city's real neighbourhoods, with a dengue cluster and a diarrhoea cluster. Clearly marked and removable."}
            </p>
          </div>
          <HowItWorks />
        </div>
      ) : (
        summary && p && (
          <>
            {summary.demo_reports > 0 && (
              <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-dashed border-border bg-muted/40 px-4 py-2.5 text-sm">
                <span className="flex items-center gap-2 text-muted-foreground">
                  <Database className="size-4" aria-hidden />
                  {busy === "demo"
                    ? "Finding neighbourhoods… the first time for a city can take up to 30 seconds."
                    : <>
                        Showing {summary.demo_reports} sample reports
                        {summary.demo_region && <> for <span className="font-medium text-foreground">{summary.demo_region}</span></>}
                        {summary.call_reports > 0 && ` alongside ${summary.call_reports} from real calls`}.
                      </>}
                </span>
                <div className="flex flex-wrap items-center gap-2">
                  <SampleCityPicker
                    key={summary.demo_region || "none"}
                    compact
                    initial={summary.demo_region || ""}
                    busy={busy === "demo"}
                    onLoad={(city) => handleDemo("demo", city)}
                  />
                  <Button variant="ghost" size="sm" onClick={() => handleDemo("clear")} disabled={busy !== null}>
                    {busy === "clear" ? <Loader2 className="size-3.5 animate-spin" /> : <Trash2 className="size-3.5" />}
                    Remove sample data
                  </Button>
                </div>
              </div>
            )}

            {/* KPIs */}
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
              <Kpi
                label="Areas flagged"
                icon={Siren}
                tone={alerts.length ? "alert" : undefined}
                value={
                  <span className="flex items-baseline gap-2">
                    {alerts.length + watches.length}
                    <span className="text-sm font-normal text-muted-foreground">
                      {alerts.length} alert · {watches.length} watch
                    </span>
                  </span>
                }
                hint={alerts[0] ? `Highest: ${alerts[0].syndrome_label} in ${alerts[0].locality}` : "No unusual rises"}
              />
              <Kpi
                label="Symptom reports"
                icon={Activity}
                value={summary.reports_in_window}
                hint={
                  summary.top_symptoms[0]
                    ? `Last ${summary.window_days} days · most common: ${summary.top_symptoms[0].label.toLowerCase()}`
                    : `Last ${summary.window_days} days`
                }
              />
              <Kpi
                label="Calls analysed"
                icon={PhoneCall}
                value={summary.calls_analysed_30d}
                hint="Last 30 days · patient replies only"
              />
              <Kpi
                label="Platelet units, next week"
                icon={Droplets}
                value={`~${p.projected_units}`}
                hint={`For about ${p.projected_cases_next_week} dengue-like cases expected`}
              />
            </div>

            {/* Filter */}
            <div className="flex flex-wrap gap-1 rounded-lg border border-border bg-card p-1" role="tablist" aria-label="Syndrome">
              {FILTERS.map((f) => (
                <button
                  key={f.value}
                  role="tab"
                  aria-selected={filter === f.value}
                  onClick={() => setFilter(f.value)}
                  className={cn(
                    "flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm transition-colors",
                    filter === f.value ? "bg-foreground text-background" : "text-muted-foreground hover:text-foreground",
                  )}
                >
                  {f.value !== "all" && (
                    <span className="size-2 rounded-full" style={{ background: SYNDROME_COLORS[f.value] }} />
                  )}
                  {f.label}
                </button>
              ))}
            </div>

            {/* Signals */}
            <section className="rounded-xl border border-border bg-card">
              <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-5 py-3">
                <h2 className="text-sm font-semibold">
                  Signals{summary.demo_region && !summary.call_reports ? ` in ${summary.demo_region}` : ""}, last {summary.window_days} days
                </h2>
                <span className="text-xs text-muted-foreground">Ranked by how unusual</span>
              </div>
              <div className="space-y-3 p-4">
                {flagged.length === 0 ? (
                  <div className="flex items-start gap-2 rounded-lg border border-success/30 bg-success/5 px-3 py-3 text-sm text-success">
                    <ShieldCheck className="mt-0.5 size-4 shrink-0" />
                    Nothing unusual. Every area is within its normal range.
                  </div>
                ) : (
                  <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                    {flagged.map((s) => (
                      <SignalCard key={`${s.locality}-${s.syndrome}`} signal={s} />
                    ))}
                  </div>
                )}
                {quiet.length > 0 && (
                  <details className="rounded-lg border border-border bg-background px-3 py-2 text-sm">
                    <summary className="cursor-pointer text-muted-foreground">
                      {quiet.length} area{quiet.length === 1 ? "" : "s"} within normal range
                    </summary>
                    <ul className="mt-2 grid gap-x-6 divide-y divide-border sm:grid-cols-2 sm:divide-y-0">
                      {quiet.map((s) => (
                        <li key={`${s.locality}-${s.syndrome}`} className="flex items-center justify-between py-1.5 text-xs">
                          <span>
                            {s.locality} · <span className="text-muted-foreground">{SYNDROME_SHORT[s.syndrome]}</span>
                          </span>
                          <span className="tabular-nums text-muted-foreground">
                            {s.observed} vs {s.expected} usual
                          </span>
                        </li>
                      ))}
                    </ul>
                  </details>
                )}
              </div>
            </section>

            {/* Trend + platelets */}
            <div className="grid gap-6 lg:grid-cols-5">
              <section className="rounded-xl border border-border bg-card p-5 lg:col-span-3">
                <h2 className="text-sm font-semibold">Daily reports, last 5 weeks</h2>
                <p className="mb-4 text-xs text-muted-foreground">
                  All areas combined. The shaded week is compared with the four before it. Tap a syndrome to show or hide it.
                </p>
                <TrendChart
                  days={summary.days}
                  trend={summary.trend}
                  windowDays={summary.window_days}
                  highlight={filter === "all" ? null : filter}
                />
              </section>

              <section className="flex flex-col rounded-xl border border-border bg-card p-5 lg:col-span-2">
                <div className="flex items-center gap-2">
                  <Droplets className="size-4" style={{ color: SYNDROME_COLORS.dengue_like }} aria-hidden />
                  <h2 className="text-sm font-semibold">Platelet demand forecast</h2>
                </div>
                <p className="mt-1 text-xs text-muted-foreground">
                  Dengue lowers platelets. A dengue rise today means platelet requests next week.
                </p>

                <div className="mt-5 grid grid-cols-3 gap-3 text-center">
                  {[
                    { label: "Last week", value: p.dengue_cases_last_week },
                    { label: "This week", value: p.dengue_cases_this_week },
                    { label: "Next week", value: `~${p.projected_cases_next_week}`, strong: true },
                  ].map((c) => (
                    <div key={c.label} className={cn("rounded-lg border px-2 py-3", c.strong ? "border-foreground/20 bg-background" : "border-border")}>
                      <p className="text-xl font-semibold tabular-nums">{c.value}</p>
                      <p className="text-[11px] text-muted-foreground">{c.label}</p>
                    </div>
                  ))}
                </div>
                <p className="mt-2 text-center text-[11px] text-muted-foreground">Dengue-like cases, all areas</p>

                <div className="mt-5 rounded-lg bg-background p-4">
                  <p className="text-sm">
                    Have <span className="font-semibold">~{p.projected_units} platelet unit{p.projected_units === 1 ? "" : "s"}</span> ready
                    for next week.
                  </p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {p.eligible_donors > 0
                      ? `${p.eligible_donors} donor${p.eligible_donors === 1 ? " is" : "s are"} in your network and past their cooldown.`
                      : "No eligible donors in your network yet."}
                  </p>
                </div>

                <Link
                  href={plateletHref}
                  className="mt-4 inline-flex items-center justify-center gap-1.5 rounded-lg bg-foreground px-3 py-2.5 text-sm font-medium text-background transition-opacity hover:opacity-85"
                >
                  Line up platelet donors now <ArrowRight className="size-3.5" />
                </Link>
                <p className="mt-auto pt-4 text-[11px] leading-relaxed text-muted-foreground">
                  Planning estimate, not a prediction. Assumes {Math.round(p.need_share * 100)}% of dengue-like cases need{" "}
                  {p.units_per_episode} single-donor platelet unit, and next week grows at this week&apos;s rate (capped at 2×).
                </p>
              </section>
            </div>

            {/* Symptoms + method */}
            <div className="grid gap-6 lg:grid-cols-5">
              <section className="rounded-xl border border-border bg-card p-5 lg:col-span-2">
                <h2 className="text-sm font-semibold">Most mentioned symptoms</h2>
                <p className="mb-4 text-xs text-muted-foreground">Last {summary.window_days} days, from patients&apos; own words</p>
                <ul className="space-y-3">
                  {summary.top_symptoms.map((s) => {
                    const max = summary.top_symptoms[0]?.count || 1;
                    return (
                      <li key={s.code} className="text-sm">
                        <div className="mb-1 flex items-center justify-between">
                          <span>{s.label}</span>
                          <span className="tabular-nums text-muted-foreground">{s.count}</span>
                        </div>
                        <div className="h-1.5 rounded-full bg-muted">
                          <div className="h-1.5 rounded-full bg-[#2C2420]/70" style={{ width: `${(s.count / max) * 100}%` }} />
                        </div>
                      </li>
                    );
                  })}
                </ul>
              </section>
              <section className="rounded-xl border border-border bg-card p-5 lg:col-span-3">
                <HowItWorks />
              </section>
            </div>
          </>
        )
      )}
    </div>
  );
}

function HowItWorks() {
  const steps = [
    {
      icon: PhoneCall,
      title: "Listen",
      text: "After each AI call, CareSync reads what the patient said (English, Hindi or Kannada) and notes symptoms. Denials like “no fever” or “bukhar nahi” are ignored.",
    },
    {
      icon: Activity,
      title: "Group",
      text: "Symptoms are grouped into syndromes (dengue-like, respiratory, diarrhoea & vomiting) and tagged with the patient’s locality.",
    },
    {
      icon: AlertTriangle,
      title: "Compare",
      text: "Each area’s last 7 days are compared with its previous 28 days. If a rise that large would happen by chance under 5% of the time, the area is on Watch; under 1%, it’s an Alert.",
    },
  ];
  return (
    <div>
      <h2 className="text-sm font-semibold">How Outbreak Watch works</h2>
      <ol className="mt-4 space-y-4">
        {steps.map((s, i) => (
          <li key={s.title} className="flex gap-3">
            <span className="flex size-7 shrink-0 items-center justify-center rounded-full border border-border bg-background text-xs font-semibold">
              {i + 1}
            </span>
            <div>
              <p className="flex items-center gap-1.5 text-sm font-medium">
                <s.icon className="size-3.5 text-muted-foreground" aria-hidden /> {s.title}
              </p>
              <p className="mt-0.5 text-xs leading-relaxed text-muted-foreground">{s.text}</p>
            </div>
          </li>
        ))}
      </ol>
      <p className="mt-4 flex items-start gap-2 rounded-lg bg-background px-3 py-2.5 text-xs text-muted-foreground">
        <ShieldCheck className="mt-0.5 size-3.5 shrink-0" aria-hidden />
        Only area-level counts leave the clinic. Names, numbers and transcripts never appear in reports to health officers.
      </p>
    </div>
  );
}
