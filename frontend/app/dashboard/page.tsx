/**
 * Overview dashboard (Phase 5.1, FR-8.1). Auth-guarded. The first UI consumer of
 * the whole Financial Engine: KPI cards (burn/runway/margins/growth from a
 * kpi_snapshot), a 12-month revenue/expenses + net-cash-flow trend (FR-4.6), and
 * recent activity with anomaly flags (FR-3.6 / FR-8.3). All numbers are computed
 * deterministically by the backend — the UI only displays them.
 *
 * KPI cards use get-or-create: on load it reuses a stored snapshot for the latest
 * month of data, generating one only if missing; "Refresh KPIs" regenerates.
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
  getFinancialSummary,
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
import { formatINR, lastDayOfMonth, monthLong } from "@/lib/format";

const RECENT_LIMIT = 8;

export default function DashboardPage() {
  const { user, token, loading: authLoading, logout } = useAuth();
  const router = useRouter();

  const [company, setCompany] = useState<Company | null>(null);
  const [history, setHistory] = useState<HistoryResponse | null>(null);
  const [snapshot, setSnapshot] = useState<KpiSnapshot | null>(null);
  const [txns, setTxns] = useState<Transaction[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [hasData, setHasData] = useState(false);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
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

      const [summary, hist, cats, allTxns] = await Promise.all([
        getFinancialSummary(co.id, token),
        getHistory(co.id, token, 12),
        listCategories(co.id, token),
        listTransactions(co.id, token),
      ]);
      const dataPresent = summary.income_count + summary.expense_count > 0;
      setHistory(hist);
      setCategories(cats);
      setTxns(allTxns.slice(0, RECENT_LIMIT));
      setHasData(dataPresent);

      if (dataPresent) {
        const periodStart = `${hist.end_month}-01`;
        const periodEnd = lastDayOfMonth(hist.end_month);
        const existing = (await listKpiSnapshots(co.id, token)).find(
          (s) => s.period_start === periodStart && s.period_end === periodEnd,
        );
        setSnapshot(
          existing ??
            (await generateKpiSnapshot(
              { company_id: co.id, period_start: periodStart, period_end: periodEnd },
              token,
            )),
        );
      } else {
        setSnapshot(null);
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't load the dashboard.");
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    // Fetch-on-mount; load() only setState()s after awaited requests.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (token) load();
  }, [token, load]);

  async function onRefresh() {
    if (!token || !company || !history || !hasData) return;
    setRefreshing(true);
    setError(null);
    try {
      const periodStart = `${history.end_month}-01`;
      const periodEnd = lastDayOfMonth(history.end_month);
      setSnapshot(
        await generateKpiSnapshot(
          { company_id: company.id, period_start: periodStart, period_end: periodEnd },
          token,
        ),
      );
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

  return (
    <main className="flex-1 w-full max-w-6xl mx-auto flex flex-col gap-8 p-8">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">Dashboard</h1>
          {company && (
            <p className="mt-1 text-sm text-black/60 dark:text-white/60">
              {company.name}
              {hasData && history ? ` · through ${monthLong(history.end_month)}` : ""}
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
          {/* KPI cards */}
          <section className="flex flex-col gap-3">
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-medium text-black/60 dark:text-white/60">
                Key metrics{history ? ` — ${monthLong(history.end_month)}` : ""}
              </h2>
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
              <p className="mb-3 text-xs text-black/50 dark:text-white/50">Last 12 months</p>
              {history && <RevenueExpenseChart months={history.months} />}
            </div>
            <div className="rounded-xl border border-black/10 dark:border-white/15 p-4">
              <h3 className="mb-1 text-sm font-medium">Net cash flow</h3>
              <p className="mb-3 text-xs text-black/50 dark:text-white/50">Last 12 months</p>
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
                  {txns.map((t) => (
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
        hint="Vs. the previous month"
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
