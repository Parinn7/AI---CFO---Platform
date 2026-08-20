/**
 * Landing-page auth affordance. Shows Log in / Sign up when signed out, or a
 * link into the dashboard plus Log out when a session is active.
 */

"use client";

import Link from "next/link";

import { useAuth } from "@/contexts/AuthContext";

export function AuthNav() {
  const { user, loading, logout } = useAuth();

  if (loading) {
    return <div className="h-10" aria-hidden />;
  }

  const primary =
    "rounded-md bg-foreground text-background px-4 py-2 text-sm font-medium hover:opacity-90 transition-opacity";
  const secondary =
    "rounded-md border border-black/15 dark:border-white/20 px-4 py-2 text-sm font-medium hover:bg-black/5 dark:hover:bg-white/10 transition-colors";

  if (user) {
    return (
      <div className="flex items-center gap-3">
        <Link href="/dashboard" className={primary}>
          Go to dashboard
        </Link>
        <button type="button" onClick={logout} className={secondary}>
          Log out
        </button>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-3">
      <Link href="/login" className={secondary}>
        Log in
      </Link>
      <Link href="/signup" className={primary}>
        Sign up
      </Link>
    </div>
  );
}
