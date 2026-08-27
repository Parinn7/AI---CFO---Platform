/**
 * Scenario input UI (Phase 6.1, FR-5.1). Auth-guarded. Lets the user define a
 * hypothetical — hire N people, change marketing spend / pricing / revenue by
 * X% — in the same plain-language, guided style as manual entry (FR-2.3),
 * against the baseline KPIs their real data already produces.
 *
 * Scope note: 6.1 is the input side only. The form validates the assumptions
 * and reads them back in plain language; the deterministic simulation engine
 * (6.2, FR-5.2) and the before/after comparison (6.3, FR-5.3) consume the draft
 * this screen produces, and 6.4 persists it to the `scenarios` table. Nothing
 * here computes a projected figure — all scenario math is backend code
 * (architecture §4.1).
 */

"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { KpiCards } from "@/components/KpiCards";
import { useAuth } from "@/contexts/AuthContext";
import {
  ApiError,
  generateKpiSnapshot,
  getHistory,
  listCompanies,
  listKpiSnapshots,
  type Company,
  type KpiSnapshot,
} from "@/lib/api";
import { addMonths, formatINR, lastDayOfMonth, monthLong } from "@/lib/format";
import {
  describeAssumptions,
  defaultScenarioName,
  EMPTY_FORM,
  FIELDS,
  MAX_NAME_LENGTH,
  validateScenario,
  type AssumptionField,
  type FieldSpec,
  type ScenarioDraft,
  type ScenarioErrors,
  type ScenarioForm,
} from "@/lib/scenarios";

/** Baseline window, matching the dashboard's default view. */
const BASELINE_MONTHS = 12;

const inputClass =
  "w-full rounded-md border border-black/15 dark:border-white/20 bg-transparent px-3 py-2 text-sm outline-none focus:border-black/40 dark:focus:border-white/40";

export default function ScenariosPage() {
  const { user, token, loading: authLoading } = useAuth();
  const router = useRouter();

  const [company, setCompany] = useState<Company | null>(null);
  const [baseline, setBaseline] = useState<KpiSnapshot | null>(null);
  const [endMonth, setEndMonth] = useState<string | null>(null);
  const [hasData, setHasData] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [name, setName] = useState("");
  const [form, setForm] = useState<ScenarioForm>(EMPTY_FORM);
  const [errors, setErrors] = useState<ScenarioErrors>({});
  const [draft, setDraft] = useState<ScenarioDraft | null>(null);

  useEffect(() => {
    if (!authLoading && !user) router.replace("/login");
  }, [authLoading, user, router]);

  const load = useCallback(async () => {
    if (!token) return;
    try {
      const co = (await listCompanies(token))[0] ?? null;
      setLoadError(null);
      setCompany(co);
      if (!co) {
        setLoading(false);
        return;
      }

      // The baseline a scenario is measured against: the same last-12-months
      // KPI snapshot the dashboard shows, get-or-create so we reuse a stored
      // one rather than regenerating on every visit.
      const hist = await getHistory(co.id, token, BASELINE_MONTHS);
      const present = hist.months.some(
        (m) => Number(m.revenue) !== 0 || Number(m.expenses) !== 0,
      );
      setHasData(present);

      if (present) {
        const end = hist.end_month;
        setEndMonth(end);
        setName(defaultScenarioName(monthLong(end)));
        const periodStart = `${addMonths(end, -(BASELINE_MONTHS - 1))}-01`;
        const periodEnd = lastDayOfMonth(end);
        const existing = (await listKpiSnapshots(co.id, token)).find(
          (s) => s.period_start === periodStart && s.period_end === periodEnd,
        );
        setBaseline(
          existing ??
            (await generateKpiSnapshot(
              { company_id: co.id, period_start: periodStart, period_end: periodEnd },
              token,
            )),
        );
      }
    } catch (err) {
      setLoadError(
        err instanceof ApiError ? err.message : "Couldn't load your baseline figures.",
      );
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    // Fetch-on-mount; load() only setState()s after awaited requests.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (token) load();
  }, [token, load]);

  function setField(id: AssumptionField, value: string) {
    setForm((prev) => ({ ...prev, [id]: value }));
    setDraft(null); // edits invalidate a reviewed draft
  }

  function onReview() {
    const result = validateScenario(name, form);
    if (!result.ok) {
      setErrors(result.errors);
      setDraft(null);
      return;
    }
    setErrors({});
    setDraft(result.draft);
  }

  function onReset() {
    setForm(EMPTY_FORM);
    setErrors({});
    setDraft(null);
    setName(endMonth ? defaultScenarioName(monthLong(endMonth)) : "");
  }

  if (authLoading || !user || loading) {
    return (
      <main className="flex-1 flex items-center justify-center p-8">
        <p className="text-sm text-black/50 dark:text-white/50">Loading…</p>
      </main>
    );
  }

  const baselineSpan =
    endMonth &&
    `${monthLong(addMonths(endMonth, -(BASELINE_MONTHS - 1)))} – ${monthLong(endMonth)}`;

  return (
    <main className="flex-1 w-full max-w-4xl mx-auto flex flex-col gap-6 p-8">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">Scenario simulator</h1>
          <p className="mt-1 text-sm text-black/60 dark:text-white/60">
            {company
              ? `${company.name} — ask "what if?" without touching your real data.`
              : 'Ask "what if?" without touching your real data.'}
          </p>
        </div>
        <nav className="flex flex-wrap items-center gap-3 text-sm">
          <Link
            href="/dashboard"
            className="underline hover:no-underline text-black/60 dark:text-white/60"
          >
            Dashboard
          </Link>
          <Link
            href="/transactions"
            className="underline hover:no-underline text-black/60 dark:text-white/60"
          >
            Transactions
          </Link>
        </nav>
      </header>

      {loadError && (
        <p className="text-sm text-red-500" role="alert">
          {loadError}
        </p>
      )}

      {!company ? (
        <EmptyState
          title="Set up your company first"
          body="Scenarios are measured against your real numbers, so we need a company profile and some data first."
          href="/company"
          cta="Company profile"
        />
      ) : !hasData ? (
        <EmptyState
          title="No financial data to simulate against"
          body="Import a CSV/XLSX or add entries manually — then you can model what happens if you hire, spend more, or change prices."
          href="/data"
          cta="Add data"
        />
      ) : (
        <>
          {/* Baseline the scenario will be compared against (FR-5.3 reads this). */}
          <section className="flex flex-col gap-3">
            <div>
              <h2 className="text-sm font-medium text-black/70 dark:text-white/70">
                Your baseline today
              </h2>
              <p className="mt-0.5 text-xs text-black/50 dark:text-white/50">
                {baselineSpan}
                {baseline && (
                  <>
                    {" "}
                    · Revenue {formatINR(baseline.total_revenue)} · Expenses{" "}
                    {formatINR(baseline.total_expenses)}
                  </>
                )}
              </p>
            </div>
            {baseline && <KpiCards snap={baseline} />}
          </section>

          {/* Assumption form (FR-5.1) */}
          <section className="rounded-xl border border-black/10 dark:border-white/15 p-6 space-y-5">
            <p className="text-sm text-black/60 dark:text-white/60">
              Answer only what you want to change — leave the rest blank. Nothing
              here touches your saved data.
            </p>

            <div className="space-y-1">
              <label htmlFor="scenario-name" className="block text-sm font-medium">
                What would you call this scenario?
              </label>
              <input
                id="scenario-name"
                type="text"
                maxLength={MAX_NAME_LENGTH}
                value={name}
                onChange={(e) => {
                  setName(e.target.value);
                  setDraft(null);
                }}
                placeholder="e.g. Aggressive hiring"
                aria-invalid={Boolean(errors.name)}
                className={inputClass}
              />
              <FieldError message={errors.name} />
            </div>

            <div className="space-y-4">
              {FIELDS.map((spec) => (
                <AssumptionInput
                  key={spec.id}
                  spec={spec}
                  value={form[spec.id]}
                  error={errors[spec.id]}
                  onChange={(v) => setField(spec.id, v)}
                />
              ))}
            </div>

            {errors.form && (
              <p className="text-sm text-red-500" role="alert">
                {errors.form}
              </p>
            )}

            <div className="flex flex-wrap items-center gap-3">
              <button
                type="button"
                onClick={onReview}
                className="rounded-md bg-foreground text-background px-4 py-2 text-sm font-medium hover:opacity-90 transition-opacity"
              >
                Review scenario
              </button>
              <button
                type="button"
                onClick={onReset}
                className="rounded-md border border-black/15 dark:border-white/20 px-4 py-2 text-sm font-medium hover:bg-black/5 dark:hover:bg-white/10 transition-colors"
              >
                Reset
              </button>
            </div>
          </section>

          {draft && (
            <section
              className="rounded-xl border border-black/10 dark:border-white/15 p-6 space-y-4"
              aria-live="polite"
            >
              <div>
                <h2 className="text-base font-semibold">{draft.name}</h2>
                <p className="mt-0.5 text-xs text-black/50 dark:text-white/50">
                  Compared against {baselineSpan}
                </p>
              </div>

              <div>
                <h3 className="text-sm font-medium text-black/70 dark:text-white/70">
                  What you&apos;re modelling
                </h3>
                <ul className="mt-2 space-y-1.5 text-sm text-black/70 dark:text-white/70">
                  {describeAssumptions(draft.assumptions).map((line) => (
                    <li key={line} className="flex gap-2">
                      <span aria-hidden className="text-black/30 dark:text-white/30">
                        •
                      </span>
                      <span>{line}</span>
                    </li>
                  ))}
                </ul>
              </div>

              <p className="rounded-md border border-black/10 dark:border-white/15 px-3 py-2 text-xs text-black/50 dark:text-white/50">
                These assumptions are ready to simulate. The simulation itself —
                recalculating cash flow, runway, profitability and growth, and
                showing the before/after — is deterministic backend work landing
                in the next steps of this phase (FR-5.2, FR-5.3). Nothing has been
                saved yet.
              </p>
            </section>
          )}
        </>
      )}
    </main>
  );
}

function AssumptionInput({
  spec,
  value,
  error,
  onChange,
}: {
  spec: FieldSpec;
  value: string;
  error?: string;
  onChange: (value: string) => void;
}) {
  const id = `assumption-${spec.id}`;
  return (
    <div className="space-y-1">
      <label htmlFor={id} className="block text-sm font-medium">
        {spec.question}
      </label>
      <p className="text-xs text-black/50 dark:text-white/50">{spec.help}</p>
      <div className="flex items-center gap-2">
        {spec.unit === "inr" && (
          <span className="text-black/40 dark:text-white/40">₹</span>
        )}
        <input
          id={id}
          type="number"
          inputMode="decimal"
          min={spec.min}
          max={spec.max}
          step={spec.integer ? 1 : "any"}
          placeholder={spec.placeholder}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          aria-invalid={Boolean(error)}
          aria-describedby={error ? `${id}-error` : undefined}
          className={inputClass}
        />
        <span className="w-24 text-right text-xs whitespace-nowrap text-black/40 dark:text-white/40">
          {spec.unit === "pct"
            ? "% change"
            : spec.unit === "inr"
              ? "per month"
              : "people"}
        </span>
      </div>
      <FieldError id={`${id}-error`} message={error} />
    </div>
  );
}

function FieldError({ id, message }: { id?: string; message?: string }) {
  if (!message) return null;
  return (
    <p id={id} className="text-xs text-red-500" role="alert">
      {message}
    </p>
  );
}

function EmptyState({
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
