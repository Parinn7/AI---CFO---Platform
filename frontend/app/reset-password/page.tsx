/**
 * Complete a password reset (Phase 2.4, FR-1.4). Reads the `token` from the URL
 * (the reset link), takes a new password, and on success sends the user to
 * login. `useSearchParams` requires a Suspense boundary, so the form is split
 * out and wrapped below.
 */

"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState, type FormEvent } from "react";

import { ApiError, resetPassword } from "@/lib/api";

function ResetPasswordForm() {
  const router = useRouter();
  const token = useSearchParams().get("token") ?? "";

  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const inputClass =
    "w-full rounded-md border border-black/15 dark:border-white/20 bg-transparent px-3 py-2 text-sm outline-none focus:border-black/40 dark:focus:border-white/40";

  if (!token) {
    return (
      <div className="w-full max-w-sm rounded-xl border border-black/10 dark:border-white/15 p-6">
        <h1 className="text-xl font-semibold">Invalid reset link</h1>
        <p className="mt-2 text-sm text-black/60 dark:text-white/60">
          This link is missing its token.{" "}
          <Link href="/forgot-password" className="underline hover:no-underline">
            Request a new one
          </Link>
          .
        </p>
      </div>
    );
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (password !== confirm) {
      setError("Passwords don't match.");
      return;
    }
    setSubmitting(true);
    try {
      await resetPassword(token, password);
      router.push("/login?reset=1");
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "Something went wrong. Please try again.",
      );
      setSubmitting(false);
    }
  }

  return (
    <div className="w-full max-w-sm rounded-xl border border-black/10 dark:border-white/15 p-6">
      <h1 className="text-xl font-semibold">Choose a new password</h1>

      <form onSubmit={onSubmit} className="mt-5 space-y-4">
        <div className="space-y-1">
          <label htmlFor="password" className="block text-sm font-medium">
            New password
          </label>
          <input
            id="password"
            type="password"
            required
            minLength={8}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="new-password"
            className={inputClass}
          />
          <p className="text-xs text-black/40 dark:text-white/40">
            At least 8 characters.
          </p>
        </div>

        <div className="space-y-1">
          <label htmlFor="confirm" className="block text-sm font-medium">
            Confirm new password
          </label>
          <input
            id="confirm"
            type="password"
            required
            minLength={8}
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            autoComplete="new-password"
            className={inputClass}
          />
        </div>

        {error && (
          <p className="text-sm text-red-500" role="alert">
            {error}
          </p>
        )}

        <button
          type="submit"
          disabled={submitting}
          className="w-full rounded-md bg-foreground text-background px-4 py-2 text-sm font-medium hover:opacity-90 disabled:opacity-50 transition-opacity"
        >
          {submitting ? "Resetting…" : "Reset password"}
        </button>
      </form>
    </div>
  );
}

export default function ResetPasswordPage() {
  return (
    <main className="flex-1 flex items-center justify-center p-8">
      <Suspense
        fallback={
          <p className="text-sm text-black/50 dark:text-white/50">Loading…</p>
        }
      >
        <ResetPasswordForm />
      </Suspense>
    </main>
  );
}
