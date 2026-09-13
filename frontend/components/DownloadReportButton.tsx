/**
 * "Download PDF" for the report screens (Phase 8.4, FR-7.4).
 *
 * One button shared by all three report types, because the only thing that
 * differs between them is which endpoint to call — the request, the busy state,
 * the failure message and the save are identical, and three copies of that is
 * three chances for one of them to leave a button spinning forever.
 *
 * The `download` prop is a thunk rather than a URL: the export endpoints need an
 * `Authorization` header, which a plain link can't send, so the file is fetched
 * and handed to the browser as a blob (see `lib/api.ts::saveFile`). Each page
 * passes a closure over exactly the arguments it is currently displaying, so the
 * PDF is always the report on screen and never the default one.
 */

"use client";

import { useState } from "react";

import { ApiError, saveFile, type DownloadedFile } from "@/lib/api";

export function DownloadReportButton({
  download,
  label = "Download PDF",
  disabled = false,
}: {
  download: () => Promise<DownloadedFile>;
  label?: string;
  disabled?: boolean;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run() {
    setBusy(true);
    setError(null);
    try {
      saveFile(await download());
    } catch (err) {
      // The report is on screen, so a failure here is about the export alone —
      // it's reported beside the button rather than replacing the page.
      setError(
        err instanceof ApiError ? err.message : "Couldn't generate the PDF.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col items-start gap-1">
      <button
        type="button"
        onClick={run}
        disabled={busy || disabled}
        aria-busy={busy}
        className="inline-flex items-center gap-2 rounded-md border border-black/15 dark:border-white/20 px-3 py-1.5 text-sm transition-colors hover:bg-black/5 dark:hover:bg-white/10 disabled:opacity-50 disabled:hover:bg-transparent"
      >
        <svg
          aria-hidden="true"
          viewBox="0 0 16 16"
          className="h-3.5 w-3.5"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="M8 1.5v8" />
          <path d="M4.5 6.5 8 10l3.5-3.5" />
          <path d="M2 11.5v1.5a1.5 1.5 0 0 0 1.5 1.5h9a1.5 1.5 0 0 0 1.5-1.5v-1.5" />
        </svg>
        {busy ? "Preparing…" : label}
      </button>
      {error && (
        <span className="text-xs text-red-500" role="alert">
          {error}
        </span>
      )}
    </div>
  );
}
