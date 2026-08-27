/**
 * KPI stat tile (Phase 5.1, FR-8.1). Label · value · optional sub/hint.
 * `accent` tints only the value (good/bad/warn); text otherwise uses ink tokens.
 *
 * `min-w-0` + `break-words` keep long INR values ("₹3,29,788.75/mo" is one
 * unbreakable token) wrapping inside the tile instead of spilling over the next
 * one when the grid is narrow — as it is on /scenarios.
 */

type Accent = "none" | "good" | "bad" | "warn";

const ACCENT: Record<Accent, string> = {
  none: "",
  good: "text-green-600 dark:text-green-500",
  bad: "text-red-600 dark:text-red-500",
  warn: "text-amber-600 dark:text-amber-500",
};

export function StatCard({
  label,
  value,
  hint,
  accent = "none",
}: {
  label: string;
  value: string;
  hint?: string;
  accent?: Accent;
}) {
  return (
    <div className="min-w-0 rounded-xl border border-black/10 dark:border-white/15 p-4">
      <p className="text-xs uppercase tracking-wide text-black/50 dark:text-white/50">
        {label}
      </p>
      <p className={`mt-1.5 break-words text-2xl font-semibold ${ACCENT[accent]}`}>
        {value}
      </p>
      {hint && (
        <p className="mt-1 text-xs text-black/50 dark:text-white/50">{hint}</p>
      )}
    </div>
  );
}
