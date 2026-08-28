/**
 * Before/after comparison of a scenario's KPIs (Phase 6.3, FR-5.3).
 *
 * Display only — every figure here was computed deterministically by the
 * backend (architecture §4.1); this component formats and never derives. It
 * renders a table rather than the dashboard's `KpiCards` because the point is
 * the *comparison*: three aligned numeric columns (before, after, change) read
 * far better across seven metrics than two rows of tiles.
 *
 * Two things it is careful about:
 *
 * 1. **A null delta is not zero.** Runway/margins/growth are undefined in real
 *    cases (not burning cash, zero revenue, no prior period), and the backend
 *    returns `null` for a delta when *either* side is undefined. "Not
 *    comparable" is shown as an em dash with an explanation, never as 0.
 * 2. **Percentage metrics change in percentage points.** Margin going 45.1% →
 *    58.4% is +13.3pp, not +13.3%; labelling it "%" would be wrong.
 */

import { type ScenarioSimulation } from "@/lib/api";
import { formatINR } from "@/lib/format";

/** Which direction is good news, for colouring the change column. */
type Direction = "up-good" | "up-bad";

type Row = {
  label: string;
  hint?: string;
  before: string;
  after: string;
  /** null = not comparable (either side undefined). */
  delta: string | null;
  /** Sign of the change, for colour. null when there's no comparable delta. */
  sign: number | null;
  direction: Direction;
  /** Shown as a tooltip on a non-comparable change. */
  notComparableReason?: string;
};

/** Signed amount. Zero gets no sign — "+₹0.00" reads as a change that isn't one. */
function signedINR(value: number): string {
  if (value === 0) return formatINR(0);
  return `${value > 0 ? "+" : "−"}${formatINR(Math.abs(value))}`;
}

/** Rounded INR for the prose explanations, matching `describeAssumptions`'s
 * 0-dp style so the two lists on screen don't disagree about formatting. The
 * comparison table keeps full paise precision — those are the actual figures. */
const inrRound = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  maximumFractionDigits: 0,
});

function signedRoundINR(value: number): string {
  if (value === 0) return inrRound.format(0);
  return `${value > 0 ? "+" : "−"}${inrRound.format(Math.abs(value))}`;
}

function signedPoints(value: number, unit: string): string {
  return `${value >= 0 ? "+" : "−"}${Math.abs(value).toFixed(1)}${unit}`;
}

/** Burn rate is stored as positive = burning, so a surplus reads as a negative. */
function burnLabel(value: string): string {
  const n = Number(value);
  return n > 0 ? `${formatINR(n)}/mo` : `+${formatINR(-n)}/mo surplus`;
}

function pctLabel(value: string | null): string {
  return value === null ? "—" : `${Number(value).toFixed(1)}%`;
}

function runwayLabel(value: string | null): string {
  return value === null ? "N/A" : `${Number(value).toFixed(1)} mo`;
}

/**
 * Why a metric has no comparable delta — the undefined case differs per metric,
 * and saying which one it is beats a bare dash.
 */
function undefinedReason(
  metric: "runway" | "margin" | "growth",
  before: string | null,
  after: string | null,
): string {
  const which =
    before === null && after === null
      ? "before or after"
      : before === null
        ? "before"
        : "after";
  if (metric === "runway") {
    return `Runway is undefined ${which} the change (not burning cash, or out of cash), so there's no difference to show.`;
  }
  if (metric === "margin") {
    return `Margin is undefined ${which} the change (no revenue), so there's no difference to show.`;
  }
  return `Growth is undefined ${which} the change (no prior period to compare against), so there's no difference to show.`;
}

function buildRows(sim: ScenarioSimulation): Row[] {
  const { baseline: b, scenario: s, deltas: d } = sim;

  return [
    {
      label: "Revenue",
      hint: "Total over the period",
      before: formatINR(b.total_revenue),
      after: formatINR(s.total_revenue),
      delta: signedINR(Number(d.total_revenue)),
      sign: Number(d.total_revenue),
      direction: "up-good",
    },
    {
      label: "Expenses",
      hint: "Total over the period",
      before: formatINR(b.total_expenses),
      after: formatINR(s.total_expenses),
      delta: signedINR(Number(d.total_expenses)),
      sign: Number(d.total_expenses),
      direction: "up-bad",
    },
    {
      label: "Net cash flow",
      hint: "Revenue minus expenses",
      before: formatINR(b.net_cash_flow),
      after: formatINR(s.net_cash_flow),
      delta: signedINR(Number(d.net_cash_flow)),
      sign: Number(d.net_cash_flow),
      direction: "up-good",
    },
    {
      label: "Burn rate",
      hint: "Monthly net cash burn",
      before: burnLabel(b.burn_rate),
      after: burnLabel(s.burn_rate),
      delta: signedINR(Number(d.burn_rate)),
      sign: Number(d.burn_rate),
      direction: "up-bad",
    },
    {
      label: "Runway",
      hint: "At that burn, against today's cash",
      before: runwayLabel(b.runway_months),
      after: runwayLabel(s.runway_months),
      delta: d.runway_months === null ? null : signedPoints(Number(d.runway_months), " mo"),
      sign: d.runway_months === null ? null : Number(d.runway_months),
      direction: "up-good",
      notComparableReason: undefinedReason(
        "runway",
        b.runway_months,
        s.runway_months,
      ),
    },
    {
      label: "Gross margin",
      hint: "Revenue minus all expenses",
      before: pctLabel(b.gross_margin_pct),
      after: pctLabel(s.gross_margin_pct),
      delta:
        d.gross_margin_pct === null
          ? null
          : signedPoints(Number(d.gross_margin_pct), "pp"),
      sign: d.gross_margin_pct === null ? null : Number(d.gross_margin_pct),
      direction: "up-good",
      notComparableReason: undefinedReason(
        "margin",
        b.gross_margin_pct,
        s.gross_margin_pct,
      ),
    },
    {
      label: "Revenue growth",
      hint: "Vs. the preceding period",
      before: pctLabel(b.revenue_growth_pct),
      after: pctLabel(s.revenue_growth_pct),
      delta:
        d.revenue_growth_pct === null
          ? null
          : signedPoints(Number(d.revenue_growth_pct), "pp"),
      sign: d.revenue_growth_pct === null ? null : Number(d.revenue_growth_pct),
      direction: "up-good",
      notComparableReason: undefinedReason(
        "growth",
        b.revenue_growth_pct,
        s.revenue_growth_pct,
      ),
    },
  ];
}

function changeClass(sign: number | null, direction: Direction): string {
  if (sign === null || sign === 0) return "text-black/50 dark:text-white/50";
  const good = direction === "up-good" ? sign > 0 : sign < 0;
  return good
    ? "text-green-600 dark:text-green-500"
    : "text-red-600 dark:text-red-500";
}

export function ScenarioComparison({ sim }: { sim: ScenarioSimulation }) {
  const rows = buildRows(sim);

  return (
    <div className="overflow-x-auto rounded-xl border border-black/10 dark:border-white/15">
      <table className="w-full text-sm">
        <thead className="text-black/50 dark:text-white/50">
          <tr className="border-b border-black/10 dark:border-white/10">
            <th className="p-3 text-left font-medium">Metric</th>
            <th className="p-3 text-right font-medium">Before</th>
            <th className="p-3 text-right font-medium">After</th>
            <th className="p-3 text-right font-medium">Change</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={row.label}
              className="border-b border-black/5 dark:border-white/5 last:border-0"
            >
              <td className="p-3">
                <span className="font-medium">{row.label}</span>
                {row.hint && (
                  <span className="block text-xs text-black/50 dark:text-white/50">
                    {row.hint}
                  </span>
                )}
              </td>
              <td className="p-3 text-right whitespace-nowrap font-mono text-black/60 dark:text-white/60">
                {row.before}
              </td>
              <td className="p-3 text-right whitespace-nowrap font-mono font-medium">
                {row.after}
              </td>
              <td
                className={`p-3 text-right whitespace-nowrap font-mono ${changeClass(
                  row.sign,
                  row.direction,
                )}`}
              >
                {row.delta ?? (
                  <span
                    title={row.notComparableReason}
                    className="cursor-help border-b border-dotted border-black/25 dark:border-white/25"
                  >
                    —
                  </span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * What the levers actually did, in rupees — the "why" behind the numbers above.
 * Lines are omitted when a lever wasn't used, so this only ever states things
 * that actually happened.
 */
export function AppliedChangesList({ sim }: { sim: ScenarioSimulation }) {
  const { applied, assumptions } = sim;
  const lines: string[] = [];

  if (Number(applied.added_payroll) !== 0) {
    lines.push(
      `${inrRound.format(Number(applied.added_payroll))} of extra payroll — ${
        assumptions.new_hires
      } ${
        assumptions.new_hires === 1 ? "hire" : "hires"
      } at ${inrRound.format(Number(assumptions.avg_salary_per_hire))}/month across ${
        applied.num_months
      } months.`,
    );
  }

  if (Number(assumptions.marketing_change_pct) !== 0) {
    lines.push(
      Number(applied.marketing_baseline) === 0
        ? "No marketing change applied — none of this period's spend is categorised as Marketing, so there was nothing to scale."
        : `${signedRoundINR(Number(applied.marketing_change))} of marketing — ${
            assumptions.marketing_change_pct
          }% of the ${inrRound.format(
            Number(applied.marketing_baseline),
          )} booked to Marketing this period.`,
    );
  }

  if (Number(applied.revenue_change) !== 0) {
    lines.push(
      `${signedRoundINR(Number(applied.revenue_change))} of revenue — a ${Number(
        applied.revenue_multiplier,
      )}× multiplier from the pricing and revenue levers combined.`,
    );
  }

  if (lines.length === 0) return null;

  return (
    <div>
      <h3 className="text-sm font-medium text-black/70 dark:text-white/70">
        Why the numbers moved
      </h3>
      <ul className="mt-2 space-y-1.5 text-sm text-black/70 dark:text-white/70">
        {lines.map((line) => (
          <li key={line} className="flex gap-2">
            <span aria-hidden className="text-black/30 dark:text-white/30">
              •
            </span>
            <span>{line}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
