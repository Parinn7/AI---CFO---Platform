/**
 * Overview dashboard (Phase 5.1 / 5.2, FR-8.1 / FR-8.2). Auth-guarded. The first
 * UI consumer of the whole Financial Engine: KPI cards (burn/runway/margins/growth
 * from a kpi_snapshot), a revenue/expenses + net-cash-flow trend (FR-4.6), and
 * recent activity with anomaly flags (FR-3.6 / FR-8.3). All numbers are computed
 * deterministically by the backend — the UI only displays them.
 *
 * Date-range filtering (5.2, FR-8.2): a period selector (3M / 6M / 12M / All,
 * default 12M, anchored to the latest month of data) re-scopes the whole view —
 * the charts, the KPI snapshot period, and the period totals all follow it. KPI
 * cards use get-or-create: reuse a stored snapshot for the selected period,
 * generating one only if missing; "Refresh KPIs" regenerates it.
 */

"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { NetCashFlowChart, RevenueExpenseChart } from "@/components/DashboardCharts";
import { StatCard } from "@/components/StatCard";
import { useAuth } from "@/contexts/AuthContext";
import {
  ApiError,
  generateKpiSnapshot,
  getHistory,
  listCategories,
  listCompanies,
  listKpiSnapshots,
  listTransactions,
  type Category,
  type Company,
  type HistoryResponse,
  type KpiSnapshot,
  type Transaction,
} from "@/lib/api";
import { addMonths, formatINR, lastDayOfMonth, monthLong, monthSpan } from "@/lib/format";

const RECENT_LIMIT = 8;
const RANGES: [RangeId, string][] = [
  ["3", "3M"],
  ["6", "6M"],
  ["12", "12M"],
  ["all", "All"],
];

type RangeId = "3" | "6" | "12" | "all";

function monthsForRange(
  rangeId: RangeId,
  endMonth: string,
  earliestMonth: string | null,
): number {
  if (rangeId === "all") {
    const span = earliestMonth ? monthSpan(earliestMonth, endMonth) : 12;
    return Math.min(60, Math.max(1, span));
  }
  return Number(rangeId);
}

export default function DashboardPage() {
  const { user, token, loading: authLoading, logout } = useAuth();
  const router = useRouter();

  const [company, setCompany] = useState<Company | null>(null);
  const [history, setHistory] = useState<HistoryResponse | null>(null);
  const [snapshot, setSnapshot] = useState<KpiSnapshot | null>(null);
  const [txns, setTxns] = useState<Transaction[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [endMonth, setEndMonth] = useState<string | null>(null);
  const [earliestMonth, setEarliestMonth] = useState<string | null>(null);
  const [rangeId, setRangeId] = useState<RangeId>("12");
  const [hasData, setHasData] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false); // range switch in flight
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!authLoading && !user) router.replace("/login");
  }, [authLoading, user, router]);

  // Get-or-create the KPI snapshot for the [months back → endMonth] window.
  const snapshotForRange = useCallback(
    async (companyId: string, end: string, months: number, force: boolean) => {
      const periodStart = `${addMonths(end, -(months - 1))}-01`;
      const periodEnd = lastDayOfMonth(end);
      if (!force) {
        const existing = (await listKpiSnapshots(companyId, token!)).find(
          (s) => s.period_start === periodStart && s.period_end === periodEnd,
        );
        if (existing) return existing;
      }
      return generateKpiSnapshot(
        { company_id: companyId, period_start: periodStart, period_end: periodEnd },
        token!,
      );
    },
    [token],
  );

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

      const [hist, cats, allTxns] = await Promise.all([
        getHistory(co.id, token, 12),
        listCategories(co.id, token),
        listTransactions(co.id, token),
      ]);
      setCategories(cats);
      setTxns(allTxns);
      const present = allTxns.length > 0;
      setHasData(present);

      if (present) {
        const em = hist.end_month;
        // listTransactions is newest-first, so the last row is the earliest.
        const earliest = allTxns[allTxns.length - 1].date.slice(0, 7);
        setEndMonth(em);
        setEarliestMonth(earliest);
        setRangeId("12");
        setHistory(hist); // default 12-month window (already fetched)
        setSnapshot(await snapshotForRange(co.id, em, 12, false));
      } else {
        setSnapshot(null);
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't load the dashboard.");
    } finally {
      setLoading(false);
    }
  }, [token, snapshotForRange]);

  useEffect(() => {
    // Fetch-on-mount; load() only setState()s after awaited requests.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (token) load();
  }, [token, load]);

  async function applyRange(next: RangeId) {
    if (!token || !company || !endMonth || next === rangeId) return;
    setBusy(true);
    setError(null);
    try {
      const months = monthsForRange(next, endMonth, earliestMonth);
      const [hist, snap] = await Promise.all([
        getHistory(company.id, token, months, endMonth),
        snapshotForRange(company.id, endMonth, months, false),
      ]);
      setHistory(hist);
      setSnapshot(snap);
      setRangeId(next);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't change the period.");
    } finally {
      setBusy(false);
    }
  }

  async function onRefresh() {
    if (!token || !company || !endMonth) return;
    setRefreshing(true);
    setError(null);
    try {
      const months = monthsForRange(rangeId, endMonth, earliestMonth);
      setSnapshot(await snapshotForRange(company.id, endMonth, months, true));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't refresh KPIs.");
    } finally {
      setRefreshing(false);
    }
  }

  const categoryName = (id: string | null) =>
    id ? categories.find((c) => c.id === id)?.name ?? "—" : "Uncategorized";

  if (authLoading || !user || loading) {
    return (
      <main className="flex-1 flex items-center justify-center p-8">
        <p className="text-sm text-black/50 dark:text-white/50">Loading…</p>
      </main>
    );
  }

  const spanStart = history?.months[0]?.month;
  const spanEnd = history?.months[history.months.length - 1]?.month;
  const spanLabel = spanStart && spanEnd ? `${monthLong(spanStart)} – ${monthLong(spanEnd)}` : "";
  const rangeLabel = rangeId === "all" ? "All time" : `Last ${rangeId} months`;

  return (
    <main className="flex-1 w-full max-w-6xl mx-auto flex flex-col gap-8 p-8">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">Dashboard</h1>
          {company && (
            <p className="mt-1 text-sm text-black/60 dark:text-white/60">
              {company.name}
              {hasData && endMonth ? ` · through ${monthLong(endMonth)}` : ""}
            </p>
          )}
        </div>
        <nav className="flex flex-wrap items-center gap-3 text-sm">
          <Link href="/transactions" className="underline hover:no-underline text-black/60 dark:text-white/60">
            Transactions
          </Link>
          <Link href="/data" className="underline hover:no-underline text-black/60 dark:text-white/60">
            Import
          </Link>
          <Link href="/company" className="underline hover:no-underline text-black/60 dark:text-white/60">
            Company
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
          body="Create a company profile, then import or enter your financial data."
          href="/company"
          cta="Company profile"
        />
      ) : !hasData ? (
        <EmptyState
          title="No financial data yet"
          body="Import a CSV/XLSX or add entries manually — your KPIs and trends will appear here."
          href="/data"
          cta="Import data"
        />
      ) : (
        <>
          {/* Date-range filter (FR-8.2) */}
          <div className="flex flex-wrap items-center gap-3">
            <span className="text-sm text-black/50 dark:text-white/50">Period</span>
            <div className="inline-flex rounded-md border border-black/15 dark:border-white/20 overflow-hidden">
              {RANGES.map(([id, label]) => (
                <button
                  key={id}
                  type="button"
                  onClick={() => applyRange(id)}
                  disabled={busy}
                  aria-pressed={id === rangeId}
                  className={`px-3 py-1.5 text-sm font-medium disabled:opacity-50 transition-colors ${
                    id === rangeId
                      ? "bg-foreground text-background"
                      : "hover:bg-black/5 dark:hover:bg-white/10"
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
            {busy && <span className="text-xs text-black/40 dark:text-white/40">Updating…</span>}
          </div>

          {/* KPI cards */}
          <section className="flex flex-col gap-3">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h2 className="text-sm font-medium text-black/70 dark:text-white/70">
                  Key metrics · {rangeLabel}
                </h2>
                {snapshot && (
                  <p className="mt-0.5 text-xs text-black/50 dark:text-white/50">
                    {spanLabel} · Revenue {formatINR(snapshot.total_revenue)} · Expenses{" "}
                    {formatINR(snapshot.total_expenses)} · Net {formatINR(snapshot.net_cash_flow)}
                  </p>
                )}
              </div>
              <button type="button" onClick={onRefresh} disabled={refreshing}
                className="rounded-md border border-black/15 dark:border-white/20 px-3 py-1.5 text-sm font-medium hover:bg-black/5 dark:hover:bg-white/10 disabled:opacity-50 transition-colors">
                {refreshing ? "Refreshing…" : "Refresh KPIs"}
              </button>
            </div>
            {snapshot && <KpiCards snap={snapshot} />}
          </section>

          {/* Charts */}
          <section className="grid gap-6 lg:grid-cols-2">
            <div className="rounded-xl border border-black/10 dark:border-white/15 p-4">
              <h3 className="mb-1 text-sm font-medium">Revenue vs. expenses</h3>
              <p className="mb-3 text-xs text-black/50 dark:text-white/50">{spanLabel}</p>
              {history && <RevenueExpenseChart months={history.months} />}
            </div>
            <div className="rounded-xl border border-black/10 dark:border-white/15 p-4">
              <h3 className="mb-1 text-sm font-medium">Net cash flow</h3>
              <p className="mb-3 text-xs text-black/50 dark:text-white/50">{spanLabel}</p>
              {history && <NetCashFlowChart months={history.months} />}
            </div>
          </section>

          {/* Recent activity */}
          <section className="flex flex-col gap-3">
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-medium text-black/60 dark:text-white/60">Recent activity</h2>
              <Link href="/transactions" className="text-sm underline hover:no-underline text-black/60 dark:text-white/60">
                View all
              </Link>
            </div>
            <div className="overflow-x-auto rounded-xl border border-black/10 dark:border-white/15">
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
                  {txns.slice(0, RECENT_LIMIT).map((t) => (
                    <tr key={t.id} className="border-b border-black/5 dark:border-white/5 last:border-0">
                      <td className="p-3 whitespace-nowrap">{t.date}</td>
                      <td className="p-3">
                        {t.description ?? "—"}
                        {t.is_flagged_anomaly && (
                          <span title="Unusual spike vs. the trailing 3-month average"
                            className="ml-2 inline-flex items-center rounded-full bg-amber-100 dark:bg-amber-500/20 px-2 py-0.5 text-xs font-medium text-amber-700 dark:text-amber-400">
                            ⚠ Anomaly
                          </span>
                        )}
                      </td>
                      <td className="p-3 text-black/60 dark:text-white/60">{categoryName(t.category_id)}</td>
                      <td className={`p-3 text-right whitespace-nowrap font-mono ${
                        t.type === "income" ? "text-green-600 dark:text-green-500" : "text-black/80 dark:text-white/80"
                      }`}>
                        {t.type === "expense" ? "-" : "+"}
                        {formatINR(t.amount)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}
    </main>
  );
}

function KpiCards({ snap }: { snap: KpiSnapshot }) {
  const burn = Number(snap.burn_rate);
  const growth = snap.revenue_growth_pct;
  const margin = snap.gross_margin_pct;
  const runway = snap.runway_months;

  return (
    <div className="grid gap-3 grid-cols-2 lg:grid-cols-4">
      <StatCard
        label="Burn rate"
        value={burn > 0 ? `${formatINR(burn)}/mo` : `+${formatINR(-burn)}/mo`}
        hint={burn > 0 ? "Monthly net cash burn" : "Monthly net cash surplus"}
        accent={burn > 0 ? "bad" : "good"}
      />
      <StatCard
        label="Runway"
        value={runway === null ? "N/A" : `${Number(runway).toFixed(1)} mo`}
        hint={runway === null ? "Not burning cash" : "At current burn rate"}
        accent={runway !== null && Number(runway) < 6 ? "warn" : "none"}
      />
      <StatCard
        label="Gross margin"
        value={margin === null ? "—" : `${Number(margin).toFixed(1)}%`}
        hint="Revenue minus all expenses"
        accent={margin === null ? "none" : Number(margin) >= 0 ? "good" : "bad"}
      />
      <StatCard
        label="Revenue growth"
        value={growth === null ? "—" : `${Number(growth) >= 0 ? "+" : ""}${Number(growth).toFixed(1)}%`}
        hint="Vs. the preceding period"
        accent={growth === null ? "none" : Number(growth) >= 0 ? "good" : "bad"}
      />
    </div>
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
