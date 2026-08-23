# Frontend — AI CFO Platform

Next.js (App Router) + TypeScript + Tailwind CSS v4. Structure follows
`system-architecture.md` §2.

## Structure

```
frontend/
  app/                 # route-level pages (App Router)
    layout.tsx         # wraps the app in AuthProvider
    page.tsx           # landing page — backend connectivity + auth nav
    login/             # /login
    signup/            # /signup
    forgot-password/   # /forgot-password — request a reset link (FR-1.4)
    reset-password/    # /reset-password — set a new password from a token (FR-1.4)
    dashboard/         # /dashboard — auth-guarded placeholder (real dashboard: Phase 5)
    company/           # /company — create/edit company profile (FR-1.3)
    data/              # /data — CSV/XLSX import + imported-transaction view (FR-2.1/2.2)
    data/manual/       # /data/manual — guided plain-language manual entry (FR-2.3)
    transactions/      # /transactions — list + inline edit/delete of transactions (FR-2.5)
    globals.css
  components/          # reusable UI (BackendStatus, AuthForm, AuthNav, CompanyForm)
  contexts/            # AuthContext — JWT session (localStorage), current user
  hooks/               # per-feature data-fetching hooks (e.g. useHealth)
  lib/                 # API client (api.ts) — apiGet/apiPost + auth calls
  public/
```

Server state is currently plain `fetch` + local state; React Query/SWR can be
layered in later without changing call sites. Charts (Recharts) arrive with the
dashboard phase.

## Auth (Phase 2.2)

`AuthProvider` (`contexts/AuthContext.tsx`) holds the JWT session: it stores the
token in `localStorage`, rehydrates the user via `GET /auth/me` on load, and
exposes `login`/`signup`/`logout` through the `useAuth()` hook. `/login` and
`/signup` share one `AuthForm`; `/dashboard` redirects to `/login` without a
valid session. (localStorage is a pragmatic prototype choice — a hardened build
would use an httpOnly cookie.)

Password reset (FR-1.4): `/forgot-password` requests a link, `/reset-password`
(reads the token from the URL) sets the new password. With no email service, the
backend returns the link inline in development, which `/forgot-password` surfaces
so the flow is completable end-to-end.

Data import (FR-2.1/2.2): `/data` (auth-guarded, linked from the dashboard)
uploads a CSV/XLSX for the user's company via `uploadFile` in `lib/api.ts`
(multipart through `apiUpload`), then shows the import result — rows imported,
any skipped-row messages, and the parsed transactions — plus a list of past
imports. Requires a company profile first.

Guided manual entry (FR-2.3): `/data/manual` (linked from `/data`) asks a
plain-language question per category ("How much did you spend on rent?") for a
single date, then POSTs the filled-in answers via `createManualTransactions`.
These are ordinary manual transactions — no separate conversion step (FR-2.6).

Manage transactions (FR-2.5): `/transactions` (linked from the dashboard and
`/data`) lists all transactions and supports inline edit + delete via
`updateTransaction`/`deleteTransaction` (`PATCH`/`DELETE /transactions/{id}`).
It also has an **Auto-categorize** button (FR-3.1) calling `autoCategorize`,
which deterministically fills in categories for uncategorized rows, and a
**Detect anomalies** button (FR-3.6) calling `detectAnomalies`, which flags
expense spikes vs. the trailing 3-month average; flagged rows show a ⚠ badge.

## Financial engine client (Phase 4.2)

`lib/api.ts` exposes `getFinancialSummary` (revenue/expense totals + net,
FR-3.2) and `getCashFlow` (per-month inflow/outflow/net, FR-3.3), both taking an
optional `startDate`/`endDate` range, plus `generateKpiSnapshot`/`listKpiSnapshots`
(burn rate, runway, gross/operating margin, revenue growth — FR-4.1–4.5) and
`getHistory` (a continuous N-month performance series for trend charts — FR-3.5/4.6).
These back the Phase 5 dashboard; the numbers are computed deterministically by the
backend (no LLM). Runway/margin/growth fields can be `null` in their undefined
cases (not burning cash / zero revenue / no prior period).

## Company profile (Phase 2.3)

`/company` (auth-guarded, linked from the dashboard) manages the user's company
profile via `CompanyForm` — one component that creates when no company exists
yet and edits otherwise. Currency is shown read-only as INR. Backed by the
company calls in `lib/api.ts` (`listCompanies`/`createCompany`/`updateCompany`).

## Setup

```bash
cd frontend
npm install
cp .env.local.example .env.local   # set NEXT_PUBLIC_API_URL if backend isn't on :8000
```

## Run

```bash
npm run dev        # http://localhost:3000
```

The backend must be running (see `../backend/README.md`) for the landing page's
connectivity panel to show "Backend connected".

## Build

```bash
npm run build
```

## Notes

- Talks to the backend via `NEXT_PUBLIC_API_URL` (default `http://localhost:8000`).
- INR-only product; no multi-currency UI.
