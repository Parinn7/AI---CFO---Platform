/**
 * Client-side auth session (Phase 2.2).
 *
 * Holds the JWT (persisted to localStorage so the session survives reloads) and
 * the current user. On mount it rehydrates from a stored token by calling
 * `/auth/me`; an invalid/expired token is cleared silently. Token-based session
 * per FR-1.2.
 *
 * Note: localStorage is a pragmatic choice for a capstone prototype. A hardened
 * production build would prefer an httpOnly cookie to reduce XSS token theft.
 */

"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import {
  getMe,
  login as apiLogin,
  signup as apiSignup,
  type AuthUser,
} from "@/lib/api";

const TOKEN_KEY = "ai_cfo_token";

type AuthContextValue = {
  user: AuthUser | null;
  token: string | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  signup: (
    email: string,
    password: string,
    fullName?: string,
  ) => Promise<void>;
  logout: () => void;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const persistToken = useCallback((next: string | null) => {
    setToken(next);
    if (typeof window === "undefined") return;
    if (next) window.localStorage.setItem(TOKEN_KEY, next);
    else window.localStorage.removeItem(TOKEN_KEY);
  }, []);

  // Rehydrate the session from a stored token on first mount.
  useEffect(() => {
    const stored =
      typeof window !== "undefined"
        ? window.localStorage.getItem(TOKEN_KEY)
        : null;
    if (!stored) {
      // Legitimate: end the one-time rehydration when there's nothing to restore.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setLoading(false);
      return;
    }
    let cancelled = false;
    getMe(stored)
      .then((me) => {
        if (cancelled) return;
        setUser(me);
        setToken(stored);
      })
      .catch(() => {
        if (cancelled) return;
        // Token invalid/expired — drop it.
        window.localStorage.removeItem(TOKEN_KEY);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const login = useCallback(
    async (email: string, password: string) => {
      const res = await apiLogin({ email, password });
      persistToken(res.access_token);
      setUser(res.user);
    },
    [persistToken],
  );

  const signup = useCallback(
    async (email: string, password: string, fullName?: string) => {
      const res = await apiSignup({
        email,
        password,
        full_name: fullName || undefined,
      });
      persistToken(res.access_token);
      setUser(res.user);
    },
    [persistToken],
  );

  const logout = useCallback(() => {
    persistToken(null);
    setUser(null);
  }, [persistToken]);

  const value = useMemo(
    () => ({ user, token, loading, login, signup, logout }),
    [user, token, loading, login, signup, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return ctx;
}
