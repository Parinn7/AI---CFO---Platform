/**
 * Live backend-connectivity indicator. Confirms the frontend can reach the
 * FastAPI backend and shows the reported database status. Used on the landing
 * page as the Phase 1 end-to-end proof.
 */

"use client";

import { useHealth } from "@/hooks/useHealth";

const DB_LABEL: Record<string, string> = {
  connected: "Database connected",
  not_configured: "Database not provisioned yet",
  unreachable: "Database unreachable",
};

export function BackendStatus() {
  const { data, loading, error, refresh } = useHealth();

  let dot = "#9ca3af"; // gray — unknown/loading
  let headline = "Checking backend…";

  if (error) {
    dot = "#ef4444"; // red
    headline = "Backend unreachable";
  } else if (data) {
    dot = data.database === "connected" ? "#22c55e" : "#f59e0b"; // green / amber
    headline = "Backend connected";
  }

  return (
    <div className="rounded-xl border border-black/10 dark:border-white/15 p-5 w-full max-w-md">
      <div className="flex items-center gap-3">
        <span
          className="inline-block h-3 w-3 rounded-full"
          style={{ backgroundColor: dot }}
          aria-hidden
        />
        <span className="font-medium">{headline}</span>
      </div>

      <dl className="mt-4 space-y-1 text-sm text-black/70 dark:text-white/70">
        {loading && <div>Contacting API…</div>}
        {error && <div className="text-red-500">{error}</div>}
        {data && (
          <>
            <div className="flex justify-between gap-4">
              <dt>Service</dt>
              <dd className="font-mono">{data.service}</dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt>Environment</dt>
              <dd className="font-mono">{data.environment}</dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt>Database</dt>
              <dd className="font-mono">{DB_LABEL[data.database] ?? data.database}</dd>
            </div>
          </>
        )}
      </dl>

      <button
        type="button"
        onClick={refresh}
        className="mt-4 rounded-md border border-black/15 dark:border-white/20 px-3 py-1.5 text-sm hover:bg-black/5 dark:hover:bg-white/10 transition-colors"
      >
        Re-check
      </button>
    </div>
  );
}
