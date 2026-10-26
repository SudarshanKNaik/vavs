"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { SyndromeKey } from "@/services/api";
import { cn } from "@/lib/utils";
import { SYNDROME_COLORS, SYNDROME_SHORT } from "./theme";

interface Props {
  days: string[];
  trend: Record<SyndromeKey, number[]>;
  windowDays: number;
  highlight: SyndromeKey | null;
}

const HEIGHT = 240;
const M = { top: 22, right: 92, bottom: 26, left: 30 };
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

export function TrendChart({ days, trend, windowDays, highlight }: Props) {
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const [width, setWidth] = useState(640);
  const [hover, setHover] = useState<number | null>(null);
  const [view, setView] = useState<"chart" | "table">("chart");

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.max(280, entry.contentRect.width)));
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const n = days.length;
  const innerW = width - M.left - M.right;
  const innerH = HEIGHT - M.top - M.bottom;
  const yMax = niceMax(Math.max(1, ...SERIES.flatMap((s) => trend[s] || [])));
  const x = (i: number) => M.left + (n <= 1 ? 0 : (i / (n - 1)) * innerW);
  const y = (v: number) => M.top + innerH - (v / yMax) * innerH;
  const ticks = [0, yMax / 4, yMax / 2, (3 * yMax) / 4, yMax];

  // Direct labels at the line ends, nudged apart so they never collide.
  const endLabels = useMemo(() => {
    const labels = SERIES.map((s) => ({ key: s, y: y(trend[s]?.[n - 1] ?? 0) })).sort((a, b) => a.y - b.y);
    for (let i = 1; i < labels.length; i++) {
      if (labels[i].y - labels[i - 1].y < 14) labels[i].y = labels[i - 1].y + 14;
    }
    return labels;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [trend, n, width, yMax]);

  const weeks = useMemo(() => {
    const rows: { label: string; values: Record<SyndromeKey, number> }[] = [];
    for (let end = n; end > 0; end -= 7) {
      const start = Math.max(0, end - 7);
      const values = Object.fromEntries(
        SERIES.map((s) => [s, (trend[s] || []).slice(start, end).reduce((a, b) => a + b, 0)]),
      ) as Record<SyndromeKey, number>;
      rows.unshift({ label: `${shortDate(days[start])} – ${shortDate(days[end - 1])}`, values });
    }
    return rows;
  }, [days, trend, n]);

  const handleMove = (event: React.MouseEvent<SVGRectElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const ratio = (event.clientX - rect.left) / rect.width;
    setHover(Math.max(0, Math.min(n - 1, Math.round(ratio * (n - 1)))));
  };

  const windowX = x(n - windowDays) - innerW / (n - 1) / 2;

  return (
    <div ref={wrapRef} className="relative">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <ul className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground" aria-label="Legend">
          {SERIES.map((s) => (
            <li key={s} className={cn("flex items-center gap-1.5", highlight && highlight !== s && "opacity-50")}>
              <span className="h-0.5 w-4 rounded-full" style={{ background: SYNDROME_COLORS[s] }} />
              {SYNDROME_SHORT[s]}
            </li>
          ))}
        </ul>
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
        <svg width={width} height={HEIGHT} role="img" aria-label="Daily symptom reports by syndrome over five weeks" className="block">
          <rect x={windowX} y={M.top} width={x(n - 1) - windowX} height={innerH} fill="#2C2420" opacity={0.045} />
          <text x={x(n - 1)} y={M.top - 8} textAnchor="end" className="fill-muted-foreground text-[10px] uppercase tracking-wider">
            Last {windowDays} days
          </text>

          {ticks.map((t) => (
            <g key={t}>
              <line x1={M.left} x2={M.left + innerW} y1={y(t)} y2={y(t)} stroke="#E8E2D9" strokeWidth={1} />
              <text x={M.left - 8} y={y(t)} dy="0.32em" textAnchor="end" className="fill-muted-foreground text-[10px] tabular-nums">
                {Number.isInteger(t) ? t : t.toFixed(1)}
              </text>
            </g>
          ))}

          {days.map((d, i) =>
            (n - 1 - i) % 7 === 0 ? (
              <text key={d} x={x(i)} y={HEIGHT - 6} textAnchor="middle" className="fill-muted-foreground text-[10px]">
                {shortDate(d)}
              </text>
            ) : null,
          )}

          {SERIES.map((s) => {
            const values = trend[s] || [];
            const path = values.map((v, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join("");
            const dim = highlight && highlight !== s;
            return (
              <path
                key={s}
                d={path}
                fill="none"
                stroke={SYNDROME_COLORS[s]}
                strokeWidth={2}
                strokeLinejoin="round"
                strokeLinecap="round"
                strokeDasharray={s === "fever" ? "4 3" : undefined}
                opacity={dim ? 0.2 : 1}
              />
            );
          })}

          {endLabels.map((label) => (
            <text
              key={label.key}
              x={x(n - 1) + 8}
              y={label.y}
              dy="0.32em"
              className={cn("fill-foreground text-[11px]", highlight && highlight !== label.key && "opacity-40")}
            >
              {SYNDROME_SHORT[label.key]}
            </text>
          ))}

          {hover !== null && (
            <g pointerEvents="none">
              <line x1={x(hover)} x2={x(hover)} y1={M.top} y2={M.top + innerH} stroke="#8C7B70" strokeWidth={1} strokeDasharray="3 3" />
              {SERIES.map((s) => (
                <circle key={s} cx={x(hover)} cy={y(trend[s]?.[hover] ?? 0)} r={4} fill={SYNDROME_COLORS[s]} stroke="#FAF8F5" strokeWidth={2} />
              ))}
            </g>
          )}

          <rect
            x={M.left}
            y={M.top}
            width={innerW}
            height={innerH}
            fill="transparent"
            onMouseMove={handleMove}
            onMouseLeave={() => setHover(null)}
          />
        </svg>
      )}

      {view === "chart" && hover !== null && (
        <div
          className="pointer-events-none absolute z-10 min-w-36 rounded-lg border border-border bg-card px-3 py-2 text-xs shadow-lg"
          style={{
            left: Math.min(x(hover) + 12, width - 160),
            top: 40,
          }}
        >
          <p className="mb-1 font-medium">{new Date(`${days[hover]}T00:00:00`).toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" })}</p>
          {[...SERIES]
            .sort((a, b) => (trend[b]?.[hover] ?? 0) - (trend[a]?.[hover] ?? 0))
            .map((s) => (
              <p key={s} className="flex items-center justify-between gap-4">
                <span className="flex items-center gap-1.5 text-muted-foreground">
                  <span className="size-2 rounded-full" style={{ background: SYNDROME_COLORS[s] }} />
                  {SYNDROME_SHORT[s]}
                </span>
                <span className="tabular-nums">{trend[s]?.[hover] ?? 0}</span>
              </p>
            ))}
        </div>
      )}
    </div>
  );
}
