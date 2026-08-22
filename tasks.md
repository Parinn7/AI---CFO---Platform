# Task Breakdown

## AI-Powered Financial Operating System

Master task list. Each subtask is one Claude Code session. Reference by ID ("do 6.1") or just say "do the next unchecked task."

**This file is self-tracking.** After finishing a subtask, Claude Code must edit this file directly, change `[ ]` to `[x]` for that item, and commit that change along with the code. This file's checked-off state is the real source of truth for what's done — `progress.md` holds the narrative log and current-focus summary, this file holds the literal checklist.

**Standing instructions for every task, unless overridden below:**
- Read `progress.md` and this file first, before starting anything.
- No AI/LLM performs financial calculations — all math is deterministic backend code (`system-architecture.md` §4.1).
- INR only, no multi-currency logic.
- Manual entry and document upload are equally first-class data input paths — never treat manual entry as a fallback. Manual entry must be guided (plain-language questions), not a blank accounting form, since many users won't know how to prepare formal financial statements (SRS FR-2.3, FR-2.6).
- Goal is a solid working prototype for a university capstone presentation — functional, reasonably robust, and honest about what it does. Not a commercial SaaS (no billing, no multi-tenant accounts, no legal pages needed).
- If you touch any file in the repo that is still an empty placeholder (e.g. `frontend/README.md`, `backend/README.md`, `deployment/deployment-plan.md`, `docs/testing/test-cases.md`, etc.) and your current task would naturally produce content for it, fill it in as part of that session rather than leaving it empty — don't wait for a dedicated "docs" phase.
- On completion: check off the subtask below, update `progress.md` (Current Status + Log + Next Up), and update `system-architecture.md`/`schema.md` if the implementation introduced anything not already documented there. Then commit everything (code + updated `.md` files) with a clear commit message describing what was built — every subtask ends in a commit, no exceptions.
- If something needed for the subtask isn't covered in the docs, ask before assuming.

---

## Phase 1 — Project Scaffolding
- [x] **1.1** Initialize Next.js + Tailwind frontend, FastAPI backend with domain-module structure, PostgreSQL connection. Confirm both sides boot and talk to each other.

## Phase 2 — Auth & Company Setup
- [x] **2.1** `users` and `companies` tables per `schema.md`.
- [x] **2.2** Signup + login (JWT sessions), password hashing (FR-1.1, FR-1.2).
- [x] **2.3** Company profile creation/management UI + API (FR-1.3).
- [x] **2.4** Password reset flow — stub email sending if no email service configured (FR-1.4).

## Phase 3 — Data Input
- [x] **3.1** `categories` table + seed default INR/SME category set.
- [x] **3.2** CSV/XLSX upload endpoint + `upload_batches`/`transactions` tables (FR-2.1, FR-2.2).
- [x] **3.3** Guided manual data entry flow — plain-language, question-based (not a blank form), covering sales, purchases, salaries, rent, marketing spend, operational costs, bank transactions (FR-2.3).
- [x] **3.4** Upload/entry validation — missing dates, non-numeric amounts, duplicates (FR-2.4).
- [x] **3.5** Edit/delete previously entered data (FR-2.5).
- [x] **3.6** Confirm manually-entered data flows into KPIs/dashboard/reports identically to uploaded data — no separate "conversion" step (FR-2.6). *(Data-layer equivalence verified now; downstream KPI/report output re-confirmed in Phase 4/5 and task 9.5.)*

## Phase 4 — Financial Engine
- [ ] **4.1** Auto-categorization logic (FR-3.1).
- [ ] **4.2** Revenue/expense totals + cash flow calculation (FR-3.2, FR-3.3).
- [ ] **4.3** `kpi_snapshots` generation: burn rate, runway, gross margin, operating margin, revenue growth (FR-4.1–4.6).
- [ ] **4.4** Historical performance tracking, 12-month view (FR-3.5).
- [ ] **4.5** Anomaly detection against fixed thresholds (FR-3.6).

## Phase 5 — Dashboard
- [ ] **5.1** Overview dashboard: KPI cards, charts, recent activity (FR-8.1).
- [ ] **5.2** Date-range filtering (FR-8.2).
- [ ] **5.3** Visual anomaly highlighting (FR-8.3).

## Phase 6 — Scenario Simulator
- [ ] **6.1** Scenario input UI (FR-5.1).
- [ ] **6.2** Simulation engine, reusing the Financial Engine deterministically (FR-5.2).
- [ ] **6.3** Before/after comparison view (FR-5.3).
- [ ] **6.4** Save/revisit past scenarios (FR-5.4).

## Phase 7 — AI CFO Assistant
- [ ] **7.1** Chat UI + `chat_sessions`/`chat_messages` tables (FR-6.1).
- [ ] **7.2** Context assembly from `kpi_snapshots` only, never raw transactions (FR-6.2, architecture §4.1).
- [ ] **7.3** System prompt: plain-language explanation + advisory disclaimer (FR-6.3, FR-6.5).
- [ ] **7.4** LLM provider integration behind a swappable interface (FR-6.4).

---

## Phase 8 — Deployment
*All core functionality (Phases 1–7) is built and working locally at this point. This is where it goes live, so the reporting phase and the final presentation both run against the real deployed version, not localhost.*
- [ ] **8.1** Choose hosting (e.g. Vercel for frontend, Railway/Render for backend + Postgres — pick whichever has the smoothest FastAPI + Postgres story).
- [ ] **8.2** Set environment variables/secrets on the hosting platform (DB connection string, JWT secret, LLM API key) — never committed to git.
- [ ] **8.3** Deploy frontend and backend, confirm they can reach each other and the database in production.
- [ ] **8.4** Smoke-test the full flow end-to-end on the live URL: signup → login → upload data or manual entry → dashboard → scenario → AI chat.
- [ ] **8.5** Fill in `deployment/deployment-plan.md` with what was actually set up (it's currently an empty placeholder) — hosting choice, live URL, how to redeploy.

## Phase 9 — Reporting
- [ ] **9.1** Monthly Financial Report (FR-7.1).
- [ ] **9.2** Board Report (FR-7.2).
- [ ] **9.3** Investor Readiness Summary (FR-7.3).
- [ ] **9.4** PDF export for all report types (FR-7.4).
- [ ] **9.5** Confirm reports generate correctly for companies whose data came entirely from manual entry, not just uploads.
- [ ] **9.6** Redeploy after this phase so the live version includes reporting.

## Phase 10 — Frontend Polish & Presentation Prep
*Everything works by now. This is purely making it look and feel finished for the demo — the wireframes we deliberately skipped earlier finally get used here.*
- [ ] **10.1** Wireframe pass — now that real screens exist, tighten up layout/flow inconsistencies across pages.
- [ ] **10.2** Visual polish — consistent spacing, colors, typography, loading/empty states.
- [ ] **10.3** Seed realistic-looking demo data (a fictional startup's financials) so the presentation doesn't rely on live data entry.
- [ ] **10.4** Final redeploy with polished UI + demo data.
- [ ] **10.5** Do a full run-through of the demo flow end-to-end as if presenting it, to catch anything broken or confusing.

---

**Done. After Phase 10, the project is ready to present — no further build work planned.**