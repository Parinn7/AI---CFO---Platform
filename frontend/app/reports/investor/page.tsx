/**
 * Investor Readiness Summary (Phase 8.3, FR-7.3). Auth-guarded.
 *
 * The monthly report answers "what happened in July" and the board report
 * "where is this heading". This one answers the question a founder actually
 * loses sleep over: **would these numbers survive a first conversation with an
 * investor** — the metrics investors typically evaluate over a trailing year,
 * and a checklist of how this company reads against them.
 *
 * The screen computes and judges nothing. Every figure comes from
 * `GET /reports/investor`, whose KPI blocks are real `kpi_snapshots` rows, and
 * every verdict is a fixed threshold applied server-side in
 * `financial_engine/readiness.py`. Even the thresholds printed beside each check
 * are the ones the API applied — the page never keeps its own copy of a rule.
 * **No LLM writes or grades any part of this** (architecture §4.1).
 *
 * There is deliberately no overall score, only a weakest-link status: a single
 * grade would imply a precision this data can't support and invite reading it
 * as a valuation.
 *
 * PDF export is task 8.4; there is deliberately no export button yet.
 */

"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { NetCashFlowChart, RevenueExpenseChart } from "@/components/DashboardCharts";
import { ReportHeader } from "@/components/ReportHeader";
import {
  CategoryBreakdown,
  MovementRow,
  ReportEmptyState,
  runwayLabel,
  signed,
  windowLabel,
} from "@/components/ReportSections";
import { StatCard } from "@/components/StatCard";
import { useAuth } from "@/contexts/AuthContext";
import {
  ApiError,
  getCashFlow,
  getInvestorSummary,
  listCompanies,
  type Company,
  type InvestorSummary,
  type ReadinessCheck,
  type ReadinessStatus,
} from "@/lib/api";
import { formatINR, monthLong } from "@/lib/format";

/** How each verdict reads on the page. The wording is the honest one: an
 * unmeasurable check says so rather than borrowing the look of a pass. */
const STATUS: Record<
  ReadinessStatus,
  { label: string; dot: string; text: string; ring: string }
> = {
  ready: {
    label: "Ready",
    dot: "bg-green-600 dark:bg-green-500",
    text: "text-green-700 dark:text-green-500",
    ring: "border-green-600/30 dark:border-green-500/30",
  },
  attention: {
    label: "Needs attention",
    dot: "bg-amber-500",
    text: "text-amber-700 dark:text-amber-500",
    ring: "border-amber-500/40 dark:border-amber-500/30",
  },
  gap: {
    label: "Gap",
    dot: "bg-red-600 dark:bg-red-500",
    text: "text-red-700 dark:text-red-500",
    ring: "border-red-600/30 dark:border-red-500/30",
  },
  not_applicable: {
    label: "Not measurable",
    dot: "bg-black/25 dark:bg-white/25",
    text: "text-black/50 dark:text-white/50",
    ring: "border-black/10 dark:border-white/15",
  },
};

/** What the weakest link means, said in a sentence rather than scored. */
const OVERALL: Record<ReadinessStatus, string> = {
  ready: "Every check clears its threshold on the data recorded so far.",
  attention:
    "Nothing here is an outright gap, but at least one metric sits below the level investors usually look for — worth a prepared answer.",
  gap: "At least one metric falls short of the level investors usually look for. The weakest check is what a conversation will open on.",
  not_applicable:
    "There isn't enough recorded data yet to measure these checks against anything.",
};

/** A check's measured value in its own unit — "12.0 mo", "15%", or "—" when the
 * figure is undefined (in which case the check's own sentence explains why). */
function checkValue(check: ReadinessCheck): string {
  if (check.value === null) return "—";
  return check.unit === "months"
    ? `${Number(check.value).toFixed(1)} mo`
    : `${Number(check.value).toFixed(1)}%`;
}

/** The rule that was applied, stated from the thresholds the API sent. */
function thresholdLabel(check: ReadinessCheck): string {
  const unit = check.unit === "months" ? " months" : "%";
  return `Ready at ${Number(check.ready_at)}${unit} or above · attention down to ${Number(
    check.attention_at,
  )}${unit}`;
}

function pct(value: string | null): string {
  return value === null ? "N/A" : `${Number(value).toFixed(1)}%`;
}

export default function InvestorReadinessPage() {
  const { user, token, loading: authLoading } = useAuth();
  const router = useRouter();

  const [company, setCompany] = useState<Company | null>(null);
  const [months, setMonths] = useState<string[]>([]);
  const [report, setReport] = useState<InvestorSummary | null>(null);
  const [hasData, setHasData] = useState(true);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false); // anchor switch in flight
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

      // The months with activity — the anchors worth offering.
      const cashFlow = await getCashFlow(co.id, token);
      setMonths(cashFlow.months.map((m) => m.month).reverse());

      setReport(await getInvestorSummary(co.id, token));
      setHasData(true);
    } catch (err) {
      // 404 here is "nothing recorded yet", not a failure.
      if (err instanceof ApiError && err.status === 404) {
        setHasData(false);
      } else {
        setError(err instanceof ApiError ? err.message : "Couldn't load the summary.");
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

  async function refresh(nextEndMonth: string) {
    if (!token || !company) return;
    setBusy(true);
    setError(null);
    try {
      setReport(await getInvestorSummary(company.id, token, nextEndMonth));
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

  return (
    <main className="flex-1 w-full max-w-6xl mx-auto flex flex-col gap-8 p-8">
      <ReportHeader
        title="Investor readiness"
        subtitle={
          report
            ? `${report.company.name} — ${windowLabel(
                report.window.start_month,
                report.window.end_month,
              )}`
            : company?.name ??
              "The metrics investors evaluate, and how your numbers read against them."
        }
      />

      {error && <p className="text-sm text-red-500" role="alert">{error}</p>}

      {!company ? (
        <ReportEmptyState
          title="Set up your company first"
          body="An investor readiness summary is about a company's metrics, so we need a company profile before there's anything to assess."
          href="/company"
          cta="Company profile"
        />
      ) : !hasData ? (
        <ReportEmptyState
          title="No financial data to assess"
          body="Import a CSV/XLSX or add entries manually — the summary is ready the moment there are recorded months behind it."
          href="/data"
          cta="Add data"
        />
      ) : report ? (
        <>
          {/* Which year the summary is measured over. */}
          <div className="flex flex-wrap items-center gap-4">
            <div className="flex items-center gap-2">
              <label
                htmlFor="investor-end-month"
                className="text-sm text-black/50 dark:text-white/50"
              >
                Year ending
              </label>
              <select
                id="investor-end-month"
                value={report.window.end_month}
                onChange={(e) => refresh(e.target.value)}
                disabled={busy}
                className="rounded-md border border-black/15 dark:border-white/20 bg-transparent px-3 py-1.5 text-sm disabled:opacity-50"
              >
                {(months.includes(report.window.end_month)
                  ? months
                  : [report.window.end_month, ...months]
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
              {report.window.period_start} – {report.window.period_end} ·{" "}
              {report.months_of_history} month
              {report.months_of_history === 1 ? "" : "s"} of history on record
            </span>
          </div>

          {/* The weakest link, said plainly. Deliberately not a score. */}
          <section
            className={`rounded-xl border p-5 ${STATUS[report.overall_status].ring}`}
          >
            <div className="flex items-center gap-2.5">
              <span
                className={`h-2.5 w-2.5 shrink-0 rounded-full ${
                  STATUS[report.overall_status].dot
                }`}
                aria-hidden
              />
              <h2 className="text-lg font-semibold">
                {STATUS[report.overall_status].label}
              </h2>
            </div>
            <p className="mt-2 max-w-3xl text-sm text-black/65 dark:text-white/65">
              {OVERALL[report.overall_status]}
            </p>
            <p className="mt-2 text-xs text-black/40 dark:text-white/40">
              This is the weakest of the checks below, not a score — a strong
              margin doesn&apos;t offset a short runway, so nothing here is
              averaged away.
            </p>
          </section>

          {/* The five numbers asked for on a first call. */}
          <section className="flex flex-col gap-3">
            <div>
              <h2 className="text-sm font-medium text-black/70 dark:text-white/70">
                The headline numbers
              </h2>
              <p className="mt-0.5 text-xs text-black/50 dark:text-white/50">
                Measured over{" "}
                {windowLabel(report.window.start_month, report.window.end_month)}
                , except the run-rate, which is {monthLong(report.run_rate.month)}{" "}
                annualised.
              </p>
            </div>
            <div className="grid gap-3 grid-cols-2 lg:grid-cols-3">
              <StatCard
                label="Revenue run-rate"
                value={formatINR(report.run_rate.annualised)}
                hint={`${formatINR(report.run_rate.monthly)} in ${monthLong(
                  report.run_rate.month,
                )} × 12`}
              />
              <StatCard
                label="Revenue growth"
                value={pct(report.window.kpis.revenue_growth_pct)}
                hint={`Against ${windowLabel(
                  report.previous.start_month,
                  report.previous.end_month,
                )}`}
                accent={
                  report.window.kpis.revenue_growth_pct === null
                    ? "none"
                    : Number(report.window.kpis.revenue_growth_pct) >= 0
                      ? "good"
                      : "bad"
                }
              />
              <StatCard
                label="Operating margin"
                value={pct(report.window.kpis.operating_margin_pct)}
                hint="Revenue left after all recorded expenses"
                accent={
                  report.window.kpis.operating_margin_pct === null
                    ? "none"
                    : Number(report.window.kpis.operating_margin_pct) >= 0
                      ? "good"
                      : "bad"
                }
              />
              <StatCard
                label="Runway"
                value={runwayLabel(report.window.kpis.runway_months)}
                hint={`Burn ${formatINR(report.window.kpis.burn_rate)}/mo`}
                accent={
                  report.window.kpis.runway_months === null
                    ? "none"
                    : Number(report.window.kpis.runway_months) < 6
                      ? "bad"
                      : "none"
                }
              />
              <StatCard
                label="Cash on hand"
                value={formatINR(report.cash.closing_cash)}
                hint={`${signed(report.cash.net_change)} over the year`}
                accent={Number(report.cash.closing_cash) < 0 ? "bad" : "none"}
              />
              <StatCard
                label="Burn multiple"
                value={
                  report.burn_multiple === null
                    ? "N/A"
                    : `${Number(report.burn_multiple).toFixed(2)}×`
                }
                hint={
                  report.burn_multiple === null
                    ? "Only meaningful while burning cash to grow revenue"
                    : "Cash burned per ₹1 of new revenue"
                }
              />
            </div>
            <p className="text-xs text-black/40 dark:text-white/40">
              Gross and operating margin are the same figure here — the category
              set has no COGS/opex split, a deliberate simplification recorded in
              the SRS rather than a bug.
            </p>
          </section>

          {/* The checklist — the distinctive half of this report. */}
          <section className="flex flex-col gap-3">
            <div>
              <h2 className="text-sm font-medium text-black/70 dark:text-white/70">
                What an investor will check
              </h2>
              <p className="mt-0.5 text-xs text-black/50 dark:text-white/50">
                Each line is a fixed threshold applied to your recorded figures —
                a rule, not a judgement, and not an opinion from the AI
                assistant.
              </p>
            </div>
            <ul className="flex flex-col gap-2">
              {report.checks.map((check) => (
                <li
                  key={check.key}
                  className={`flex flex-wrap items-start gap-x-4 gap-y-1 rounded-xl border p-4 ${
                    STATUS[check.status].ring
                  }`}
                >
                  <span
                    className={`mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full ${
                      STATUS[check.status].dot
                    }`}
                    aria-hidden
                  />
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-baseline gap-x-3">
                      <p className="font-medium">{check.label}</p>
                      <p className={`text-xs font-medium ${STATUS[check.status].text}`}>
                        {STATUS[check.status].label}
                      </p>
                    </div>
                    <p className="mt-1 text-sm text-black/65 dark:text-white/65">
                      {check.detail}
                    </p>
                    <p className="mt-1 text-xs text-black/40 dark:text-white/40">
                      {thresholdLabel(check)}
                    </p>
                  </div>
                  <p className="whitespace-nowrap font-mono text-lg">
                    {checkValue(check)}
                  </p>
                </li>
              ))}
            </ul>
            <p className="text-xs text-black/40 dark:text-white/40">
              The thresholds are conventional early-stage benchmarks, shown so you
              can see what each verdict was measured against. They are not a claim
              about what any particular investor requires.
            </p>
          </section>

          {/* The year against the year before it. */}
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
                  Nothing is recorded for that year, so these changes are measured
                  against zero — an absence of records, not a year of no activity.
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
                        report.window.start_month,
                        report.window.end_month,
                      )}
                    </th>
                    <th className="p-3 font-medium text-right">Change</th>
                  </tr>
                </thead>
                <tbody>
                  <MovementRow
                    label="Revenue"
                    before={report.previous.kpis.total_revenue}
                    after={report.window.kpis.total_revenue}
                    change={report.movement.revenue_change}
                    goodWhenUp
                  />
                  <MovementRow
                    label="Expenses"
                    before={report.previous.kpis.total_expenses}
                    after={report.window.kpis.total_expenses}
                    change={report.movement.expenses_change}
                  />
                  <MovementRow
                    label="Net cash flow"
                    before={report.previous.kpis.net_cash_flow}
                    after={report.window.kpis.net_cash_flow}
                    change={report.movement.net_change}
                    goodWhenUp
                  />
                  <MovementRow
                    label="Burn rate (per month)"
                    before={report.previous.kpis.burn_rate}
                    after={report.window.kpis.burn_rate}
                    change={report.movement.burn_rate_change}
                  />
                </tbody>
              </table>
            </div>
          </section>

          {/* The shape of the year, drawn by the dashboard's own charts. */}
          <section className="flex flex-col gap-3">
            <div>
              <h2 className="text-sm font-medium text-black/70 dark:text-white/70">
                The shape of the year
              </h2>
              <p className="mt-0.5 text-xs text-black/50 dark:text-white/50">
                Month by month — months with no activity are shown as zero, not
                skipped. Revenue was recorded in {report.months_with_revenue} of
                the {report.months_of_history} months on record.
              </p>
            </div>
            <div className="grid gap-4 lg:grid-cols-2">
              <div className="rounded-xl border border-black/10 dark:border-white/15 p-4">
                <RevenueExpenseChart months={report.monthly} />
              </div>
              <div className="rounded-xl border border-black/10 dark:border-white/15 p-4">
                <NetCashFlowChart months={report.monthly} />
              </div>
            </div>
          </section>

          {/* Cost structure — the follow-up question after the headline numbers. */}
          <section className="flex flex-col gap-3">
            <div>
              <h2 className="text-sm font-medium text-black/70 dark:text-white/70">
                Where the money goes
              </h2>
              <p className="mt-0.5 text-xs text-black/50 dark:text-white/50">
                Each share is of its own side of the ledger. Spend sitting under
                &ldquo;Uncategorized&rdquo; is spend you can&apos;t explain in the
                room —{" "}
                <Link href="/transactions" className="underline hover:no-underline">
                  categorize it
                </Link>{" "}
                and this summary updates with it.
              </p>
            </div>
            <CategoryBreakdown lines={report.categories} />
          </section>

          <p className="text-xs text-black/40 dark:text-white/40">
            Generated {new Date(report.generated_at).toLocaleString()} from your
            recorded transactions. Every figure is computed by the platform&apos;s
            financial engine and every verdict is a fixed threshold applied to it —
            no part of this summary is written, calculated or judged by the AI
            assistant. It is a readiness check against common benchmarks, not a
            valuation and not investment advice.
          </p>
        </>
      ) : null}
    </main>
  );
}
