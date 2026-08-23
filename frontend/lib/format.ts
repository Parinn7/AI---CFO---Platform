/** Shared display formatters (INR + month labels). */

const MONTHS_SHORT = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];

const inrFull = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  maximumFractionDigits: 2,
});

/** Full INR amount, e.g. "₹1,20,000.00". */
export function formatINR(value: number | string): string {
  return inrFull.format(Number(value));
}

/**
 * Compact INR using Indian magnitudes (K / L / Cr), for axis ticks and dense
 * labels, e.g. 120000 → "₹1.2L", 5000 → "₹5K".
 */
export function formatCompactINR(value: number | string): string {
  const n = Number(value);
  const sign = n < 0 ? "-" : "";
  const abs = Math.abs(n);
  const trim = (x: number) => x.toFixed(1).replace(/\.0$/, "");
  if (abs >= 1e7) return `${sign}₹${trim(abs / 1e7)}Cr`;
  if (abs >= 1e5) return `${sign}₹${trim(abs / 1e5)}L`;
  if (abs >= 1e3) return `${sign}₹${trim(abs / 1e3)}K`;
  return `${sign}₹${Math.round(abs)}`;
}

/** "2026-01" → "Jan". */
export function monthShort(ym: string): string {
  const m = Number(ym.split("-")[1]);
  return MONTHS_SHORT[m - 1] ?? ym;
}

/** "2026-01" → "Jan 2026". */
export function monthLong(ym: string): string {
  const [y, m] = ym.split("-");
  return `${MONTHS_SHORT[Number(m) - 1] ?? m} ${y}`;
}

/** Last calendar day of a "YYYY-MM" month → "YYYY-MM-DD". */
export function lastDayOfMonth(ym: string): string {
  const [y, m] = ym.split("-").map(Number);
  const day = new Date(y, m, 0).getDate();
  return `${ym}-${String(day).padStart(2, "0")}`;
}
