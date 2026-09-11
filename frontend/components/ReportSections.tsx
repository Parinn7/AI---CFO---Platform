/**
 * Pieces every report screen shares (Phase 8) — the category breakdown table,
 * the period-comparison row, the empty states, and the small formatters a
 * report's prose depends on.
 *
 * Extracted from the monthly report in 8.2 rather than copied, and widened in
 * 8.3 when the investor summary became the second screen to state a period
 * against the one before it: two reports drawing the same comparison
 * differently would be two claims about one period, which is the whole reason
 * the KPI tiles are shared with the dashboard too.
 *
 * Display only. Every figure arrives already computed by the Financial Engine
 * (architecture §4.1) and is rendered through `lib/format.ts`, so a rupee reads
 * the same on every screen.
 */

import Link from "next/link";

import { type CategoryLine } from "@/lib/api";
import { formatINR, monthLong, monthShort } from "@/lib/format";

/** A signed change, e.g. "+₹1,00,000.00" / "-₹20,000.00". */
export function signed(value: string): string {
  const n = Number(value);
  return `${n >= 0 ? "+" : "-"}${formatINR(Math.abs(n))}`;
}

/** "May – Jul 2026", or "Aug 2025 – Jul 2026" when the window crosses a year
 * boundary — a report that says "Aug – Jul 2026" is ambiguous about which
 * August it means, and this label is the reader's only statement of the period
 * once the report leaves the app. */
export function windowLabel(startMonth: string, endMonth: string): string {
  if (startMonth === endMonth) return monthLong(endMonth);
  const sameYear = startMonth.slice(0, 4) === endMonth.slice(0, 4);
  const start = sameYear ? monthShort(startMonth) : monthLong(startMonth);
  return `${start} – ${monthLong(endMonth)}`;
}

/** Runway in months, or "N/A" — which the engine returns whenever the division
 * has no meaning (not burning, or no cash left). Never rendered as 0. */
export function runwayLabel(months: string | null): string {
  return months === null ? "N/A" : `${Number(months).toFixed(1)} mo`;
}

/** One line of a "period before → period now → change" table. Expenses and
 * burn rising isn't good news, so `goodWhenUp` decides which direction reads
 * green rather than assuming up is always better. */
export function MovementRow({
  label,
  before,
  after,
  change,
  goodWhenUp = false,
}: {
  label: string;
  before: string;
  after: string;
  change: string;
  goodWhenUp?: boolean;
}) {
  const delta = Number(change);
  const accent =
    delta === 0
      ? "text-black/50 dark:text-white/50"
      : (delta > 0) === goodWhenUp
        ? "text-green-600 dark:text-green-500"
        : "text-red-600 dark:text-red-500";
  return (
    <tr className="border-b border-black/5 dark:border-white/5 last:border-0">
      <td className="p-3">{label}</td>
      <td className="p-3 text-right whitespace-nowrap font-mono text-black/60 dark:text-white/60">
        {formatINR(before)}
      </td>
      <td className="p-3 text-right whitespace-nowrap font-mono">
        {formatINR(after)}
      </td>
      <td className={`p-3 text-right whitespace-nowrap font-mono ${accent}`}>
        {signed(change)}
      </td>
    </tr>
  );
}

/** Where the money went, by category. Shares are of the line's own side of the
 * ledger (an expense as a % of all expenses); "Uncategorized" is a real line,
 * never dropped, so the lines add up to the totals printed above them. */
export function CategoryBreakdown({ lines }: { lines: CategoryLine[] }) {
  if (lines.length === 0) {
    return (
      <p className="rounded-xl border border-black/10 dark:border-white/15 p-6 text-center text-sm text-black/50 dark:text-white/50">
        No transactions in this period to break down.
      </p>
    );
  }
  return (
    <div className="overflow-x-auto rounded-xl border border-black/10 dark:border-white/15">
      <table className="w-full text-sm">
        <thead className="text-left text-black/50 dark:text-white/50">
          <tr className="border-b border-black/10 dark:border-white/10">
            <th className="p-3 font-medium">Category</th>
            <th className="p-3 font-medium">Share</th>
            <th className="p-3 font-medium text-right">Entries</th>
            <th className="p-3 font-medium text-right">Total</th>
          </tr>
        </thead>
        <tbody>
          {lines.map((line) => (
            <CategoryRow
              key={`${line.type}-${line.category_id ?? "none"}`}
              line={line}
            />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function CategoryRow({ line }: { line: CategoryLine }) {
  const share = line.share_pct === null ? null : Number(line.share_pct);
  return (
    <tr className="border-b border-black/5 dark:border-white/5 last:border-0">
      <td className="p-3">
        {line.name}
        <span className="ml-2 text-xs text-black/40 dark:text-white/40">
          {line.type === "income" ? "in" : "out"}
        </span>
      </td>
      <td className="p-3">
        <div className="flex items-center gap-2">
          <div className="h-1.5 w-24 shrink-0 rounded-full bg-black/10 dark:bg-white/10">
            <div
              className={`h-1.5 rounded-full ${
                line.type === "income"
                  ? "bg-green-600 dark:bg-green-500"
                  : "bg-black/50 dark:bg-white/50"
              }`}
              style={{ width: `${share ?? 0}%` }}
            />
          </div>
          <span className="text-xs text-black/50 dark:text-white/50">
            {share === null ? "—" : `${share.toFixed(1)}%`}
          </span>
        </div>
      </td>
      <td className="p-3 text-right text-black/60 dark:text-white/60">
        {line.transaction_count}
      </td>
      <td className="p-3 text-right whitespace-nowrap font-mono">
        {formatINR(line.total)}
      </td>
    </tr>
  );
}

/** Nothing to report on yet, and the one action that changes that. */
export function ReportEmptyState({
  title,
  body,
  href,
  cta,
}: {
  title: string;
  body: string;
  href: string;
  cta: string;
}) {
  return (
    <div className="rounded-xl border border-black/10 dark:border-white/15 p-8 text-center">
      <h2 className="text-lg font-semibold">{title}</h2>
      <p className="mx-auto mt-2 max-w-md text-sm text-black/60 dark:text-white/60">
        {body}
      </p>
      <Link
        href={href}
        className="mt-5 inline-block rounded-md bg-foreground text-background px-4 py-2 text-sm font-medium hover:opacity-90 transition-opacity"
      >
        {cta}
      </Link>
    </div>
  );
}
