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

export async function apiDelete(path: string, token?: string): Promise<void> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    method: "DELETE",
    headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    cache: "no-store",
  });
  if (!res.ok) {
    throw new ApiError(res.status, await errorMessage(res));
  }
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

// --- Categories & manual entry (Phase 3.3) ---

export type Category = {
  id: string;
  company_id: string | null; // null = system default
  name: string;
  type: "income" | "expense";
};

export type ManualEntryInput = {
  date: string;
  amount: string;
  category_id?: string | null;
  type?: "income" | "expense" | null;
  description?: string | null;
};

export function listCategories(
  companyId: string,
  token: string,
): Promise<Category[]> {
  return apiGet<Category[]>(
    `/api/v1/categories?company_id=${encodeURIComponent(companyId)}`,
    token,
  );
}

export type ManualEntryResult = {
  created: Transaction[];
  skipped_duplicates: string[];
};

export function createManualTransactions(
  companyId: string,
  transactions: ManualEntryInput[],
  token: string,
): Promise<ManualEntryResult> {
  return apiPost<ManualEntryResult>(
    "/api/v1/transactions",
    { company_id: companyId, transactions },
    token,
  );
}

export function listTransactions(
  companyId: string,
  token: string,
): Promise<Transaction[]> {
  return apiGet<Transaction[]>(
    `/api/v1/transactions?company_id=${encodeURIComponent(companyId)}`,
    token,
  );
}

export type TransactionUpdate = {
  date?: string;
  amount?: string;
  category_id?: string | null;
  type?: "income" | "expense";
  description?: string | null;
};

export function updateTransaction(
  id: string,
  patch: TransactionUpdate,
  token: string,
): Promise<Transaction> {
  return apiPatch<Transaction>(`/api/v1/transactions/${id}`, patch, token);
}

export function deleteTransaction(id: string, token: string): Promise<void> {
  return apiDelete(`/api/v1/transactions/${id}`, token);
}

export type AutoCategorizeResult = {
  categorized: number;
  uncategorized_remaining: number;
};

export function autoCategorize(
  companyId: string,
  token: string,
): Promise<AutoCategorizeResult> {
  return apiPost<AutoCategorizeResult>(
    "/api/v1/transactions/auto-categorize",
    { company_id: companyId },
    token,
  );
}

// --- Anomaly detection (4.5, FR-3.6) ---

export type AnomalyDetectionResult = {
  flagged: number;
  expenses_scanned: number;
};

export function detectAnomalies(
  companyId: string,
  token: string,
): Promise<AnomalyDetectionResult> {
  return apiPost<AnomalyDetectionResult>(
    "/api/v1/transactions/detect-anomalies",
    { company_id: companyId },
    token,
  );
}

// --- Financial engine: revenue/expense totals + cash flow (4.2, FR-3.2/3.3) ---

export type FinancialSummary = {
  company_id: string;
  start_date: string | null;
  end_date: string | null;
  total_income: string;
  total_expenses: string;
  net: string;
  income_count: number;
  expense_count: number;
};

export type MonthlyCashFlow = {
  month: string; // "YYYY-MM"
  inflow: string;
  outflow: string;
  net: string;
};

export type CashFlowResponse = {
  company_id: string;
  start_date: string | null;
  end_date: string | null;
  months: MonthlyCashFlow[];
};

function rangeQuery(
  companyId: string,
  startDate?: string,
  endDate?: string,
): string {
  const params = new URLSearchParams({ company_id: companyId });
  if (startDate) params.set("start_date", startDate);
  if (endDate) params.set("end_date", endDate);
  return params.toString();
}

export function getFinancialSummary(
  companyId: string,
  token: string,
  startDate?: string,
  endDate?: string,
): Promise<FinancialSummary> {
  return apiGet<FinancialSummary>(
    `/api/v1/financial/summary?${rangeQuery(companyId, startDate, endDate)}`,
    token,
  );
}

export function getCashFlow(
  companyId: string,
  token: string,
  startDate?: string,
  endDate?: string,
): Promise<CashFlowResponse> {
  return apiGet<CashFlowResponse>(
    `/api/v1/financial/cash-flow?${rangeQuery(companyId, startDate, endDate)}`,
    token,
  );
}

// --- Historical performance / 12-month view (4.4, FR-3.5/FR-4.6) ---

export type MonthlyPerformance = {
  month: string; // "YYYY-MM"
  revenue: string;
  expenses: string;
  net_cash_flow: string;
  margin_pct: string | null; // null when revenue is 0
};

export type HistoryResponse = {
  company_id: string;
  num_months: number;
  end_month: string; // "YYYY-MM"
  months: MonthlyPerformance[];
};

export function getHistory(
  companyId: string,
  token: string,
  months?: number,
  endMonth?: string,
): Promise<HistoryResponse> {
  const params = new URLSearchParams({ company_id: companyId });
  if (months) params.set("months", String(months));
  if (endMonth) params.set("end_month", endMonth);
  return apiGet<HistoryResponse>(
    `/api/v1/financial/history?${params.toString()}`,
    token,
  );
}

// --- KPI snapshots: burn rate, runway, margins, revenue growth (4.3, FR-4.x) ---

export type KpiSnapshot = {
  id: string;
  company_id: string;
  period_start: string;
  period_end: string;
  total_revenue: string;
  total_expenses: string;
  net_cash_flow: string;
  burn_rate: string;
  // null in their undefined cases: not burning cash / zero revenue / no prior period.
  runway_months: string | null;
  gross_margin_pct: string | null;
  operating_margin_pct: string | null;
  revenue_growth_pct: string | null;
  created_at: string;
};

export function generateKpiSnapshot(
  input: { company_id: string; period_start: string; period_end: string },
  token: string,
): Promise<KpiSnapshot> {
  return apiPost<KpiSnapshot>("/api/v1/financial/kpi-snapshots", input, token);
}

export function listKpiSnapshots(
  companyId: string,
  token: string,
): Promise<KpiSnapshot[]> {
  return apiGet<KpiSnapshot[]>(
    `/api/v1/financial/kpi-snapshots?company_id=${companyId}`,
    token,
  );
}

// --- Scenario simulator (6.2, FR-5.2/FR-5.3) ---

/** The scenario levers, as *sent*. Mirrors `lib/scenarios.ts`'s
 * `ScenarioAssumptions` and the backend's `ScenarioAssumptionsIn` — all three
 * agree on names + bounds. */
export type ScenarioAssumptionsPayload = {
  new_hires: number;
  avg_salary_per_hire: number;
  marketing_change_pct: number;
  pricing_change_pct: number;
  revenue_change_pct: number;
};

/** The same levers, as *read back*. Every money/percentage field is a backend
 * `Decimal`, which serialises to a string like the rest of the API's figures,
 * while `new_hires` is a plain integer — so a reader must coerce rather than
 * assume. Send `ScenarioAssumptionsPayload`, read this. */
export type ScenarioAssumptionsRead = {
  [K in keyof ScenarioAssumptionsPayload]: number | string;
};

/** One side of the before/after — the same KPI set a snapshot holds. */
export type ScenarioKpis = {
  total_revenue: string;
  total_expenses: string;
  net_cash_flow: string;
  burn_rate: string;
  runway_months: string | null;
  gross_margin_pct: string | null;
  operating_margin_pct: string | null;
  revenue_growth_pct: string | null;
};

/** scenario − baseline per metric; null when either side is undefined. */
export type ScenarioDeltas = ScenarioKpis;

/** What the levers actually did, in rupees, so the comparison can explain
 * itself. `marketing_baseline` is the categorised Marketing spend the
 * percentage was applied to; `revenue_multiplier` is the combined
 * pricing × revenue factor. */
export type AppliedChanges = {
  num_months: number;
  added_payroll: string;
  marketing_baseline: string;
  marketing_change: string;
  revenue_multiplier: string;
  revenue_change: string;
};

export type ScenarioSimulation = {
  company_id: string;
  period_start: string;
  period_end: string;
  num_months: number;
  assumptions: ScenarioAssumptionsRead;
  baseline: ScenarioKpis;
  scenario: ScenarioKpis;
  deltas: ScenarioDeltas;
  applied: AppliedChanges;
};

/**
 * Recalculate cash flow, runway, profitability and growth under a hypothetical
 * (FR-5.2), returned alongside the real figures for the same period.
 *
 * Stateless — the backend persists nothing (architecture §5.2); saving is 6.4.
 * All the math is deterministic backend code, never an LLM (architecture §4.1).
 */
export function simulateScenario(
  input: {
    company_id: string;
    period_start: string;
    period_end: string;
    assumptions: ScenarioAssumptionsPayload;
  },
  token: string,
): Promise<ScenarioSimulation> {
  return apiPost<ScenarioSimulation>("/api/v1/scenarios/simulate", input, token);
}

// --- Saved scenarios (6.4, FR-5.4) ---

/**
 * A scenario the user chose to keep. `result` is the comparison **as it was
 * computed at save time** — the backend replays it from storage rather than
 * recomputing, so revisiting a scenario shows the same figures it showed when
 * saved even after new transactions land. Re-running against today's data is a
 * separate, explicit action (load it back into the form and run it).
 *
 * It has the same shape as a fresh `ScenarioSimulation`, so one component
 * renders both.
 */
export type SavedScenario = {
  id: string;
  company_id: string;
  name: string;
  assumptions: ScenarioAssumptionsRead;
  /** The `kpi_snapshots` row the comparison was made against. */
  baseline_kpi_snapshot_id: string | null;
  result: ScenarioSimulation;
  created_at: string;
};

/**
 * Save a scenario (FR-5.4). Only the levers are sent — the backend re-runs the
 * simulation itself, so a stored result is always engine output rather than
 * anything this client computed (architecture §4.1).
 */
export function saveScenario(
  input: {
    company_id: string;
    name: string;
    period_start: string;
    period_end: string;
    assumptions: ScenarioAssumptionsPayload;
  },
  token: string,
): Promise<SavedScenario> {
  return apiPost<SavedScenario>("/api/v1/scenarios", input, token);
}

/** A company's saved scenarios, newest first. Each carries its full stored
 * comparison, so opening one needs no extra request. */
export function listScenarios(
  companyId: string,
  token: string,
): Promise<SavedScenario[]> {
  return apiGet<SavedScenario[]>(
    `/api/v1/scenarios?company_id=${companyId}`,
    token,
  );
}

export function deleteScenario(id: string, token: string): Promise<void> {
  return apiDelete(`/api/v1/scenarios/${id}`, token);
}

// --- AI CFO chat (7.1–7.2, FR-6.1 / FR-6.2) ---

export type ChatMessage = {
  id: string;
  session_id: string;
  role: "user" | "assistant";
  content: string;
  /** Which precomputed KPI snapshot the assistant was given for this turn
   * (7.2) — null for user turns, and when the company has no transactions yet
   * and so no calculated figures to be grounded in. */
  kpi_context_snapshot_id: string | null;
  created_at: string;
};

/** A conversation, without its history. `preview` is the opening question,
 * which is what labels it in the list — there is no title column. */
export type ChatSession = {
  id: string;
  company_id: string;
  user_id: string;
  created_at: string;
  message_count: number;
  preview: string | null;
};

export type ChatSessionDetail = ChatSession & { messages: ChatMessage[] };

/** What you asked and what came back, as stored. Rendering these rather than
 * echoing a local copy keeps the screen and the database in agreement. */
export type ChatTurn = {
  user_message: ChatMessage;
  assistant_message: ChatMessage;
};

export function createChatSession(
  companyId: string,
  token: string,
): Promise<ChatSession> {
  return apiPost<ChatSession>(
    "/api/v1/chat/sessions",
    { company_id: companyId },
    token,
  );
}

/** A company's conversations, newest first. */
export function listChatSessions(
  companyId: string,
  token: string,
): Promise<ChatSession[]> {
  return apiGet<ChatSession[]>(
    `/api/v1/chat/sessions?company_id=${companyId}`,
    token,
  );
}

export function getChatSession(
  id: string,
  token: string,
): Promise<ChatSessionDetail> {
  return apiGet<ChatSessionDetail>(`/api/v1/chat/sessions/${id}`, token);
}

/**
 * Ask the assistant something. Only the question is sent — the role and the
 * answer are decided server-side, so this client can't write into the
 * assistant's half of the conversation.
 *
 * Until 7.4 the answer is a fixed placeholder saying the assistant isn't
 * connected yet; it quotes no figures and is not financial output.
 */
export function postChatMessage(
  sessionId: string,
  content: string,
  token: string,
): Promise<ChatTurn> {
  return apiPost<ChatTurn>(
    `/api/v1/chat/sessions/${sessionId}/messages`,
    { content },
    token,
  );
}

export function deleteChatSession(id: string, token: string): Promise<void> {
  return apiDelete(`/api/v1/chat/sessions/${id}`, token);
}

/** One precomputed figure as the assistant receives it. `value` is already
 * rendered by the backend (including "Not applicable" and why), so the screen
 * and the model are looking at the same words. */
export type ContextFigure = {
  key: string;
  label: string;
  value: string;
  meaning: string;
  note: string;
};

/** Everything the AI CFO is given about a company for one answer (FR-6.2).
 * Every number in it is a stored `kpi_snapshots` value; no transaction appears
 * anywhere — that boundary is architecture §4.1. */
export type CfoContext = {
  company_id: string;
  company_name: string;
  industry: string | null;
  currency: string;
  period_start: string;
  period_end: string;
  num_months: number;
  snapshot_id: string;
  computed_at: string;
  figures: ContextFigure[];
  rendered: string;
};

/** A company with no transactions has no computed figures — a normal state, so
 * it comes back as `available: false` with a readable reason, not an error. */
export type ChatContext = {
  company_id: string;
  available: boolean;
  unavailable_reason: string | null;
  context: CfoContext | null;
};

/** Exactly what the assistant can see. Fetched so the user can read it too —
 * an assistant whose inputs are inspectable is one you can argue with. */
export function getChatContext(
  companyId: string,
  token: string,
): Promise<ChatContext> {
  return apiGet<ChatContext>(
    `/api/v1/chat/context?company_id=${companyId}`,
    token,
  );
}

/** The standing instructions the assistant answers under (7.3, FR-6.3/FR-6.5).
 * `system_prompt` is the stable half — identical for every company;
 * `system_message` is the literal message sent, those instructions followed by
 * this company's figure block (or by one saying it has none). */
export type ChatPrompt = {
  company_id: string;
  system_prompt: string;
  system_message: string;
  max_history_messages: number;
};

/** Fetched so the rules can be read, not just claimed — the companion to
 * `getChatContext`: what the assistant is given, and what it's told to do with
 * it. */
export function getChatPrompt(
  companyId: string,
  token: string,
): Promise<ChatPrompt> {
  return apiGet<ChatPrompt>(
    `/api/v1/chat/prompt?company_id=${companyId}`,
    token,
  );
}
