# System Architecture

## AI-Powered Financial Operating System for Startups and SMEs

**Version:** 1.0 (Draft)

---

## 1. Architecture Overview

The system follows a standard three-tier architecture with an integrated AI layer:

```
┌─────────────────────────────────────────────────┐
│                   Frontend (Next.js)             │
│   Dashboard · Upload/Entry Forms · Scenario UI   │
│   AI CFO Chat UI · Reports View                  │
└───────────────────────┬───────────────────────────┘
                         │ REST (JSON, HTTPS)
┌───────────────────────▼───────────────────────────┐
│                Backend (FastAPI, Python)          │
│  ┌───────────────┐ ┌───────────────┐ ┌──────────┐│
│  │ Auth Service  │ │ Financial     │ │ Report   ││
│  │               │ │ Engine        │ │ Generator││
│  └───────────────┘ └───────────────┘ └──────────┘│
│  ┌───────────────┐ ┌───────────────┐              │
│  │ Scenario      │ │ AI CFO        │              │
│  │ Simulator     │ │ Orchestrator  │              │
│  └───────────────┘ └───────┬───────┘              │
└───────────────────────┬────┼───────────────────────┘
                         │    │
              ┌──────────▼┐  ┌▼─────────────────┐
              │ PostgreSQL │  │ LLM API           │
              │ (primary   │  │ (OpenAI / Gemini) │
              │  data store)│ └───────────────────┘
              └────────────┘
```

## 2. Frontend Architecture

- **Framework:** Next.js (React) with Tailwind CSS
- **Structure:**
  - `/app` or `/pages` — route-level pages (dashboard, upload, scenarios, chat, reports, auth)
  - `/components` — reusable UI components (charts, tables, forms, chat bubble, KPI cards)
  - `/lib` — API client, auth helpers, formatting utilities
  - `/hooks` — data-fetching hooks per feature (e.g., `useDashboardData`, `useScenarios`)
- **State management:** React Query (or SWR) for server state; local component state for UI-only state. No need for a heavier global store (Redux) at MVP scale.
- **Charts:** a charting library (e.g., Recharts) for KPI trends, cash flow, scenario comparisons.

## 3. Backend Architecture

- **Framework:** FastAPI (Python), organized by domain module rather than by technical layer, so each feature is self-contained:

```
/backend
  /app
    /auth          # signup, login, session/token handling
    /companies      # company profile CRUD
    /transactions   # upload parsing, manual entry, categorization
    /financial_engine  # revenue/expense calc, cash flow, KPIs, anomaly detection
    /scenarios      # scenario simulation logic
    /ai_cfo         # LLM orchestration, prompt construction, chat history
    /reports        # report generation, PDF export
    /core           # config, db session, security utils, shared schemas
  /tests
```

- **API style:** REST, versioned under `/api/v1/`
- **Auth:** JWT-based session tokens; password hashing via bcrypt. Each auth module is split into `security.py` (stateless hashing + JWT encode/decode), `service.py` (DB-backed user creation and credential checks), `schemas.py`, `dependencies.py` (`get_current_user` resolves a Bearer token → `User`, the reusable guard for all protected routes), and `router.py`. Implemented endpoints (task 2.2):
  - `POST /api/v1/auth/signup` — create account, returns `{access_token, token_type, user}` (auto-login); `409` if email taken.
  - `POST /api/v1/auth/login` — verify credentials, returns the same token payload; `401` on bad credentials.
  - `GET /api/v1/auth/me` — returns the authenticated user; requires `Authorization: Bearer <token>`.
  - `POST /api/v1/auth/password-reset/request` — always `200` with a generic message (no account enumeration). No email provider is wired up, so the reset link is logged server-side and, in `development` only, returned inline (`reset_token`/`reset_link`) so the flow is demoable without an inbox.
  - `POST /api/v1/auth/password-reset/confirm` — sets a new password given a valid token; `400` if invalid/expired/used.
- **Token types:** access tokens and reset tokens are both signed JWTs but carry a `type` claim (`access`/`reset`) that each decoder verifies, so one kind can't be replayed as the other. Reset tokens are stateless and single-use *without* a DB table: they embed a fingerprint (`pwf`) of the user's current password hash, which stops matching once the password changes (task 2.4).
- **Companies:** `app/companies/` mirrors the auth split (`schemas.py`/`service.py`/`router.py`). Every endpoint depends on `get_current_user` and every query is scoped by `owner_user_id`, so a user can only see/mutate their own companies (NFR-3). `currency` is server-fixed to INR (not a client input). Implemented endpoints (task 2.3, FR-1.3):
  - `POST /api/v1/companies` — create a company profile for the current user (`201`).
  - `GET /api/v1/companies` — list the current user's companies.
  - `GET /api/v1/companies/{id}` — get one; `404` if it isn't the caller's (existence not leaked).
  - `PATCH /api/v1/companies/{id}` — partial update (name/industry/fiscal-year-start-month); `404` if not owned.
- **Data input — uploads (`app/transactions/`):** CSV/XLSX import (task 3.2, FR-2.1/FR-2.2). `parsing.py` is **DB-free and unit-tested** — it maps real-world headers to standard fields by normalised aliases (e.g. "Transaction Date"→date, "Amount (INR)"→amount, "Narration"→description), parses Indian-format amounts, and skips unparseable rows with per-row messages instead of failing the file (NFR-6). `service.py` resolves each row's category (case-insensitive name match against the company's + system-default categories) and its final `type`, then persists an `UploadBatch` + `Transaction`s. All routes are `get_current_user`-guarded and company-owner-scoped. Endpoints:
  - `POST /api/v1/uploads` — multipart (`file` + `company_id`); imports and returns the batch + created transactions (`201`); `400` on unsupported type / missing date+amount columns / oversize (10 MB), `404` if the company isn't the caller's.
  - `GET /api/v1/uploads?company_id=` — list a company's import batches.
  - `GET /api/v1/uploads/{id}` — one batch + its transactions.
- **Data input — guided manual entry (task 3.3, FR-2.3):** manual entry is a **first-class** path, not a fallback (SRS). The frontend `/data/manual` asks plain-language questions ("How much did you spend on rent?"), one per category, for a single date — no accounting form. Answered prompts POST as manual transactions that land in the **same `transactions` table** as uploads (`source="manual"`, null `upload_batch_id`), so they feed KPIs/dashboard/reports identically with no conversion step (FR-2.6). Endpoints (all owner-scoped):
  - `GET /api/v1/categories?company_id=` — categories the guided prompts render from (system defaults + the company's).
  - `POST /api/v1/transactions` — batch-create manual transactions; `type` comes from each entry's category (explicit `type` can override, e.g. "Other" as income); amounts must be `> 0`. Returns `{created, skipped_duplicates}`. `400` if an entry names an inaccessible category, `404` if the company isn't the caller's.
  - `GET /api/v1/transactions?company_id=` — list a company's transactions (upload + manual), newest first.
  - `PATCH /api/v1/transactions/{id}` — edit any field of a transaction (FR-2.5); partial. Changing `category_id` does **not** recompute `type` (only an explicit `type` changes it, per the schema.md §4 stability rule). `400` on an inaccessible category.
  - `DELETE /api/v1/transactions/{id}` — delete a transaction (FR-2.5), `204`. Both resolve ownership via a transaction→company→owner join (`404` otherwise). Deleting a row leaves its upload batch's `row_count` as the historical import count (not decremented).
- **Manual == upload, no conversion (task 3.6, FR-2.6):** both input paths write to the **same `transactions` table**, differing only in `source` (`manual`|`upload`) and a null `upload_batch_id` for manual entries. No read path branches on `source`, so any source-agnostic aggregation (the Financial Engine, dashboard, reports) counts manual and uploaded rows identically — a manual entry never needs "converting" into a document first. Locked in at the data layer by `tests/test_source_equivalence.py`; downstream output equivalence is re-confirmed as each layer lands (reports: task 9.5).
- **Financial engine — auto-categorization (task 4.1, FR-3.1):** `app/financial_engine/categorization.py` is a **deterministic, rule-based, DB-free** `guess_category(description, type)` (income → Revenue; expense → first whole-word keyword rule, else None) — **no LLM** (reinforces §4.1). `financial_engine/service.auto_categorize_company` fills `category_id` on a company's uncategorized rows; it's also applied inline during upload for rows that arrive without a category. Endpoint: `POST /api/v1/transactions/auto-categorize` (owner-scoped) → `{categorized, uncategorized_remaining}`; unmatched rows are left uncategorized rather than guessed.
- **Financial engine — totals & cash flow (task 4.2, FR-3.2/FR-3.3):** `app/financial_engine/calculations.py` holds **pure, DB-free** aggregations — `compute_totals` (revenue vs. expenses + net over the rows given) and `compute_monthly_cash_flow` (per-calendar-month inflow/outflow/net, oldest→newest) — returning exact `Decimal`s quantized to paise; **no LLM** (§4.1). `financial_engine/service` loads only `(date, amount, type)` for a company (source-agnostic, so manual + uploaded rows count identically per FR-2.6) with an optional inclusive date range, then calls the pure functions. Endpoints (owner-scoped, new `/financial` prefix): `GET /api/v1/financial/summary` → `{total_income, total_expenses, net, income_count, expense_count}`; `GET /api/v1/financial/cash-flow` → `{months: [{month, inflow, outflow, net}]}`. Both accept optional `start_date`/`end_date` (omit = all-time; only months with data appear — continuous 12-month gap-filling is task 4.4); `start_date > end_date` → 400.
- **Financial engine — KPI snapshots (task 4.3, FR-4.1–4.5):** `financial_engine.service.generate_kpi_snapshot` computes and **stores** a per-company, per-period `kpi_snapshots` row (schema §6) — the table the AI CFO later reads from and never derives itself (§4.1). Pure metric math is in `calculations.compute_kpis` (DB-free): `burn_rate = (expenses − revenue) / months` (positive = burning); `runway_months = cash_on_hand / burn_rate`, where cash-on-hand is the **cumulative net cash flow** through `period_end` (opening cash ₹0), null when not burning or out of cash; `gross_margin_pct == operating_margin_pct = (revenue − expenses)/revenue×100` (COGS out of MVP scope per SRS §7 → the two are the same figure), null at zero revenue; `revenue_growth_pct` vs. the immediately preceding equal-length window, null with no baseline. numeric(6,2) ratios are clamped to ±9999.99. Endpoints (owner-scoped): `POST /api/v1/financial/kpi-snapshots` (compute + persist; `period_start > period_end` → 422) and `GET /api/v1/financial/kpi-snapshots?company_id=` (list, newest period first).
- **Financial engine — historical / 12-month view (task 4.4, FR-3.5 / FR-4.6):** `calculations.monthly_history` (DB-free) emits a **continuous** N-month series (default 12) ending at an anchor month, oldest→newest, with empty months **zero-filled** (unlike `compute_monthly_cash_flow`, which skips gaps) so the dashboard trend line is unbroken. Each month carries revenue, expenses, net, and `margin_pct` (net/revenue×100, null at zero revenue). `service.company_history` anchors to the **latest month with data** by default (the "last 12 months of available data"), or an explicit `end_month`, or the current month when there are no transactions; it loads only the window's rows. Endpoint (owner-scoped): `GET /api/v1/financial/history?company_id=[&months=1..60&end_month=YYYY-MM]` → `{num_months, end_month, months:[…]}`; bad `end_month` → 400, out-of-range `months` → 422.
- **Financial engine — anomaly detection (task 4.5, FR-3.6):** `financial_engine/anomaly.py` (DB-free, **no LLM**) flags **expense categories whose monthly spend spikes above their trailing 3-month average** by more than a fixed threshold (default 50%), then marks that (category, month) bucket's transactions. Matches the SRS §7 MVP decision (fixed default thresholds, not per-company config). A month is only evaluated once a **full** trailing 3 months of that category's spend exists, so brand-new categories aren't false-flagged. `service.detect_anomalies_for_company` is an **idempotent full recompute** of every transaction's `is_flagged_anomaly` (clears stale flags when data changes; only expenses can be flagged). Endpoint (owner-scoped): `POST /api/v1/transactions/detect-anomalies` → `{flagged, expenses_scanned}`. The flag rides on `TransactionRead`, so the dashboard highlights flagged rows (FR-8.3); the frontend `/transactions` page has a "Detect anomalies" button + an ⚠ badge on flagged rows.
- **Validation & dedupe (task 3.4, FR-2.4):** missing dates / non-numeric amounts are caught per-row (uploads: skipped + reported in the batch's `error_log`; manual: rejected by Pydantic — date required, amount `> 0`). **Duplicate detection** runs on both paths against a signature of `(date, amount, type, description)` within a company (category excluded so a re-import still matches): duplicates — whether of existing rows or repeats within the same file/submission — are **skipped, not double-entered**, and reported to the user (upload `error_log`; manual `skipped_duplicates`). Trade-off: two genuinely-identical entries can't be distinguished and collapse to one.
- **Decisions (task 3.2):** (a) `type` resolution order — explicit type/direction column → matched category's type → sign of amount; (b) `amount` is stored as a **positive magnitude**, with income/expense direction carried solely by `type` (keeps downstream KPI math unambiguous, consistent with the schema.md §4 denormalized-`type` decision). Parsing runs **synchronously** at MVP scale (files are small); can move to a background task later.
- **Validation:** Pydantic models for all request/response schemas
- **Background/async work:** file parsing and report generation should run as async tasks (FastAPI background tasks at MVP scale; can move to a proper task queue like Celery/RQ later if volume grows)

## 4. AI CFO Orchestration Layer

This is the piece that turns "just call an LLM API" into something reliable:

1. **Context assembly** — before calling the LLM, the backend assembles a structured context from the company's precomputed KPIs. This is built server-side, not left to the frontend. **Narrowed in 7.2 to `kpi_snapshots` only** — the original sketch above this line also listed a "recent transactions summary" and active scenarios; the transaction summary was dropped because §4.1 is easier to hold as an absolute than as a rule with exceptions (any transaction-shaped input is an invitation for the model to aggregate it), and scenarios were left out because a saved scenario is a hypothetical, not a fact about the business. Non-numeric company facts (name, industry) do come from `companies` — "you're a SaaS business" changes how a figure should be explained without being a figure.
2. **Prompt construction** — a system prompt defines the AI CFO's role, tone (plain language, non-technical), and constraints (must reference actual data, must include the "not a licensed financial advisor" disclaimer where relevant). **As implemented (7.3):** `app/ai_cfo/prompt.py` holds `SYSTEM_PROMPT` plus `build_messages(context, history, question)`, both pure and DB-free. The system message is the standing instructions followed by the 7.2 figure block — that order so the rules are read before the numbers they govern, and so a provider can cache the stable prefix. `GET /api/v1/chat/prompt?company_id=` returns it, and `/chat` shows it verbatim under **"The instructions it follows"**, next to the figures panel. Most of the prompt is prohibition on purpose: the failure mode worth preventing isn't an unhelpful answer, it's a confident one containing arithmetic the model did itself ("so that's about ₹50L a year"), which is indistinguishable from a correct figure at a glance. Up to `MAX_HISTORY_MESSAGES` (12) prior turns travel with a question for continuity; the prompt states that only the current figure block is authoritative, since replayed answers may quote a superseded snapshot.
3. **LLM call** — sent to OpenAI or Gemini (configurable provider, behind an interface so switching providers doesn't require rewriting the feature).
4. **Response handling** — response is stored in `ChatMessage` history tied to the company/session, so conversations persist and can reference prior turns.

Keeping this as its own module (`/ai_cfo`) matters because it's the part most likely to change (prompt tuning, provider swaps, cost optimization) — it shouldn't be tangled into the core financial engine logic.

### 4.1 Hard Rule: AI Never Calculates

This is a non-negotiable architectural boundary, not a style preference:

- **All numerical calculations** (revenue/expense totals, cash flow, burn rate, runway, margins, growth, scenario deltas, anomaly detection thresholds) are computed exclusively by deterministic Python code in `/financial_engine` and `/scenarios`.
- **The LLM never performs arithmetic on financial data.** It receives already-computed numbers as context and is only used to interpret, explain, or narrate them in plain language.
- This exists because LLMs are unreliable at precise arithmetic over large/complex numeric data — which is one of the core reasons this platform exists instead of just pointing users at ChatGPT. A tool that gets a founder's runway calculation wrong has no value.
- In practice: the AI CFO Orchestrator's prompt should always include pre-computed figures (e.g., "Runway: 7.2 months, Burn rate: ₹4.1L/month") rather than raw transaction data and a request to "calculate the runway." If a user's question requires a number that hasn't been pre-computed, the correct flow is: Financial Engine computes it first → result is passed to the LLM to explain, never the LLM computing it live.
- **As implemented (7.2):** `app/ai_cfo/context.py` is pure and DB-free (like `financial_engine/calculations.py`) and reads *one* `kpi_snapshots` row. It never touches `transactions` — the module has no import path to them. `GET /api/v1/chat/context?company_id=` returns exactly what the model is given, including the rendered prompt block, and `/chat` shows it under **"What the assistant can see"**, so the boundary is something a reader can check rather than take on trust. A test plants a transaction with a distinctive description and asserts it appears nowhere in the assembled context.
- **Enforced in the prompt too (7.3):** the rule is stated to the model as an absolute with no "unless it's simple" escape — no addition, subtraction, percentages, ratios, averages or annualising, and a figure absent from the block "does not exist for you". A figure the block marks *Not applicable* must be reported as undefined with its reason, never as zero. A test asserts the fully assembled prompt — instructions, figures, replayed history and the question — still contains no transaction text.

## 5. Data Flow (Key Scenarios)

### 5.1 Upload → Dashboard
`User uploads CSV/XLSX` → `Backend parses & validates` → `Transactions stored (categorized)` → `Financial Engine recalculates KPIs/cash flow` → `Dashboard reflects updated data`

### 5.2 Scenario Simulation
`User defines scenario inputs` → `Scenario Simulator reads current baseline from Financial Engine` → `Applies hypothetical changes` → `Returns before/after comparison` → `(optionally) saved to DB`

**Simulation is stateless; saving is a separate step (decided in 6.1).** Defining
and running a scenario writes nothing: the input UI (`/scenarios`) collects the
assumptions, and `POST /api/v1/scenarios/simulate` returns the comparison
(**200, not 201** — nothing is created). Only an explicit save persists a row to
`scenarios` (schema §7) — which is why the table and its migration land with
save/revisit (6.4) rather than with the input form. The `assumptions` jsonb keys
are fixed by `frontend/lib/scenarios.ts` and mirrored by the backend schema:
`new_hires`, `avg_salary_per_hire`, `marketing_change_pct`,
`pricing_change_pct`, `revenue_change_pct`.

**The simulator reuses the Financial Engine rather than reimplementing it (6.2).**
Aggregation comes from `financial_engine.service.company_totals`, and *both*
sides of the comparison are derived by `calculations.compute_kpis` — so a
simulated runway is produced by exactly the code that produces a real one, and
the returned `baseline` block is identical to the `kpi_snapshot` stored for the
same company + period (pinned by a regression test). This is what lets 6.4 store
a `baseline_kpi_snapshot_id` beside a saved result without the two disagreeing.
`scenarios/simulation.py` is pure and DB-free, like `financial_engine/calculations.py`.

Modelling decisions locked in with the user during 6.2:

- A scenario **restates the period** — assumptions apply as if they had held
  throughout, so both sides share one period and one set of KPI definitions.
- Pricing and revenue **compose multiplicatively** (`× (1+p) × (1+r)`): revenue is
  price × volume and the pricing lever holds volume constant, which makes the
  revenue lever the volume/other lever.
- **Cash on hand is never restated.** The scenario changes the burn rate, not the
  money in the bank, so runway answers "how long does my actual cash last if I do
  this?". Restating cash is more internally consistent but collapses runway to
  N/A (out of cash) in most realistic scenarios.
- **Growth compares against the real prior window** on both sides — a scenario
  does not rewrite history.

**Saving is explicit, and a saved scenario is replayed rather than recomputed (6.4).**
`POST /api/v1/scenarios` (201) re-runs the simulation server-side from the
submitted levers and persists the result to `scenarios`; the client never sends
a result, so nothing but engine output can be stored. `GET /api/v1/scenarios`
lists a company's saved scenarios newest-first (each carrying its full stored
comparison, so reopening one costs no extra request), `GET|DELETE
/api/v1/scenarios/{id}` revisit and discard one. Ownership-scoped like every
other route, 404 rather than 403 for someone else's row.

The decision that shapes this: **`result` is read back verbatim.** A saved
scenario states the answer it gave *at save time*, so recording new transactions
never silently restates a comparison the user already read and acted on. Loading
one back into the form and pressing Run is how you ask the same question of
today's data — a deliberate, visible act rather than a side effect. The saved
`baseline_kpi_snapshot_id` reuses an existing snapshot only while that snapshot
still agrees with the computed baseline, so the traceability link never points
at figures the comparison didn't use.

### 5.3 AI CFO Chat
`User asks a question` → `AI CFO Orchestrator pulls current KPIs/context` → `Constructs prompt` → `Calls LLM API` → `Stores + returns response`

**The interface and its persistence land before the model (7.1).** `app/ai_cfo/`
ships the chat screen, `chat_sessions`/`chat_messages` (migration `0006`) and
owner-scoped endpoints — `POST /api/v1/chat/sessions`, `GET
/api/v1/chat/sessions`, `GET|DELETE /api/v1/chat/sessions/{id}`, `POST
/api/v1/chat/sessions/{id}/messages` — with **no LLM call at all**. Context
assembly (7.2), the system prompt (7.3) and the provider (7.4) fill in behind a
single seam, `service.answer_question(question) -> (reply, snapshot_id)`, whose
signature is already the one the real implementation needs.

Decisions made in 7.1:

- **A question always produces an exchange.** Both turns are written in one
  transaction, so history can never hold a question with no answer. Until the
  provider exists, the answer is a fixed placeholder that says the assistant
  isn't connected and quotes **no figures and no advice** — a plausible-sounding
  stub is the real hazard, because a demo could show it and a reader believe it.
- **Only the question crosses the wire.** `POST .../messages` accepts `content`
  and nothing else; role and answer are server-decided, so a client cannot forge
  an assistant turn into stored history.
- **`kpi_context_snapshot_id` exists from the first migration**, even though
  nothing populates it until 7.2, because it is the audit trail for §4.1 — being
  able to point at the exact snapshot behind an answer is what makes "the AI
  never calculates" verifiable.
- **The advisory disclaimer (FR-6.5) is shown from 7.1**, not deferred to 7.3
  with the system prompt: a screen rendering assistant-labelled text should
  carry it the moment that text exists.

### 5.4 Report Generation
`User requests report` → `Report Generator pulls KPIs, trends, and (optionally) AI-generated commentary` → `Renders to PDF` → `Stored/returned for download`

## 6. Database

PostgreSQL as the single primary data store for MVP (schema detailed separately in `database/schema.md`). No separate analytics DB needed at this scale — computed KPIs can be cached/snapshotted in a `kpi_snapshots` table rather than requiring a full OLAP setup.

**Implementation notes (Phase 1.1 / 2.1):**
- Hosted on **Supabase** (managed Postgres) — used purely as the database; the app keeps its own SQLAlchemy models and JWT auth, not Supabase Auth.
- Async access via SQLAlchemy 2.0 with the **psycopg 3** driver (`postgresql+psycopg://…`), chosen over asyncpg for cleaner Python 3.14 wheel support. Connection config lives in `backend/app/core/config.py`; the engine/session/`Base` in `backend/app/core/database.py`.
- The backend **boots without a database**: if `DATABASE_URL` is unset, the app still starts and `GET /api/v1/health` reports `database: "not_configured"` (vs `connected`/`unreachable`). Lets the frontend verify backend reachability before the DB exists.
- Schema is versioned with **Alembic** (`backend/migrations/`). ORM models live in their domain modules (`app/auth/models.py`, `app/companies/models.py`, `app/transactions/models.py`) on the shared `Base`; every table uses a UUID PK + `created_at`/`updated_at` via mixins in `app/core/models.py`. Migration `0001` creates `users` + `companies`; `0002` creates `categories` and seeds the system-default set (`company_id NULL`); `0003` creates `upload_batches` + `transactions`; `0004` creates `kpi_snapshots` (KPI model in `app/financial_engine/models.py`).

## 7. Third-Party Integrations

| Integration | Purpose | Notes |
|---|---|---|
| OpenAI / Gemini API | AI CFO Assistant | Abstracted behind a provider interface for flexibility |
| PDF generation library (e.g., WeasyPrint or a JS equivalent) | Report export | Runs server-side in the `/reports` module |

## 8. Deployment Topology (High-Level)

- Frontend and backend deployed as separate services (matches Next.js + FastAPI split)
- PostgreSQL as a managed database instance
- Environment-based config (`.env`) for API keys, DB connection strings — never committed to git
- Detailed hosting choices and CI/CD covered in `deployment/deployment-plan.md`

## 9. Security Considerations

- All traffic over HTTPS
- Financial data scoped per-company; every query filtered by the authenticated user's company ID (no cross-company data leakage)
- LLM API calls should avoid sending more raw data than necessary — send aggregated KPIs/summaries as context rather than full raw transaction dumps where possible, both for cost and data-minimization reasons
- Secrets (DB credentials, LLM API keys) managed via environment variables, not hardcoded

## 10. Why This Structure

The backend is organized by domain (auth, transactions, financial_engine, scenarios, ai_cfo, reports) rather than by technical layer (models/views/controllers) because most future work — and most Claude Code prompts — will be scoped to a single feature at a time ("build the scenario simulator", "add anomaly detection to the financial engine"). Domain-based folders mean each prompt touches one self-contained module instead of scattering changes across the codebase.