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
- **Auth:** JWT-based session tokens; password hashing via bcrypt/argon2
- **Validation:** Pydantic models for all request/response schemas
- **Background/async work:** file parsing and report generation should run as async tasks (FastAPI background tasks at MVP scale; can move to a proper task queue like Celery/RQ later if volume grows)

## 4. AI CFO Orchestration Layer

This is the piece that turns "just call an LLM API" into something reliable:

1. **Context assembly** — before calling the LLM, the backend assembles a structured context: relevant KPIs, recent transactions summary, active scenarios, and the user's question. This is built server-side, not left to the frontend.
2. **Prompt construction** — a system prompt defines the AI CFO's role, tone (plain language, non-technical), and constraints (must reference actual data, must include the "not a licensed financial advisor" disclaimer where relevant).
3. **LLM call** — sent to OpenAI or Gemini (configurable provider, behind an interface so switching providers doesn't require rewriting the feature).
4. **Response handling** — response is stored in `ChatMessage` history tied to the company/session, so conversations persist and can reference prior turns.

Keeping this as its own module (`/ai_cfo`) matters because it's the part most likely to change (prompt tuning, provider swaps, cost optimization) — it shouldn't be tangled into the core financial engine logic.

### 4.1 Hard Rule: AI Never Calculates

This is a non-negotiable architectural boundary, not a style preference:

- **All numerical calculations** (revenue/expense totals, cash flow, burn rate, runway, margins, growth, scenario deltas, anomaly detection thresholds) are computed exclusively by deterministic Python code in `/financial_engine` and `/scenarios`.
- **The LLM never performs arithmetic on financial data.** It receives already-computed numbers as context and is only used to interpret, explain, or narrate them in plain language.
- This exists because LLMs are unreliable at precise arithmetic over large/complex numeric data — which is one of the core reasons this platform exists instead of just pointing users at ChatGPT. A tool that gets a founder's runway calculation wrong has no value.
- In practice: the AI CFO Orchestrator's prompt should always include pre-computed figures (e.g., "Runway: 7.2 months, Burn rate: ₹4.1L/month") rather than raw transaction data and a request to "calculate the runway." If a user's question requires a number that hasn't been pre-computed, the correct flow is: Financial Engine computes it first → result is passed to the LLM to explain, never the LLM computing it live.

## 5. Data Flow (Key Scenarios)

### 5.1 Upload → Dashboard
`User uploads CSV/XLSX` → `Backend parses & validates` → `Transactions stored (categorized)` → `Financial Engine recalculates KPIs/cash flow` → `Dashboard reflects updated data`

### 5.2 Scenario Simulation
`User defines scenario inputs` → `Scenario Simulator reads current baseline from Financial Engine` → `Applies hypothetical changes` → `Returns before/after comparison` → `(optionally) saved to DB`

### 5.3 AI CFO Chat
`User asks a question` → `AI CFO Orchestrator pulls current KPIs/context` → `Constructs prompt` → `Calls LLM API` → `Stores + returns response`

### 5.4 Report Generation
`User requests report` → `Report Generator pulls KPIs, trends, and (optionally) AI-generated commentary` → `Renders to PDF` → `Stored/returned for download`

## 6. Database

PostgreSQL as the single primary data store for MVP (schema detailed separately in `database/schema.md`). No separate analytics DB needed at this scale — computed KPIs can be cached/snapshotted in a `kpi_snapshots` table rather than requiring a full OLAP setup.

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