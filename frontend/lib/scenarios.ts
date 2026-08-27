/**
 * Scenario assumptions — the shared input model for the Scenario Simulator
 * (Phase 6, FR-5.x). This module owns the *shape* and *validation* of a
 * scenario's inputs plus their plain-language description; it deliberately
 * contains no financial math.
 *
 * All simulation arithmetic is deterministic backend code (architecture §4.1),
 * arriving in 6.2 — so nothing here derives a KPI, a projected total, or any
 * other figure the engine is responsible for. `payrollDelta` is the one
 * exception and is not a result: it's `hires x salary`, echoed back so the user
 * can sanity-check the number they just typed.
 *
 * The `ScenarioAssumptions` object is what schema.md §7 stores as the
 * `assumptions` jsonb column, so the keys here are the persisted keys (6.4).
 */

/** Structured scenario inputs — persisted verbatim as `scenarios.assumptions`. */
export type ScenarioAssumptions = {
  /** Headcount added on top of today's team. */
  new_hires: number;
  /** Fully-loaded monthly cost per new hire, in ₹. */
  avg_salary_per_hire: number;
  /** Change to monthly marketing spend, in % (negative = a cut). */
  marketing_change_pct: number;
  /** Change to prices, in % — assumes sales volume holds. */
  pricing_change_pct: number;
  /** Change to top-line revenue, in % (independent of the pricing lever). */
  revenue_change_pct: number;
};

export type AssumptionField = keyof ScenarioAssumptions;

/** Raw form state: one string per field, "" meaning "no change". */
export type ScenarioForm = Record<AssumptionField, string>;

/** A validated, named scenario, ready for the engine (6.2) and saving (6.4). */
export type ScenarioDraft = {
  name: string;
  assumptions: ScenarioAssumptions;
};

export type FieldSpec = {
  id: AssumptionField;
  /** Plain-language question, in the guided style of manual entry (FR-2.3). */
  question: string;
  help: string;
  unit: "count" | "inr" | "pct";
  min: number;
  max: number;
  integer?: boolean;
  placeholder: string;
};

/**
 * The levers, in the order FR-5.1 names them: hire N employees, change
 * marketing spend by X%, change pricing by X%, change revenue by X%.
 * `avg_salary_per_hire` follows `new_hires` because hiring has no cash effect
 * until we know what a hire costs.
 */
export const FIELDS: FieldSpec[] = [
  {
    id: "new_hires",
    question: "How many people would you hire?",
    help: "Added on top of your current team. Leave blank if you're not hiring.",
    unit: "count",
    min: 0,
    max: 500,
    integer: true,
    placeholder: "0",
  },
  {
    id: "avg_salary_per_hire",
    question: "Roughly what would each new hire cost per month?",
    help: "Fully-loaded monthly cost — salary plus anything you pay on top.",
    unit: "inr",
    min: 0,
    max: 10_000_000,
    placeholder: "0",
  },
  {
    id: "marketing_change_pct",
    question: "Would you change your marketing spend?",
    help: "A percentage of what you spend today. 50 = spend half again as much, -20 = cut it by a fifth.",
    unit: "pct",
    min: -100,
    max: 1000,
    placeholder: "0",
  },
  {
    id: "pricing_change_pct",
    question: "Would you change your prices?",
    help: "Assumes you keep selling the same amount — so a price rise flows straight to revenue.",
    unit: "pct",
    min: -100,
    max: 1000,
    placeholder: "0",
  },
  {
    id: "revenue_change_pct",
    question: "Would your revenue change for any other reason?",
    help: "Separate from pricing — use this for winning or losing business (new customers, a lost contract).",
    unit: "pct",
    min: -100,
    max: 1000,
    placeholder: "0",
  },
];

export const EMPTY_FORM: ScenarioForm = {
  new_hires: "",
  avg_salary_per_hire: "",
  marketing_change_pct: "",
  pricing_change_pct: "",
  revenue_change_pct: "",
};

export const MAX_NAME_LENGTH = 80;

/** Error keys are field ids, plus `name` and `form` for whole-scenario problems. */
export type ScenarioErrors = Partial<
  Record<AssumptionField | "name" | "form", string>
>;

export type ValidationResult =
  | { ok: true; draft: ScenarioDraft }
  | { ok: false; errors: ScenarioErrors };

/** Parse one raw field. Blank means "no change" → 0. */
function parseField(spec: FieldSpec, raw: string): number | string {
  const trimmed = raw.trim();
  if (trimmed === "") return 0;

  const n = Number(trimmed);
  if (!Number.isFinite(n)) return "Enter a number, or leave this blank.";
  if (spec.integer && !Number.isInteger(n)) return "Enter a whole number.";
  if (n < spec.min || n > spec.max) {
    return spec.unit === "pct"
      ? `Enter a percentage between ${spec.min} and ${spec.max}.`
      : `Enter a value between ${spec.min} and ${spec.max}.`;
  }
  return n;
}

/** True when every lever is at zero — nothing to simulate. */
export function isUnchanged(a: ScenarioAssumptions): boolean {
  return FIELDS.every((f) => a[f.id] === 0);
}

/** Extra monthly payroll implied by the hiring lever, in ₹. */
export function payrollDelta(a: ScenarioAssumptions): number {
  return a.new_hires * a.avg_salary_per_hire;
}

/**
 * Validate raw form state into a named draft. Returns per-field messages rather
 * than throwing so the form can show them all at once.
 */
export function validateScenario(
  name: string,
  form: ScenarioForm,
): ValidationResult {
  const errors: ScenarioErrors = {};

  const trimmedName = name.trim();
  if (!trimmedName) {
    errors.name = "Give this scenario a name so you can find it later.";
  } else if (trimmedName.length > MAX_NAME_LENGTH) {
    errors.name = `Keep the name under ${MAX_NAME_LENGTH} characters.`;
  }

  const assumptions: ScenarioAssumptions = {
    new_hires: 0,
    avg_salary_per_hire: 0,
    marketing_change_pct: 0,
    pricing_change_pct: 0,
    revenue_change_pct: 0,
  };
  for (const spec of FIELDS) {
    const parsed = parseField(spec, form[spec.id]);
    if (typeof parsed === "string") {
      errors[spec.id] = parsed;
      assumptions[spec.id] = 0;
    } else {
      assumptions[spec.id] = parsed;
    }
  }

  // Hiring only has a cash effect once we know what a hire costs.
  if (
    !errors.new_hires &&
    !errors.avg_salary_per_hire &&
    assumptions.new_hires > 0 &&
    assumptions.avg_salary_per_hire <= 0
  ) {
    errors.avg_salary_per_hire =
      "Add a monthly cost per hire — otherwise hiring costs nothing in the simulation.";
  }

  if (Object.keys(errors).length === 0 && isUnchanged(assumptions)) {
    errors.form = "Change at least one thing — otherwise there's nothing to simulate.";
  }

  if (Object.keys(errors).length > 0) return { ok: false, errors };
  return { ok: true, draft: { name: trimmedName, assumptions } };
}

const inr = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  maximumFractionDigits: 0,
});

/**
 * Magnitude only — no sign. Every caller states the direction in words
 * ("Increase"/"Cut"/"Raise"/"Lower"/"Win"/"Lose"), so a `+` here would say it
 * twice, and "Lose +5%" reads as a contradiction.
 */
function pct(n: number): string {
  return `${Number(Math.abs(n).toFixed(2))}%`;
}

/**
 * Plain-language recap of what a scenario models — one line per active lever,
 * so the user reads back their own assumptions before running anything.
 * Levers left at zero are omitted.
 */
export function describeAssumptions(a: ScenarioAssumptions): string[] {
  const lines: string[] = [];

  if (a.new_hires > 0) {
    const each = inr.format(a.avg_salary_per_hire);
    const total = inr.format(payrollDelta(a));
    lines.push(
      `Hire ${a.new_hires} ${a.new_hires === 1 ? "person" : "people"} at ${each} per month each — ${total} added to monthly payroll.`,
    );
  }

  if (a.marketing_change_pct !== 0) {
    lines.push(
      a.marketing_change_pct > 0
        ? `Increase marketing spend by ${pct(a.marketing_change_pct)}.`
        : `Cut marketing spend by ${pct(a.marketing_change_pct)}.`,
    );
  }

  if (a.pricing_change_pct !== 0) {
    lines.push(
      `${a.pricing_change_pct > 0 ? "Raise" : "Lower"} prices by ${pct(a.pricing_change_pct)}, with sales volume holding steady.`,
    );
  }

  if (a.revenue_change_pct !== 0) {
    lines.push(
      `${a.revenue_change_pct > 0 ? "Win" : "Lose"} ${pct(a.revenue_change_pct)} of revenue for other reasons.`,
    );
  }

  return lines;
}

/** Default scenario name, e.g. "Scenario — Aug 2026". */
export function defaultScenarioName(monthLabel: string): string {
  return `Scenario — ${monthLabel}`;
}
