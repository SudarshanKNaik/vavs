"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowDownRight, ArrowUpRight, Minus } from "lucide-react";
import type { SyndromeKey } from "@/services/api";
import { cn } from "@/lib/utils";
import { SYNDROME_COLORS, SYNDROME_SHORT } from "./theme";

interface Props {
  days: string[];
  trend: Record<SyndromeKey, number[]>;
  windowDays: number;
  highlight: SyndromeKey | null;
}

const HEIGHT = 280;
const M = { top: 28, right: 16, bottom: 28, left: 34 };
const SERIES: SyndromeKey[] = ["dengue_like", "respiratory", "gastro", "fever"];

function niceMax(value: number) {
  if (value <= 4) return 4;
  const step = Math.pow(10, Math.floor(Math.log10(value)));
  for (const m of [1, 2, 2.5, 5, 10]) {
    if (value <= m * step) return m * step;
  }
  return value;
}

function shortDate(iso: string) {
  return new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

function sum(values: number[]) {
  return values.reduce((a, b) => a + b, 0);
}

// Monotone cubic (Fritsch–Carlson): smooth, but never overshoots below zero or above a peak.
function smoothPath(points: [number, number][]) {
  const n = points.length;
  if (n === 0) return "";
  if (n < 3) return points.map(([px, py], i) => `${i ? "L" : "M"}${px.toFixed(1)},${py.toFixed(1)}`).join("");
  const dx = points.slice(1).map(([px], i) => px - points[i][0]);
  const slope = points.slice(1).map(([, py], i) => (py - points[i][1]) / dx[i]);
  const t = points.map((_, i) => {
    if (i === 0) return slope[0];
    if (i === n - 1) return slope[n - 2];
    return slope[i - 1] * slope[i] <= 0 ? 0 : (slope[i - 1] + slope[i]) / 2;
  });
  for (let i = 0; i < n - 1; i++) {
    if (slope[i] === 0) {
      t[i] = 0;
      t[i + 1] = 0;
      continue;
    }
    const a = t[i] / slope[i];
    const b = t[i + 1] / slope[i];
    const h = a * a + b * b;
    if (h > 9) {
      const k = 3 / Math.sqrt(h);
      t[i] = k * a * slope[i];
      t[i + 1] = k * b * slope[i];
    }
  }
  let d = `M${points[0][0].toFixed(1)},${points[0][1].toFixed(1)}`;
  for (let i = 0; i < n - 1; i++) {
    const [x0, y0] = points[i];
    const [x1, y1] = points[i + 1];
    const h = dx[i] / 3;
    d += `C${(x0 + h).toFixed(1)},${(y0 + t[i] * h).toFixed(1)} ${(x1 - h).toFixed(1)},${(y1 - t[i + 1] * h).toFixed(1)} ${x1.toFixed(1)},${y1.toFixed(1)}`;
  }
  return d;
}

function Change({ now, before }: { now: number; before: number }) {
  if (now === before) {
    return (
      <span className="flex items-center gap-0.5 text-muted-foreground">
        <Minus className="size-3" aria-hidden /> same
      </span>
    );
  }
  const up = now > before;
  const label = before === 0 ? "new" : `${Math.round((Math.abs(now - before) / before) * 100)}%`;
  const Icon = up ? ArrowUpRight : ArrowDownRight;
  return (
    <span className={cn("flex items-center gap-0.5 font-medium", up ? "text-[#b42f2f]" : "text-success")}>
      <Icon className="size-3" aria-hidden />
      {label}
      <span className="sr-only">{up ? "up" : "down"} on the week before</span>
    </span>
  );
}

export function TrendChart({ days, trend, windowDays, highlight }: Props) {
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const [width, setWidth] = useState(640);
  const [hover, setHover] = useState<number | null>(null);
  const [view, setView] = useState<"chart" | "table">("chart");
  const [hidden, setHidden] = useState<Set<SyndromeKey>>(new Set());

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.max(280, entry.contentRect.width)));
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const visible = SERIES.filter((s) => !hidden.has(s));
  const n = days.length;
  const innerW = width - M.left - M.right;
  const innerH = HEIGHT - M.top - M.bottom;
  const yMax = niceMax(Math.max(1, ...visible.flatMap((s) => trend[s] || [])));
  const x = (i: number) => M.left + (n <= 1 ? 0 : (i / (n - 1)) * innerW);
  const y = (v: number) => M.top + innerH - (v / yMax) * innerH;
  const ticks = [0, yMax / 4, yMax / 2, (3 * yMax) / 4, yMax];

  const totals = useMemo(
    () =>
      Object.fromEntries(
        SERIES.map((s) => {
          const values = trend[s] || [];
          return [s, { now: sum(values.slice(-windowDays)), before: sum(values.slice(-2 * windowDays, -windowDays)) }];
        }),
      ) as Record<SyndromeKey, { now: number; before: number }>,
    [trend, windowDays],
  );

  const weeks = useMemo(() => {
    const rows: { label: string; values: Record<SyndromeKey, number> }[] = [];
    for (let end = n; end > 0; end -= 7) {
      const start = Math.max(0, end - 7);
      const values = Object.fromEntries(
        SERIES.map((s) => [s, sum((trend[s] || []).slice(start, end))]),
      ) as Record<SyndromeKey, number>;
      rows.unshift({ label: `${shortDate(days[start])} – ${shortDate(days[end - 1])}`, values });
    }
    return rows;
  }, [days, trend, n]);

  const toggle = (s: SyndromeKey) =>
    setHidden((prev) => {
      const next = new Set(prev);
      if (next.has(s)) next.delete(s);
      else if (next.size < SERIES.length - 1) next.add(s);
      return next;
    });

  const handleMove = (event: React.PointerEvent<SVGRectElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const ratio = (event.clientX - rect.left) / rect.width;
    setHover(Math.max(0, Math.min(n - 1, Math.round(ratio * (n - 1)))));
  };

  const windowX = x(n - windowDays) - innerW / (n - 1) / 2;
  const baseline = y(0);
  const hoverTotal = hover === null ? 0 : visible.reduce((a, s) => a + (trend[s]?.[hover] ?? 0), 0);
  const tooltipLeft = hover === null ? 0 : x(hover) > width / 2 ? x(hover) - 176 : x(hover) + 14;

  return (
    <div ref={wrapRef} className="relative">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div className="grid flex-1 grid-cols-2 gap-2 sm:grid-cols-4" aria-label="Syndromes, this week">
          {SERIES.map((s) => {
            const off = hidden.has(s);
            const dim = highlight && highlight !== s;
            return (
              <button
                key={s}
                type="button"
                aria-pressed={!off}
                onClick={() => toggle(s)}
                className={cn(
                  "rounded-lg border px-3 py-2 text-left transition-all hover:border-foreground/30",
                  off ? "border-dashed border-border bg-transparent opacity-50" : "border-border bg-background",
                  dim && !off && "opacity-60",
                )}
              >
                <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
                  <span
                    className="size-2.5 rounded-full"
                    style={{ background: off ? "transparent" : SYNDROME_COLORS[s], boxShadow: `inset 0 0 0 1.5px ${SYNDROME_COLORS[s]}` }}
                  />
                  {SYNDROME_SHORT[s]}
                </span>
                <span className="mt-1 flex items-baseline justify-between gap-2">
                  <span className="text-lg font-semibold tabular-nums">{totals[s].now}</span>
                  <span className="text-[11px]">
                    <Change now={totals[s].now} before={totals[s].before} />
                  </span>
                </span>
              </button>
            );
          })}
        </div>
        <div className="flex rounded-lg border border-border p-0.5 text-xs" role="tablist" aria-label="Trend view">
          {(["chart", "table"] as const).map((v) => (
            <button
              key={v}
              role="tab"
              aria-selected={view === v}
              onClick={() => setView(v)}
              className={cn(
                "rounded-md px-2.5 py-1 capitalize transition-colors",
                view === v ? "bg-foreground text-background" : "text-muted-foreground hover:text-foreground",
              )}
            >
              {v}
            </button>
          ))}
        </div>
      </div>

      {view === "table" ? (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-xs text-muted-foreground">
                <th className="py-2 pr-4 font-medium">Week</th>
                {SERIES.map((s) => (
                  <th key={s} className="py-2 pr-4 text-right font-medium">{SYNDROME_SHORT[s]}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {weeks.map((w, i) => (
                <tr key={w.label} className={cn("border-b border-border/60", i === weeks.length - 1 && "font-medium")}>
                  <td className="py-2 pr-4">{w.label}{i === weeks.length - 1 && " (this week)"}</td>
                  {SERIES.map((s) => (
                    <td key={s} className="py-2 pr-4 text-right tabular-nums">{w.values[s]}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="relative">
          <svg width={width} height={HEIGHT} role="img" aria-label="Daily symptom reports by syndrome over five weeks" className="block touch-pan-y select-none">
            <defs>
              {SERIES.map((s) => (
                <linearGradient key={s} id={`ow-fill-${s}`} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={SYNDROME_COLORS[s]} stopOpacity={0.22} />
                  <stop offset="100%" stopColor={SYNDROME_COLORS[s]} stopOpacity={0} />
                </linearGradient>
              ))}
            </defs>

            <rect x={windowX} y={M.top} width={x(n - 1) - windowX + 6} height={innerH} rx={8} className="fill-foreground" opacity={0.04} />
            <g transform={`translate(${x(n - 1) + 6}, ${M.top - 20})`}>
              <text textAnchor="end" y={10} className="fill-muted-foreground text-[10px] font-medium uppercase tracking-wider">
                This week
              </text>
            </g>

            {ticks.map((t) => (
              <g key={t}>
                <line
                  x1={M.left}
                  x2={M.left + innerW}
                  y1={y(t)}
                  y2={y(t)}
                  className="stroke-border"
                  strokeWidth={1}
                  strokeDasharray={t === 0 ? undefined : "2 4"}
                />
                <text x={M.left - 10} y={y(t)} dy="0.32em" textAnchor="end" className="fill-muted-foreground text-[10px] tabular-nums">
                  {Number.isInteger(t) ? t : t.toFixed(1)}
                </text>
              </g>
            ))}

            {days.map((d, i) =>
              (n - 1 - i) % 7 === 0 ? (
                <text key={d} x={x(i)} y={HEIGHT - 8} textAnchor={i === n - 1 ? "end" : "middle"} className="fill-muted-foreground text-[10px]">
                  {i === n - 1 ? "Today" : shortDate(d)}
                </text>
              ) : null,
            )}

            {visible.map((s) => {
              const pts = (trend[s] || []).map((v, i) => [x(i), y(v)] as [number, number]);
              if (!pts.length) return null;
              const line = smoothPath(pts);
              const dim = highlight && highlight !== s;
              return (
                <g key={s} opacity={dim ? 0.15 : 1} className="transition-opacity duration-300">
                  {s !== "fever" && (
                    <path d={`${line}L${pts[pts.length - 1][0].toFixed(1)},${baseline}L${pts[0][0].toFixed(1)},${baseline}Z`} fill={`url(#ow-fill-${s})`} />
                  )}
                  <path
                    d={line}
                    fill="none"
                    stroke={SYNDROME_COLORS[s]}
                    strokeWidth={highlight === s ? 3 : 2.25}
                    strokeLinejoin="round"
                    strokeLinecap="round"
                    strokeDasharray={s === "fever" ? "4 4" : undefined}
                  />
                  {hover === null && (
                    <circle cx={pts[pts.length - 1][0]} cy={pts[pts.length - 1][1]} r={3.5} fill={SYNDROME_COLORS[s]} className="stroke-card" strokeWidth={2} />
                  )}
                </g>
              );
            })}

            {hover !== null && (
              <g pointerEvents="none">
                <line x1={x(hover)} x2={x(hover)} y1={M.top} y2={M.top + innerH} className="stroke-muted-foreground" strokeWidth={1} strokeDasharray="3 3" />
                {visible.map((s) => (
                  <circle key={s} cx={x(hover)} cy={y(trend[s]?.[hover] ?? 0)} r={5} fill={SYNDROME_COLORS[s]} className="stroke-card" strokeWidth={2.5} />
                ))}
              </g>
            )}

            <rect
              x={M.left}
              y={M.top}
              width={innerW}
              height={innerH}
              fill="transparent"
              onPointerMove={handleMove}
              onPointerDown={handleMove}
              onPointerLeave={() => setHover(null)}
            />
          </svg>
          {hover !== null && (
            <div
              className="pointer-events-none absolute z-10 w-[164px] rounded-xl border border-border bg-card/95 px-3 py-2.5 text-xs shadow-xl backdrop-blur"
              style={{ left: Math.max(0, tooltipLeft), top: 36 }}
            >
              <p className="mb-1.5 flex items-center justify-between font-medium">
                {new Date(`${days[hover]}T00:00:00`).toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" })}
              </p>
              <div className="space-y-1">
                {[...visible]
                  .sort((a, b) => (trend[b]?.[hover] ?? 0) - (trend[a]?.[hover] ?? 0))
                  .map((s) => (
                    <p key={s} className="flex items-center justify-between gap-4">
                      <span className="flex items-center gap-1.5 text-muted-foreground">
                        <span className="size-2 rounded-full" style={{ background: SYNDROME_COLORS[s] }} />
                        {SYNDROME_SHORT[s]}
                      </span>
                      <span className="font-medium tabular-nums">{trend[s]?.[hover] ?? 0}</span>
                    </p>
                  ))}
              </div>
              <p className="mt-1.5 flex items-center justify-between border-t border-border pt-1.5 font-medium">
                <span>Total</span>
                <span className="tabular-nums">{hoverTotal}</span>
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
