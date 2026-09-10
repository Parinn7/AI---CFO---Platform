/**
 * Shared chrome for the report screens (Phase 8) — title, the app nav, and the
 * tabs between report types.
 *
 * Extracted in 8.2, when there were two reports to switch between. The tabs are
 * routes rather than local state so a particular report is a URL a founder can
 * bookmark or send to someone, and so each report page stays a page rather than
 * a branch inside one.
 *
 * `REPORT_TABS` is the single list of report types; 8.3's investor summary adds
 * one line here and nothing else.
 */

"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { useAuth } from "@/contexts/AuthContext";

const REPORT_TABS = [
  { href: "/reports", label: "Monthly" },
  { href: "/reports/board", label: "Board" },
];

export function ReportHeader({
  title,
  subtitle,
}: {
  title: string;
  subtitle: string;
}) {
  const { logout } = useAuth();
  const pathname = usePathname();

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">{title}</h1>
          <p className="mt-1 text-sm text-black/60 dark:text-white/60">{subtitle}</p>
        </div>
        <nav className="flex flex-wrap items-center gap-3 text-sm">
          <Link href="/dashboard" className="underline hover:no-underline text-black/60 dark:text-white/60">
            Dashboard
          </Link>
          <Link href="/chat" className="underline hover:no-underline text-black/60 dark:text-white/60">
            AI CFO
          </Link>
          <Link href="/scenarios" className="underline hover:no-underline text-black/60 dark:text-white/60">
            Scenarios
          </Link>
          <Link href="/transactions" className="underline hover:no-underline text-black/60 dark:text-white/60">
            Transactions
          </Link>
          <button type="button" onClick={logout}
            className="rounded-md border border-black/15 dark:border-white/20 px-3 py-1.5 hover:bg-black/5 dark:hover:bg-white/10 transition-colors">
            Log out
          </button>
        </nav>
      </header>

      <div className="flex flex-wrap gap-1 border-b border-black/10 dark:border-white/15">
        {REPORT_TABS.map((tab) => {
          const active = pathname === tab.href;
          return (
            <Link
              key={tab.href}
              href={tab.href}
              aria-current={active ? "page" : undefined}
              className={`-mb-px border-b-2 px-3 py-2 text-sm transition-colors ${
                active
                  ? "border-foreground font-medium"
                  : "border-transparent text-black/55 dark:text-white/55 hover:text-black dark:hover:text-white"
              }`}
            >
              {tab.label}
            </Link>
          );
        })}
      </div>
    </div>
  );
}
