"use client";

import { useCallback, useEffect, useState } from "react";
import { Loader2, Pencil } from "lucide-react";
import { Button } from "@/components/ui/button";
import { getDoctorSchedule, saveDoctorSchedule, type DoctorSchedule } from "@/services/api";

const WEEKDAYS = [
  { iso: 1, short: "Mon" },
  { iso: 2, short: "Tue" },
  { iso: 3, short: "Wed" },
  { iso: 4, short: "Thu" },
  { iso: 5, short: "Fri" },
  { iso: 6, short: "Sat" },
  { iso: 7, short: "Sun" },
];
const SLOT_LENGTHS = [10, 15, 20, 30, 45, 60, 90, 120];
const WINDOWS = [7, 14, 30, 60, 90];

function to12h(value: string | null) {
  if (!value) return "";
  const [h, m] = value.split(":").map(Number);
  return `${h % 12 || 12}:${String(m).padStart(2, "0")} ${h < 12 ? "AM" : "PM"}`;
}

function describeDays(days: number[]) {
  const sorted = [...days].sort((a, b) => a - b);
  const names = sorted.map((d) => WEEKDAYS[d - 1].short);
  const consecutive = sorted.every((d, i) => i === 0 || d === sorted[i - 1] + 1);
  if (sorted.length >= 3 && consecutive) return `${names[0]} to ${names[names.length - 1]}`;
  return names.join(", ");
}

export function describeSchedule(s: DoctorSchedule) {
  const parts = [
    `${describeDays(s.working_days)}, ${to12h(s.day_start)} to ${to12h(s.day_end)}`,
    `${s.slot_minutes}-minute slots`,
    s.break_start && s.break_end ? `break ${to12h(s.break_start)} to ${to12h(s.break_end)}` : "no break",
    `bookable ${s.window_days} days ahead`,
  ];
  return parts.join(" · ");
}

const inputClass =
  "w-full rounded-lg border border-border bg-background px-3 py-2 text-sm focus:border-primary/30 focus:outline-none focus:ring-2 focus:ring-primary/20";

/** Shows the doctor's schedule rules and lets them edit them. */
export function ScheduleRulesCard({ doctorId, onSaved }: { doctorId?: string; onSaved: () => void }) {
  const [saved, setSaved] = useState<DoctorSchedule | null>(null);
  const [draft, setDraft] = useState<DoctorSchedule | null>(null);
  const [hasBreak, setHasBreak] = useState(true);
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);

  const load = useCallback(async () => {
    if (!doctorId) return;
    try {
      const data = await getDoctorSchedule(doctorId);
      setSaved(data);
    } catch (err) {
      setMessage({ type: "error", text: err instanceof Error ? err.message : "Could not load schedule." });
    }
  }, [doctorId]);

  useEffect(() => {
    load();
  }, [load]);

  const startEditing = () => {
    if (!saved) return;
    setDraft({ ...saved });
    setHasBreak(Boolean(saved.break_start && saved.break_end));
    setMessage(null);
    setEditing(true);
  };

  const update = <K extends keyof DoctorSchedule>(key: K, value: DoctorSchedule[K]) =>
    setDraft((prev) => (prev ? { ...prev, [key]: value } : prev));

  const toggleDay = (iso: number) =>
    setDraft((prev) =>
      prev
        ? {
            ...prev,
            working_days: prev.working_days.includes(iso)
              ? prev.working_days.filter((d) => d !== iso)
              : [...prev.working_days, iso].sort((a, b) => a - b),
          }
        : prev,
    );

  const save = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!doctorId || !draft) return;
    if (draft.working_days.length === 0) {
      setMessage({ type: "error", text: "Choose at least one working day." });
      return;
    }
    setSaving(true);
    setMessage(null);
    try {
      const result = await saveDoctorSchedule(doctorId, {
        ...draft,
        break_start: hasBreak ? draft.break_start || "13:00" : null,
        break_end: hasBreak ? draft.break_end || "14:00" : null,
      });
      setSaved(result.schedule);
      setEditing(false);
      setMessage({
        type: "success",
        text:
          `Schedule saved: ${result.slots_added} slot(s) added, ${result.slots_removed} removed.` +
          (result.booked_outside_new_hours > 0
            ? ` ${result.booked_outside_new_hours} booked appointment(s) now fall outside your hours; they were kept. Cancel them from the calendar if needed.`
            : ""),
      });
      onSaved();
    } catch (err) {
      setMessage({ type: "error", text: err instanceof Error ? err.message : "Could not save the schedule." });
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="mt-3 rounded-lg border border-border bg-background/60 p-3">
      {!editing ? (
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-xs text-muted-foreground">
            <span className="font-medium text-foreground">Schedule:</span>{" "}
            {saved ? describeSchedule(saved) : "Loading…"}
          </p>
          <Button variant="outline" size="sm" onClick={startEditing} disabled={!saved}>
            <Pencil className="size-3.5" />
            Edit schedule
          </Button>
        </div>
      ) : (
        draft && (
          <form onSubmit={save} className="space-y-4">
            <div>
              <span className="text-xs font-medium">Working days</span>
              <div className="mt-1 flex flex-wrap gap-1.5">
                {WEEKDAYS.map((d) => {
                  const on = draft.working_days.includes(d.iso);
                  return (
                    <button
                      key={d.iso}
                      type="button"
                      aria-pressed={on}
                      onClick={() => toggleDay(d.iso)}
                      className={`rounded-md border px-2.5 py-1 text-xs transition-colors ${
                        on ? "border-primary bg-primary/10 text-foreground" : "border-border text-muted-foreground hover:border-primary/40"
                      }`}
                    >
                      {d.short}
                    </button>
                  );
                })}
              </div>
            </div>

            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <label className="space-y-1 text-xs">
                <span className="font-medium">Day starts</span>
                <input type="time" required value={draft.day_start} onChange={(e) => update("day_start", e.target.value)} className={inputClass} />
              </label>
              <label className="space-y-1 text-xs">
                <span className="font-medium">Day ends</span>
                <input type="time" required value={draft.day_end} onChange={(e) => update("day_end", e.target.value)} className={inputClass} />
              </label>
              <label className="space-y-1 text-xs">
                <span className="font-medium">Slot length</span>
                <select value={draft.slot_minutes} onChange={(e) => update("slot_minutes", Number(e.target.value))} className={inputClass}>
                  {SLOT_LENGTHS.map((m) => (
                    <option key={m} value={m}>{m} minutes</option>
                  ))}
                </select>
              </label>
              <label className="space-y-1 text-xs">
                <span className="font-medium">Bookable ahead</span>
                <select value={draft.window_days} onChange={(e) => update("window_days", Number(e.target.value))} className={inputClass}>
                  {WINDOWS.map((d) => (
                    <option key={d} value={d}>{d} days</option>
                  ))}
                </select>
              </label>
            </div>

            <div className="space-y-2">
              <label className="inline-flex items-center gap-2 text-xs font-medium">
                <input type="checkbox" checked={hasBreak} onChange={(e) => setHasBreak(e.target.checked)} />
                Daily break
              </label>
              {hasBreak && (
                <div className="grid gap-3 sm:grid-cols-2 lg:max-w-md">
                  <label className="space-y-1 text-xs">
                    <span className="font-medium">Break starts</span>
                    <input type="time" required value={draft.break_start || "13:00"} onChange={(e) => update("break_start", e.target.value)} className={inputClass} />
                  </label>
                  <label className="space-y-1 text-xs">
                    <span className="font-medium">Break ends</span>
                    <input type="time" required value={draft.break_end || "14:00"} onChange={(e) => update("break_end", e.target.value)} className={inputClass} />
                  </label>
                </div>
              )}
            </div>

            <p className="text-[11px] text-muted-foreground">
              Saving rebuilds your open slots. Booked appointments are never changed.
            </p>
            <div className="flex gap-2">
              <Button type="submit" size="sm" disabled={saving}>
                {saving && <Loader2 className="size-3.5 animate-spin" />}
                {saving ? "Saving…" : "Save schedule"}
              </Button>
              <Button type="button" variant="ghost" size="sm" onClick={() => setEditing(false)} disabled={saving}>
                Cancel
              </Button>
            </div>
          </form>
        )
      )}
      {message && (
        <p className={`mt-2 text-xs ${message.type === "success" ? "text-success" : "text-destructive"}`}>{message.text}</p>
      )}
    </div>
  );
}
