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

/** Error carrying the HTTP status so callers can distinguish 401/409/etc. */
export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** Pull a human-readable message out of a FastAPI error body (`detail`). */
async function errorMessage(res: Response): Promise<string> {
  try {
    const body = await res.json();
    const detail = body?.detail;
    if (typeof detail === "string") return detail;
    // 422 validation errors come back as an array of {msg, loc, ...}.
    if (Array.isArray(detail) && detail[0]?.msg) return detail[0].msg;
  } catch {
    /* fall through to the generic message */
  }
  return `Request failed: ${res.status} ${res.statusText}`;
}

export async function apiGet<T>(path: string, token?: string): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    cache: "no-store",
  });
  if (!res.ok) {
    throw new ApiError(res.status, await errorMessage(res));
  }
  return res.json() as Promise<T>;
}

export async function apiPost<T>(
  path: string,
  body: unknown,
  token?: string,
): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(body),
    cache: "no-store",
  });
  if (!res.ok) {
    throw new ApiError(res.status, await errorMessage(res));
  }
  return res.json() as Promise<T>;
}

export async function apiPatch<T>(
  path: string,
  body: unknown,
  token?: string,
): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(body),
    cache: "no-store",
  });
  if (!res.ok) {
    throw new ApiError(res.status, await errorMessage(res));
  }
  return res.json() as Promise<T>;
}

/** Multipart POST for file uploads. Deliberately does NOT set Content-Type so
 * the browser adds the multipart boundary itself. */
export async function apiUpload<T>(
  path: string,
  form: FormData,
  token?: string,
): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    method: "POST",
    headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: form,
    cache: "no-store",
  });
  if (!res.ok) {
    throw new ApiError(res.status, await errorMessage(res));
  }
  return res.json() as Promise<T>;
}

export function getHealth(): Promise<HealthResponse> {
  return apiGet<HealthResponse>("/api/v1/health");
}

// --- Auth (Phase 2.2) ---

export type AuthUser = {
  id: string;
  email: string;
  full_name: string | null;
  created_at: string;
};

export type TokenResponse = {
  access_token: string;
  token_type: string;
  user: AuthUser;
};

export function signup(input: {
  email: string;
  password: string;
  full_name?: string;
}): Promise<TokenResponse> {
  return apiPost<TokenResponse>("/api/v1/auth/signup", input);
}

export function login(input: {
  email: string;
  password: string;
}): Promise<TokenResponse> {
  return apiPost<TokenResponse>("/api/v1/auth/login", input);
}

export function getMe(token: string): Promise<AuthUser> {
  return apiGet<AuthUser>("/api/v1/auth/me", token);
}

export type PasswordResetRequestResponse = {
  message: string;
  // Present only in development (no email service) so the flow can be completed.
  reset_token?: string | null;
  reset_link?: string | null;
};

export function requestPasswordReset(
  email: string,
): Promise<PasswordResetRequestResponse> {
  return apiPost<PasswordResetRequestResponse>(
    "/api/v1/auth/password-reset/request",
    { email },
  );
}

export function resetPassword(
  token: string,
  newPassword: string,
): Promise<{ message: string }> {
  return apiPost<{ message: string }>("/api/v1/auth/password-reset/confirm", {
    token,
    new_password: newPassword,
  });
}

// --- Companies (Phase 2.3) ---

export type Company = {
  id: string;
  owner_user_id: string;
  name: string;
  industry: string | null;
  fiscal_year_start_month: number | null;
  currency: string;
  created_at: string;
  updated_at: string;
};

export type CompanyInput = {
  name: string;
  industry?: string | null;
  fiscal_year_start_month?: number | null;
};

export function listCompanies(token: string): Promise<Company[]> {
  return apiGet<Company[]>("/api/v1/companies", token);
}

export function createCompany(
  input: CompanyInput,
  token: string,
): Promise<Company> {
  return apiPost<Company>("/api/v1/companies", input, token);
}

export function updateCompany(
  id: string,
  input: Partial<CompanyInput>,
  token: string,
): Promise<Company> {
  return apiPatch<Company>(`/api/v1/companies/${id}`, input, token);
}

// --- Uploads & transactions (Phase 3.2) ---

export type Transaction = {
  id: string;
  company_id: string;
  category_id: string | null;
  source: "upload" | "manual";
  upload_batch_id: string | null;
  date: string;
  description: string | null;
  amount: string; // numeric(14,2) serialized as a string, e.g. "120000.00"
  type: "income" | "expense";
  is_flagged_anomaly: boolean;
  created_at: string;
};

export type UploadBatch = {
  id: string;
  company_id: string;
  filename: string;
  status: "processing" | "completed" | "failed";
  row_count: number;
  error_log: string | null;
  created_at: string;
};

export type UploadResult = {
  batch: UploadBatch;
  transactions: Transaction[];
};

export function uploadFile(
  companyId: string,
  file: File,
  token: string,
): Promise<UploadResult> {
  const form = new FormData();
  form.append("company_id", companyId);
  form.append("file", file);
  return apiUpload<UploadResult>("/api/v1/uploads", form, token);
}

export function listUploads(
  companyId: string,
  token: string,
): Promise<UploadBatch[]> {
  return apiGet<UploadBatch[]>(
    `/api/v1/uploads?company_id=${encodeURIComponent(companyId)}`,
    token,
  );
}

export function getUpload(
  batchId: string,
  token: string,
): Promise<UploadResult> {
  return apiGet<UploadResult>(`/api/v1/uploads/${batchId}`, token);
}
