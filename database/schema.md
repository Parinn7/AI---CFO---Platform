# Database Schema

## AI-Powered Financial Operating System for Startups and SMEs

**Database:** PostgreSQL
**Version:** 1.0 (Draft)

---

## Design Notes

- All monetary values stored in INR, as `numeric(14,2)` — never floats, to avoid rounding errors in financial data.
- All KPIs (`kpi_snapshots`) are **precomputed by the Financial Engine and stored**, not calculated on-the-fly by the AI layer. The AI CFO reads from this table; it never derives these numbers itself.
- `company_id` foreign keys everywhere data is company-scoped — every query must filter by it to prevent cross-company data leakage (per NFR-3 in the SRS).
- Timestamps (`created_at`, `updated_at`) are omitted from the listing below for brevity but should be present on every table.

---

## 1. `users`

| Column | Type | Notes |
|---|---|---|
| id | uuid, PK | |
| email | text, unique, not null | |
| password_hash | text, not null | bcrypt/argon2 |
| full_name | text | |
| created_at | timestamptz | |

## 2. `companies`

| Column | Type | Notes |
|---|---|---|
| id | uuid, PK | |
| owner_user_id | uuid, FK → users.id | MVP: single owner per company |
| name | text, not null | |
| industry | text | |
| fiscal_year_start_month | int | 1–12 |
| currency | text, default `'INR'` | fixed at INR for MVP per SRS decision |
| created_at | timestamptz | |

## 3. `categories`

| Column | Type | Notes |
|---|---|---|
| id | uuid, PK | |
| company_id | uuid, FK → companies.id, nullable | null = system default category |
| name | text, not null | e.g. Revenue, Payroll, Rent, Marketing, Software/Tools, Operations, Other |
| type | text, not null | `income` \| `expense`; enforced by check constraint `ck_categories_type` |

Seeded with the simplified default category set from the SRS; companies can add custom categories later (post-MVP). Defaults are **system-wide** (`company_id IS NULL`) and applied by Alembic migration `0002`: **Revenue** (`income`), and **Payroll / Rent / Marketing / Software/Tools / Operations / Other** (all `expense`). The living copy of this list is `app/transactions/categories.py::DEFAULT_CATEGORIES`; migration `0002` keeps a frozen copy so re-running it never changes behaviour.

## 4. `transactions`

| Column | Type | Notes |
|---|---|---|
| id | uuid, PK | |
| company_id | uuid, FK → companies.id, not null | |
| category_id | uuid, FK → categories.id | nullable until categorized |
| source | text, not null | `upload` \| `manual` |
| upload_batch_id | uuid, FK → upload_batches.id | nullable, set if from a file upload |
| date | date, not null | |
| description | text | |
| amount | numeric(14,2), not null | positive = income, negative = expense (or use `type` — see note) |
| type | text, not null | `income` \| `expense` (explicit, intentionally denormalized from `categories.type` — see note below) |
| is_flagged_anomaly | boolean, default false | set by anomaly detection |
| created_at | timestamptz | |

**Design decision — locked in:** `transactions.type` duplicates information derivable from `categories.type`, a deliberate deviation from strict 3NF. A transaction's income/expense classification is set once at creation and stays fixed even if its category is later edited — without this, changing a category's type could silently reclassify every historical transaction linked to it, retroactively altering past KPI snapshots and reports. For a financial platform, audit-stability of historical records outweighs strict normalization here.

**Implementation note (task 3.2):** `amount` is stored as a **positive magnitude**; income/expense direction is carried solely by `type` (so KPI sums are unambiguous). On import, `type` is resolved as: explicit type/direction column → matched category's type → sign of the amount in the file. Created by Alembic migration `0003` alongside `upload_batches`.

## 5. `upload_batches`

| Column | Type | Notes |
|---|---|---|
| id | uuid, PK | |
| company_id | uuid, FK → companies.id | |
| filename | text | |
| status | text | `processing` \| `completed` \| `failed` |
| row_count | int | |
| error_log | text | nullable, validation issues found (FR-2.4) |
| uploaded_at | timestamptz | |

## 6. `kpi_snapshots`

Precomputed KPI values, stored per company per period. This is the table the AI CFO reads from — it never calculates these itself.

| Column | Type | Notes |
|---|---|---|
| id | uuid, PK | |
| company_id | uuid, FK → companies.id | |
| period_start | date | |
| period_end | date | |
| total_revenue | numeric(14,2) | |
| total_expenses | numeric(14,2) | |
| net_cash_flow | numeric(14,2) | |
| burn_rate | numeric(14,2) | |
| runway_months | numeric(6,2) | nullable if burn rate ≤ 0 (i.e. profitable) |
| gross_margin_pct | numeric(6,2) | nullable if revenue = 0 (margin undefined) |
| operating_margin_pct | numeric(6,2) | nullable if revenue = 0; **== gross_margin_pct** — COGS is out of MVP scope (SRS §7), so both hold the same operating figure |
| revenue_growth_pct | numeric(6,2) | period-over-period; nullable if no prior-period revenue to compare against |
| computed_at | timestamptz | stored as the `created_at` timestamp mixin |

**Implementation note (task 4.3):** created by Alembic migration `0004`, composite index on `(company_id, period_start, period_end)`. Written only by `financial_engine.service.generate_kpi_snapshot` — all figures deterministic, the AI never derives them. Definitions (locked in): `burn_rate = (expenses − revenue) / months in period` (positive = burning); `runway_months = cash_on_hand / burn_rate` where `cash_on_hand` is cumulative net cash flow through `period_end` (opening cash ₹0), **null** when not burning (burn ≤ 0) or out of cash (≤ 0); margins as above; `revenue_growth_pct` vs. the immediately preceding equal-length window. `runway`/margins/growth values are clamped to numeric(6,2)'s ±9999.99 range. Margin/growth nullability is a deliberate widening of this table's original spec (which marked only `runway_months` nullable) — storing NULL for an undefined ratio beats a bogus 0.

## 7. `scenarios`

| Column | Type | Notes |
|---|---|---|
| id | uuid, PK | |
| company_id | uuid, FK → companies.id | |
| name | text | user-given label |
| assumptions | jsonb | structured input, e.g. `{"new_hires": 3, "marketing_change_pct": 50}` |
| baseline_kpi_snapshot_id | uuid, FK → kpi_snapshots.id | what it was compared against |
| result | jsonb | computed before/after KPI comparison (Financial Engine output, stored not re-derived) |
| created_at | timestamptz | |

## 8. `chat_sessions`

| Column | Type | Notes |
|---|---|---|
| id | uuid, PK | |
| company_id | uuid, FK → companies.id | |
| user_id | uuid, FK → users.id | |
| started_at | timestamptz | |

## 9. `chat_messages`

| Column | Type | Notes |
|---|---|---|
| id | uuid, PK | |
| session_id | uuid, FK → chat_sessions.id | |
| role | text | `user` \| `assistant` |
| content | text | |
| kpi_context_snapshot_id | uuid, FK → kpi_snapshots.id | nullable — which precomputed KPIs were passed as context for this message, for traceability/debugging |
| created_at | timestamptz | |

## 10. `reports`

| Column | Type | Notes |
|---|---|---|
| id | uuid, PK | |
| company_id | uuid, FK → companies.id | |
| type | text | `monthly` \| `board` \| `investor_readiness` |
| period_start | date | |
| period_end | date | |
| file_path | text | location of generated PDF |
| generated_at | timestamptz | |

---

## Entity Relationship Summary

```
users ──1:N── companies (owner)
companies ──1:N── categories (custom, plus system defaults)
companies ──1:N── transactions
companies ──1:N── upload_batches ──1:N── transactions
companies ──1:N── kpi_snapshots
companies ──1:N── scenarios ──references──> kpi_snapshots (baseline)
companies ──1:N── chat_sessions ──1:N── chat_messages ──references──> kpi_snapshots (context)
companies ──1:N── reports
```

## Indexing Notes (for Claude Code implementation)

- `transactions(company_id, date)` — composite index, since most queries filter by company + date range
- `kpi_snapshots(company_id, period_start, period_end)` — composite index for lookups
- `chat_messages(session_id, created_at)` — for ordered conversation retrieval