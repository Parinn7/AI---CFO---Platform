# Progress Tracker

## AI-Powered Financial Operating System

This file is the single source of truth for build status. **Claude Code must read this file before starting any work session**, and update it before ending one.

---

## How to Use This File

- **Current Status** — always overwritten to reflect the real current state. Never let this go stale.
- **Next Up** — the immediate next task(s), specific enough to turn directly into a prompt.
- **Log** — append-only. One entry per work session, newest at the top. Never edit past entries, just add new ones.
- **Known Issues** — anything broken, half-done, or deliberately deferred. Remove an item once it's actually fixed.

**Standing rule for every Claude Code session:** if the work introduces a new API endpoint, DB table/column, or architectural decision not yet reflected in `system-architecture.md` or `schema.md`, update that doc (or create a new one in the right folder) as part of the same session — don't leave documentation to drift from code.

---

## Current Status

**Phase:** Phase 2.3 **complete** — owner-scoped company profile CRUD API + create/edit UI, working end-to-end against live Supabase. Next: 2.4 (password reset flow, email stubbed).

**What exists:**
- ✅ Docs: proposal, SRS, `system-architecture.md`, `database/schema.md`
- ✅ **Backend** — FastAPI, domain-module structure (`app/core` + `auth`/`companies`/`transactions`/`financial_engine`/`scenarios`/`ai_cfo`/`reports` placeholders). Boots on `:8000`; `GET /api/v1/health` live; 2 pytest smoke tests pass.
- ✅ **Frontend** — Next.js 16 (App Router) + React 19 + Tailwind v4 + TypeScript. Boots on `:3000`; landing page renders a live `BackendStatus` panel that fetches backend health. Lint + production build pass.
- ✅ **Frontend ↔ backend** confirmed: CORS allows `:3000` (preflight 200 + correct allow-origin header); health reachable end-to-end.
- ✅ **DB layer (2.1)** — SQLAlchemy models `User`/`Company` per `schema.md` §1–2 (UUID PK + `created_at`/`updated_at` mixins, INR default, single-owner FK, fiscal-month check constraint). Alembic migration `0001` **applied to Supabase**; `users`/`companies`/`alembic_version` tables verified live with correct types + constraints. 3 model tests pass.
- ✅ **Supabase connected** — Session pooler (ap-southeast-1), `DATABASE_URL` in `backend/.env` (gitignored). Health endpoint reports `database: "connected"`.
- ✅ **Auth (2.2)** — Backend: `app/auth/` split into `security.py` (bcrypt hashing + PyJWT encode/decode), `service.py`, `schemas.py`, `dependencies.py` (`get_current_user` Bearer guard), `router.py`. Endpoints `POST /auth/signup` (201, auto-login, 409 on dup), `POST /auth/login` (401 on bad creds), `GET /auth/me` (Bearer). Verified end-to-end against live Supabase. Frontend: `AuthContext` (JWT in localStorage + `/auth/me` rehydrate), shared `AuthForm`, `/login` + `/signup` + auth-guarded `/dashboard`, `AuthNav` on the landing page.
- ✅ **Company profiles (2.3)** — Backend: `app/companies/` (`schemas.py`/`service.py`/`router.py`) mirroring the auth split. Endpoints `POST/GET /companies`, `GET/PATCH /companies/{id}`, all Bearer-guarded and scoped by `owner_user_id` (cross-user access → 404, existence not leaked). `currency` server-fixed to INR. Frontend: `/company` page + shared `CompanyForm` (create-or-edit), linked from the dashboard; INR shown read-only, fiscal-month as a month select. **28 backend tests pass** (7 new company endpoint tests incl. owner-scoping); frontend lint + build clean; all 6 routes serve 200.
- ❌ Wireframes deliberately deferred until after a working end-to-end version exists.

**Stack versions:** Node 22, Python 3.14, Next 16.3, React 19.2, Tailwind 4, FastAPI 0.141, SQLAlchemy 2.0, psycopg 3.3, Alembic 1.14+. Backend deps use lower-bound pins (`>=`) so pip resolves Python-3.14-compatible wheels.

**Build approach:** Get the whole system functionally working end-to-end with a decent (not final) frontend first. Polish/UX pass comes later, wireframes included.

---

## Next Up

1. **2.4** — Password reset flow (FR-1.4). Stub email sending if no email service configured (log/return the reset link/token instead of sending). Add reset-request + reset-confirm endpoints under `app/auth/`, a short-lived reset token, and matching request/confirm pages on the frontend.

Then Phase 3 (data input) onward. Order follows the dependency chain: nothing downstream works without auth + data + the financial engine first.

---

## Known Issues

- **⚠️ DB password was briefly exposed.** The Supabase DB password was pasted into the (git-tracked) `.env.example` and appeared in chat. It was scrubbed from `.env.example` before any commit (never entered git history) and moved to the gitignored `.env`. **Recommended:** reset the database password in Supabase (Settings → Database → Reset database password) and update `backend/.env`, since it was shown in plaintext. Low urgency for a capstone, but worth doing.
- **`greenlet` must be installed** for SQLAlchemy async on Python 3.14 (not auto-pulled). Now pinned in `requirements.txt`.
- **Health-panel browser fetch verified only indirectly.** Backend health, CORS preflight, and the page HTML/JS were each confirmed via curl; the actual in-browser fetch (client-side JS) wasn't exercised with a real browser. All dependencies of it are green, so risk is low.
- `frontend/AGENTS.md` + `frontend/CLAUDE.md` are regenerated by `create-next-app`/Next build; gitignored and not part of this project's conventions.

---

## Log

### 2026-08-20 — Phase 2.3 DONE: company profile CRUD API + UI, owner-scoped, end-to-end
- **Backend (`app/companies/`):** `schemas.py` — `CompanyCreate`/`CompanyUpdate` (fiscal month validated 1–12) / `CompanyRead`; currency deliberately *not* a client input (INR-only, DB `server_default`). `service.py` — create / list / `get_company_for_user` / `update_company`, every query filtered by `owner_user_id` (NFR-3). `router.py` — `POST`/`GET /companies`, `GET`/`PATCH /companies/{id}`, all `Depends(get_current_user)`; cross-user access returns `404` (existence not leaked). Registered under `/api/v1/companies` in `main.py`.
- **Frontend:** `lib/api.ts` gained `apiPatch` + `Company` type + `listCompanies`/`createCompany`/`updateCompany`. New `/company` page (auth-guarded, redirects to `/login`) loads the user's company and renders `CompanyForm` — one component that creates when none exists and edits otherwise. INR shown read-only; fiscal-year-start as a month `<select>`. Dashboard now links to it.
- **Verified:** 28 backend tests pass (7 new company tests, incl. "user B can't read/patch user A's company" and INR default). Full flow curl'd against **live Supabase**: create 201 (currency INR) → list → patch (bumps `updated_at`, preserves untouched fields) → no-auth 401 → bad-month 422; test rows cleaned up (cascade via user FK). Frontend lint + build + TS clean; `/`, `/login`, `/signup`, `/dashboard`, `/company` all serve 200.
- **Docs updated:** architecture §3 (company endpoints + owner-scoping note), backend README (companies table + curl), frontend README (company section + structure), `tasks.md` 2.3 → [x].
- **Caveat:** same standing one — in-browser client JS not driven by a real browser; API proven live, build/lint/types green. MVP manages a single company via the UI though the model/API support many.

### 2026-08-20 — Phase 2.2 DONE: signup + login (JWT) + password hashing, end-to-end
- **Backend auth (`app/auth/`):** `security.py` — bcrypt hashing (72-byte-safe) + PyJWT `HS256` access tokens signed with `JWT_SECRET`; `service.py` — `create_user` (email lowercased, dup → `EmailAlreadyRegisteredError`) / `authenticate_user`; `schemas.py` — `SignupRequest`/`LoginRequest`/`UserRead`/`TokenResponse` (never exposes `password_hash`); `dependencies.py` — `get_current_user` (Bearer → `User`, 401 otherwise), the reusable guard for future protected routes; `router.py` — `POST /auth/signup` (201/409), `POST /auth/login` (200/401), `GET /auth/me` (Bearer). Mounted under `/api/v1/auth`.
- **Bug found + fixed via live verification:** signup 500'd on Postgres with `KeyError('Company')` — SQLAlchemy couldn't resolve `User.companies` because only `User` was imported at app startup. Fixed by importing both model modules in `main.py` so all mappers register before the first request. (Tests hadn't caught it: they import both models explicitly.)
- **Frontend:** `AuthContext` (token in localStorage, rehydrates via `/auth/me`, `login`/`signup`/`logout`); `lib/api.ts` gained `apiPost` + `ApiError` (surfaces FastAPI `detail`) + auth calls; shared `AuthForm` for `/login` + `/signup`; auth-guarded `/dashboard` placeholder; `AuthNav` + refreshed copy on the landing page. `layout.tsx` wraps everything in `AuthProvider`.
- **Deps:** backend + `bcrypt`, `PyJWT`, `email-validator`, plus `aiosqlite` + `pytest-asyncio` (test-only) and a `pytest.ini` (`asyncio_mode=auto`).
- **Verified:** 21 backend tests pass (7 security unit, 8 auth-endpoint against in-memory SQLite, 6 prior). Full flow curl'd against **live Supabase**: signup 201 → dup 409 → login 200 → wrong-pw 401 → `/me` 200 → no-token 401; test rows cleaned up afterward. Frontend `lint` + `build` clean; `/`, `/login`, `/signup`, `/dashboard` all serve 200.
- **Docs updated:** architecture §3 (concrete auth endpoints + module split), backend README (auth table + curl example), frontend README (auth section + structure), `tasks.md` 2.2 → [x].
- **Not done / caveat:** in-browser client JS not driven by a real browser (same standing caveat as the health panel) — but every dependency is green and the API is proven live. Argon2 not used; bcrypt chosen (schema allows either). Password-reset (2.4) and company profile (2.3) still pending.

### 2026-08-14 — Phase 2.1 DONE: migration applied to live Supabase
- Provisioned Supabase project; `DATABASE_URL` (Session pooler, ap-southeast-1) in gitignored `backend/.env`. `alembic upgrade head` → `0001 (head)`; verified `users`/`companies` tables live with correct types + all constraints; health endpoint → `database: "connected"`. 2.1 checked off.
- **Fixes along the way:** (a) installed + pinned `greenlet` (SQLAlchemy async needs it on Python 3.14); (b) rewrote `migrations/env.py` to build the engine straight from `settings.database_url` instead of `config.set_main_option` — ConfigParser's `%`-interpolation broke on the URL-encoded `%40` in the password.
- **Security:** DB password had been pasted into the tracked `.env.example`; scrubbed it back to a placeholder before committing (never hit git history) and moved the real value to `.env`. Flagged password rotation in Known Issues.

### 2026-08-14 — Phase 2.1 (code): users + companies models + Alembic (Supabase)
- **DB choice:** Supabase as managed Postgres (managed DB only; not Supabase Auth). Documented in architecture §6 and READMEs.
- **Models:** `app/core/models.py` mixins (UUID PK, `created_at`/`updated_at`); `app/auth/models.py` `User`; `app/companies/models.py` `Company` — per `schema.md` §1–2 (INR default, single-owner FK `ON DELETE CASCADE`, fiscal-month check constraint, unique email index).
- **Migrations:** Alembic wired for async psycopg 3, URL injected from settings (nothing secret in `alembic.ini`). Migration `0001_users_and_companies` hand-written; `env.py` imports models for autogenerate.
- **Verified (no live DB):** models register on `Base.metadata`; `alembic upgrade head --sql` renders correct Postgres DDL (UUID/TEXT/timestamptz/FK/check/unique index); 3 new model tests pass (5 total).
- **NOT done:** migration not applied to a real DB — no Supabase project yet. 2.1 left **unchecked** pending that. Also added `alembic>=1.14` to requirements.
- **Docs updated:** architecture §6, backend README (migrations + Supabase setup), `.env.example`, progress. Committed the pending SRS FR-2.3/FR-2.6 refinement per user request.

### 2026-08-14 — Phase 1.1: project scaffolding (frontend + backend boot end-to-end)
- **Backend:** FastAPI app with domain-module layout per architecture §3 (`app/core` for config + async DB; `auth`/`companies`/`transactions`/`financial_engine`/`scenarios`/`ai_cfo`/`reports` as documented placeholders). Added `GET /api/v1/health` (reports DB status) + CORS. SQLAlchemy 2.0 async engine via psycopg 3, reads `DATABASE_URL`; boots fine with no DB. `requirements.txt`, `.env.example`, README, and 2 pytest smoke tests (both pass).
- **Frontend:** Next.js 16 App Router + React 19 + Tailwind 4 + TS (via create-next-app, reshaped). Added `lib/api.ts` (API client), `hooks/useHealth.ts`, `components/BackendStatus.tsx`; landing page shows live backend connectivity. `.env.local.example`, README. Lint + `next build` pass.
- **What's working:** backend `:8000` serves health (`database: not_configured`); frontend `:3000` renders and ships the health fetch; CORS preflight from `:3000` returns 200 with correct allow-origin. End-to-end path proven.
- **Decisions:** psycopg 3 over asyncpg (Python 3.14 wheels); backend deps lower-bound pinned so pip picks 3.14-compatible wheels; app boots without a DB by design.
- **Docs updated:** `system-architecture.md` §6 (psycopg driver + graceful-degradation health check); both READMEs filled in; `.gitignore` extended. `tasks.md` 1.1 → [x].
- **Incomplete/deferred:** no Postgres provisioned (see Known Issues) — first item of task 2.1.

### 2026-08-14 — Reconciliation check (no code written)
- Verified the repo against `task.md`. Found **no application code anywhere** — no `package.json`, no Python files, no `.tsx`, no configs; `backend/README.md` and `frontend/README.md` are empty placeholders; git history is docs-only (2 commits).
- **Corrected a false checkbox:** `task.md` 1.1 (project scaffolding) was marked `[x]` but nothing was scaffolded — reset to `[ ]`.
- `progress.md` Current Status ("Not started — no code yet") already matched reality; left as-is.
- Net: build has genuinely not started. Phase 1.1 is the true next task.

_First implementation entry will be added after the first build session._

<!-- 
Template for new entries:

### [Date] — [Short session title]
- What was built/changed:
- What's now working:
- What broke or is incomplete:
- Docs updated (if any):
-->