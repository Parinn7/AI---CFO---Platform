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
    transactions/        # Phase 3 — upload parsing, manual entry, categorization (FR-2.x)
    financial_engine/    # Phase 4 — deterministic KPI/cash-flow/anomaly math (FR-3.x, FR-4.x)
    scenarios/           # Phase 6 — scenario simulation (FR-5.x)
    ai_cfo/              # Phase 7 — LLM orchestration, chat (FR-6.x)
    reports/             # Phase 9 — report generation + PDF export (FR-7.x)
  migrations/            # Alembic: env.py + versions/ (0001 = users + companies; 0002 = categories + seed)
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

## Notes

- **All financial math is deterministic Python** in `financial_engine`/`scenarios`.
  The AI layer never calculates figures (`system-architecture.md` §4.1).
- INR only, no multi-currency logic.
- Secrets live in `.env` (gitignored), never in code.
