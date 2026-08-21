/**
 * Guided manual data entry (Phase 3.3, FR-2.3). Auth-guarded. Instead of a blank
 * accounting form, it asks plain-language questions ("How much did you spend on
 * rent?") — one per category — for a single period. Filled-in answers are sent
 * as manual transactions, which land in the same table as uploads (FR-2.6).
 */

"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { useAuth } from "@/contexts/AuthContext";
import {
  ApiError,
  createManualTransactions,
  listCategories,
  listCompanies,
  type Category,
  type Company,
  type ManualEntryInput,
  type Transaction,
} from "@/lib/api";

const inr = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  maximumFractionDigits: 2,
});

// Plain-language prompt per category (falls back to a generic question).
const PROMPTS: Record<string, string> = {
  Revenue: "How much did you make in sales / revenue?",
  Payroll: "How much did you pay in salaries / wages?",
  Rent: "How much did you spend on rent?",
  Marketing: "How much did you spend on marketing / advertising?",
  "Software/Tools": "How much did you spend on software & tools?",
  Operations: "How much on operations, purchases & other running costs?",
  Other: "Any other money in or out? (e.g. bank charges, misc.)",
};

function promptFor(name: string): string {
  return PROMPTS[name] ?? `How much for ${name}?`;
}

function todayISO(): string {
  return new Date().toISOString().slice(0, 10);
}

export default function ManualEntryPage() {
  const { user, token, loading: authLoading } = useAuth();
  const router = useRouter();

  const [company, setCompany] = useState<Company | null>(null);
  const [categories, setCategories] = useState<Category[]>([]);
  const [loading, setLoading] = useState(true);

  const [date, setDate] = useState(todayISO());
  const [amounts, setAmounts] = useState<Record<string, string>>({});
  // For the flexible "Other" category, let the user pick income vs expense.
  const [otherType, setOtherType] = useState<"income" | "expense">("expense");

  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<Transaction[] | null>(null);
  const [skipped, setSkipped] = useState<string[]>([]);

  useEffect(() => {
    if (!authLoading && !user) router.replace("/login");
  }, [authLoading, user, router]);

  const load = useCallback(async () => {
    if (!token) return;
    try {
      const companies = await listCompanies(token);
      const c = companies[0] ?? null;
      setCompany(c);
      if (c) setCategories(await listCategories(c.id, token));
    } catch {
      setError("Couldn't load your company or categories.");
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    // Fetch-on-mount; load() only setState()s after awaited requests.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (token) load();
  }, [token, load]);

  function setAmount(categoryId: string, value: string) {
    setAmounts((prev) => ({ ...prev, [categoryId]: value }));
  }

  async function onSubmit() {
    if (!token || !company) return;
    setError(null);
    setSaved(null);
    setSkipped([]);

    const entries: ManualEntryInput[] = [];
    for (const cat of categories) {
      const raw = (amounts[cat.id] ?? "").trim();
      if (!raw) continue;
      const n = Number(raw);
      if (!Number.isFinite(n) || n <= 0) {
        setError(`Enter a positive number for "${cat.name}", or leave it blank.`);
        return;
      }
      entries.push({
        date,
        amount: raw,
        category_id: cat.id,
        // Only "Other" gets an explicit direction; the rest use their category type.
        type: cat.name === "Other" ? otherType : undefined,
      });
    }

    if (entries.length === 0) {
      setError("Fill in at least one amount.");
      return;
    }

    setSubmitting(true);
    try {
      const result = await createManualTransactions(company.id, entries, token);
      setSaved(result.created);
      setSkipped(result.skipped_duplicates);
      setAmounts({});
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Couldn't save. Please try again.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  if (authLoading || !user || loading) {
    return (
      <main className="flex-1 flex items-center justify-center p-8">
        <p className="text-sm text-black/50 dark:text-white/50">Loading…</p>
      </main>
    );
  }

  const inputClass =
    "w-full rounded-md border border-black/15 dark:border-white/20 bg-transparent px-3 py-2 text-sm outline-none focus:border-black/40 dark:focus:border-white/40";

  return (
    <main className="flex-1 w-full max-w-2xl mx-auto flex flex-col gap-6 p-8">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Enter data manually</h1>
        <Link
          href="/data"
          className="text-sm underline hover:no-underline text-black/60 dark:text-white/60"
        >
          Upload a file instead
        </Link>
      </div>

      {!company ? (
        <div className="rounded-xl border border-black/10 dark:border-white/15 p-6">
          <p className="text-sm text-black/70 dark:text-white/70">
            Set up your company first.{" "}
            <Link href="/company" className="underline hover:no-underline">
              Company profile
            </Link>
          </p>
        </div>
      ) : (
        <>
          <div className="rounded-xl border border-black/10 dark:border-white/15 p-6 space-y-5">
            <p className="text-sm text-black/60 dark:text-white/60">
              Answer whatever applies — leave the rest blank. No accounting
              knowledge needed. Amounts are in ₹ (INR).
            </p>

            <div className="space-y-1">
              <label htmlFor="date" className="block text-sm font-medium">
                Which date does this cover?
              </label>
              <input
                id="date"
                type="date"
                value={date}
                onChange={(e) => setDate(e.target.value)}
                className={`${inputClass} max-w-xs`}
              />
            </div>

            <div className="space-y-4">
              {categories.map((cat) => (
                <div key={cat.id} className="space-y-1">
                  <label
                    htmlFor={`amt-${cat.id}`}
                    className="block text-sm font-medium"
                  >
                    {promptFor(cat.name)}
                  </label>
                  <div className="flex items-center gap-2">
                    <span className="text-black/40 dark:text-white/40">₹</span>
                    <input
                      id={`amt-${cat.id}`}
                      type="number"
                      min="0"
                      step="0.01"
                      inputMode="decimal"
                      placeholder="0"
                      value={amounts[cat.id] ?? ""}
                      onChange={(e) => setAmount(cat.id, e.target.value)}
                      className={inputClass}
                    />
                    {cat.name === "Other" ? (
                      <select
                        aria-label="Money in or out"
                        value={otherType}
                        onChange={(e) =>
                          setOtherType(e.target.value as "income" | "expense")
                        }
                        className={`${inputClass} max-w-[8rem]`}
                      >
                        <option value="expense">Money out</option>
                        <option value="income">Money in</option>
                      </select>
                    ) : (
                      <span className="text-xs whitespace-nowrap text-black/40 dark:text-white/40 w-20 text-right">
                        {cat.type === "income" ? "Money in" : "Money out"}
                      </span>
                    )}
                  </div>
                </div>
              ))}
            </div>

            {error && (
              <p className="text-sm text-red-500" role="alert">
                {error}
              </p>
            )}

            <button
              type="button"
              onClick={onSubmit}
              disabled={submitting}
              className="rounded-md bg-foreground text-background px-4 py-2 text-sm font-medium hover:opacity-90 disabled:opacity-50 transition-opacity"
            >
              {submitting ? "Saving…" : "Save entries"}
            </button>
          </div>

          {saved && (
            <div className="rounded-xl border border-green-600/30 bg-green-600/5 p-6 space-y-3">
              <p className="text-sm font-medium text-green-700 dark:text-green-400">
                {saved.length > 0
                  ? `Saved ${saved.length} ${saved.length === 1 ? "entry" : "entries"}.`
                  : "Nothing new saved."}
              </p>

              {saved.length > 0 && (
                <ul className="text-sm divide-y divide-black/5 dark:divide-white/10">
                  {saved.map((t) => (
                    <li key={t.id} className="py-2 flex justify-between gap-4">
                      <span className="text-black/70 dark:text-white/70">
                        {t.date} · {t.description ?? t.type}
                      </span>
                      <span
                        className={`font-mono ${
                          t.type === "income"
                            ? "text-green-600 dark:text-green-500"
                            : "text-black/80 dark:text-white/80"
                        }`}
                      >
                        {t.type === "expense" ? "-" : "+"}
                        {inr.format(Number(t.amount))}
                      </span>
                    </li>
                  ))}
                </ul>
              )}

              {skipped.length > 0 && (
                <div className="rounded-md border border-amber-500/40 bg-amber-500/10 p-3 text-xs whitespace-pre-line">
                  <p className="font-medium mb-1">
                    Skipped {skipped.length} likely duplicate
                    {skipped.length === 1 ? "" : "s"}:
                  </p>
                  {skipped.join("\n")}
                </div>
              )}

              <Link
                href="/data"
                className="inline-block text-sm underline hover:no-underline"
              >
                View all imports &amp; data
              </Link>
            </div>
          )}
        </>
      )}
    </main>
  );
}
