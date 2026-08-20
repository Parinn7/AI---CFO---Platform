import Link from "next/link";

import { BackendStatus } from "@/components/BackendStatus";
import { AuthNav } from "@/components/AuthNav";

export default function Home() {
  return (
    <main className="flex-1 flex flex-col items-center justify-center gap-8 p-8">
      <div className="text-center max-w-xl">
        <p className="text-sm uppercase tracking-widest text-black/50 dark:text-white/50">
          Capstone Prototype
        </p>
        <h1 className="mt-2 text-3xl sm:text-4xl font-semibold">
          AI-Powered Financial Operating System
        </h1>
        <p className="mt-3 text-black/60 dark:text-white/60">
          A financial operating system for startups and SMEs — upload or enter
          your data and get KPIs, scenarios, and an AI CFO in plain language.
        </p>
      </div>

      <AuthNav />

      <BackendStatus />

      <p className="text-xs text-black/40 dark:text-white/40">
        Next: company setup &amp; data input.{" "}
        <Link href="/signup" className="underline hover:no-underline">
          Get started
        </Link>
      </p>
    </main>
  );
}
