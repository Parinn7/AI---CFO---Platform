/**
 * Scenario input UI (Phase 6.1, FR-5.1). Auth-guarded. Lets the user define a
 * hypothetical — hire N people, change marketing spend / pricing / revenue by
 * X% — in the same plain-language, guided style as manual entry (FR-2.3),
 * against the baseline KPIs their real data already produces.
 *
 * "Run simulation" validates the form, then posts the assumptions to
 * `POST /scenarios/simulate` (6.2, FR-5.2) and renders the before/after
 * comparison (6.3, FR-5.3). Nothing here computes a projected figure — all
 * scenario math is deterministic backend code (architecture §4.1) and this
 * screen only formats what comes back. Editing any field clears the result, so
 * what's on screen always describes the form above it.
 *
 * Running is stateless — the backend persists nothing until the user explicitly
 * saves (6.4, FR-5.4). A saved scenario keeps the comparison as it was computed
 * at save time, so reopening one replays that answer rather than quietly
 * restating it against data recorded since; the levers come back with it, so
 * "re-run this against today's numbers" is one click away and clearly a
 * different act.
 */

"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { KpiCards } from "@/components/KpiCards";
import {
  AppliedChangesList,
  ScenarioComparison,
} from "@/components/ScenarioComparison";
import { useAuth } from "@/contexts/AuthContext";
import {
  ApiError,
  deleteScenario,
  generateKpiSnapshot,
  getHistory,
  listCompanies,
  listKpiSnapshots,
  listScenarios,
  saveScenario,
  simulateScenario,
  type Company,
  type KpiSnapshot,
  type SavedScenario,
  type ScenarioSimulation,
} from "@/lib/api";
import {
  addMonths,
  formatCompactINR,
  formatINR,
  lastDayOfMonth,
  monthLong,
} from "@/lib/format";
import {
  describeAssumptions,
  defaultScenarioName,
  EMPTY_FORM,
  FIELDS,
  formFromAssumptions,
  MAX_NAME_LENGTH,
  validateScenario,
  type AssumptionField,
  type ScenarioAssumptions,
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
  const [sim, setSim] = useState<ScenarioSimulation | null>(null);
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);

  // Saved scenarios (6.4, FR-5.4). `savedView` is the stored scenario the
  // result panel is currently showing — null means what's on screen is a fresh
  // run that hasn't been kept.
  const [saved, setSaved] = useState<SavedScenario[]>([]);
  const [savedView, setSavedView] = useState<SavedScenario | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  // Opening a saved scenario updates the panel *above* the list it was clicked
  // in, which reads as "nothing happened" when the list is below the fold.
  // Bumping this after an open scrolls the result into view; a plain ref check
  // inside the handler would run before the panel has rendered.
  const resultRef = useRef<HTMLElement | null>(null);
  const [openCount, setOpenCount] = useState(0);

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

      // Past scenarios (FR-5.4). Each arrives with its stored comparison, so
      // reopening one needs no further request.
      setSaved(await listScenarios(co.id, token));
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

  useEffect(() => {
    if (openCount > 0) {
      resultRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }, [openCount]);

  /** Any edit invalidates the result on screen — it no longer describes the
   * form. That includes the saved-scenario framing: once a lever is touched,
   * what's displayed is no longer the scenario that was stored. */
  function invalidate() {
    setDraft(null);
    setSim(null);
    setRunError(null);
    setSavedView(null);
    setSaveError(null);
  }

  function setField(id: AssumptionField, value: string) {
    setForm((prev) => ({ ...prev, [id]: value }));
    invalidate();
  }

  /**
   * Validate, then run the simulation (FR-5.2/FR-5.3). The period is the same
   * last-12-months window the baseline snapshot covers, so before and after
   * describe exactly the same stretch of time. The backend does all the math
   * and persists nothing.
   */
  async function onRun() {
    const result = validateScenario(name, form);
    if (!result.ok) {
      setErrors(result.errors);
      invalidate();
      return;
    }
    setErrors({});
    setDraft(result.draft);
    if (!token || !company || !endMonth) return;

    setRunning(true);
    setRunError(null);
    try {
      setSim(
        await simulateScenario(
          {
            company_id: company.id,
            period_start: `${addMonths(endMonth, -(BASELINE_MONTHS - 1))}-01`,
            period_end: lastDayOfMonth(endMonth),
            assumptions: result.draft.assumptions,
          },
          token,
        ),
      );
    } catch (err) {
      setSim(null);
      setRunError(
        err instanceof ApiError ? err.message : "Couldn't run the simulation.",
      );
    } finally {
      setRunning(false);
    }
  }

  function onReset() {
    setForm(EMPTY_FORM);
    setErrors({});
    invalidate();
    setName(endMonth ? defaultScenarioName(monthLong(endMonth)) : "");
  }

  /**
   * Keep the scenario on screen (FR-5.4). Only the levers go up — the backend
   * re-runs the simulation and stores its own result, so nothing this page
   * computed can end up in the database.
   */
  async function onSave() {
    if (!token || !company || !endMonth || !draft || !sim) return;

    setSaving(true);
    setSaveError(null);
    try {
      const created = await saveScenario(
        {
          company_id: company.id,
          name: draft.name,
          period_start: `${addMonths(endMonth, -(BASELINE_MONTHS - 1))}-01`,
          period_end: lastDayOfMonth(endMonth),
          assumptions: draft.assumptions,
        },
        token,
      );
      // Show the stored copy from here on, so what's on screen is what was
      // actually kept rather than a look-alike computed a moment earlier.
      setSaved((prev) => [created, ...prev]);
      setSavedView(created);
      setSim(created.result);
    } catch (err) {
      setSaveError(
        err instanceof ApiError ? err.message : "Couldn't save this scenario.",
      );
    } finally {
      setSaving(false);
    }
  }

  /**
   * Reopen a past scenario (FR-5.4): its stored comparison goes back on screen
   * verbatim, and its levers go back into the form so it can be re-run against
   * today's data as a deliberate next step.
   */
  function onOpenSaved(scenario: SavedScenario) {
    const restored = formFromAssumptions(scenario.assumptions);
    const parsed = validateScenario(scenario.name, restored);

    setName(scenario.name);
    setForm(restored);
    setErrors({});
    setRunError(null);
    setSaveError(null);
    // A saved scenario passed validation before it was stored, so this holds;
    // the fallback keeps the stored result readable rather than blanking the
    // screen if a much older row ever fails today's rules.
    setDraft(
      parsed.ok
        ? parsed.draft
        : {
            name: scenario.name,
            // Coerced, not cast: the API returns these as strings, and
            // `describeAssumptions` compares against 0 — `"0" !== 0` is true,
            // which would print a line for a lever that isn't set.
            assumptions: Object.fromEntries(
              FIELDS.map((f) => [f.id, Number(scenario.assumptions[f.id]) || 0]),
            ) as ScenarioAssumptions,
          },
    );
    setSim(scenario.result);
    setSavedView(scenario);
    setOpenCount((n) => n + 1);
  }

  async function onDeleteSaved(scenario: SavedScenario) {
    if (!token) return;
    if (
      !window.confirm(
        `Delete "${scenario.name}"? This removes the saved scenario only — your financial data is untouched.`,
      )
    ) {
      return;
    }

    setDeletingId(scenario.id);
    setSaveError(null);
    try {
      await deleteScenario(scenario.id, token);
      setSaved((prev) => prev.filter((s) => s.id !== scenario.id));
      // If the deleted one was on screen, clear it rather than leaving a result
      // labelled "saved" that no longer is.
      if (savedView?.id === scenario.id) invalidate();
    } catch (err) {
      setSaveError(
        err instanceof ApiError ? err.message : "Couldn't delete that scenario.",
      );
    } finally {
      setDeletingId(null);
    }
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
            href="/chat"
            className="underline hover:no-underline text-black/60 dark:text-white/60"
          >
            AI CFO
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
                  invalidate();
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
                onClick={onRun}
                disabled={running}
                className="rounded-md bg-foreground text-background px-4 py-2 text-sm font-medium hover:opacity-90 disabled:opacity-50 transition-opacity"
              >
                {running ? "Running…" : "Run simulation"}
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

          {runError && (
            <p className="text-sm text-red-500" role="alert">
              {runError}
            </p>
          )}

          {/* Before/after comparison (FR-5.3) */}
          {draft && sim && (
            <section
              ref={resultRef}
              className="rounded-xl border border-black/10 dark:border-white/15 p-6 space-y-5"
              aria-live="polite"
            >
              <div>
                <h2 className="text-base font-semibold">{draft.name}</h2>
                <p className="mt-0.5 text-xs text-black/50 dark:text-white/50">
                  {periodSpan(sim)} · {sim.num_months} months · before vs. after
                  {savedView
                    ? ` · saved ${formatSavedAt(savedView.created_at)}`
                    : " · not saved"}
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

              <ScenarioComparison sim={sim} />

              <AppliedChangesList sim={sim} />

              <p className="rounded-md border border-black/10 dark:border-white/15 px-3 py-2 text-xs text-black/50 dark:text-white/50">
                Every figure is calculated by the same deterministic engine that
                produces your real KPIs — the scenario restates this period as if
                the assumptions had held throughout, and your actual cash on hand
                is left untouched, so runway answers &ldquo;how long does the
                money I have last?&rdquo;.{" "}
                {savedView
                  ? "These are the figures as they stood when you saved this — reopening never quietly restates them. Run it again to see it against today's data."
                  : "Nothing has been saved yet."}
              </p>

              {saveError && (
                <p className="text-sm text-red-500" role="alert">
                  {saveError}
                </p>
              )}

              {!savedView ? (
                <button
                  type="button"
                  onClick={onSave}
                  disabled={saving}
                  className="rounded-md border border-black/15 dark:border-white/20 px-4 py-2 text-sm font-medium hover:bg-black/5 dark:hover:bg-white/10 disabled:opacity-50 transition-colors"
                >
                  {saving ? "Saving…" : "Save this scenario"}
                </button>
              ) : (
                <p className="text-xs text-black/50 dark:text-white/50">
                  Saved — you&apos;ll find it under &ldquo;Saved scenarios&rdquo;
                  below.
                </p>
              )}
            </section>
          )}

          {/* Save / revisit (FR-5.4) */}
          <SavedScenarioList
            scenarios={saved}
            openId={savedView?.id ?? null}
            deletingId={deletingId}
            onOpen={onOpenSaved}
            onDelete={onDeleteSaved}
          />
        </>
      )}
    </main>
  );
}

/**
 * The window a displayed comparison actually covers, read off the result
 * itself rather than the page's current baseline window. A scenario saved
 * months ago covers an older period, and the header has to name the period its
 * own figures describe — not the one a fresh run would use.
 */
function periodSpan(sim: ScenarioSimulation): string {
  return `${monthLong(sim.period_start.slice(0, 7))} – ${monthLong(sim.period_end.slice(0, 7))}`;
}

/** "29 Aug 2026, 15:34" — enough to tell two runs of the same idea apart. */
function formatSavedAt(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleString("en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/**
 * Past scenarios, newest first (FR-5.4). Each row is a one-line reminder of
 * what the scenario concluded — net cash flow before → after — so the list is
 * scannable without opening anything.
 *
 * Those figures come from the *stored* result, i.e. what the engine computed
 * when the scenario was saved. Nothing here recalculates.
 */
function SavedScenarioList({
  scenarios,
  openId,
  deletingId,
  onOpen,
  onDelete,
}: {
  scenarios: SavedScenario[];
  openId: string | null;
  deletingId: string | null;
  onOpen: (scenario: SavedScenario) => void;
  onDelete: (scenario: SavedScenario) => void;
}) {
  return (
    <section className="rounded-xl border border-black/10 dark:border-white/15 p-6 space-y-4">
      <div>
        <h2 className="text-base font-semibold">Saved scenarios</h2>
        <p className="mt-0.5 text-xs text-black/50 dark:text-white/50">
          {scenarios.length === 0
            ? "Run a scenario and save it to keep it here."
            : "Opening one shows the comparison exactly as it was calculated then, and puts its assumptions back in the form so you can run it again against today's numbers."}
        </p>
      </div>

      {scenarios.length > 0 && (
        <ul className="divide-y divide-black/10 dark:divide-white/10">
          {scenarios.map((scenario) => {
            const before = Number(scenario.result.baseline.net_cash_flow);
            const after = Number(scenario.result.scenario.net_cash_flow);
            const isOpen = scenario.id === openId;
            return (
              <li
                key={scenario.id}
                className="flex flex-wrap items-center justify-between gap-3 py-3 first:pt-0 last:pb-0"
              >
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium">
                    {scenario.name}
                    {isOpen && (
                      <span className="ml-2 text-xs font-normal text-black/50 dark:text-white/50">
                        (showing above)
                      </span>
                    )}
                  </p>
                  <p className="mt-0.5 text-xs text-black/50 dark:text-white/50">
                    Saved {formatSavedAt(scenario.created_at)} · net cash flow{" "}
                    {formatCompactINR(before)} → {formatCompactINR(after)}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => onOpen(scenario)}
                    className="rounded-md border border-black/15 dark:border-white/20 px-3 py-1.5 text-xs font-medium hover:bg-black/5 dark:hover:bg-white/10 transition-colors"
                  >
                    Open
                  </button>
                  <button
                    type="button"
                    onClick={() => onDelete(scenario)}
                    disabled={deletingId === scenario.id}
                    className="rounded-md border border-black/15 dark:border-white/20 px-3 py-1.5 text-xs font-medium text-red-600 dark:text-red-500 hover:bg-red-500/10 disabled:opacity-50 transition-colors"
                  >
                    {deletingId === scenario.id ? "…" : "Delete"}
                  </button>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </section>
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
