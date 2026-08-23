/**
 * Dashboard charts (Phase 5.1, FR-8.1 / FR-4.6) — dependency-free inline SVG,
 * theme-aware via the --viz-* tokens in globals.css (dataviz skill palette,
 * validated light + dark). Marks wear the series colors; all text uses ink
 * tokens. Both charts carry a legend and a hover tooltip.
 */

"use client";

import { useState } from "react";

import type { MonthlyPerformance } from "@/lib/api";
import { formatCompactINR, formatINR, monthLong, monthShort } from "@/lib/format";

const VB_W = 760;
const VB_H = 280;
const PAD = { top: 20, right: 60, bottom: 30, left: 54 };
const PLOT_W = VB_W - PAD.left - PAD.right;
const PLOT_H = VB_H - PAD.top - PAD.bottom;
const X0 = PAD.left;
const Y_TOP = PAD.top;
const Y_BASE = PAD.top + PLOT_H;

/** Round up to a clean 1/2/5×10ⁿ ceiling for axis ticks. */
function niceCeil(v: number): number {
  if (v <= 0) return 1;
  const pow = Math.pow(10, Math.floor(Math.log10(v)));
  const n = v / pow;
  const f = n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10;
  return f * pow;
}

function EmptyChart({ label }: { label: string }) {
  return (
    <div className="flex h-40 items-center justify-center rounded-lg border border-dashed border-black/15 dark:border-white/15 text-sm text-black/40 dark:text-white/40">
      {label}
    </div>
  );
}

// --- Revenue vs Expenses (two lines) ---

export function RevenueExpenseChart({ months }: { months: MonthlyPerformance[] }) {
  const [hover, setHover] = useState<number | null>(null);

  const rev = months.map((m) => Number(m.revenue));
  const exp = months.map((m) => Number(m.expenses));
  const n = months.length;
  if (n === 0 || rev.every((v) => v === 0) && exp.every((v) => v === 0)) {
    return <EmptyChart label="No revenue or expenses in this period yet." />;
  }

  const maxY = niceCeil(Math.max(1, ...rev, ...exp));
  const x = (i: number) => (n === 1 ? X0 + PLOT_W / 2 : X0 + (i / (n - 1)) * PLOT_W);
  const y = (v: number) => Y_BASE - (v / maxY) * PLOT_H;
  const path = (vals: number[]) =>
    vals.map((v, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");

  const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => f * maxY);

  const tip = hover === null ? null : buildTip(x(hover), [
    monthLong(months[hover].month),
    `Revenue ${formatINR(rev[hover])}`,
    `Expenses ${formatINR(exp[hover])}`,
  ]);

  return (
    <figure className="viz">
      <Legend items={[["var(--viz-series-rev)", "Revenue"], ["var(--viz-series-exp)", "Expenses"]]} />
      <svg viewBox={`0 0 ${VB_W} ${VB_H}`} className="w-full h-auto" role="img"
        aria-label="Monthly revenue and expenses">
        {ticks.map((t, i) => (
          <g key={i}>
            <line x1={X0} x2={X0 + PLOT_W} y1={y(t)} y2={y(t)} stroke="var(--viz-grid)" strokeWidth={1} />
            <text x={X0 - 8} y={y(t) + 3} textAnchor="end" fontSize={10} fill="var(--viz-muted)"
              style={{ fontVariantNumeric: "tabular-nums" }}>
              {formatCompactINR(t)}
            </text>
          </g>
        ))}
        {months.map((m, i) => (
          <text key={i} x={x(i)} y={Y_BASE + 16} textAnchor="middle" fontSize={10} fill="var(--viz-muted)">
            {monthShort(m.month)}
          </text>
        ))}

        <path d={path(rev)} fill="none" stroke="var(--viz-series-rev)" strokeWidth={2}
          strokeLinejoin="round" strokeLinecap="round" />
        <path d={path(exp)} fill="none" stroke="var(--viz-series-exp)" strokeWidth={2}
          strokeLinejoin="round" strokeLinecap="round" />

        {hover !== null && (
          <>
            <line x1={x(hover)} x2={x(hover)} y1={Y_TOP} y2={Y_BASE} stroke="var(--viz-baseline)" strokeWidth={1} />
            {[["var(--viz-series-rev)", rev[hover]], ["var(--viz-series-exp)", exp[hover]]].map(
              ([c, v], i) => (
                <circle key={i} cx={x(hover)} cy={y(v as number)} r={4}
                  fill={c as string} stroke="var(--viz-surface)" strokeWidth={2} />
              ),
            )}
          </>
        )}
        {tip}

        <rect x={X0} y={Y_TOP} width={PLOT_W} height={PLOT_H} fill="transparent"
          onMouseMove={(e) => setHover(nearestIndex(e, n))}
          onMouseLeave={() => setHover(null)} />
      </svg>
    </figure>
  );
}

// --- Net cash flow (diverging bars around zero) ---

export function NetCashFlowChart({ months }: { months: MonthlyPerformance[] }) {
  const [hover, setHover] = useState<number | null>(null);

  const net = months.map((m) => Number(m.net_cash_flow));
  const n = months.length;
  if (n === 0 || net.every((v) => v === 0)) {
    return <EmptyChart label="No net cash flow in this period yet." />;
  }

  const maxAbs = niceCeil(Math.max(1, ...net.map(Math.abs)));
  const yZero = Y_TOP + PLOT_H / 2;
  const y = (v: number) => yZero - (v / maxAbs) * (PLOT_H / 2);
  const band = PLOT_W / n;
  const barW = Math.min(24, band * 0.6);
  const cx = (i: number) => X0 + band * i + band / 2;

  const ticks = [maxAbs, maxAbs / 2, 0, -maxAbs / 2, -maxAbs];

  const tip = hover === null ? null : buildTip(cx(hover), [
    monthLong(months[hover].month),
    `Net ${formatINR(net[hover])}`,
  ]);

  return (
    <figure className="viz">
      <Legend items={[["var(--viz-pos)", "Net positive"], ["var(--viz-neg)", "Net negative"]]} />
      <svg viewBox={`0 0 ${VB_W} ${VB_H}`} className="w-full h-auto" role="img"
        aria-label="Monthly net cash flow">
        {ticks.map((t, i) => (
          <g key={i}>
            <line x1={X0} x2={X0 + PLOT_W} y1={y(t)} y2={y(t)}
              stroke={t === 0 ? "var(--viz-baseline)" : "var(--viz-grid)"} strokeWidth={1} />
            <text x={X0 - 8} y={y(t) + 3} textAnchor="end" fontSize={10} fill="var(--viz-muted)"
              style={{ fontVariantNumeric: "tabular-nums" }}>
              {formatCompactINR(t)}
            </text>
          </g>
        ))}

        {net.map((v, i) => {
          const positive = v >= 0;
          const yv = y(v);
          const top = positive ? yv : yZero;
          const h = Math.abs(yv - yZero);
          const color = positive ? "var(--viz-pos)" : "var(--viz-neg)";
          return (
            <g key={i} onMouseEnter={() => setHover(i)} onMouseMove={() => setHover(i)}
              onMouseLeave={() => setHover(null)}>
              <path d={barTopRounded(cx(i) - barW / 2, top, barW, h, positive)} fill={color}
                opacity={hover === null || hover === i ? 1 : 0.55} />
              <text x={cx(i)} y={Y_BASE + 16} textAnchor="middle" fontSize={10} fill="var(--viz-muted)">
                {monthShort(months[i].month)}
              </text>
              <title>{`${monthLong(months[i].month)}: ${formatINR(v)}`}</title>
            </g>
          );
        })}
        {tip}
      </svg>
    </figure>
  );
}

// --- shared bits ---

function Legend({ items }: { items: [string, string][] }) {
  return (
    <figcaption className="mb-2 flex flex-wrap gap-4 text-xs text-black/60 dark:text-white/60">
      {items.map(([color, label]) => (
        <span key={label} className="inline-flex items-center gap-1.5">
          <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: color }} />
          {label}
        </span>
      ))}
    </figcaption>
  );
}

/** Index of the month nearest the cursor within the plot area. */
function nearestIndex(e: React.MouseEvent<SVGRectElement>, n: number): number {
  const rect = e.currentTarget.getBoundingClientRect();
  const frac = (e.clientX - rect.left) / rect.width; // 0..1 across the plot
  return Math.max(0, Math.min(n - 1, Math.round(frac * (n - 1))));
}

/** A rect with the far (data) end rounded and the baseline end square. */
function barTopRounded(x: number, yTop: number, w: number, h: number, positive: boolean): string {
  const r = Math.min(4, w / 2, h);
  if (h <= 0.5) return `M${x},${yTop} h${w}`; // flat: hairline at baseline
  if (positive) {
    return `M${x},${yTop + h} L${x},${yTop + r} Q${x},${yTop} ${x + r},${yTop} `
      + `L${x + w - r},${yTop} Q${x + w},${yTop} ${x + w},${yTop + r} L${x + w},${yTop + h} Z`;
  }
  const yBot = yTop + h;
  return `M${x},${yTop} L${x},${yBot - r} Q${x},${yBot} ${x + r},${yBot} `
    + `L${x + w - r},${yBot} Q${x + w},${yBot} ${x + w},${yBot - r} L${x + w},${yTop} Z`;
}

/** An SVG tooltip box near x, clamped inside the plot. */
function buildTip(atX: number, lines: string[]) {
  const w = Math.max(...lines.map((l) => l.length)) * 6.1 + 18;
  const h = 16 + lines.length * 14;
  const x = Math.max(X0, Math.min(X0 + PLOT_W - w, atX - w / 2));
  const y = Y_TOP + 2;
  return (
    <g pointerEvents="none">
      <rect x={x} y={y} width={w} height={h} rx={6} fill="var(--viz-surface)"
        stroke="var(--viz-baseline)" strokeWidth={1} />
      {lines.map((line, i) => (
        <text key={i} x={x + 9} y={y + 16 + i * 14} fontSize={11}
          fill="var(--foreground)" fontWeight={i === 0 ? 600 : 400}
          style={{ fontVariantNumeric: "tabular-nums" }}>
          {line}
        </text>
      ))}
    </g>
  );
}
