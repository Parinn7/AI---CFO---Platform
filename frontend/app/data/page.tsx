/**
 * Data import page (Phase 3.2, FR-2.1/FR-2.2). Auth-guarded. Uploads a CSV/XLSX
 * for the user's company, then shows the resulting batch (imported count + any
 * skipped-row messages) and the parsed transactions. Also lists past imports.
 *
 * A company must exist first (uploads are company-scoped) — if none, we point
 * the user to the company setup page.
 */

"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { useAuth } from "@/contexts/AuthContext";
import {
  ApiError,
  getUpload,
  listCompanies,
  listUploads,
  uploadFile,
  type Company,
  type UploadBatch,
  type UploadResult,
} from "@/lib/api";

const inr = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  maximumFractionDigits: 2,
});

function formatAmount(amount: string, type: string) {
  const n = Number(amount);
  const sign = type === "expense" ? "-" : "+";
  return `${sign}${inr.format(n)}`;
}

export default function DataPage() {
  const { user, token, loading: authLoading } = useAuth();
  const router = useRouter();

  const [company, setCompany] = useState<Company | null>(null);
  const [batches, setBatches] = useState<UploadBatch[]>([]);
  const [loading, setLoading] = useState(true);
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [result, setResult] = useState<UploadResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!authLoading && !user) router.replace("/login");
  }, [authLoading, user, router]);

  const load = useCallback(async () => {
    if (!token) return;
    try {
      const companies = await listCompanies(token);
      const c = companies[0] ?? null;
      setCompany(c);
      if (c) setBatches(await listUploads(c.id, token));
    } catch {
      setError("Couldn't load your data.");
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    // Fetch-on-mount; load() only setState()s after awaited requests.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (token) load();
  }, [token, load]);

  async function onUpload() {
    if (!token || !company || !file) return;
    setError(null);
    setResult(null);
    setUploading(true);
    try {
      const res = await uploadFile(company.id, file, token);
      setResult(res);
      setBatches((prev) => [res.batch, ...prev]);
      setFile(null);
      if (fileInputRef.current) fileInputRef.current.value = "";
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "Upload failed. Please try again.",
      );
    } finally {
      setUploading(false);
    }
  }

  async function viewBatch(id: string) {
    if (!token) return;
    setError(null);
    try {
      setResult(await getUpload(id, token));
    } catch {
      setError("Couldn't load that import.");
    }
  }

  if (authLoading || !user || loading) {
    return (
      <main className="flex-1 flex items-center justify-center p-8">
        <p className="text-sm text-black/50 dark:text-white/50">Loading…</p>
      </main>
    );
  }

  return (
    <main className="flex-1 w-full max-w-3xl mx-auto flex flex-col gap-6 p-8">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Import data</h1>
        <div className="flex items-center gap-3 text-sm">
          <Link
            href="/transactions"
            className="underline hover:no-underline text-black/60 dark:text-white/60"
          >
            Transactions
          </Link>
          <Link
            href="/dashboard"
            className="underline hover:no-underline text-black/60 dark:text-white/60"
          >
            Dashboard
          </Link>
        </div>
      </div>

      {!company ? (
        <div className="rounded-xl border border-black/10 dark:border-white/15 p-6">
          <p className="text-sm text-black/70 dark:text-white/70">
            Set up your company first, then come back to import data.{" "}
            <Link href="/company" className="underline hover:no-underline">
              Company profile
            </Link>
          </p>
        </div>
      ) : (
        <>
          <div className="rounded-xl border border-black/10 dark:border-white/15 p-6 space-y-4">
            <p className="text-sm text-black/60 dark:text-white/60">
              Upload a CSV or Excel (.xlsx) file with your transactions. We look
              for a <strong>date</strong> and <strong>amount</strong> column;
              optional <strong>description</strong>, <strong>category</strong>,
              and <strong>type</strong> columns are used when present.
            </p>
            <p className="text-sm text-black/60 dark:text-white/60">
              Don&apos;t have a file?{" "}
              <Link href="/data/manual" className="underline hover:no-underline">
                Enter your data manually
              </Link>{" "}
              by answering a few plain-language questions.
            </p>

            <input
              ref={fileInputRef}
              type="file"
              accept=".csv,.xlsx"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              className="block w-full text-sm file:mr-4 file:rounded-md file:border-0 file:bg-foreground file:text-background file:px-4 file:py-2 file:text-sm file:font-medium hover:file:opacity-90"
            />

            {error && (
              <p className="text-sm text-red-500" role="alert">
                {error}
              </p>
            )}

            <button
              type="button"
              onClick={onUpload}
              disabled={!file || uploading}
              className="rounded-md bg-foreground text-background px-4 py-2 text-sm font-medium hover:opacity-90 disabled:opacity-50 transition-opacity"
            >
              {uploading ? "Importing…" : "Import file"}
            </button>
          </div>

          {result && (
            <div className="rounded-xl border border-black/10 dark:border-white/15 p-6 space-y-4">
              <div>
                <h2 className="font-semibold">
                  {result.batch.filename}{" "}
                  <span className="text-sm font-normal text-black/50 dark:text-white/50">
                    · {result.batch.status}
                  </span>
                </h2>
                <p className="text-sm text-black/60 dark:text-white/60">
                  {result.batch.row_count} transaction
                  {result.batch.row_count === 1 ? "" : "s"} imported.
                </p>
              </div>

              {result.batch.error_log && (
                <div className="rounded-md border border-amber-500/40 bg-amber-500/10 p-3 text-xs whitespace-pre-line">
                  <p className="font-medium mb-1">Some rows were skipped:</p>
                  {result.batch.error_log}
                </div>
              )}

              {result.transactions.length > 0 && (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead className="text-left text-black/50 dark:text-white/50">
                      <tr className="border-b border-black/10 dark:border-white/15">
                        <th className="py-2 pr-4 font-medium">Date</th>
                        <th className="py-2 pr-4 font-medium">Description</th>
                        <th className="py-2 pr-4 font-medium">Type</th>
                        <th className="py-2 font-medium text-right">Amount</th>
                      </tr>
                    </thead>
                    <tbody>
                      {result.transactions.map((t) => (
                        <tr
                          key={t.id}
                          className="border-b border-black/5 dark:border-white/10"
                        >
                          <td className="py-2 pr-4 whitespace-nowrap">{t.date}</td>
                          <td className="py-2 pr-4">{t.description ?? "—"}</td>
                          <td className="py-2 pr-4 capitalize">{t.type}</td>
                          <td
                            className={`py-2 text-right whitespace-nowrap font-mono ${
                              t.type === "income"
                                ? "text-green-600 dark:text-green-500"
                                : "text-black/80 dark:text-white/80"
                            }`}
                          >
                            {formatAmount(t.amount, t.type)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}

          <div className="rounded-xl border border-black/10 dark:border-white/15 p-6">
            <h2 className="font-semibold mb-3">Past imports</h2>
            {batches.length === 0 ? (
              <p className="text-sm text-black/50 dark:text-white/50">
                No imports yet.
              </p>
            ) : (
              <ul className="divide-y divide-black/5 dark:divide-white/10 text-sm">
                {batches.map((b) => (
                  <li
                    key={b.id}
                    className="py-2 flex items-center justify-between gap-4"
                  >
                    <span className="truncate">
                      {b.filename}{" "}
                      <span className="text-black/40 dark:text-white/40">
                        · {b.row_count} rows · {b.status}
                      </span>
                    </span>
                    <button
                      type="button"
                      onClick={() => viewBatch(b.id)}
                      className="text-xs underline hover:no-underline shrink-0"
                    >
                      View
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </>
      )}
    </main>
  );
}
