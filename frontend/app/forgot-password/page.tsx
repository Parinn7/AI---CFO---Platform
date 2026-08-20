/**
 * Request a password reset (Phase 2.4, FR-1.4). Submits an email and always
 * shows the same confirmation, whether or not the account exists (no
 * enumeration). Since there's no email service, in development the backend
 * returns the reset link inline — we surface it here so the flow is completable.
 */

"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";

import { ApiError, requestPasswordReset } from "@/lib/api";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [devLink, setDevLink] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setMessage(null);
    setDevLink(null);
    setSubmitting(true);
    try {
      const res = await requestPasswordReset(email);
      setMessage(res.message);
      // Dev-only: no inbox, so let the user continue straight to the reset page.
      if (res.reset_token) {
        setDevLink(`/reset-password?token=${res.reset_token}`);
      }
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "Something went wrong. Please try again.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  const inputClass =
    "w-full rounded-md border border-black/15 dark:border-white/20 bg-transparent px-3 py-2 text-sm outline-none focus:border-black/40 dark:focus:border-white/40";

  return (
    <main className="flex-1 flex items-center justify-center p-8">
      <div className="w-full max-w-sm rounded-xl border border-black/10 dark:border-white/15 p-6">
        <h1 className="text-xl font-semibold">Reset your password</h1>
        <p className="mt-1 text-sm text-black/60 dark:text-white/60">
          Enter your email and we&apos;ll send you a reset link.
        </p>

        <form onSubmit={onSubmit} className="mt-5 space-y-4">
          <div className="space-y-1">
            <label htmlFor="email" className="block text-sm font-medium">
              Email
            </label>
            <input
              id="email"
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="email"
              className={inputClass}
            />
          </div>

          {error && (
            <p className="text-sm text-red-500" role="alert">
              {error}
            </p>
          )}
          {message && (
            <div
              className="text-sm text-black/70 dark:text-white/70 space-y-2"
              role="status"
            >
              <p>{message}</p>
              {devLink && (
                <p className="rounded-md border border-amber-500/40 bg-amber-500/10 p-2 text-xs">
                  Dev mode (no email service):{" "}
                  <Link href={devLink} className="underline hover:no-underline">
                    continue to reset password
                  </Link>
                </p>
              )}
            </div>
          )}

          <button
            type="submit"
            disabled={submitting}
            className="w-full rounded-md bg-foreground text-background px-4 py-2 text-sm font-medium hover:opacity-90 disabled:opacity-50 transition-opacity"
          >
            {submitting ? "Sending…" : "Send reset link"}
          </button>
        </form>

        <p className="mt-4 text-sm text-black/60 dark:text-white/60">
          Remembered it?{" "}
          <Link href="/login" className="underline hover:no-underline">
            Log in
          </Link>
        </p>
      </div>
    </main>
  );
}
