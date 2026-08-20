/**
 * Shared login/signup form (Phase 2.2). One component, two modes — the only
 * differences are the full-name field, the submit label, and which auth action
 * runs. On success it redirects to the dashboard.
 */

"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { useAuth } from "@/contexts/AuthContext";
import { ApiError } from "@/lib/api";

type Mode = "login" | "signup";

const COPY: Record<Mode, { title: string; cta: string; alt: string; altHref: string; altLabel: string }> = {
  login: {
    title: "Log in",
    cta: "Log in",
    alt: "Need an account?",
    altHref: "/signup",
    altLabel: "Sign up",
  },
  signup: {
    title: "Create your account",
    cta: "Sign up",
    alt: "Already have an account?",
    altHref: "/login",
    altLabel: "Log in",
  },
};

export function AuthForm({ mode, notice }: { mode: Mode; notice?: string }) {
  const router = useRouter();
  const { login, signup } = useAuth();
  const copy = COPY[mode];

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      if (mode === "signup") {
        await signup(email, password, fullName);
      } else {
        await login(email, password);
      }
      router.push("/dashboard");
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "Something went wrong. Please try again.",
      );
      setSubmitting(false);
    }
  }

  const inputClass =
    "w-full rounded-md border border-black/15 dark:border-white/20 bg-transparent px-3 py-2 text-sm outline-none focus:border-black/40 dark:focus:border-white/40";

  return (
    <div className="w-full max-w-sm rounded-xl border border-black/10 dark:border-white/15 p-6">
      <h1 className="text-xl font-semibold">{copy.title}</h1>

      {notice && (
        <p
          className="mt-4 rounded-md border border-green-600/30 bg-green-600/10 p-2 text-sm text-green-700 dark:text-green-400"
          role="status"
        >
          {notice}
        </p>
      )}

      <form onSubmit={onSubmit} className="mt-5 space-y-4">
        {mode === "signup" && (
          <div className="space-y-1">
            <label htmlFor="fullName" className="block text-sm font-medium">
              Full name <span className="text-black/40 dark:text-white/40">(optional)</span>
            </label>
            <input
              id="fullName"
              type="text"
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              autoComplete="name"
              className={inputClass}
            />
          </div>
        )}

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

        <div className="space-y-1">
          <div className="flex items-center justify-between">
            <label htmlFor="password" className="block text-sm font-medium">
              Password
            </label>
            {mode === "login" && (
              <Link
                href="/forgot-password"
                className="text-xs text-black/50 dark:text-white/50 underline hover:no-underline"
              >
                Forgot password?
              </Link>
            )}
          </div>
          <input
            id="password"
            type="password"
            required
            minLength={mode === "signup" ? 8 : undefined}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete={mode === "signup" ? "new-password" : "current-password"}
            className={inputClass}
          />
          {mode === "signup" && (
            <p className="text-xs text-black/40 dark:text-white/40">
              At least 8 characters.
            </p>
          )}
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
          {submitting ? "Please wait…" : copy.cta}
        </button>
      </form>

      <p className="mt-4 text-sm text-black/60 dark:text-white/60">
        {copy.alt}{" "}
        <Link href={copy.altHref} className="underline hover:no-underline">
          {copy.altLabel}
        </Link>
      </p>
    </div>
  );
}
