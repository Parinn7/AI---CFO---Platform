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

**Phase:** Not started — repo has docs only (proposal, SRS, architecture, schema), no code yet.

**What exists:**
- ✅ `docs/proposal/project-proposal.md`
- ✅ `docs/srs/software-requirements-specification.md`
- ✅ `designs/diagrams/system-architecture.md`
- ✅ `database/schema.md`
- ❌ No frontend code
- ❌ No backend code
- ❌ No database provisioned
- ❌ Wireframes deliberately deferred until after a working end-to-end version exists

**Build approach:** Get the whole system functionally working end-to-end with a decent (not final) frontend first. Polish/UX pass comes later, wireframes included.

---

## Next Up

1. **Project scaffolding** — initialize Next.js frontend and FastAPI backend per the folder structure in `system-architecture.md`, connect to PostgreSQL, confirm the stack boots end-to-end.
2. **Auth + Company setup** (FR-1.1–FR-1.4) — signup, login, JWT sessions, company profile creation. Everything else in the SRS depends on a user + company existing, so this is the true starting point.
3. Data input (upload + manual entry) — FR-2.x
4. Financial engine (categorization, cash flow, KPIs) — FR-3.x, FR-4.x
5. Dashboard — FR-8.x
6. Scenario simulator — FR-5.x
7. AI CFO chat — FR-6.x
8. Reports — FR-7.x

(This order follows dependency chain: nothing downstream works without auth + data + the financial engine existing first.)

---

## Known Issues

_None yet — build hasn't started._

---

## Log

_No entries yet. First entry will be added after the first Claude Code session._

<!-- 
Template for new entries:

### [Date] — [Short session title]
- What was built/changed:
- What's now working:
- What broke or is incomplete:
- Docs updated (if any):
-->