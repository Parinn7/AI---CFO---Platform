/**
 * Monthly Financial Report (Phase 8.1, FR-7.1). Auth-guarded.
 *
 * One calendar month, on one page: what came in, what went out, what that left
 * in the bank, the four KPIs, where the money actually went, how the month
 * moved against the one before it, a six-month trend, and anything flagged.
 *
 * The screen computes nothing. Every figure is rendered straight from
 * `GET /reports/monthly`, whose KPI block is the same `kpi_snapshots` row the
 * dashboard's tiles read — which is why `KpiCards` and `RevenueExpenseChart`
 * are reused here rather than reimplemented: a report and a dashboard that draw
 * the same month differently are two claims about one period.
 *
 * PDF export is task 8.4, so there is no export button yet — a dead one would
 * be worse than none.
 */

"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { RevenueExpenseChart } from "@/components/DashboardCharts";
import { KpiCards } from "@/components/KpiCards";
import { StatCard } from "@/components/StatCard";
import { useAuth } from "@/contexts/AuthContext";
import {
  ApiError,
  detectAnomalies,
  getCashFlow,
  getMonthlyReport,
  listCompanies,
  type CategoryLine,
  type Company,
  type MonthlyReport,
} from "@/lib/api";
import { formatINR, monthLong } from "@/lib/format";

/** A signed change, e.g. "+₹1,00,000.00" / "-₹20,000.00". */
function signed(value: string): string {
  const n = Number(value);
  return `${n >= 0 ? "+" : "-"}${formatINR(Math.abs(n))}`;
}

export default function ReportsPage() {
  const { user, token, loading: authLoading, logout } = useAuth();
  const router = useRouter();

  const [company, setCompany] = useState<Company | null>(null);
  const [months, setMonths] = useState<string[]>([]);
  const [report, setReport] = useState<MonthlyReport | null>(null);
  const [hasData, setHasData] = useState(true);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false); // month switch in flight
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!authLoading && !user) router.replace("/login");
  }, [authLoading, user, router]);

  const load = useCallback(async () => {
    if (!token) return;
    try {
      const companies = await listCompanies(token);
      setError(null);
      const co = companies[0] ?? null;
      setCompany(co);
      if (!co) {
        setLoading(false);
        return;
      }

      // Refresh anomaly flags first, as the dashboard does, so a report opened
      // directly doesn't quote stale ones. Idempotent; non-fatal if it hiccups.
      try {
        await detectAnomalies(co.id, token);
      } catch {
        /* keep existing flags */
      }

      // Months with activity, newest first — the report can be asked for any
      // month, but these are the ones worth offering.
      const cashFlow = await getCashFlow(co.id, token);
      setMonths(cashFlow.months.map((m) => m.month).reverse());

      setReport(await getMonthlyReport(co.id, token));
      setHasData(true);
    } catch (err) {
      // 404 here is "nothing recorded yet", not a failure.
      if (err instanceof ApiError && err.status === 404) {
        setHasData(false);
      } else {
        setError(err instanceof ApiError ? err.message : "Couldn't load the report.");
      }
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    // Fetch-on-mount; load() only setState()s after awaited requests.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (token) load();
  }, [token, load]);

  async function selectMonth(month: string) {
    if (!token || !company || month === report?.month) return;
    setBusy(true);
    setError(null);
    try {
      setReport(await getMonthlyReport(company.id, token, month));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't load that month.");
    } finally {
      setBusy(false);
    }
  }

  if (authLoading || !user || loading) {
    return (
      <main className="flex-1 flex items-center justify-center p-8">
        <p className="text-sm text-black/50 dark:text-white/50">Loading…</p>
      </main>
    );
  }

  return (
    <main className="flex-1 w-full max-w-6xl mx-auto flex flex-col gap-8 p-8">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">Monthly report</h1>
          <p className="mt-1 text-sm text-black/60 dark:text-white/60">
            {report
              ? `${report.company.name} — ${monthLong(report.month)}`
              : company?.name ?? "One month of your finances, in full."}
          </p>
        </div>
        <nav className="flex flex-wrap items-center gap-3 text-sm">
          <Link href="/dashboard" className="underline hover:no-underline text-black/60 dark:text-white/60">
            Dashboard
          </Link>
          <Link href="/chat" className="underline hover:no-underline text-black/60 dark:text-white/60">
            AI CFO
          </Link>
          <Link href="/scenarios" className="underline hover:no-underline text-black/60 dark:text-white/60">
            Scenarios
          </Link>
          <Link href="/transactions" className="underline hover:no-underline text-black/60 dark:text-white/60">
            Transactions
          </Link>
          <button type="button" onClick={logout}
            className="rounded-md border border-black/15 dark:border-white/20 px-3 py-1.5 hover:bg-black/5 dark:hover:bg-white/10 transition-colors">
            Log out
          </button>
        </nav>
      </header>

      {error && <p className="text-sm text-red-500" role="alert">{error}</p>}

      {!company ? (
        <EmptyState
          title="Set up your company first"
          body="A report is about a company's month, so we need a company profile before there's anything to report on."
          href="/company"
          cta="Company profile"
        />
      ) : !hasData ? (
        <EmptyState
          title="No financial data to report on"
          body="Import a CSV/XLSX or add entries manually — your first monthly report is ready the moment there's a month of data."
          href="/data"
          cta="Add data"
        />
      ) : report ? (
        <>
          {/* Month picker — the months that actually have activity. */}
          <div className="flex flex-wrap items-center gap-3">
            <label htmlFor="report-month" className="text-sm text-black/50 dark:text-white/50">
              Month
            </label>
            <select
              id="report-month"
              value={report.month}
              onChange={(e) => selectMonth(e.target.value)}
              disabled={busy}
              className="rounded-md border border-black/15 dark:border-white/20 bg-transparent px-3 py-1.5 text-sm disabled:opacity-50"
            >
              {(months.includes(report.month) ? months : [report.month, ...months]).map(
                (m) => (
                  <option key={m} value={m} className="bg-background">
                    {monthLong(m)}
                  </option>
                ),
              )}
            </select>
            {busy && <span className="text-xs text-black/40 dark:text-white/40">Updating…</span>}
            <span className="text-xs text-black/40 dark:text-white/40">
              {report.period_start} – {report.period_end} ·{" "}
              {report.transaction_count} transaction
              {report.transaction_count === 1 ? "" : "s"}
            </span>
          </div>

          {report.transaction_count === 0 && (
            <p className="rounded-xl border border-black/10 dark:border-white/15 px-4 py-3 text-sm text-black/60 dark:text-white/60">
              Nothing was recorded in {monthLong(report.month)}. The figures below
              are genuine zeros for the month, not a loading error — ratios that
              need revenue to be defined are shown as “—”.
            </p>
          )}

          {/* Headline: revenue, expenses, cash flow (FR-7.1). */}
          <section className="flex flex-col gap-3">
            <h2 className="text-sm font-medium text-black/70 dark:text-white/70">
              The month at a glance
            </h2>
            <div className="grid gap-3 grid-cols-2 lg:grid-cols-4">
              <StatCard
                label="Revenue"
                value={formatINR(report.kpis.total_revenue)}
                hint={`${report.income_count} income entr${report.income_count === 1 ? "y" : "ies"}`}
              />
              <StatCard
                label="Expenses"
                value={formatINR(report.kpis.total_expenses)}
                hint={`${report.expense_count} expense entr${report.expense_count === 1 ? "y" : "ies"}`}
              />
              <StatCard
                label="Net cash flow"
                value={formatINR(report.kpis.net_cash_flow)}
                hint={Number(report.kpis.net_cash_flow) >= 0 ? "The month generated cash" : "The month consumed cash"}
                accent={Number(report.kpis.net_cash_flow) >= 0 ? "good" : "bad"}
              />
              <StatCard
                label="Cash on hand"
                value={formatINR(report.closing_cash)}
                hint={`At ${report.period_end}, from an opening balance of ₹0`}
                accent={Number(report.closing_cash) < 0 ? "bad" : "none"}
              />
            </div>
          </section>

          {/* KPIs — the same tiles, off the same snapshot, as the dashboard. */}
          <section className="flex flex-col gap-3">
            <div>
              <h2 className="text-sm font-medium text-black/70 dark:text-white/70">
                Key metrics
              </h2>
              <p className="mt-0.5 text-xs text-black/50 dark:text-white/50">
                Measured over {monthLong(report.month)} alone — growth is against{" "}
                {monthLong(report.comparison.month)}.
              </p>
            </div>
            <KpiCards snap={report.kpis} />
          </section>

          {/* Where the money went. */}
          <section className="flex flex-col gap-3">
            <div>
              <h2 className="text-sm font-medium text-black/70 dark:text-white/70">
                Where the money went
              </h2>
              <p className="mt-0.5 text-xs text-black/50 dark:text-white/50">
                Each share is of its own side of the ledger — an expense as a
                percentage of all expenses.
              </p>
            </div>
            {report.categories.length === 0 ? (
              <p className="rounded-xl border border-black/10 dark:border-white/15 p-6 text-center text-sm text-black/50 dark:text-white/50">
                No transactions in this month to break down.
              </p>
            ) : (
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
                    {report.categories.map((line) => (
                      <CategoryRow key={`${line.type}-${line.category_id ?? "none"}`} line={line} />
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          {/* Movement against the previous month. */}
          <section className="flex flex-col gap-3">
            <div>
              <h2 className="text-sm font-medium text-black/70 dark:text-white/70">
                Versus {monthLong(report.comparison.month)}
              </h2>
              {!report.comparison.has_data && (
                <p className="mt-0.5 text-xs text-amber-600 dark:text-amber-500">
                  Nothing is recorded for {monthLong(report.comparison.month)}, so
                  these changes are measured against zero — an absence of records,
                  not a month of no activity.
                </p>
              )}
            </div>
            <div className="overflow-x-auto rounded-xl border border-black/10 dark:border-white/15">
              <table className="w-full text-sm">
                <thead className="text-left text-black/50 dark:text-white/50">
                  <tr className="border-b border-black/10 dark:border-white/10">
                    <th className="p-3 font-medium"></th>
                    <th className="p-3 font-medium text-right">{monthLong(report.comparison.month)}</th>
                    <th className="p-3 font-medium text-right">{monthLong(report.month)}</th>
                    <th className="p-3 font-medium text-right">Change</th>
                  </tr>
                </thead>
                <tbody>
                  <ComparisonRow
                    label="Revenue"
                    before={report.comparison.total_revenue}
                    after={report.kpis.total_revenue}
                    change={report.comparison.revenue_change}
                    goodWhenUp
                  />
                  <ComparisonRow
                    label="Expenses"
                    before={report.comparison.total_expenses}
                    after={report.kpis.total_expenses}
                    change={report.comparison.expenses_change}
                  />
                  <ComparisonRow
                    label="Net cash flow"
                    before={report.comparison.net_cash_flow}
                    after={report.kpis.net_cash_flow}
                    change={report.comparison.net_change}
                    goodWhenUp
                  />
                </tbody>
              </table>
            </div>
          </section>

          {/* Six-month trend, drawn by the dashboard's own chart. */}
          <section className="flex flex-col gap-3">
            <div>
              <h2 className="text-sm font-medium text-black/70 dark:text-white/70">
                Recent trend
              </h2>
              <p className="mt-0.5 text-xs text-black/50 dark:text-white/50">
                The six months ending {monthLong(report.month)} — months with no
                activity are shown as zero, not skipped.
              </p>
            </div>
            <div className="rounded-xl border border-black/10 dark:border-white/15 p-4">
              <RevenueExpenseChart
                months={report.trend}
                anomalyMonths={new Set(report.anomalies.map((a) => a.date.slice(0, 7)))}
              />
            </div>
          </section>

          {/* What needs attention. */}
          <section className="flex flex-col gap-3">
            <h2 className="text-sm font-medium text-black/70 dark:text-white/70">
              Needs attention
            </h2>
            {report.anomalies.length === 0 ? (
              <p className="rounded-xl border border-black/10 dark:border-white/15 p-6 text-center text-sm text-black/50 dark:text-white/50">
                No unusual expenses were flagged in {monthLong(report.month)}.
              </p>
            ) : (
              <div className="overflow-x-auto rounded-xl border border-amber-300/60 dark:border-amber-500/30">
                <table className="w-full text-sm">
                  <thead className="text-left text-black/50 dark:text-white/50">
                    <tr className="border-b border-black/10 dark:border-white/10">
                      <th className="p-3 font-medium">Date</th>
                      <th className="p-3 font-medium">Description</th>
                      <th className="p-3 font-medium">Category</th>
                      <th className="p-3 font-medium text-right">Amount</th>
                    </tr>
                  </thead>
                  <tbody>
                    {report.anomalies.map((a) => (
                      <tr key={a.id} className="border-b border-black/5 dark:border-white/5 last:border-0">
                        <td className="p-3 whitespace-nowrap">{a.date}</td>
                        <td className="p-3">{a.description ?? "—"}</td>
                        <td className="p-3 text-black/60 dark:text-white/60">{a.category_name}</td>
                        <td className="p-3 text-right whitespace-nowrap font-mono text-amber-700 dark:text-amber-400">
                          {formatINR(a.amount)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <p className="text-xs text-black/40 dark:text-white/40">
              Flagged where a category&apos;s spend rose more than 50% above its
              trailing three-month average — a fixed rule, not a judgement.
            </p>
          </section>

          <p className="text-xs text-black/40 dark:text-white/40">
            Generated {new Date(report.generated_at).toLocaleString()} from your
            recorded transactions. Every figure is computed by the platform&apos;s
            financial engine — no part of this report is written or calculated by
            the AI assistant.
          </p>
        </>
      ) : null}
    </main>
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
                line.type === "income" ? "bg-green-600 dark:bg-green-500" : "bg-black/50 dark:bg-white/50"
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

function ComparisonRow({
  label, before, after, change, goodWhenUp = false,
}: {
  label: string;
  before: string;
  after: string;
  change: string;
  goodWhenUp?: boolean;
}) {
  const delta = Number(change);
  // Expenses rising isn't good news, so "up" only reads green where it is.
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
      <td className="p-3 text-right whitespace-nowrap font-mono">{formatINR(after)}</td>
      <td className={`p-3 text-right whitespace-nowrap font-mono ${accent}`}>
        {signed(change)}
      </td>
    </tr>
  );
}

function EmptyState({
  title, body, href, cta,
}: { title: string; body: string; href: string; cta: string }) {
  return (
    <div className="rounded-xl border border-black/10 dark:border-white/15 p-8 text-center">
      <h2 className="text-lg font-semibold">{title}</h2>
      <p className="mx-auto mt-2 max-w-md text-sm text-black/60 dark:text-white/60">{body}</p>
      <Link href={href}
        className="mt-5 inline-block rounded-md bg-foreground text-background px-4 py-2 text-sm font-medium hover:opacity-90 transition-opacity">
        {cta}
      </Link>
    </div>
  );
}
