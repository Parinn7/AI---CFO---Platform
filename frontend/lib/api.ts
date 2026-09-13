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

/** Which language model is answering, if any (7.4, FR-6.4). `configured` is
 * false when no API key is set — the assistant then replies with a placeholder
 * rather than failing, and the chat screen says so. No key is ever exposed. */
export type ChatProvider = {
  provider: string;
  model: string;
  configured: boolean;
};

/** The third disclosure call, beside `getChatContext` (what the assistant is
 * given) and `getChatPrompt` (what it's told to do with it): who wrote the
 * words. Fetched rather than hard-coded so the banner on `/chat` can't drift
 * out of step with the server's actual configuration. */
export function getChatProvider(token: string): Promise<ChatProvider> {
  return apiGet<ChatProvider>("/api/v1/chat/provider", token);
}

/* --- Reports (Phase 8, FR-7.x) --- */

/** The company a report is about, carried on the report itself so an exported
 * copy still names its subject once it's away from the app. */
export type ReportCompany = {
  id: string;
  name: string;
  industry: string | null;
  currency: string;
};

/** One category's line in a report's breakdown. `share_pct` is a share of that
 * line's **own type** (an expense as a % of all expenses), null when the type
 * had no total to take a share of. "Uncategorized" is a real line, not an
 * omission — the lines have to add up to the totals printed above them. */
export type CategoryLine = {
  category_id: string | null;
  name: string;
  type: "income" | "expense";
  total: string;
  share_pct: string | null;
  transaction_count: number;
};

/** The month before the reported one, and the movement between them.
 * `has_data` false means nothing was recorded then — the changes are
 * differences against zero, which is true but means "no record", not "the
 * business did nothing". */
export type MonthComparison = {
  month: string;
  has_data: boolean;
  total_revenue: string;
  total_expenses: string;
  net_cash_flow: string;
  revenue_change: string;
  expenses_change: string;
  net_change: string;
};

/** A flagged expense inside the reported month (FR-3.6). */
export type ReportAnomaly = {
  id: string;
  date: string;
  description: string | null;
  category_name: string;
  amount: string;
};

/** The Monthly Financial Report (8.1, FR-7.1). Every figure is Financial Engine
 * output — `kpis` is the literal `kpi_snapshots` row the dashboard's tiles and
 * the AI CFO's context read, so all three quote one set of numbers rather than
 * three that happen to agree. No LLM writes any part of it (architecture §4.1). */
export type MonthlyReport = {
  report_type: "monthly";
  company: ReportCompany;
  month: string;
  period_start: string;
  period_end: string;
  generated_at: string;
  kpis: KpiSnapshot;
  transaction_count: number;
  income_count: number;
  expense_count: number;
  closing_cash: string;
  categories: CategoryLine[];
  comparison: MonthComparison;
  trend: MonthlyPerformance[];
  anomalies: ReportAnomaly[];
};

/** Generate the monthly report for `month` ("YYYY-MM"), or for the latest month
 * with data when omitted. `404` when the company has no transactions at all —
 * a company with nothing recorded has no month to report on. */
export function getMonthlyReport(
  companyId: string,
  token: string,
  month?: string,
): Promise<MonthlyReport> {
  const query = month ? `&month=${month}` : "";
  return apiGet<MonthlyReport>(
    `/api/v1/reports/monthly?company_id=${companyId}${query}`,
    token,
  );
}

/* --- Board Report (8.2, FR-7.2) --- */

/** One reporting period's figures, stated off a real `kpi_snapshots` row — the
 * board report states "last quarter" the same way it states "this quarter",
 * rather than one side being a snapshot and the other a hand-rolled total.
 * `has_data` false means nothing was recorded in the window: honest zeros that
 * mean "no record", not "no activity". */
export type PeriodTotals = {
  start_month: string; // "YYYY-MM"
  end_month: string; // "YYYY-MM"
  period_start: string;
  period_end: string;
  has_data: boolean;
  kpis: KpiSnapshot;
  transaction_count: number;
};

/** The movement between the previous period and this one — each field one
 * already-computed engine total minus another. Percentage growth is absent on
 * purpose: `kpis.revenue_growth_pct` already states it. */
export type PeriodMovement = {
  revenue_change: string;
  expenses_change: string;
  net_change: string;
  burn_rate_change: string;
};

/** Cash at both ends of the period. `net_change` is `closing − opening`, which
 * is the period's net cash flow by construction. */
export type CashPosition = {
  opening_cash: string;
  closing_cash: string;
  net_change: string;
};

/** Flagged spend grouped as the detection rule sees it — one category in one
 * month (FR-3.6). A board reads exposure, not individual card charges. */
export type WatchItem = {
  month: string; // "YYYY-MM"
  category_name: string;
  total: string;
  transaction_count: number;
};

/** A saved what-if (FR-5.4) as it was computed at save time — nothing is
 * re-run, so a board pack says what the plan looked like when it was modelled. */
export type ScenarioSummary = {
  id: string;
  name: string;
  created_at: string;
  period_start: string;
  period_end: string;
  revenue_change: string;
  expenses_change: string;
  net_cash_flow_change: string;
  burn_rate_change: string;
  baseline_runway_months: string | null;
  scenario_runway_months: string | null;
};

/** The Board Report (8.2, FR-7.2) — a trailing quarter or year for a reader who
 * wasn't in the building. Where the monthly report answers "what happened in
 * July", this answers "where is this heading". Every figure is Financial Engine
 * output; no LLM writes any part of it (architecture §4.1). */
export type BoardReport = {
  report_type: "board";
  company: ReportCompany;
  period: BoardPeriod;
  num_months: number;
  generated_at: string;
  current: PeriodTotals;
  previous: PeriodTotals;
  movement: PeriodMovement;
  cash: CashPosition;
  monthly: MonthlyPerformance[];
  categories: CategoryLine[];
  watch_items: WatchItem[];
  scenarios: ScenarioSummary[];
};

/** The windows a board report can be asked for: a trailing quarter (3 months)
 * or year (12), anchored on the latest month with data. */
export type BoardPeriod = "quarter" | "year";

/** Generate the board report. `endMonth` ("YYYY-MM") anchors the trailing
 * window — omit it for the latest month with data, or name it to produce a
 * calendar/fiscal quarter. `404` when the company has no transactions at all. */
export function getBoardReport(
  companyId: string,
  token: string,
  period: BoardPeriod = "quarter",
  endMonth?: string,
): Promise<BoardReport> {
  const params = new URLSearchParams({ company_id: companyId, period });
  if (endMonth) params.set("end_month", endMonth);
  return apiGet<BoardReport>(`/api/v1/reports/board?${params.toString()}`, token);
}

/* --- Investor Readiness Summary (8.3, FR-7.3) --- */

/** What the business is earning *now*, annualised. `monthly` is the latest
 * month with data — not the trailing year averaged — because a run-rate answers
 * "what is this earning today"; the year's total travels alongside in
 * `window.kpis.total_revenue` so a reader sees both. */
export type RunRate = {
  month: string; // "YYYY-MM"
  monthly: string;
  annualised: string;
};

/** How one readiness check came out. `not_applicable` means the figure it
 * grades is undefined — never a quiet pass. `ready_at`/`attention_at` are the
 * fixed thresholds the value was measured against, carried so the screen states
 * the rule instead of keeping its own copy of it. Every check is
 * higher-is-better. `detail` is template-filled prose from the engine; no LLM
 * writes it. */
export type ReadinessStatus = "ready" | "attention" | "gap" | "not_applicable";

export type ReadinessCheck = {
  key: string;
  label: string;
  status: ReadinessStatus;
  value: string | null;
  unit: "months" | "pct";
  ready_at: string;
  attention_at: string;
  detail: string;
};

/** The Investor Readiness Summary (8.3, FR-7.3) — the metrics investors
 * typically evaluate over a trailing year, and a fixed-rule checklist of how the
 * company reads against them. `overall_status` is the **weakest link**, not a
 * score: no weighted total exists, because a single grade would imply a
 * precision this data can't support. Every figure is Financial Engine output and
 * no LLM writes any part of it (architecture §4.1). */
export type InvestorSummary = {
  report_type: "investor";
  company: ReportCompany;
  num_months: number;
  generated_at: string;
  window: PeriodTotals;
  previous: PeriodTotals;
  movement: PeriodMovement;
  cash: CashPosition;
  run_rate: RunRate;
  burn_multiple: string | null;
  months_of_history: number;
  months_with_revenue: number;
  overall_status: ReadinessStatus;
  checks: ReadinessCheck[];
  monthly: MonthlyPerformance[];
  categories: CategoryLine[];
};

/** Generate the investor readiness summary. `endMonth` ("YYYY-MM") anchors the
 * trailing year — omit it for the latest month with data. `404` when the company
 * has no transactions at all. */
export function getInvestorSummary(
  companyId: string,
  token: string,
  endMonth?: string,
): Promise<InvestorSummary> {
  const params = new URLSearchParams({ company_id: companyId });
  if (endMonth) params.set("end_month", endMonth);
  return apiGet<InvestorSummary>(
    `/api/v1/reports/investor?${params.toString()}`,
    token,
  );
}

/* --- PDF export (8.4, FR-7.4) --- */

/** A downloaded file: the bytes, and the name the server gave them. */
export type DownloadedFile = { blob: Blob; filename: string };

/** Pull the filename out of a `Content-Disposition` header.
 *
 * The backend sends `attachment; filename="Acme-Monthly-Report-2026-07.pdf"`,
 * and that name is the only thing identifying the file once it's sitting in a
 * downloads folder. The header is only readable cross-origin because the
 * backend also sends `Access-Control-Expose-Headers`; `fallback` covers the
 * case where a proxy strips it anyway. */
function filenameFrom(disposition: string | null, fallback: string): string {
  const match = disposition?.match(/filename="?([^";]+)"?/);
  return match?.[1] ?? fallback;
}

/** GET a binary file with auth, as a blob.
 *
 * Not `apiGet`: the response is a PDF, not JSON, so `res.json()` would throw on
 * the bytes. Errors still come back as a JSON `detail`, so those are parsed the
 * normal way — a 404 here means "no financial data yet", exactly as it does on
 * the report endpoints themselves. */
export async function apiDownload(
  path: string,
  fallbackName: string,
  token?: string,
): Promise<DownloadedFile> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    cache: "no-store",
  });
  if (!res.ok) {
    throw new ApiError(res.status, await errorMessage(res));
  }
  return {
    blob: await res.blob(),
    filename: filenameFrom(res.headers.get("Content-Disposition"), fallbackName),
  };
}

/** Hand a downloaded file to the browser as a save.
 *
 * The file arrives over `fetch` because the endpoint needs an `Authorization`
 * header, which a plain `<a href>` navigation can't send — so the save has to
 * be driven from a temporary object URL rather than a link to the API. The URL
 * is revoked straight after; holding it keeps the whole blob in memory. */
export function saveFile({ blob, filename }: DownloadedFile): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

/** The Monthly Financial Report as a PDF (FR-7.4). Same arguments, same
 * behaviour and the same `404` as `getMonthlyReport` — it is that report,
 * rendered rather than serialised. */
export function downloadMonthlyReport(
  companyId: string,
  token: string,
  month?: string,
): Promise<DownloadedFile> {
  const params = new URLSearchParams({ company_id: companyId });
  if (month) params.set("month", month);
  return apiDownload(
    `/api/v1/reports/monthly/pdf?${params.toString()}`,
    `monthly-report${month ? `-${month}` : ""}.pdf`,
    token,
  );
}

/** The Board Report as a PDF (FR-7.4). */
export function downloadBoardReport(
  companyId: string,
  token: string,
  period: BoardPeriod,
  endMonth?: string,
): Promise<DownloadedFile> {
  const params = new URLSearchParams({ company_id: companyId, period });
  if (endMonth) params.set("end_month", endMonth);
  return apiDownload(
    `/api/v1/reports/board/pdf?${params.toString()}`,
    `board-report-${period}.pdf`,
    token,
  );
}

/** The Investor Readiness Summary as a PDF (FR-7.4). */
export function downloadInvestorSummary(
  companyId: string,
  token: string,
  endMonth?: string,
): Promise<DownloadedFile> {
  const params = new URLSearchParams({ company_id: companyId });
  if (endMonth) params.set("end_month", endMonth);
  return apiDownload(
    `/api/v1/reports/investor/pdf?${params.toString()}`,
    "investor-readiness.pdf",
    token,
  );
}
