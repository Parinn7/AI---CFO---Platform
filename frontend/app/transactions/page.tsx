/**
 * Transactions management (Phase 3.5, FR-2.5). Auth-guarded. Lists all of the
 * company's transactions (upload + manual) and lets the user edit any field
 * inline or delete a row. Backed by PATCH/DELETE /transactions/{id}.
 */

"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { useAuth } from "@/contexts/AuthContext";
import {
  ApiError,
  deleteTransaction,
  listCategories,
  listCompanies,
  listTransactions,
  updateTransaction,
  type Category,
  type Company,
  type Transaction,
} from "@/lib/api";

const inr = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  maximumFractionDigits: 2,
});

type Draft = {
  date: string;
  amount: string;
  description: string;
  category_id: string;
  type: "income" | "expense";
};

export default function TransactionsPage() {
  const { user, token, loading: authLoading } = useAuth();
  const router = useRouter();

  const [company, setCompany] = useState<Company | null>(null);
  const [categories, setCategories] = useState<Category[]>([]);
  const [txns, setTxns] = useState<Transaction[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  useEffect(() => {
    if (!authLoading && !user) router.replace("/login");
  }, [authLoading, user, router]);

  const load = useCallback(async () => {
    if (!token) return;
    try {
      const companies = await listCompanies(token);
      const c = companies[0] ?? null;
      setCompany(c);
      if (c) {
        const [cats, list] = await Promise.all([
          listCategories(c.id, token),
          listTransactions(c.id, token),
        ]);
        setCategories(cats);
        setTxns(list);
      }
    } catch {
      setError("Couldn't load your transactions.");
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    // Fetch-on-mount; load() only setState()s after awaited requests.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (token) load();
  }, [token, load]);

  const categoryName = useCallback(
    (id: string | null) =>
      id ? (categories.find((c) => c.id === id)?.name ?? "—") : "Uncategorized",
    [categories],
  );

  function startEdit(t: Transaction) {
    setError(null);
    setEditingId(t.id);
    setDraft({
      date: t.date,
      amount: t.amount,
      description: t.description ?? "",
      category_id: t.category_id ?? "",
      type: t.type,
    });
  }

  function cancelEdit() {
    setEditingId(null);
    setDraft(null);
  }

  async function saveEdit(id: string) {
    if (!token || !draft) return;
    const n = Number(draft.amount);
    if (!Number.isFinite(n) || n <= 0) {
      setError("Amount must be a positive number.");
      return;
    }
    setBusyId(id);
    setError(null);
    try {
      const updated = await updateTransaction(
        id,
        {
          date: draft.date,
          amount: draft.amount,
          description: draft.description.trim() || null,
          category_id: draft.category_id || null,
          type: draft.type,
        },
        token,
      );
      setTxns((prev) => prev.map((t) => (t.id === id ? updated : t)));
      cancelEdit();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't save changes.");
    } finally {
      setBusyId(null);
    }
  }

  async function onDelete(id: string) {
    if (!token) return;
    if (!window.confirm("Delete this transaction? This can't be undone.")) return;
    setBusyId(id);
    setError(null);
    try {
      await deleteTransaction(id, token);
      setTxns((prev) => prev.filter((t) => t.id !== id));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't delete.");
    } finally {
      setBusyId(null);
    }
  }

  if (authLoading || !user || loading) {
    return (
      <main className="flex-1 flex items-center justify-center p-8">
        <p className="text-sm text-black/50 dark:text-white/50">Loading…</p>
      </main>
    );
  }

  const cellInput =
    "w-full rounded border border-black/15 dark:border-white/20 bg-transparent px-2 py-1 text-sm outline-none focus:border-black/40 dark:focus:border-white/40";

  return (
    <main className="flex-1 w-full max-w-5xl mx-auto flex flex-col gap-6 p-8">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Transactions</h1>
        <div className="flex items-center gap-3 text-sm">
          <Link href="/data" className="underline hover:no-underline text-black/60 dark:text-white/60">
            Import
          </Link>
          <Link href="/dashboard" className="underline hover:no-underline text-black/60 dark:text-white/60">
            Dashboard
          </Link>
        </div>
      </div>

      {error && (
        <p className="text-sm text-red-500" role="alert">
          {error}
        </p>
      )}

      {!company ? (
        <div className="rounded-xl border border-black/10 dark:border-white/15 p-6">
          <p className="text-sm text-black/70 dark:text-white/70">
            Set up your company first.{" "}
            <Link href="/company" className="underline hover:no-underline">
              Company profile
            </Link>
          </p>
        </div>
      ) : txns.length === 0 ? (
        <div className="rounded-xl border border-black/10 dark:border-white/15 p-6">
          <p className="text-sm text-black/70 dark:text-white/70">
            No transactions yet.{" "}
            <Link href="/data" className="underline hover:no-underline">
              Import a file
            </Link>{" "}
            or{" "}
            <Link href="/data/manual" className="underline hover:no-underline">
              enter data manually
            </Link>
            .
          </p>
        </div>
      ) : (
        <div className="rounded-xl border border-black/10 dark:border-white/15 overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-black/50 dark:text-white/50">
              <tr className="border-b border-black/10 dark:border-white/15">
                <th className="p-3 font-medium">Date</th>
                <th className="p-3 font-medium">Description</th>
                <th className="p-3 font-medium">Category</th>
                <th className="p-3 font-medium">Type</th>
                <th className="p-3 font-medium text-right">Amount</th>
                <th className="p-3 font-medium">Source</th>
                <th className="p-3 font-medium text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {txns.map((t) => {
                const editing = editingId === t.id;
                const busy = busyId === t.id;
                return (
                  <tr
                    key={t.id}
                    className="border-b border-black/5 dark:border-white/10 align-top"
                  >
                    {editing && draft ? (
                      <>
                        <td className="p-2">
                          <input
                            type="date"
                            value={draft.date}
                            onChange={(e) => setDraft({ ...draft, date: e.target.value })}
                            className={cellInput}
                          />
                        </td>
                        <td className="p-2">
                          <input
                            type="text"
                            value={draft.description}
                            onChange={(e) =>
                              setDraft({ ...draft, description: e.target.value })
                            }
                            className={cellInput}
                          />
                        </td>
                        <td className="p-2">
                          <select
                            value={draft.category_id}
                            onChange={(e) =>
                              setDraft({ ...draft, category_id: e.target.value })
                            }
                            className={cellInput}
                          >
                            <option value="">Uncategorized</option>
                            {categories.map((c) => (
                              <option key={c.id} value={c.id}>
                                {c.name}
                              </option>
                            ))}
                          </select>
                        </td>
                        <td className="p-2">
                          <select
                            value={draft.type}
                            onChange={(e) =>
                              setDraft({
                                ...draft,
                                type: e.target.value as "income" | "expense",
                              })
                            }
                            className={cellInput}
                          >
                            <option value="income">Income</option>
                            <option value="expense">Expense</option>
                          </select>
                        </td>
                        <td className="p-2">
                          <input
                            type="number"
                            min="0"
                            step="0.01"
                            value={draft.amount}
                            onChange={(e) =>
                              setDraft({ ...draft, amount: e.target.value })
                            }
                            className={`${cellInput} text-right`}
                          />
                        </td>
                        <td className="p-3 capitalize text-black/50 dark:text-white/50">
                          {t.source}
                        </td>
                        <td className="p-2 text-right whitespace-nowrap">
                          <button
                            type="button"
                            onClick={() => saveEdit(t.id)}
                            disabled={busy}
                            className="text-xs font-medium underline hover:no-underline disabled:opacity-50 mr-3"
                          >
                            {busy ? "Saving…" : "Save"}
                          </button>
                          <button
                            type="button"
                            onClick={cancelEdit}
                            disabled={busy}
                            className="text-xs underline hover:no-underline text-black/50 dark:text-white/50"
                          >
                            Cancel
                          </button>
                        </td>
                      </>
                    ) : (
                      <>
                        <td className="p-3 whitespace-nowrap">{t.date}</td>
                        <td className="p-3">{t.description ?? "—"}</td>
                        <td className="p-3">{categoryName(t.category_id)}</td>
                        <td className="p-3 capitalize">{t.type}</td>
                        <td
                          className={`p-3 text-right whitespace-nowrap font-mono ${
                            t.type === "income"
                              ? "text-green-600 dark:text-green-500"
                              : "text-black/80 dark:text-white/80"
                          }`}
                        >
                          {t.type === "expense" ? "-" : "+"}
                          {inr.format(Number(t.amount))}
                        </td>
                        <td className="p-3 capitalize text-black/50 dark:text-white/50">
                          {t.source}
                        </td>
                        <td className="p-3 text-right whitespace-nowrap">
                          <button
                            type="button"
                            onClick={() => startEdit(t)}
                            disabled={busy}
                            className="text-xs font-medium underline hover:no-underline disabled:opacity-50 mr-3"
                          >
                            Edit
                          </button>
                          <button
                            type="button"
                            onClick={() => onDelete(t.id)}
                            disabled={busy}
                            className="text-xs underline hover:no-underline text-red-600 dark:text-red-500 disabled:opacity-50"
                          >
                            {busy ? "…" : "Delete"}
                          </button>
                        </td>
                      </>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </main>
  );
}
