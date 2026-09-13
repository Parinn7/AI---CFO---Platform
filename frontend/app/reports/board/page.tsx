/**
 * Board Report (Phase 8.2, FR-7.2). Auth-guarded.
 *
 * The monthly report answers "what happened in July". This answers "where is
 * this business heading", for a board member or investor who wasn't in the
 * building: a trailing quarter (or year) of KPIs beside the equal-length period
 * before it, the cash position at both ends, the month-by-month shape, the cost
 * structure, the spend being watched, and the plans that have been modelled.
 *
 * The screen computes nothing. Every figure comes from `GET /reports/board`,
 * whose two KPI blocks are real `kpi_snapshots` rows — the same rows the
 * dashboard's tiles and the AI CFO's context read. `KpiCards`, both dashboard
 * charts and the shared report sections are reused rather than reimplemented,
 * so a board pack and a dashboard can't draw one period two ways.
 *
 * "Download PDF" (8.4) exports the period currently on screen — the button
 * closes over the controls' state, so the file and the page can't describe
 * different windows.
 */

"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { NetCashFlowChart, RevenueExpenseChart } from "@/components/DashboardCharts";
import { DownloadReportButton } from "@/components/DownloadReportButton";
import { KpiCards } from "@/components/KpiCards";
import { ReportHeader } from "@/components/ReportHeader";
import {
  CategoryBreakdown,
  MovementRow,
  ReportEmptyState,
  runwayLabel as runway,
  signed,
  windowLabel,
} from "@/components/ReportSections";
import { StatCard } from "@/components/StatCard";
import { useAuth } from "@/contexts/AuthContext";
import {
  ApiError,
  detectAnomalies,
  downloadBoardReport,
  getBoardReport,
  getCashFlow,
  listCompanies,
  type BoardPeriod,
  type BoardReport,
  type Company,
  type ScenarioSummary,
} from "@/lib/api";
import { formatINR, monthLong } from "@/lib/format";

const PERIODS: { value: BoardPeriod; label: string }[] = [
  { value: "quarter", label: "Quarter" },
  { value: "year", label: "Year" },
];

export default function BoardReportPage() {
  const { user, token, loading: authLoading } = useAuth();
  const router = useRouter();

  const [company, setCompany] = useState<Company | null>(null);
  const [months, setMonths] = useState<string[]>([]);
  const [report, setReport] = useState<BoardReport | null>(null);
  const [period, setPeriod] = useState<BoardPeriod>("quarter");
  const [endMonth, setEndMonth] = useState<string | null>(null);
  const [hasData, setHasData] = useState(true);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false); // period/anchor switch in flight
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

      // Refresh anomaly flags first, as the dashboard does, so a pack opened
      // directly doesn't quote stale ones. Idempotent; non-fatal if it hiccups.
      try {
        await detectAnomalies(co.id, token);
      } catch {
        /* keep existing flags */
      }

      // The months with activity — the anchors worth offering.
      const cashFlow = await getCashFlow(co.id, token);
      setMonths(cashFlow.months.map((m) => m.month).reverse());

      const board = await getBoardReport(co.id, token);
      setReport(board);
      setEndMonth(board.current.end_month);
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

  async function refresh(nextPeriod: BoardPeriod, nextEndMonth: string | null) {
    if (!token || !company) return;
    setBusy(true);
    setError(null);
    try {
      const board = await getBoardReport(
        company.id,
        token,
        nextPeriod,
        nextEndMonth ?? undefined,
      );
      setReport(board);
      setPeriod(nextPeriod);
      setEndMonth(board.current.end_month);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't load that period.");
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

  const anomalyMonths = new Set(report?.watch_items.map((w) => w.month) ?? []);

  return (
    <main className="flex-1 w-full max-w-6xl mx-auto flex flex-col gap-8 p-8">
      <ReportHeader
        title="Board report"
        subtitle={
          report
            ? `${report.company.name} — ${windowLabel(
                report.current.start_month,
                report.current.end_month,
              )}`
            : company?.name ?? "The period's trajectory, for people outside the building."
        }
      />

      {error && <p className="text-sm text-red-500" role="alert">{error}</p>}

      {!company ? (
        <ReportEmptyState
          title="Set up your company first"
          body="A board report is about a company's trajectory, so we need a company profile before there's anything to report on."
          href="/company"
          cta="Company profile"
        />
      ) : !hasData ? (
        <ReportEmptyState
          title="No financial data to report on"
          body="Import a CSV/XLSX or add entries manually — a board pack is ready the moment there's a period of data behind it."
          href="/data"
          cta="Add data"
        />
      ) : report ? (
        <>
          {/* Period controls: how long a window, and which month it ends on. */}
          <div className="flex flex-wrap items-center gap-4">
            <div
              className="flex rounded-md border border-black/15 dark:border-white/20 p-0.5"
              role="group"
              aria-label="Reporting period"
            >
              {PERIODS.map((p) => (
                <button
                  key={p.value}
                  type="button"
                  onClick={() => refresh(p.value, endMonth)}
                  disabled={busy}
                  aria-pressed={period === p.value}
                  className={`rounded px-3 py-1.5 text-sm transition-colors disabled:opacity-50 ${
                    period === p.value
                      ? "bg-foreground text-background"
                      : "hover:bg-black/5 dark:hover:bg-white/10"
                  }`}
                >
                  {p.label}
                </button>
              ))}
            </div>

            <div className="flex items-center gap-2">
              <label
                htmlFor="board-end-month"
                className="text-sm text-black/50 dark:text-white/50"
              >
                Ending
              </label>
              <select
                id="board-end-month"
                value={report.current.end_month}
                onChange={(e) => refresh(period, e.target.value)}
                disabled={busy}
                className="rounded-md border border-black/15 dark:border-white/20 bg-transparent px-3 py-1.5 text-sm disabled:opacity-50"
              >
                {(months.includes(report.current.end_month)
                  ? months
                  : [report.current.end_month, ...months]
                ).map((m) => (
                  <option key={m} value={m} className="bg-background">
                    {monthLong(m)}
                  </option>
                ))}
              </select>
            </div>

            {busy && (
              <span className="text-xs text-black/40 dark:text-white/40">Updating…</span>
            )}
            <span className="text-xs text-black/40 dark:text-white/40">
              {report.current.period_start} – {report.current.period_end} ·{" "}
              {report.current.transaction_count} transaction
              {report.current.transaction_count === 1 ? "" : "s"}
            </span>
            {/* Exports the window currently on screen — the same period and
                end month the controls above are set to. */}
            <div className="ml-auto">
              <DownloadReportButton
                disabled={busy}
                download={() =>
                  downloadBoardReport(
                    company.id,
                    token!,
                    period,
                    report.current.end_month,
                  )
                }
              />
            </div>
          </div>

          {report.current.transaction_count === 0 && (
            <p className="rounded-xl border border-black/10 dark:border-white/15 px-4 py-3 text-sm text-black/60 dark:text-white/60">
              Nothing was recorded between {report.current.period_start} and{" "}
              {report.current.period_end}. The figures below are genuine zeros for
              the period, not a loading error.
            </p>
          )}

          {/* Where we stand. */}
          <section className="flex flex-col gap-3">
            <h2 className="text-sm font-medium text-black/70 dark:text-white/70">
              Where we stand
            </h2>
            <div className="grid gap-3 grid-cols-2 lg:grid-cols-4">
              <StatCard
                label="Revenue"
                value={formatINR(report.current.kpis.total_revenue)}
                hint={`Over ${report.num_months} months`}
              />
              <StatCard
                label="Expenses"
                value={formatINR(report.current.kpis.total_expenses)}
                hint={`Over ${report.num_months} months`}
              />
              <StatCard
                label="Net result"
                value={formatINR(report.current.kpis.net_cash_flow)}
                hint={
                  Number(report.current.kpis.net_cash_flow) >= 0
                    ? "The period generated cash"
                    : "The period consumed cash"
                }
                accent={
                  Number(report.current.kpis.net_cash_flow) >= 0 ? "good" : "bad"
                }
              />
              <StatCard
                label="Cash on hand"
                value={formatINR(report.cash.closing_cash)}
                hint={`Opened at ${formatINR(report.cash.opening_cash)} · ${signed(
                  report.cash.net_change,
                )} over the period`}
                accent={Number(report.cash.closing_cash) < 0 ? "bad" : "none"}
              />
            </div>
            <p className="text-xs text-black/40 dark:text-white/40">
              Cash is cumulative net cash flow from an opening balance of ₹0, so
              the movement above is exactly the period&apos;s net result.
            </p>
          </section>

          {/* The four KPIs, off the period's own snapshot. */}
          <section className="flex flex-col gap-3">
            <div>
              <h2 className="text-sm font-medium text-black/70 dark:text-white/70">
                Key metrics
              </h2>
              <p className="mt-0.5 text-xs text-black/50 dark:text-white/50">
                Measured over{" "}
                {windowLabel(
                  report.current.start_month,
                  report.current.end_month,
                )}
                . Burn rate is per month; growth is against the equal-length
                period before it.
              </p>
            </div>
            <KpiCards snap={report.current.kpis} />
          </section>

          {/* Trajectory: this period against the one before it. */}
          <section className="flex flex-col gap-3">
            <div>
              <h2 className="text-sm font-medium text-black/70 dark:text-white/70">
                Versus{" "}
                {windowLabel(
                  report.previous.start_month,
                  report.previous.end_month,
                )}
              </h2>
              {!report.previous.has_data && (
                <p className="mt-0.5 text-xs text-amber-600 dark:text-amber-500">
                  Nothing is recorded for that period, so these changes are
                  measured against zero — an absence of records, not a period of
                  no activity.
                </p>
              )}
            </div>
            <div className="overflow-x-auto rounded-xl border border-black/10 dark:border-white/15">
              <table className="w-full text-sm">
                <thead className="text-left text-black/50 dark:text-white/50">
                  <tr className="border-b border-black/10 dark:border-white/10">
                    <th className="p-3 font-medium"></th>
                    <th className="p-3 font-medium text-right">
                      {windowLabel(
                        report.previous.start_month,
                        report.previous.end_month,
                      )}
                    </th>
                    <th className="p-3 font-medium text-right">
                      {windowLabel(
                        report.current.start_month,
                        report.current.end_month,
                      )}
                    </th>
                    <th className="p-3 font-medium text-right">Change</th>
                  </tr>
                </thead>
                <tbody>
                  <MovementRow
                    label="Revenue"
                    before={report.previous.kpis.total_revenue}
                    after={report.current.kpis.total_revenue}
                    change={report.movement.revenue_change}
                    goodWhenUp
                  />
                  <MovementRow
                    label="Expenses"
                    before={report.previous.kpis.total_expenses}
                    after={report.current.kpis.total_expenses}
                    change={report.movement.expenses_change}
                  />
                  <MovementRow
                    label="Net cash flow"
                    before={report.previous.kpis.net_cash_flow}
                    after={report.current.kpis.net_cash_flow}
                    change={report.movement.net_change}
                    goodWhenUp
                  />
                  <MovementRow
                    label="Burn rate (per month)"
                    before={report.previous.kpis.burn_rate}
                    after={report.current.kpis.burn_rate}
                    change={report.movement.burn_rate_change}
                  />
                  <tr className="border-b border-black/5 dark:border-white/5 last:border-0">
                    <td className="p-3">Runway</td>
                    <td className="p-3 text-right whitespace-nowrap font-mono text-black/60 dark:text-white/60">
                      {runway(report.previous.kpis.runway_months)}
                    </td>
                    <td className="p-3 text-right whitespace-nowrap font-mono">
                      {runway(report.current.kpis.runway_months)}
                    </td>
                    <td className="p-3 text-right text-xs text-black/40 dark:text-white/40">
                      N/A while not burning cash
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </section>

          {/* The shape of the period, drawn by the dashboard's own charts. */}
          <section className="flex flex-col gap-3">
            <div>
              <h2 className="text-sm font-medium text-black/70 dark:text-white/70">
                The shape of the period
              </h2>
              <p className="mt-0.5 text-xs text-black/50 dark:text-white/50">
                Month by month — months with no activity are shown as zero, not
                skipped. Amber marks a month with flagged spend.
              </p>
            </div>
            <div className="grid gap-4 lg:grid-cols-2">
              <div className="rounded-xl border border-black/10 dark:border-white/15 p-4">
                <RevenueExpenseChart
                  months={report.monthly}
                  anomalyMonths={anomalyMonths}
                />
              </div>
              <div className="rounded-xl border border-black/10 dark:border-white/15 p-4">
                <NetCashFlowChart
                  months={report.monthly}
                  anomalyMonths={anomalyMonths}
                />
              </div>
            </div>
          </section>

          {/* Cost structure. */}
          <section className="flex flex-col gap-3">
            <div>
              <h2 className="text-sm font-medium text-black/70 dark:text-white/70">
                What the money goes on
              </h2>
              <p className="mt-0.5 text-xs text-black/50 dark:text-white/50">
                Each share is of its own side of the ledger — an expense as a
                percentage of all expenses over the period.
              </p>
            </div>
            <CategoryBreakdown lines={report.categories} />
          </section>

          {/* What we're watching. */}
          <section className="flex flex-col gap-3">
            <h2 className="text-sm font-medium text-black/70 dark:text-white/70">
              What we&apos;re watching
            </h2>
            {report.watch_items.length === 0 ? (
              <p className="rounded-xl border border-black/10 dark:border-white/15 p-6 text-center text-sm text-black/50 dark:text-white/50">
                No unusual spend was flagged in this period.
              </p>
            ) : (
              <div className="overflow-x-auto rounded-xl border border-amber-300/60 dark:border-amber-500/30">
                <table className="w-full text-sm">
                  <thead className="text-left text-black/50 dark:text-white/50">
                    <tr className="border-b border-black/10 dark:border-white/10">
                      <th className="p-3 font-medium">Month</th>
                      <th className="p-3 font-medium">Category</th>
                      <th className="p-3 font-medium text-right">Entries</th>
                      <th className="p-3 font-medium text-right">Flagged spend</th>
                    </tr>
                  </thead>
                  <tbody>
                    {report.watch_items.map((item) => (
                      <tr
                        key={`${item.month}-${item.category_name}`}
                        className="border-b border-black/5 dark:border-white/5 last:border-0"
                      >
                        <td className="p-3 whitespace-nowrap">
                          {monthLong(item.month)}
                        </td>
                        <td className="p-3">{item.category_name}</td>
                        <td className="p-3 text-right text-black/60 dark:text-white/60">
                          {item.transaction_count}
                        </td>
                        <td className="p-3 text-right whitespace-nowrap font-mono text-amber-700 dark:text-amber-400">
                          {formatINR(item.total)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <p className="text-xs text-black/40 dark:text-white/40">
              Flagged where a category&apos;s spend rose more than 50% above its
              trailing three-month average — a fixed rule, not a judgement.{" "}
              <Link href="/transactions" className="underline hover:no-underline">
                See the transactions behind it
              </Link>
              .
            </p>
          </section>

          {/* Plans that have been modelled. */}
          <section className="flex flex-col gap-3">
            <div>
              <h2 className="text-sm font-medium text-black/70 dark:text-white/70">
                Plans on the table
              </h2>
              <p className="mt-0.5 text-xs text-black/50 dark:text-white/50">
                Saved scenarios, shown as they were computed when they were saved
                — not re-run against today&apos;s numbers.
              </p>
            </div>
            {report.scenarios.length === 0 ? (
              <p className="rounded-xl border border-black/10 dark:border-white/15 p-6 text-center text-sm text-black/50 dark:text-white/50">
                No saved scenarios yet.{" "}
                <Link href="/scenarios" className="underline hover:no-underline">
                  Model one
                </Link>{" "}
                and it appears here.
              </p>
            ) : (
              <div className="grid gap-3 md:grid-cols-3">
                {report.scenarios.map((s) => (
                  <ScenarioCard key={s.id} scenario={s} />
                ))}
              </div>
            )}
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

function ScenarioCard({ scenario }: { scenario: ScenarioSummary }) {
  const net = Number(scenario.net_cash_flow_change);
  return (
    <div className="flex flex-col gap-2 rounded-xl border border-black/10 dark:border-white/15 p-4">
      <div>
        <p className="font-medium">{scenario.name}</p>
        <p className="mt-0.5 text-xs text-black/50 dark:text-white/50">
          Modelled over {scenario.period_start} – {scenario.period_end}
        </p>
      </div>
      <dl className="flex flex-col gap-1 text-sm">
        <div className="flex items-baseline justify-between gap-2">
          <dt className="text-black/55 dark:text-white/55">Net cash flow</dt>
          <dd
            className={`font-mono ${
              net >= 0
                ? "text-green-600 dark:text-green-500"
                : "text-red-600 dark:text-red-500"
            }`}
          >
            {signed(scenario.net_cash_flow_change)}
          </dd>
        </div>
        <div className="flex items-baseline justify-between gap-2">
          <dt className="text-black/55 dark:text-white/55">Runway</dt>
          <dd className="font-mono text-xs">
            {runway(scenario.baseline_runway_months)} →{" "}
            <span className="text-sm">
              {runway(scenario.scenario_runway_months)}
            </span>
          </dd>
        </div>
      </dl>
      <Link
        href="/scenarios"
        className="text-xs underline hover:no-underline text-black/60 dark:text-white/60"
      >
        Open in the simulator
      </Link>
    </div>
  );
}
