# Software Requirements Specification (SRS)

## AI-Powered Financial Operating System for Startups and SMEs

**Prepared for:** Ahmedabad University Capstone Project
**Guide:** Professor Jinraj Joshipura
**Version:** 1.0 (Draft)

---

## 1. Introduction

### 1.1 Purpose

This document specifies the functional and non-functional requirements for the AI-Powered Financial Operating System, a platform that converts raw business and financial data into actionable financial intelligence for startup founders and SME owners. It is intended to guide the design, development, and testing of the platform, and to serve as a shared reference between the technical, finance, marketing, and supply chain contributors on the team.

### 1.2 Scope

The system will allow users to input financial data (via document upload or manual entry), automatically process that data into KPIs and summaries, run scenario simulations, provide an AI-driven conversational CFO assistant, and generate structured financial reports. The MVP will focus on a working prototype covering authentication, data upload, a financial dashboard, scenario simulation, the AI CFO chat, and PDF board-report generation. Later phases may expand to deeper accounting integrations, multi-user organizations, and more advanced forecasting models.

### 1.3 Intended Audience

- Development team (frontend, backend, AI integration)
- Finance/accounting contributor (validating financial logic and KPI correctness)
- Marketing contributor (positioning, user-facing language)
- Supply chain contributor (cost-structure and operational-expense modeling input)
- Capstone guide/evaluators

### 1.4 Definitions

- **KPI** — Key Performance Indicator (e.g., burn rate, runway, gross margin)
- **Runway** — Number of months a company can operate before running out of cash at current burn rate
- **Burn Rate** — Net rate at which a company spends cash, typically monthly
- **SME** — Small and Medium-sized Enterprise
- **AI CFO Assistant** — The conversational AI component that answers financial questions based on the user's uploaded/entered data

---

## 2. Overall Description

### 2.1 Product Perspective

The platform is a standalone web application (Next.js frontend, FastAPI backend, PostgreSQL database) with an integrated AI layer (OpenAI/Gemini APIs) for interpretation and conversational features. It is not an accounting system of record — it consumes financial data (uploaded or manually entered) and layers analysis, simulation, and reporting on top.

### 2.2 User Classes

| User Class | Description |
|---|---|
| Founder / Business Owner | Primary user; uploads/enters data, views dashboard, runs simulations, uses AI CFO chat, generates reports |
| Team Member (future) | Secondary user with limited access, invited by the founder (post-MVP) |
| Admin (internal) | Platform-level admin for support and monitoring (post-MVP) |

### 2.3 Operating Environment

- Web application, accessed via modern browsers (Chrome, Edge, Safari, Firefox)
- Backend hosted on a cloud provider (TBD in deployment plan)
- PostgreSQL as the primary data store
- Responsive design for desktop-first use, with reasonable tablet support

### 2.4 Assumptions and Dependencies

- Users have access to at least basic financial data (bank statements, expense records, or accounting exports) or are willing to enter data manually
- Third-party AI APIs (OpenAI/Gemini) remain available and within acceptable cost/rate limits
- Currency and accounting standards are assumed India-first (INR, GST-aware where relevant) but should not hard-block other currencies in the schema

---

## 3. Functional Requirements

### 3.1 Authentication & User Management

| ID | Requirement |
|---|---|
| FR-1.1 | The system shall allow users to sign up using email and password |
| FR-1.2 | The system shall allow users to log in and maintain a session (token-based auth) |
| FR-1.3 | The system shall allow users to create/manage a company profile (name, industry, currency, fiscal year start) |
| FR-1.4 | The system shall support password reset via email |

### 3.2 Data Input

The platform supports two equally first-class data input paths — neither is a fallback for the other. Many founders/SME owners do not know how to prepare a formal financial statement (income statement, balance sheet, cash flow statement); the manual entry path exists specifically so those users can still get full KPIs and reports without ever needing to produce or upload a document.

| ID | Requirement |
|---|---|
| FR-2.1 | The system shall allow users to upload financial documents in CSV/XLSX format |
| FR-2.2 | The system shall parse uploaded files and map columns to standard financial categories (income, expense, date, category) |
| FR-2.3 | The system shall allow users to manually enter raw business data (sales, purchases, salaries, rent, marketing spend, operational costs, bank transactions) through a **guided, question-based form** — plain-language prompts (e.g. "How much did you spend on rent this month?") rather than a blank accounting-style entry table, so no prior financial-statement knowledge is required |
| FR-2.6 | Once enough manual entries exist for a given period, the system shall automatically make that period's KPIs, dashboard, and reports available — identical in output to the upload path. The user should never need to "convert" manual entries into a document first |
| FR-2.4 | The system shall validate uploaded/entered data for obvious errors (missing dates, non-numeric amounts, duplicate rows) and flag them to the user |
| FR-2.5 | The system shall allow users to edit or delete previously entered/uploaded data |

### 3.3 Financial Intelligence Engine

| ID | Requirement |
|---|---|
| FR-3.1 | The system shall automatically categorize transactions (e.g., payroll, marketing, rent, revenue) |
| FR-3.2 | The system shall calculate total revenue and total expenses over user-selected time periods |
| FR-3.3 | The system shall estimate cash flow (inflows vs. outflows) on a monthly basis |
| FR-3.4 | The system shall generate a financial summary view combining revenue, expenses, and cash position |
| FR-3.5 | The system shall track historical performance across at least the last 12 months of available data |
| FR-3.6 | The system shall detect anomalies in expenses (e.g., unusual spikes relative to historical average) and surface them to the user |

### 3.4 KPI Generation

| ID | Requirement |
|---|---|
| FR-4.1 | The system shall calculate Burn Rate (monthly net cash outflow) |
| FR-4.2 | The system shall calculate Runway (months of cash remaining at current burn rate) |
| FR-4.3 | The system shall calculate Gross Margin |
| FR-4.4 | The system shall calculate Operating Margin |
| FR-4.5 | The system shall calculate Revenue Growth (period-over-period) |
| FR-4.6 | The system shall display profitability trends over time on the dashboard |

**Implementation decisions (locked in during Phase 4 build):**

- **Runway cash-on-hand (FR-4.2):** since the schema has no stored cash-balance field, cash-on-hand is derived as cumulative net cash flow — the sum of all income minus all expenses across every transaction up to the period end, with an assumed ₹0 opening balance. Known limitation: an early-stage company with more cumulative spend than income will show negative/zero cash, making runway undefined by design (displayed as N/A, not a negative number). Runway is also undefined when burn rate ≤ 0 (i.e., the company isn't burning cash).
- **Gross Margin vs. Operating Margin (FR-4.3, FR-4.4):** since the category set has no COGS/opex distinction (§7, deferred to future scope), both metrics use the identical formula — `(revenue − total expenses) / revenue × 100` — and will report the same number. This is a deliberate simplification given current category granularity, not a bug. Revisiting this requires first adding a COGS/opex split to the category taxonomy.

### 3.5 Scenario Simulation

| ID | Requirement |
|---|---|
| FR-5.1 | The system shall allow users to define a hypothetical scenario (e.g., hire N employees, change marketing spend by X%, change pricing by X%, change revenue by X%) |
| FR-5.2 | The system shall recalculate cash flow, runway, profitability, and growth under the simulated scenario |
| FR-5.3 | The system shall display a before/after comparison of key metrics for each simulation |
| FR-5.4 | The system shall allow users to save and revisit past simulations |

### 3.6 AI CFO Assistant

**Core principle:** The AI is used strictly for interpretation and analytics — explaining, summarizing, and contextualizing numbers in plain language. It never performs the underlying financial calculations itself. All KPIs, totals, cash flow, and scenario results are computed exclusively by deterministic backend code (see FR-3.x, FR-4.x, FR-5.2, and `system-architecture.md` §4.1 for the full architectural rule). This is a deliberate design decision: LLMs are unreliable at precise arithmetic over large or complex numeric data, which is one of the core reasons this platform exists rather than a user simply using a general-purpose AI tool.

| ID | Requirement |
|---|---|
| FR-6.1 | The system shall provide a conversational chat interface for financial questions |
| FR-6.2 | The AI CFO Assistant shall answer using the user's actual financial data as context (not generic advice) |
| FR-6.3 | The AI CFO Assistant shall explain financial concepts in plain, non-technical language |
| FR-6.4 | The AI CFO Assistant shall be able to reference specific KPIs and trends when answering |
| FR-6.5 | The system shall clearly indicate that AI-generated advice is not a substitute for a licensed financial professional |
| FR-6.6 | The AI CFO Assistant shall never perform financial calculations itself — it shall only receive and explain figures already computed by the Financial Engine (FR-3.x, FR-4.x) |

### 3.7 Reporting

| ID | Requirement |
|---|---|
| FR-7.1 | The system shall generate a Monthly Financial Report summarizing revenue, expenses, cash flow, and KPIs |
| FR-7.2 | The system shall generate a Board Report suitable for sharing with investors/board members |
| FR-7.3 | The system shall generate an Investor Readiness Summary highlighting key metrics investors typically evaluate |
| FR-7.4 | The system shall export reports as PDF |

### 3.8 Dashboard

| ID | Requirement |
|---|---|
| FR-8.1 | The system shall display an overview dashboard with key financial metrics, charts, and recent activity |
| FR-8.2 | The system shall allow filtering the dashboard by date range |
| FR-8.3 | The dashboard shall visually highlight anomalies or metrics requiring attention |

---

## 4. Non-Functional Requirements

| ID | Category | Requirement |
|---|---|---|
| NFR-1 | Security | All financial data shall be encrypted in transit (TLS) and at rest |
| NFR-2 | Security | Passwords shall be hashed (e.g., bcrypt/argon2), never stored in plaintext |
| NFR-3 | Security | Access to a company's financial data shall be restricted to authorized users of that company |
| NFR-4 | Performance | Dashboard views shall load within 3 seconds for datasets up to 12 months of typical SME transaction volume |
| NFR-5 | Performance | File upload processing (CSV/XLSX) shall complete within 30 seconds for files up to 10MB |
| NFR-6 | Reliability | The system shall handle malformed uploads gracefully without crashing, returning clear error messages |
| NFR-7 | Usability | The interface shall be usable by non-finance-expert founders without requiring a manual |
| NFR-8 | Scalability | The architecture shall support adding new KPI calculations and report types without major restructuring |
| NFR-9 | Maintainability | Backend and AI logic shall be modular so financial calculation logic can be tested independently of the AI layer |
| NFR-10 | Compliance | The system shall avoid storing more sensitive personal/financial data than necessary for its stated features |

---

## 5. Data Requirements (High-Level)

The following entities are expected to be needed (detailed schema to follow in `database/schema.md`):

- User
- Company
- Transaction (income/expense records, uploaded or manual)
- Category (transaction categorization taxonomy)
- KPI Snapshot (calculated metrics over time, for trend tracking)
- Scenario (saved simulation inputs and results)
- Report (generated report metadata and file references)
- ChatSession / ChatMessage (AI CFO Assistant conversation history)

---

## 6. Constraints

- MVP is scoped to a single-user-per-company model; multi-user/team access is a future enhancement
- AI CFO Assistant responses depend on third-party LLM API availability and cost limits
- No direct bank-account integration in MVP — data enters via upload or manual entry only
- Reporting is limited to PDF export in MVP; other formats (e.g., XLSX export) are future scope

---

## 7. Future Considerations (Post-MVP)

- Direct bank/accounting software integrations (e.g., QuickBooks, Zoho Books, Tally)
- Multi-user organizations with role-based access
- Multi-currency and multi-entity support
- Supply-chain and inventory cost modeling (potential contribution area for supply chain team member)
- Investor-facing shared dashboards with controlled access

---

## 8. Decisions

- **Currency/localization:** INR-only for MVP. All amounts stored and displayed in INR; no multi-currency conversion logic needed at this stage.
- **Anomaly detection:** fixed default thresholds (e.g., expense category deviates >X% from trailing 3-month average) rather than per-company configuration, to keep MVP scope tight. Configurability is a post-MVP enhancement.
- **Categorization rigor:** a simplified, startup-relevant category set (not a full formal chart of accounts) — e.g., Revenue, Payroll, Rent, Marketing, Software/Tools, Operations, Other. Enough to drive KPIs and reports without accounting-grade complexity.
- **Supply chain / inventory scope:** dropped from MVP. Team execution is effectively solo (Parin + Claude + Claude Code), so scope is kept to what's already defined in this SRS; inventory/COGS modeling remains a documented future-scope idea (Section 7) rather than an active module.