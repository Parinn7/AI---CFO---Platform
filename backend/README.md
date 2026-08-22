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
    financial_engine/    # Phase 4 — deterministic categorization/KPI/cash-flow/anomaly math: categorization, calculations, service, schemas, router (FR-3.x, FR-4.x)
    scenarios/           # Phase 6 — scenario simulation (FR-5.x)
    ai_cfo/              # Phase 7 — LLM orchestration, chat (FR-6.x)
    reports/             # Phase 9 — report generation + PDF export (FR-7.x)
  migrations/            # Alembic: env.py + versions/ (0001 users+companies; 0002 categories+seed; 0003 upload_batches+transactions)
  tests/                 # pytest smoke + feature tests
  alembic.ini
  requirements.txt
  .env.example
```

The domain modules beyond `core` are currently package placeholders — they gain
routers/models/services in their respective phases.

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

## Notes

- **All financial math is deterministic Python** in `financial_engine`/`scenarios`.
  The AI layer never calculates figures (`system-architecture.md` §4.1).
- INR only, no multi-currency logic.
- Secrets live in `.env` (gitignored), never in code.
