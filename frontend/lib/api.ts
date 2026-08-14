/**
 * API client for the FastAPI backend.
 *
 * Base URL comes from NEXT_PUBLIC_API_URL (see `.env.local.example`), defaulting
 * to the local backend. Feature-specific calls are added alongside this as each
 * phase is built; for now it exposes the health check used to confirm the
 * frontend and backend can talk to each other.
 */

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type HealthResponse = {
  status: string;
  service: string;
  environment: string;
  database: "connected" | "not_configured" | "unreachable";
};

export async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    headers: { "Content-Type": "application/json" },
    cache: "no-store",
  });
  if (!res.ok) {
    throw new Error(`Request failed: ${res.status} ${res.statusText}`);
  }
  return res.json() as Promise<T>;
}

export function getHealth(): Promise<HealthResponse> {
  return apiGet<HealthResponse>("/api/v1/health");
}
