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

**Phase:** Phase 3 **in progress** — 3.1–3.4 done: categories seeded, CSV/XLSX upload, guided manual entry, and upload/entry validation + duplicate detection all working end-to-end (schema at migration `0003`; 3.4 added dedupe with no migration). Next: 3.5 (edit/delete previously entered data).

**What exists:**
- ✅ Docs: proposal, SRS, `system-architecture.md`, `database/schema.md`
- ✅ **Backend** — FastAPI, domain-module structure (`app/core` + `auth`/`companies`/`transactions`/`financial_engine`/`scenarios`/`ai_cfo`/`reports` placeholders). Boots on `:8000`; `GET /api/v1/health` live; 2 pytest smoke tests pass.
- ✅ **Frontend** — Next.js 16 (App Router) + React 19 + Tailwind v4 + TypeScript. Boots on `:3000`; landing page renders a live `BackendStatus` panel that fetches backend health. Lint + production build pass.
- ✅ **Frontend ↔ backend** confirmed: CORS allows `:3000` (preflight 200 + correct allow-origin header); health reachable end-to-end.
- ✅ **DB layer (2.1)** — SQLAlchemy models `User`/`Company` per `schema.md` §1–2 (UUID PK + `created_at`/`updated_at` mixins, INR default, single-owner FK, fiscal-month check constraint). Alembic migration `0001` **applied to Supabase**; `users`/`companies`/`alembic_version` tables verified live with correct types + constraints. 3 model tests pass.
- ✅ **Supabase connected** — Session pooler (ap-southeast-1), `DATABASE_URL` in `backend/.env` (gitignored). Health endpoint reports `database: "connected"`.
- ✅ **Auth (2.2)** — Backend: `app/auth/` split into `security.py` (bcrypt hashing + PyJWT encode/decode), `service.py`, `schemas.py`, `dependencies.py` (`get_current_user` Bearer guard), `router.py`. Endpoints `POST /auth/signup` (201, auto-login, 409 on dup), `POST /auth/login` (401 on bad creds), `GET /auth/me` (Bearer). Verified end-to-end against live Supabase. Frontend: `AuthContext` (JWT in localStorage + `/auth/me` rehydrate), shared `AuthForm`, `/login` + `/signup` + auth-guarded `/dashboard`, `AuthNav` on the landing page.
- ✅ **Company profiles (2.3)** — Backend: `app/companies/` (`schemas.py`/`service.py`/`router.py`) mirroring the auth split. Endpoints `POST/GET /companies`, `GET/PATCH /companies/{id}`, all Bearer-guarded and scoped by `owner_user_id` (cross-user access → 404, existence not leaked). `currency` server-fixed to INR. Frontend: `/company` page + shared `CompanyForm` (create-or-edit), linked from the dashboard; INR shown read-only, fiscal-month as a month select.
- ✅ **Validation + dedupe (3.4)** — No migration. Missing-date/non-numeric already handled (uploads skip+report; manual via Pydantic). Added **duplicate detection** on both paths: signature `(date, amount, type, description)` per company (category excluded so re-imports match). Uploads seed the seen-set from existing rows → re-upload/within-file repeats skipped and listed in `error_log` (parser now carries `source_row` for "Row N" messages). Manual `POST /transactions` now returns `{created, skipped_duplicates}` (dupes skipped, not double-entered), surfaced in `/data/manual`. **76 backend tests pass** (4 new: 2 upload + 2 manual dedupe). Verified live: re-upload same CSV → row_count 0 + per-row dup messages; manual re-submit → skipped.
- ✅ **Manual entry (3.3)** — Guided plain-language flow (FR-2.3), no migration (reuses `transactions`, `source="manual"`). Backend: `GET /categories?company_id=` (defaults + company's), `POST /transactions` (batch manual create; type from category, explicit override e.g. Other-as-income; amount `>0`; 400 bad category / 404 not-owner), `GET /transactions?company_id=` (upload+manual, newest first) — all owner-scoped. Frontend: `/data/manual` asks one question per category ("How much did you spend on rent?") for a single date, "money in/out" hint per row (toggle on Other), submits filled answers as a batch; linked from `/data`. Manual entries land identically to uploads → feed KPIs with no conversion (FR-2.6, confirmed in 3.6). **72 backend tests pass** (9 new). Verified live on Supabase.
- ✅ **Data upload (3.2)** — Backend: `UploadBatch` + `Transaction` models (`schema.md` §4–5; check constraints on `status`/`source`/`type`, FK cascades, `amount` numeric(14,2) stored as positive magnitude). Migration `0003` **applied to Supabase** (head). DB-free `parsing.py` (alias header mapping, Indian-format amounts, parenthesised negatives, bad-row skip w/ messages) + `service.py` (category name-match → `category_id`; type = explicit col → category type → amount sign). Endpoints `POST /uploads` (multipart file+company_id), `GET /uploads?company_id=`, `GET /uploads/{id}` — all owner-scoped (cross-user → 404). Frontend: `/data` page (file picker, import result table, past imports), linked from dashboard; `apiUpload` + upload API calls. **63 backend tests pass** (19 new: 8 parsing unit + 9 upload endpoint + model structure). Verified live: CSV with `1,20,000` → 120000.00, categories mapped, types resolved, bad row skipped→error_log; list/get; ownership 404.
- ✅ **Categories (3.1)** — `Category` model in `app/transactions/models.py` per `schema.md` §3 (nullable `company_id` → NULL = system default, FK→companies `ON DELETE CASCADE`, `type` check constraint `income`|`expense`, index on `company_id`). Alembic migration `0002` creates the table and seeds 7 system defaults (Revenue=income; Payroll/Rent/Marketing/Software/Tools/Operations/Other=expense) from a frozen list. **Applied to Supabase** (head `0002`); 7 rows + check constraint verified live (constraint also confirmed to reject a bad type). Living default list: `app/transactions/categories.py::DEFAULT_CATEGORIES`. Registered in `env.py` + `main.py`. **44 backend tests pass** (5 new: 4 constant + 1 model structure). No endpoint/UI yet — that arrives with the phases that consume categories.
- ✅ **Password reset (2.4)** — Backend: `POST /auth/password-reset/{request,confirm}`. Request always returns 200 (no enumeration); with no email service the link is logged and returned inline in `development`. Reset tokens are stateless JWTs with a `type: reset` claim + a fingerprint (`pwf`) of the current password hash → single-use (self-invalidate on password change), no DB table. Access/reset tokens now both carry a `type` claim each decoder checks (no cross-use). Frontend: `/forgot-password` + `/reset-password` (token from URL, Suspense-wrapped), "Forgot password?" link on login, success banner via `?reset=1`. **39 backend tests pass** (11 new: 5 security unit + 6 reset endpoint incl. single-use); frontend lint + build clean; all 8 routes serve 200.
- ❌ Wireframes deliberately deferred until after a working end-to-end version exists.

**Stack versions:** Node 22, Python 3.14, Next 16.3, React 19.2, Tailwind 4, FastAPI 0.141, SQLAlchemy 2.0, psycopg 3.3, Alembic 1.14+. Backend deps use lower-bound pins (`>=`) so pip resolves Python-3.14-compatible wheels.

**Build approach:** Get the whole system functionally working end-to-end with a decent (not final) frontend first. Polish/UX pass comes later, wireframes included.

---

## Next Up

1. **3.5** — Edit/delete previously entered/uploaded data (FR-2.5). A `GET /transactions?company_id=` list endpoint already exists; add `PATCH`/`DELETE /transactions/{id}` (owner-scoped) + a frontend transactions table with inline edit/delete. On edit, keep the stored-positive-amount + `type` conventions.
2. **3.6** — Confirm manual data flows into KPIs/dashboard/reports identically to uploads, no conversion step (FR-2.6). Largely already true by design (same table, `source` only differs) — this task is the explicit verification once the financial engine exists.

Phase 2 done; Phase 3 (data input) underway (3.1–3.4 done). Order follows the dependency chain — nothing downstream works without data + the financial engine first.

---

## Known Issues

- **⚠️ DB password was briefly exposed.** The Supabase DB password was pasted into the (git-tracked) `.env.example` and appeared in chat. It was scrubbed from `.env.example` before any commit (never entered git history) and moved to the gitignored `.env`. **Recommended:** reset the database password in Supabase (Settings → Database → Reset database password) and update `backend/.env`, since it was shown in plaintext. Low urgency for a capstone, but worth doing.
- **`greenlet` must be installed** for SQLAlchemy async on Python 3.14 (not auto-pulled). Now pinned in `requirements.txt`.
- **Health-panel browser fetch verified only indirectly.** Backend health, CORS preflight, and the page HTML/JS were each confirmed via curl; the actual in-browser fetch (client-side JS) wasn't exercised with a real browser. All dependencies of it are green, so risk is low.
- `frontend/AGENTS.md` + `frontend/CLAUDE.md` are regenerated by `create-next-app`/Next build; gitignored and not part of this project's conventions.

---

## Log

### 2026-08-21 — Phase 3.4 DONE: upload/entry validation + duplicate detection (FR-2.4)
- **No migration.** Missing-date / non-numeric amounts were already handled (uploads skip+report per row; manual rejected by Pydantic — date required, amount `>0`). This task adds **duplicate detection** on both paths.
- **Dedupe design:** signature = `(date, amount(2dp), type, normalized description)` scoped to a company; category deliberately excluded so a re-import still matches. `service._existing_signatures` loads the company's current signatures; the per-run `seen` set is seeded from them, so both re-imports/re-submissions *and* repeats within one file/submission are caught. Trade-off (documented): two genuinely identical entries collapse to one.
- **Uploads:** `parsing.ParsedRow` gained `source_row` (file line no.); `process_upload` skips duplicates and appends `Row N: duplicate … — skipped.` to `error_log`; `row_count` counts only inserted rows.
- **Manual:** `create_manual_transactions` now returns `(created, skipped_messages)`; `POST /transactions` response changed to `ManualEntryResult {created, skipped_duplicates}`. Frontend `/data/manual` shows saved entries + an amber "skipped N likely duplicates" panel; `lib/api.ts` type updated.
- **Verified:** 76 backend tests pass (4 new — re-upload skips all as dup, within-file dup, manual dup-of-existing, manual within-batch dup). Live on Supabase: upload #1 row_count 2 → re-upload same file row_count 0 with two "Row N: duplicate" messages; manual create 1 → re-submit created 0 / skipped 1. Frontend lint + build + TS clean. Test data cleaned up.
- **Docs updated:** architecture §3 (validation & dedupe note + manual response shape), backend README (upload + manual dedupe), `tasks.md` 3.4 → [x].

### 2026-08-21 — Phase 3.3 DONE: guided manual data entry (plain-language), end-to-end
- **No migration** — manual entries reuse the `transactions` table with `source="manual"` + null `upload_batch_id`, so they're first-class and feed KPIs identically to uploads (FR-2.6, to be confirmed in 3.6).
- **Backend:** schemas `CategoryRead` / `ManualTransactionInput` (amount `>0`, `model_validator` requires category or explicit type) / `ManualTransactionBatch`. `service.py` — `list_categories` (defaults + company's, defaults-first), `create_manual_transactions` (validates category is usable → `ManualEntryError`; type = explicit → category type; stores positive amount), `list_transactions`. `router.py` gained two routers: `categories_router` (`GET /categories?company_id=`) and `transactions_router` (`POST /transactions` batch create → 201, `GET /transactions?company_id=`), both `_require_company`-scoped; registered in `main.py`.
- **Frontend:** `/data/manual` — one plain-language question per category ("How much did you spend on rent?"), single date field, "money in/out" hint per row (income/expense toggle only on flexible "Other"); submits filled answers as a batch and shows a saved summary. `lib/api.ts` + `Category`/`ManualEntryInput` types, `listCategories`/`createManualTransactions`/`listTransactions`. `/data` links to it.
- **Verified:** 72 backend tests pass (9 new — categories list + manual create incl. category-type resolution, explicit override, unknown-category 400, missing type/category 422, non-positive 422, cross-user 404, list includes manual). Live on Supabase: signup→company→list categories (7 defaults, types correct)→create 2 manual (income/expense, source=manual, batch_id null, positive amounts)→list shows them; test data cleaned up. Frontend lint + build + TS clean; `/data`, `/data/manual` serve 200.
- **Docs updated:** architecture §3 (categories + manual-entry endpoints + FR-2.6 note), both READMEs, `tasks.md` 3.3 → [x].
- **Scope note:** validation feedback + duplicate detection is 3.4; transaction edit/delete UI is 3.5. Added a `GET /transactions` list endpoint now (small, needed by the flow + useful for 3.5/dashboard).

### 2026-08-20 — Phase 3.2 DONE: CSV/XLSX upload → upload_batches + transactions, end-to-end
- **Models/migration:** `UploadBatch` + `Transaction` added to `app/transactions/models.py` per `schema.md` §4–5 (check constraints `ck_upload_batches_status`, `ck_transactions_source`, `ck_transactions_type`; company/category/batch FKs with CASCADE / SET NULL; `amount` numeric(14,2)). Migration `0003` created both tables + indexes; offline `--sql` reviewed, `alembic upgrade head` applied to **live Supabase** (head `0003`).
- **Parsing (`parsing.py`, DB-free/unit-tested):** normalises headers and maps aliases (Transaction Date→date, Amount (INR)→amount, Narration→description, Category, Type); cleans Indian-format amounts (`1,20,000`, `₹`, parenthesised negatives); requires date+amount columns (else `UploadParseError`); skips unparseable rows with `Row N: …` messages instead of aborting (NFR-6). Handles CSV + XLSX (openpyxl; date cells rendered ISO).
- **Service/router:** `service.py` resolves category by case-insensitive name (company + system defaults) → `category_id`, and `type` via explicit column → category type → amount sign; stores `amount` as positive magnitude. `router.py`: `POST /uploads` (multipart), `GET /uploads?company_id=`, `GET /uploads/{id}`, all owner-scoped via `get_company_for_user` / a batch→company→owner join (cross-user → 404). `400` on bad file/missing columns/oversize (10 MB).
- **Frontend:** `apiUpload` (multipart, no forced Content-Type) + `uploadFile`/`listUploads`/`getUpload` in `lib/api.ts`; new `/data` page (auth-guarded) — file picker, import-result panel (rows imported + skipped-row notes + transaction table with INR formatting), past-imports list. Dashboard links to it.
- **Deps:** `python-multipart` (uploads) + `openpyxl` (XLSX).
- **Verified:** 63 backend tests pass (19 new — 8 parsing, 9 upload-endpoint incl. ownership 404 + category/type resolution + bad-row logging, plus model-structure). Live against Supabase: CSV with aliased headers + `1,20,000` → `120000.00`, categories mapped (`category_id` set), types from category (Revenue→income, Rent/Software/Tools→expense), bad no-date row skipped → `error_log` + `row_count=3`; list + get-by-id; sign-based inference. Frontend lint + build + TS clean; `/`, `/dashboard`, `/company`, `/data` serve 200. Test rows cleaned up (cascade).
- **Docs updated:** architecture §3 (upload endpoints + parser/type/amount decisions) & §6 (0003), `schema.md` §4 (amount-magnitude + type-resolution note), both READMEs, `tasks.md` 3.2 → [x].
- **Scope note:** richer validation + duplicate detection is task 3.4 (parser already reports missing-date/non-numeric per row; duplicates not yet handled). Transaction edit/delete + a full transactions list endpoint are 3.5.

### 2026-08-20 — Phase 3.1 DONE: categories table + seeded defaults, live on Supabase
- **Model:** `app/transactions/models.py` `Category` per `schema.md` §3 — nullable `company_id` (NULL = system default) FK→companies `ON DELETE CASCADE`, `name`, `type` with check constraint `ck_categories_type` (`income`|`expense`), index on `company_id`. Living default list in `app/transactions/categories.py` (`DEFAULT_CATEGORIES` + `CATEGORY_TYPES`).
- **Migration `0002`:** creates `categories` and seeds 7 system defaults (Revenue=income; Payroll/Rent/Marketing/Software/Tools/Operations/Other=expense) via `op.bulk_insert`. The seed list is a **frozen copy** inlined in the migration (a migration must not change if the app constant is later edited). Registered transactions models in `migrations/env.py` and `app/main.py`.
- **Verified:** offline `--sql` render correct (table + FK + check + index + 7 inserts). `alembic upgrade head` on **live Supabase** → head `0002`; queried live: 7 rows all `company_id NULL` with correct types, `ck_categories_type` present, and a bad-type insert is rejected by the constraint (rolled back). 44 backend tests pass (5 new: 4 default-set constant + 1 model structure; also updated the exact-table-set assertion to include `categories`).
- **Docs updated:** `schema.md` §3 (default income/expense mapping + migration/constant note), backend README (migration list + upgrade comment), architecture §6 (0002), `tasks.md` 3.1 → [x].
- **Scope note:** table + seed only — no categories endpoint or UI yet (added by the phases that consume them: manual entry 3.3, auto-categorization 4.1). No unique constraint on category names for MVP (custom categories are post-MVP; seed idempotency comes from migrations running once).

### 2026-08-20 — Phase 2.4 DONE: password reset flow (email stubbed), end-to-end — Phase 2 complete
- **Backend:** `security.py` gained reset-token helpers — `create_password_reset_token` / `decode_password_reset_token` / `password_fingerprint`; both token kinds now carry a `type` claim (`access`/`reset`) that each decoder verifies (a reset token can't be replayed as a session token, or vice versa). Reset tokens embed `pwf` = fingerprint of the current password hash → single-use with **no DB table** (stops matching once the password changes). `service.py` — `create_password_reset` (returns token or None, no enumeration) + `reset_password` (validates token, checks fingerprint, rehashes). `router.py` — `POST /auth/password-reset/request` (always 200; logs link, returns it inline in `development`) + `/confirm` (400 on bad/used token). New config: `reset_token_expire_minutes` (30), `frontend_base_url`.
- **Frontend:** `/forgot-password` (surfaces the dev reset link) + `/reset-password` (token from URL, `useSearchParams` wrapped in `Suspense`). `AuthForm` gained a "Forgot password?" link (login mode) + a `notice` prop; `/login` is now a server component reading `?reset=1` to show a success banner (avoids a Suspense boundary on the form). `lib/api.ts` + `requestPasswordReset`/`resetPassword`.
- **Verified:** 39 backend tests pass (11 new — 5 security unit incl. access/reset cross-use rejection, 6 reset-endpoint incl. single-use + no-enumeration). Full flow curl'd against **live Supabase**: request (dev returns token) → unknown-email (no token) → confirm 200 → old-pw login 401 → new-pw login 200 → token reuse 400; test user cleaned up. Frontend lint + build + TS clean; all 8 routes serve 200 (incl. `/forgot-password`, `/reset-password?token=…`, `/login?reset=1`).
- **Docs updated:** architecture §3 (reset endpoints + token-type/single-use note), backend README (reset rows + how to wire real email later), frontend README, `.env.example` (`FRONTEND_BASE_URL`), `tasks.md` 2.4 → [x].
- **Design note:** chose stateless single-use JWT reset tokens (fingerprint trick) over a `password_reset_tokens` table — no migration needed, self-invalidating. Trade-off: can't list/revoke outstanding tokens server-side, acceptable for the prototype. Real email delivery is a one-line swap in the router (documented).

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