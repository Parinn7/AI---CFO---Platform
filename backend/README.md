# Backend — AI CFO Platform API

FastAPI service, organized by **domain module** (see `system-architecture.md` §3),
so each feature is self-contained.

## Structure

```
backend/
  app/
    main.py              # FastAPI app: CORS, health endpoint, router wiring
    core/                # config (env/settings) + database (async engine, session, Base)
    auth/                # Phase 2 — signup, login, JWT (FR-1.x)
    companies/           # Phase 2 — company profile CRUD (FR-1.3)
    transactions/        # Phase 3 — upload parsing, manual entry, categorization (FR-2.x)
    financial_engine/    # Phase 4 — deterministic KPI/cash-flow/anomaly math (FR-3.x, FR-4.x)
    scenarios/           # Phase 6 — scenario simulation (FR-5.x)
    ai_cfo/              # Phase 7 — LLM orchestration, chat (FR-6.x)
    reports/             # Phase 9 — report generation + PDF export (FR-7.x)
  tests/                 # pytest smoke + feature tests
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

## Test

```bash
source venv/bin/activate
pytest -q
```

## Notes

- **All financial math is deterministic Python** in `financial_engine`/`scenarios`.
  The AI layer never calculates figures (`system-architecture.md` §4.1).
- INR only, no multi-currency logic.
- Secrets live in `.env` (gitignored), never in code.
