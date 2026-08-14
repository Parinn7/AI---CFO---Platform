import { BackendStatus } from "@/components/BackendStatus";

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
          Frontend scaffolding is live. The panel below confirms the Next.js
          frontend can reach the FastAPI backend end-to-end — the Phase 1 goal.
        </p>
      </div>

      <BackendStatus />

      <p className="text-xs text-black/40 dark:text-white/40">
        Next: authentication &amp; company setup (Phase 2).
      </p>
    </main>
  );
}
