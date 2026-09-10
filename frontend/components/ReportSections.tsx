/**
 * Pieces every report screen shares (Phase 8) — the category breakdown table
 * and the empty states.
 *
 * Extracted from the monthly report in 8.2 rather than copied: two reports
 * drawing the same breakdown differently would be two claims about one period,
 * which is the whole reason the KPI tiles are shared with the dashboard too.
 *
 * Display only. Every figure arrives already computed by the Financial Engine
 * (architecture §4.1) and is rendered through `lib/format.ts`, so a rupee reads
 * the same on every screen.
 */

import Link from "next/link";

import { type CategoryLine } from "@/lib/api";
import { formatINR } from "@/lib/format";

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
