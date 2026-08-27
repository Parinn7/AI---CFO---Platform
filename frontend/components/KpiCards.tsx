/**
 * The four headline KPIs off a `kpi_snapshot` — burn rate, runway, gross margin,
 * revenue growth (FR-4.1–4.5). Extracted from the dashboard in 6.1 so the
 * Scenario Simulator can show the same baseline figures, and so 6.3's
 * before/after comparison reads from one definition of these tiles.
 *
 * Display only: every figure is computed deterministically by the backend
 * (architecture §4.1). `null` values are the genuinely-undefined cases — not
 * burning cash, zero revenue, no prior period — and render as "N/A"/"—" rather
 * than a misleading zero.
 */

import { StatCard } from "@/components/StatCard";
import { type KpiSnapshot } from "@/lib/api";
import { formatINR } from "@/lib/format";

export function KpiCards({ snap }: { snap: KpiSnapshot }) {
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
        value={
          growth === null
            ? "—"
            : `${Number(growth) >= 0 ? "+" : ""}${Number(growth).toFixed(1)}%`
        }
        hint="Vs. the preceding period"
        accent={growth === null ? "none" : Number(growth) >= 0 ? "good" : "bad"}
      />
    </div>
  );
}
