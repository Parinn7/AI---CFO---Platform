# Backend — AI CFO Platform API

FastAPI service, organized by **domain module** (see `system-architecture.md` §3),
so each feature is self-contained.

## Structure

```
backend/
  app/
    main.py              # FastAPI app: CORS, health endpoint, router wiring
    core/                # config, database (async engine, session, Base), shared model mixins
    auth/                # Phase 2 — User model + signup/login/JWT: security, service, schemas, dependencies, router (FR-1.1, FR-1.2)
    companies/           # Phase 2 — Company model + owner-scoped profile CRUD: schemas, service, router (FR-1.3)
    transactions/        # Phase 3 — categories, CSV/XLSX upload+parsing, transactions (FR-2.x): models, parsing, service, router
    financial_engine/    # Phase 4 — deterministic categorization/KPI/cash-flow/anomaly math: categorization, calculations, anomaly, service, schemas, models (kpi_snapshots), router (FR-3.x, FR-4.x)
    scenarios/           # Phase 6 — deterministic scenario simulation: simulation, service, schemas, router (FR-5.x)
    ai_cfo/              # Phase 7 — LLM orchestration, chat (FR-6.x)
    reports/             # Phase 9 — report generation + PDF export (FR-7.x)
  migrations/            # Alembic: env.py + versions/ (0001 users+companies; 0002 categories+seed; 0003 upload_batches+transactions; 0004 kpi_snapshots)
  tests/                 # pytest smoke + feature tests
  alembic.ini
  requirements.txt
  .env.example
```

The remaining domain modules (`ai_cfo`, `reports`) are package placeholders —
they gain routers/models/services in their respective phases.

## Setup

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # fill in DATABASE_URL, JWT_SECRET, LLM_API_KEY as needed
```

## Run

```bash
source venv/bin/activate
uvicorn app.main:app --reload --port 8000
```

- API root: http://localhost:8000/
- Interactive docs: http://localhost:8000/docs
- Health: http://localhost:8000/api/v1/health

The health endpoint reports database connectivity as `connected`,
`not_configured` (no `DATABASE_URL` set yet), or `unreachable`. The app boots
regardless, so the frontend can confirm reachability before Postgres exists.

## Database & migrations (Supabase + Alembic)

Postgres is hosted on **Supabase** (managed Postgres only — the app uses its own
SQLAlchemy models and JWT auth, not Supabase Auth). ORM models live in their
domain modules (`app/auth/models.py`, `app/companies/models.py`) on the shared
`Base`; schema changes are versioned with Alembic under `migrations/`.

**One-time Supabase setup:**
1. Create a project at supabase.com.
2. Project Settings → Database → Connection string → copy the URI.
3. Put it in `backend/.env` as `DATABASE_URL`, changing the scheme to
   `postgresql+psycopg://…` (see `.env.example`). Use the Direct connection or
   Session pooler for migrations.

**Apply migrations:**

```bash
source venv/bin/activate
alembic upgrade head          # creates users + companies, then categories (+ seeds defaults)
alembic downgrade -1          # roll back one revision
alembic current               # show applied revision
alembic upgrade head --sql    # render DDL without connecting (offline)
```

After `alembic upgrade head`, `GET /api/v1/health` reports `database: "connected"`.

New models must be imported in `migrations/env.py` so autogenerate sees them:

```bash
alembic revision --autogenerate -m "add <thing>"
```

## Test

```bash
source venv/bin/activate
pytest -q
```

## Authentication (Phase 2.2)

Email + password signup/login with JWT session tokens. Passwords are bcrypt-hashed
(NFR-2); `JWT_SECRET` from `.env` signs tokens (`HS256`, default 24h expiry).

| Endpoint | Auth | Purpose |
|---|---|---|
| `POST /api/v1/auth/signup` | – | Create account; returns `{access_token, token_type, user}` (auto-login). `409` if email exists. |
| `POST /api/v1/auth/login` | – | Verify credentials; returns the same token payload. `401` on failure. |
| `GET /api/v1/auth/me` | Bearer | Return the authenticated user. |
| `POST /api/v1/auth/password-reset/request` | – | Start a reset. Always `200` (no enumeration). |
| `POST /api/v1/auth/password-reset/confirm` | – | Set a new password from a reset token. `400` if invalid/used. |

**Password reset (FR-1.4):** no email service is configured, so the request
endpoint logs the reset link and — in `development` only — returns it inline
(`reset_token`/`reset_link`) so the flow works without an inbox. Reset tokens are
stateless JWTs carrying a `type: reset` claim plus a fingerprint of the user's
current password hash, which makes them single-use (they stop verifying once the
password changes) without a DB table. To wire up real email later, replace the
`logger.info(...)` "send" in `app/auth/router.py` with an email provider call.

Send the token on protected routes as `Authorization: Bearer <access_token>`.
`app.auth.dependencies.get_current_user` is the reusable dependency that turns
that header into a loaded `User` (raising `401` otherwise) — protected endpoints
in later phases depend on it. Example:

```bash
TOKEN=$(curl -s -X POST localhost:8000/api/v1/auth/signup \
  -H 'Content-Type: application/json' \
  -d '{"email":"you@example.com","password":"at-least-8-chars","full_name":"You"}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
curl localhost:8000/api/v1/auth/me -H "Authorization: Bearer $TOKEN"
```

## Company profiles (Phase 2.3)

Owner-scoped CRUD for a user's company profile (FR-1.3). All routes require a
Bearer token; every query is filtered by the authenticated user's id, so no one
can read or edit another user's company (NFR-3). `currency` is always INR — the
server ignores any client-supplied currency (INR-only MVP).

| Endpoint | Purpose |
|---|---|
| `POST /api/v1/companies` | Create a profile (name, optional industry + fiscal-year-start-month). `201`. |
| `GET /api/v1/companies` | List the current user's companies. |
| `GET /api/v1/companies/{id}` | Get one; `404` if not the caller's. |
| `PATCH /api/v1/companies/{id}` | Partial update; `404` if not owned. |

```bash
curl -X POST localhost:8000/api/v1/companies -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"name":"Acme SME","industry":"Retail","fiscal_year_start_month":4}'
```

## Data import — CSV/XLSX upload (Phase 3.2)

Import transactions from a CSV or Excel file (FR-2.1, FR-2.2). Owner-scoped:
uploads target a company the caller owns. The parser (`app/transactions/parsing.py`)
is DB-free and maps real-world headers by alias — it needs a **date** and an
**amount** column; **description**, **category**, and **type** are used if
present. Amounts are stored as a positive magnitude with direction in `type`;
unparseable rows (missing date, non-numeric amount) and **duplicates** are
skipped and reported in the batch's `error_log` (FR-2.4). A duplicate is any row
matching an existing transaction on `(date, amount, type, description)` within
the company — so re-uploading the same file imports nothing.

| Endpoint | Purpose |
|---|---|
| `POST /api/v1/uploads` | Multipart (`file` + `company_id`); imports, returns batch + transactions. `400` bad file/columns, `404` not your company. |
| `GET /api/v1/uploads?company_id=` | List a company's import batches. |
| `GET /api/v1/uploads/{id}` | One batch + its transactions. |

```bash
printf 'Date,Description,Amount,Category\n2026-01-05,Client invoice,120000,Revenue\n' > sample.csv
curl -X POST localhost:8000/api/v1/uploads -H "Authorization: Bearer $TOKEN" \
  -F "company_id=$COMPANY_ID" -F "file=@sample.csv;type=text/csv"
```

## Guided manual entry (Phase 3.3)

Manual entry is a **first-class** input path (SRS FR-2.3), not a fallback. The
frontend asks plain-language questions per category; answers become manual
transactions in the **same `transactions` table** as uploads (`source="manual"`,
no `upload_batch_id`), so they feed KPIs/reports identically (FR-2.6).

| Endpoint | Purpose |
|---|---|
| `GET /api/v1/categories?company_id=` | Categories the prompts render from (defaults + company's). |
| `POST /api/v1/transactions` | Batch-create manual transactions → `{created, skipped_duplicates}`. `type` from category (explicit override allowed); amount `> 0`; exact duplicates skipped (FR-2.4). `400` bad category, `404` not your company. |
| `GET /api/v1/transactions?company_id=` | A company's transactions (upload + manual), newest first. |
| `PATCH /api/v1/transactions/{id}` | Edit a transaction (FR-2.5); partial. Changing category doesn't recompute `type`. `400` bad category, `404` not yours. |
| `DELETE /api/v1/transactions/{id}` | Delete a transaction (FR-2.5); `204`, `404` if not yours. |
| `POST /api/v1/transactions/auto-categorize` | Deterministically categorize uncategorized rows (FR-3.1) → `{categorized, uncategorized_remaining}`. |
| `POST /api/v1/transactions/detect-anomalies` | Flag anomalous expenses (FR-3.6) → `{flagged, expenses_scanned}`. Idempotent full recompute of `is_flagged_anomaly`. |

**Anomaly detection (Phase 4.5)** lives in `app/financial_engine/anomaly.py`
(DB-free, **no LLM**): it flags an expense **category whose monthly spend
exceeds its trailing 3-month average by >50%** (a fixed default threshold, SRS
§7), marking that month's transactions in that category. A full trailing-3-month
baseline is required, so new categories aren't false-flagged. The endpoint is an
idempotent full recompute (clears stale flags when data changes; only expenses
can be flagged). Surfaced via a "Detect anomalies" button + ⚠ badge on
`/transactions`, and the `is_flagged_anomaly` flag feeds the dashboard (FR-8.3).

**Auto-categorization (Phase 4.1)** is rule-based and lives in
`app/financial_engine/categorization.py` (`guess_category` — income → Revenue,
expense → whole-word keyword match, else left uncategorized). **No LLM does this**
(architecture §4.1). It runs inline during upload for rows without a category,
and on demand via the endpoint above (a button on the frontend `/transactions`).

```bash
curl -X POST localhost:8000/api/v1/transactions -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"company_id":"'"$COMPANY_ID"'","transactions":[
        {"date":"2026-01-31","amount":"150000","category_id":"<revenue-id>"}]}'
```

## Financial engine — totals & cash flow (Phase 4.2)

Deterministic aggregations over a company's transactions (FR-3.2/FR-3.3) — **no
LLM** (architecture §4.1). Pure math lives in `app/financial_engine/calculations.py`
(unit-tested without a DB); the service loads only `(date, amount, type)` rows,
source-agnostic so manual + uploaded entries count identically (FR-2.6). Both
endpoints are owner-scoped and accept optional `start_date`/`end_date`
(inclusive; omit for all-time). `start_date > end_date` → `400`.

| Endpoint | Purpose |
| --- | --- |
| `GET /api/v1/financial/summary?company_id=[&start_date=&end_date=]` | Total revenue vs. expenses + net → `{total_income, total_expenses, net, income_count, expense_count}`. |
| `GET /api/v1/financial/cash-flow?company_id=[&start_date=&end_date=]` | Per-month inflow/outflow/net → `{months: [{month:"YYYY-MM", inflow, outflow, net}]}`, oldest→newest, only months with data. |

```bash
curl "localhost:8000/api/v1/financial/summary?company_id=$COMPANY_ID" \
  -H "Authorization: Bearer $TOKEN"
curl "localhost:8000/api/v1/financial/cash-flow?company_id=$COMPANY_ID&start_date=2026-01-01" \
  -H "Authorization: Bearer $TOKEN"
```

## Financial engine — historical / 12-month view (Phase 4.4)

A continuous month-by-month performance series (FR-3.5) for trend charts
(FR-4.6) — **no LLM**. `calculations.monthly_history` zero-fills empty months so
the series is unbroken and always `months` rows long; each month has revenue,
expenses, net, and `margin_pct` (net/revenue×100, null at zero revenue). By
default it anchors to the **latest month with data** ("last 12 months of
available data"); pass `end_month` to anchor explicitly.

| Endpoint | Purpose |
| --- | --- |
| `GET /api/v1/financial/history?company_id=[&months=1..60&end_month=YYYY-MM]` | Continuous monthly series, oldest→newest → `{num_months, end_month, months:[{month, revenue, expenses, net_cash_flow, margin_pct}]}`. Bad `end_month` → `400`, `months` out of 1..60 → `422`, not your company → `404`. |

```bash
curl "localhost:8000/api/v1/financial/history?company_id=$COMPANY_ID&months=12" \
  -H "Authorization: Bearer $TOKEN"
```

## Financial engine — KPI snapshots (Phase 4.3)

Precomputed, **stored** KPIs per company per period (FR-4.1–4.5) — the
`kpi_snapshots` table the AI CFO reads from and never derives itself
(architecture §4.1). Metric math is pure/unit-tested in `calculations.compute_kpis`;
`service.generate_kpi_snapshot` is the only writer. **No LLM.**

Definitions (locked in): `burn_rate = (expenses − revenue) / months` (positive =
burning); `runway_months = cash_on_hand / burn_rate` with cash-on-hand = cumulative
net cash flow through `period_end` (opening ₹0), **null** when not burning or out
of cash; `gross_margin_pct == operating_margin_pct = (revenue − expenses)/revenue×100`
(COGS out of MVP scope, SRS §7 → same figure), null at zero revenue;
`revenue_growth_pct` vs. the immediately preceding equal-length window, null with
no baseline. numeric(6,2) ratios clamp to ±9999.99.

| Endpoint | Purpose |
| --- | --- |
| `POST /api/v1/financial/kpi-snapshots` | Body `{company_id, period_start, period_end}`; computes + stores a snapshot → the full KPI row. `422` if `period_start > period_end`, `404` not your company. |
| `GET /api/v1/financial/kpi-snapshots?company_id=` | A company's stored snapshots, most recent period first. |

```bash
curl -X POST localhost:8000/api/v1/financial/kpi-snapshots \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"company_id":"'"$COMPANY_ID"'","period_start":"2026-01-01","period_end":"2026-01-31"}'
```

## Scenario simulator (Phase 6.2 / 6.4)

Answers "what if?" against a company's real figures (FR-5.2) — **deterministic
Python, no LLM** (architecture §4.1). **Running is stateless**: `/simulate`
computes and returns, persisting nothing (architecture §5.2). Only an explicit
save writes a row, which is 6.4 below.

It **reuses the Financial Engine** rather than reimplementing it: aggregation
comes from `financial_engine.service.company_totals`, and *both* sides of the
comparison are derived by `calculations.compute_kpis`, so a simulated runway is
produced by exactly the code that produces a real one. A regression test pins
this — the returned `baseline` block equals the `kpi_snapshot` stored for the
same company + period, field for field.

`simulation.py` is pure/DB-free (like `calculations.py`) and holds the four
FR-5.1 levers. Its field names and bounds mirror `frontend/lib/scenarios.ts`, so
client- and server-side validation agree and the object can be persisted verbatim
as `scenarios.assumptions` in 6.4 (schema §7).

**Modelling decisions (locked in):**

- **A scenario restates the period.** Assumptions are applied as if they had held
  for the whole window, so hiring costs `new_hires × salary × months`. Both sides
  then share one period and one set of KPI definitions.
- **Pricing and revenue compose multiplicatively:** `revenue × (1 + pricing%) ×
  (1 + revenue%)`. Revenue is price × volume and the pricing lever holds volume
  constant, so the revenue lever is the volume/other lever — +10% price and +20%
  business is 1.32×, not 1.30×.
- **Cash on hand is never restated** (decided with the user). The scenario changes
  the burn rate, not the money in the bank, so runway answers "I have this much
  cash; if I hire five people, how long does it last?". Restating cash as well is
  more internally consistent but collapses runway to N/A (out of cash) in most
  realistic scenarios, making one of the four KPIs FR-5.2 names useless.
- **Growth compares against the real prior window** on both sides — a scenario
  doesn't rewrite history.
- **Only categorised Marketing spend moves.** The marketing lever scales what the
  period actually booked to the Marketing category; uncategorised spend can't be
  identified, so it stays put. The `applied` block echoes the base it used.
- An **all-zero scenario is accepted**, returning identical before/after figures —
  a truthful answer rather than an error.

| Endpoint | Purpose |
| --- | --- |
| `POST /api/v1/scenarios/simulate` | Body `{company_id, period_start, period_end, assumptions}` → `{baseline, scenario, deltas, applied}`. **200, not 201** — nothing is created. `422` on an out-of-range lever or reversed period, `404` not your company. |
| `POST /api/v1/scenarios` | Same body plus `name` → the saved scenario (**201**). Re-runs the simulation server-side; a client never supplies a result. |
| `GET /api/v1/scenarios?company_id=` | A company's saved scenarios, newest first, each with its full stored comparison. |
| `GET /api/v1/scenarios/{id}` | One saved scenario, replayed from storage. |
| `DELETE /api/v1/scenarios/{id}` | Discard one (`204`). Transactions and KPI snapshots are untouched. |

A delta is `null` whenever either side is undefined: a runway that exists only
after the change has no meaningful difference.

**Saving and revisiting (6.4, FR-5.4).** `POST /scenarios` takes only the levers
and re-runs the simulation itself, so a stored `result` can only be
deterministic engine output. Two rules matter:

- **A saved scenario is replayed, not recomputed.** `result` is the comparison as
  computed at save time and is read back verbatim, so a scenario keeps stating
  the answer it gave even after the company records new transactions.
  Recomputing on read would silently restate something the user already read and
  acted on. Re-running against today's data is a separate, explicit action (the
  UI loads the levers back into the form).
- **The baseline link never goes stale.** `baseline_kpi_snapshot_id` reuses the
  newest snapshot for the same company + period *only if it still agrees with
  the freshly computed baseline*; otherwise a fresh snapshot is generated. It's
  nullable with `ON DELETE SET NULL` — losing a snapshot must not delete a
  user's saved scenario.

```bash
curl -X POST localhost:8000/api/v1/scenarios/simulate \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"company_id":"'"$COMPANY_ID"'","period_start":"2025-09-01","period_end":"2026-08-31",
       "assumptions":{"new_hires":5,"avg_salary_per_hire":"90000","marketing_change_pct":"50"}}'
```

## AI CFO chat (Phase 7.1)

The conversational interface (FR-6.1) and its persistence — `chat_sessions` and
`chat_messages` (schema §8–9, migration `0006`). **No LLM is called yet.** 7.1 is
deliberately the interface: context assembly from `kpi_snapshots` (7.2), the
plain-language system prompt and disclaimer (7.3), and the swappable provider
(7.4) come next, all behind one seam — `service.answer_question(question) ->
(reply, snapshot_id)` — whose signature is already what the real version needs.

| Endpoint | Purpose |
| --- | --- |
| `POST /api/v1/chat/sessions` | Start a conversation for a company (`201`). |
| `GET /api/v1/chat/sessions?company_id=` | Conversations, newest first, each labelled by its opening question. |
| `GET /api/v1/chat/sessions/{id}` | One conversation with its full history, oldest turn first. |
| `POST /api/v1/chat/sessions/{id}/messages` | Ask a question → `{user_message, assistant_message}` (`201`). Body carries **only** `content`. |
| `DELETE /api/v1/chat/sessions/{id}` | Delete a conversation and its messages (`204`). |

**Decisions worth knowing:**

- **A question always produces an exchange**, both turns written in one
  transaction, so history can never hold a question with no answer.
- **The placeholder answer is deliberately inert** — it states the assistant
  isn't connected and contains no figures and no advice. A stub that *sounded*
  like financial output is the real hazard: someone could demo it and a reader
  could believe it. A test pins that the reply contains no digits, `₹` or `%`.
- **Only the question crosses the wire.** Role and answer are server-decided, so
  a client can't forge an assistant turn into stored history (also pinned).
- **Timestamps are set in Python, not by `now()`.** Conversation order is a
  correctness property and the server clock can't carry it: Postgres stamps a
  whole transaction identically (question and answer tie) and SQLite's
  `CURRENT_TIMESTAMP` has second resolution (a whole fast conversation ties).
- **Access is scoped by company ownership**, not `chat_sessions.user_id` — the
  company carries the data; `user_id` records who started the conversation.

## Notes

- **All financial math is deterministic Python** in `financial_engine`/`scenarios`.
  The AI layer never calculates figures (`system-architecture.md` §4.1).
- INR only, no multi-currency logic.
- Secrets live in `.env` (gitignored), never in code.
