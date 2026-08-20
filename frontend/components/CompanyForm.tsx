/**
 * Company profile form (Phase 2.3, FR-1.3). One component for both create and
 * edit — when `company` is null it creates, otherwise it PATCHes. Currency is
 * shown read-only (INR-only MVP; the backend ignores any client currency).
 */

"use client";

import { useState, type FormEvent } from "react";

import { useAuth } from "@/contexts/AuthContext";
import {
  ApiError,
  createCompany,
  updateCompany,
  type Company,
} from "@/lib/api";

const MONTHS = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

export function CompanyForm({
  company,
  onSaved,
}: {
  company: Company | null;
  onSaved: (c: Company) => void;
}) {
  const { token } = useAuth();
  const isEdit = company !== null;

  const [name, setName] = useState(company?.name ?? "");
  const [industry, setIndustry] = useState(company?.industry ?? "");
  const [fiscalMonth, setFiscalMonth] = useState<string>(
    company?.fiscal_year_start_month
      ? String(company.fiscal_year_start_month)
      : "",
  );
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!token) return;
    setError(null);
    setSaved(false);
    setSubmitting(true);

    const payload = {
      name: name.trim(),
      industry: industry.trim() || null,
      fiscal_year_start_month: fiscalMonth ? Number(fiscalMonth) : null,
    };

    try {
      const result = isEdit
        ? await updateCompany(company.id, payload, token)
        : await createCompany(payload, token);
      setSaved(true);
      onSaved(result);
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "Something went wrong. Please try again.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  const inputClass =
    "w-full rounded-md border border-black/15 dark:border-white/20 bg-transparent px-3 py-2 text-sm outline-none focus:border-black/40 dark:focus:border-white/40";

  return (
    <form onSubmit={onSubmit} className="space-y-4">
      <div className="space-y-1">
        <label htmlFor="name" className="block text-sm font-medium">
          Company name
        </label>
        <input
          id="name"
          type="text"
          required
          value={name}
          onChange={(e) => setName(e.target.value)}
          className={inputClass}
        />
      </div>

      <div className="space-y-1">
        <label htmlFor="industry" className="block text-sm font-medium">
          Industry{" "}
          <span className="text-black/40 dark:text-white/40">(optional)</span>
        </label>
        <input
          id="industry"
          type="text"
          value={industry}
          onChange={(e) => setIndustry(e.target.value)}
          placeholder="e.g. Retail, SaaS, Manufacturing"
          className={inputClass}
        />
      </div>

      <div className="space-y-1">
        <label htmlFor="fiscalMonth" className="block text-sm font-medium">
          Fiscal year start month{" "}
          <span className="text-black/40 dark:text-white/40">(optional)</span>
        </label>
        <select
          id="fiscalMonth"
          value={fiscalMonth}
          onChange={(e) => setFiscalMonth(e.target.value)}
          className={inputClass}
        >
          <option value="">Not set</option>
          {MONTHS.map((label, i) => (
            <option key={label} value={i + 1}>
              {label}
            </option>
          ))}
        </select>
        <p className="text-xs text-black/40 dark:text-white/40">
          In India the financial year usually starts in April.
        </p>
      </div>

      <div className="space-y-1">
        <label htmlFor="currency" className="block text-sm font-medium">
          Currency
        </label>
        <input
          id="currency"
          type="text"
          value="INR (₹)"
          disabled
          className={`${inputClass} opacity-60 cursor-not-allowed`}
        />
        <p className="text-xs text-black/40 dark:text-white/40">
          This prototype is INR-only.
        </p>
      </div>

      {error && (
        <p className="text-sm text-red-500" role="alert">
          {error}
        </p>
      )}
      {saved && !error && (
        <p className="text-sm text-green-600 dark:text-green-500" role="status">
          Saved.
        </p>
      )}

      <button
        type="submit"
        disabled={submitting}
        className="w-full rounded-md bg-foreground text-background px-4 py-2 text-sm font-medium hover:opacity-90 disabled:opacity-50 transition-opacity"
      >
        {submitting
          ? "Saving…"
          : isEdit
            ? "Save changes"
            : "Create company profile"}
      </button>
    </form>
  );
}
