# Frontend — AI CFO Platform

Next.js (App Router) + TypeScript + Tailwind CSS v4. Structure follows
`system-architecture.md` §2.

## Structure

```
frontend/
  app/                 # route-level pages (App Router)
    layout.tsx
    page.tsx           # landing page — confirms backend connectivity (Phase 1 proof)
    globals.css
  components/          # reusable UI (e.g. BackendStatus); charts/tables/forms come later
  hooks/               # per-feature data-fetching hooks (e.g. useHealth)
  lib/                 # API client (api.ts), formatting + auth helpers (added later)
  public/
```

Server state is currently plain `fetch` + local state; React Query/SWR can be
layered in later without changing call sites. Charts (Recharts) arrive with the
dashboard phase.

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
