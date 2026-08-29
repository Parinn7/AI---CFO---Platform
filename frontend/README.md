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
    dashboard/         # /dashboard — overview: KPI cards, charts, recent activity (FR-8.1)
    company/           # /company — create/edit company profile (FR-1.3)
    data/              # /data — CSV/XLSX import + imported-transaction view (FR-2.1/2.2)
    data/manual/       # /data/manual — guided plain-language manual entry (FR-2.3)
    transactions/      # /transactions — list + inline edit/delete of transactions (FR-2.5)
    scenarios/         # /scenarios — define + simulate a "what if?" scenario (FR-5.1/5.2/5.3)
    globals.css
  components/          # reusable UI (BackendStatus, AuthForm, AuthNav, CompanyForm,
                       #   StatCard, KpiCards, ScenarioComparison, DashboardCharts —
                       #   inline-SVG KPI/trend charts)
  contexts/            # AuthContext — JWT session (localStorage), current user
  hooks/               # per-feature data-fetching hooks (e.g. useHealth)
  lib/                 # API client (api.ts) — apiGet/apiPost + auth calls; format.ts — INR/month;
                       #   scenarios.ts — scenario assumption model + validation
  public/
```

Server state is currently plain `fetch` + local state; React Query/SWR can be
layered in later without changing call sites. Charts are **dependency-free inline
SVG** (no chart library), theme-aware via `--viz-*` tokens in `globals.css`.

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

## Overview dashboard (Phase 5.1 / 5.2 / 5.3)

`/dashboard` (auth-guarded) is the first UI consumer of the whole Financial
Engine (FR-8.1). It shows **KPI cards** (burn rate, runway, gross margin, revenue
growth — from a `kpi_snapshot`), two **charts** (revenue-vs-expenses lines +
net-cash-flow diverging bars, FR-4.6), and **recent activity**. All numbers come
from the backend; the UI only displays them.

- **Anomaly highlighting (5.3, FR-8.3):** anomaly detection is re-run on load
  (idempotent), then flagged expenses are surfaced three ways — an **attention
  callout** with the count for the viewed period, **amber markers** on the
  anomalous months in both charts (dot under the axis + a legend key + a bar
  ring + a tooltip note), and the **⚠ badge** on flagged rows in recent activity.

- **Date-range filtering (5.2, FR-8.2):** a period selector (**3M / 6M / 12M /
  All**, default 12M, anchored to the latest month of data) re-scopes the whole
  view — the charts, the KPI snapshot period, and the period-totals line all
  follow it (`All` spans earliest→latest data month, capped at 60). Switching
  re-queries `getHistory` + the snapshot for the new window.
- **KPI cards use get-or-create:** reuse a stored snapshot for the selected
  period, generating one only if missing; "Refresh KPIs" force-regenerates.
- **Charts** are dependency-free inline SVG in `components/DashboardCharts.tsx`,
  theme-aware via the `--viz-*` tokens in `globals.css` (dataviz-skill reference
  palette, validated light + dark), with a legend + hover tooltip on each.
  `components/StatCard.tsx` is the KPI tile; `lib/format.ts` has the INR/month
  formatters (incl. `addMonths`/`monthSpan` for the range windows).

## Scenario simulator (Phase 6.1 / 6.2 / 6.3 / 6.4)

`/scenarios` (auth-guarded, linked from the dashboard) is the input side of the
Scenario Simulator (FR-5.1). It shows the company's **baseline** — the same
last-12-months `kpi_snapshot` the dashboard uses, get-or-create — then asks the
levers as plain-language questions, in the guided style of manual entry: how
many people would you hire, what would each cost per month, and what would you
change about marketing spend / prices / revenue (in %).

`lib/scenarios.ts` owns the shared input model: the `ScenarioAssumptions` shape
(whose keys are exactly what `scenarios.assumptions` stores, schema §7), the
field specs that drive the form, `validateScenario` (range checks, whole-number
hires, "hiring needs a cost per hire", "change at least one thing"), and
`describeAssumptions`, which reads the scenario back in plain English before
anything is run. It contains **no financial math** — every projected figure is
deterministic backend code (architecture §4.1).

**Running it (6.3, FR-5.3):** "Run simulation" validates the form, then posts the
assumptions via `simulateScenario` to `POST /scenarios/simulate` and renders the
result. Editing any field clears the result, so what's on screen always describes
the form above it. The call is stateless — nothing is saved until you say so.

`components/ScenarioComparison.tsx` renders the before/after. It's a **table**
rather than `KpiCards`, because the point is the comparison: three aligned
numeric columns (before / after / change) read far better across seven metrics
than two rows of tiles. Two details it gets right:

- **A null delta is not zero.** The backend returns `null` for a delta whenever
  *either* side is undefined (runway when not burning cash or out of cash, margin
  at zero revenue, growth with no prior period). Those render as an em dash with
  a tooltip naming which side is undefined — never as `0`, which would read as
  "no change".
- **Percentage metrics change in percentage points.** A margin going 39.0% →
  50.6% is **+11.6pp**, not +11.6%.

`AppliedChangesList` (same file) renders the `applied` block as prose — the extra
payroll in rupees, the Marketing base the percentage was applied to, and the
combined revenue multiplier — so the view explains *why* the numbers moved rather
than just showing different ones. It says so explicitly when the marketing lever
had no effect because none of the period's spend is categorised as Marketing.

`components/KpiCards.tsx` holds the four headline KPI tiles, shared with the
dashboard, and renders the scenario page's baseline panel.

**Saving and revisiting (6.4, FR-5.4):** "Save this scenario" posts the levers to
`POST /scenarios` — never the result, which the backend re-runs and stores
itself. A **Saved scenarios** list (name · save time · net cash flow before →
after) sits below, with Open and Delete. **Opening one shows the stored
comparison verbatim** — the figures as they were when it was saved, not a
recomputation against today's data — and drops its levers back into the form, so
re-running it is a deliberate next click. The result header says which it is
("· saved 29 Aug 2026, 15:34" vs. "· not saved"), and touching any lever clears
the saved framing along with the result.

`formFromAssumptions()` in `lib/scenarios.ts` restores saved levers into form
state; a lever at 0 comes back **blank**, because blank is how this form spells
"no change". Note the read/write asymmetry in `lib/api.ts`: assumptions are
*sent* as numbers (`ScenarioAssumptionsPayload`) but come *back* with the
Decimal fields as strings (`ScenarioAssumptionsRead`), like every other figure
the API returns — coerce, don't assume.

## AI CFO chat (Phase 7.1)

`/chat` (auth-guarded, linked from the dashboard and `/scenarios`) is the
conversational interface (FR-6.1): a conversation list, a transcript, and a
composer. Conversations persist and reopen where you left off.

**It is honest that it isn't finished.** 7.1 is the interface and its
persistence — no model is connected — so the page carries a "Not connected yet"
notice and the assistant replies with a placeholder that quotes no figures. A
screen that looked like a working assistant and simply gave poor answers would
be worse than one that says what it is.

Details it gets right:

- **A conversation is created lazily**, on the first question, so opening the
  page never leaves an empty session in the history.
- **The transcript renders the stored rows** returned by the server, not a local
  echo of what was typed — so what's on screen is what's in the database.
- **The advisory disclaimer (FR-6.5) is shown from the start**, under the
  composer, because assistant-labelled text exists from the start. Enter sends,
  Shift+Enter breaks a line.

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
