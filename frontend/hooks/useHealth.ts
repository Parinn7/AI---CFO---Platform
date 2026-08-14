/**
 * Data-fetching hook for backend health/connectivity.
 *
 * Kept as a per-feature hook (architecture §2). Uses plain fetch + local state
 * for now; server-state libraries (React Query/SWR) can be layered in later
 * without changing this hook's call sites.
 */

"use client";

import { useCallback, useEffect, useState } from "react";

import { getHealth, type HealthResponse } from "@/lib/api";

type State = {
  data: HealthResponse | null;
  loading: boolean;
  error: string | null;
};

export function useHealth() {
  const [state, setState] = useState<State>({
    data: null,
    loading: true,
    error: null,
  });

  // Only sets state after the awaited fetch, so it's safe to call from an effect.
  const load = useCallback(async () => {
    try {
      const data = await getHealth();
      setState({ data, loading: false, error: null });
    } catch (e) {
      setState({
        data: null,
        loading: false,
        error: e instanceof Error ? e.message : "Unknown error",
      });
    }
  }, []);

  // Event-handler entry point (e.g. the "Re-check" button): shows loading first.
  const refresh = useCallback(() => {
    setState((s) => ({ ...s, loading: true, error: null }));
    return load();
  }, [load]);

  useEffect(() => {
    // Fetch connectivity once on mount. The setState happens only after the
    // awaited fetch inside load(), which is a legitimate data-fetch-on-mount.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load();
  }, [load]);

  return { ...state, refresh };
}
