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
