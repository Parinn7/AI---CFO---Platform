/**
 * Company profile page (Phase 2.3, FR-1.3). Auth-guarded. Loads the user's
 * company; if none exists it shows the create form, otherwise an edit form
 * pre-filled with the current profile. MVP treats the first company as "your"
 * profile (the model supports more, but the UI manages one).
 */

"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { CompanyForm } from "@/components/CompanyForm";
import { useAuth } from "@/contexts/AuthContext";
import { listCompanies, type Company } from "@/lib/api";

export default function CompanyPage() {
  const { user, token, loading: authLoading } = useAuth();
  const router = useRouter();

  const [company, setCompany] = useState<Company | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Redirect unauthenticated visitors to login.
  useEffect(() => {
    if (!authLoading && !user) {
      router.replace("/login");
    }
  }, [authLoading, user, router]);

  const load = useCallback(async () => {
    if (!token) return;
    try {
      const companies = await listCompanies(token);
      setCompany(companies[0] ?? null);
    } catch {
      setError("Couldn't load your company profile.");
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    // Fetch-on-mount: load() only setState()s after its awaited request.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (token) load();
  }, [token, load]);

  if (authLoading || !user || loading) {
    return (
      <main className="flex-1 flex items-center justify-center p-8">
        <p className="text-sm text-black/50 dark:text-white/50">Loading…</p>
      </main>
    );
  }

  return (
    <main className="flex-1 flex flex-col items-center justify-center gap-6 p-8">
      <div className="w-full max-w-md rounded-xl border border-black/10 dark:border-white/15 p-6">
        <div className="flex items-center justify-between">
          <h1 className="text-xl font-semibold">
            {company ? "Company profile" : "Set up your company"}
          </h1>
          <Link
            href="/dashboard"
            className="text-sm underline hover:no-underline text-black/60 dark:text-white/60"
          >
            Dashboard
          </Link>
        </div>

        <p className="mt-1 mb-5 text-sm text-black/60 dark:text-white/60">
          {company
            ? "Update the details of your company."
            : "Tell us about your company to get started."}
        </p>

        {error ? (
          <p className="text-sm text-red-500">{error}</p>
        ) : (
          <CompanyForm company={company} onSaved={setCompany} />
        )}
      </div>
    </main>
  );
}
