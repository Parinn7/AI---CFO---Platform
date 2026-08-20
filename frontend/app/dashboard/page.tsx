/**
 * Minimal authenticated landing area (Phase 2.2). Proves the JWT session works
 * end-to-end: it reads the current user from the auth context and redirects to
 * /login when there's no valid session. The real dashboard is built in Phase 5.
 */

"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { useAuth } from "@/contexts/AuthContext";

export default function DashboardPage() {
  const { user, loading, logout } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!loading && !user) {
      router.replace("/login");
    }
  }, [loading, user, router]);

  if (loading || !user) {
    return (
      <main className="flex-1 flex items-center justify-center p-8">
        <p className="text-sm text-black/50 dark:text-white/50">Loading…</p>
      </main>
    );
  }

  return (
    <main className="flex-1 flex flex-col items-center justify-center gap-6 p-8">
      <div className="w-full max-w-md rounded-xl border border-black/10 dark:border-white/15 p-6">
        <p className="text-sm uppercase tracking-widest text-black/50 dark:text-white/50">
          Signed in
        </p>
        <h1 className="mt-2 text-2xl font-semibold">
          Welcome{user.full_name ? `, ${user.full_name}` : ""}
        </h1>
        <p className="mt-1 text-sm text-black/60 dark:text-white/60">
          {user.email}
        </p>

        <p className="mt-4 text-sm text-black/60 dark:text-white/60">
          Set up your company profile, then import your financial data. KPIs and
          the dashboard arrive in the coming phases.
        </p>

        <div className="mt-6 flex flex-wrap items-center gap-3">
          <Link
            href="/company"
            className="rounded-md border border-black/15 dark:border-white/20 px-4 py-2 text-sm font-medium hover:bg-black/5 dark:hover:bg-white/10 transition-colors"
          >
            Company profile
          </Link>
          <Link
            href="/data"
            className="rounded-md bg-foreground text-background px-4 py-2 text-sm font-medium hover:opacity-90 transition-opacity"
          >
            Import data
          </Link>
          <button
            type="button"
            onClick={logout}
            className="rounded-md border border-black/15 dark:border-white/20 px-3 py-1.5 text-sm hover:bg-black/5 dark:hover:bg-white/10 transition-colors"
          >
            Log out
          </button>
        </div>
      </div>
    </main>
  );
}
