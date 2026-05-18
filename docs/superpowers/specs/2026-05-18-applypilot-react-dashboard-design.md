# ApplyPilot Real-Time React Control Dashboard

**Date:** 2026-05-18  
**Status:** Implemented (v1)  
**Scope:** Local-only control panel for `applypilot run` pipeline; phase 2 extends to apply/refer/inbox.

## Goal

Start the ApplyPilot pipeline from a browser, then watch in real time: current phase, logs, errors, jobs discovered, and fit scores — without tailing terminals or regenerating static HTML.

## Architecture

| Layer | Responsibility |
|-------|----------------|
| **React UI** (`dashboard/web/`) | Start/stop, phase stepper, log console (SSE), jobs table, stats |
| **FastAPI** (`applypilot serve`, port 9477) | REST + SSE; spawns `applypilot run` subprocess |
| **SQLite** | Existing `jobs` table + new `runs` / `run_events` |
| **Pipeline** | `emit_run_event()` when `APPLYPILOT_RUN_ID` is set |

## v1 constraints

- **Bind:** `127.0.0.1` only.
- **Start:** `POST /api/runs` → subprocess with `APPLYPILOT_RUN_ID`.
- **Monitor:** SSE `/api/runs/{id}/events`; poll `/api/stats` and `/api/jobs`.
- **One active run** at a time unless previous finished.

## Data model

### `runs`

- `id`, `run_type` (`pipeline` | `apply` | `refer` | `inbox`), `status`, `stages_json`, `stream`, `dry_run`, `current_stage`, `exit_code`, timestamps.

### `run_events`

- `id`, `run_id`, `event_type`, `stage`, `level`, `message`, `payload_json`, `created_at`.

Event types: `run_started`, `run_finished`, `stage_start`, `stage_end`, `stage_error`, `log`, `stats_tick`.

## API (v1)

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/runs` | Start pipeline run |
| POST | `/api/runs/{id}/stop` | Stop run |
| GET | `/api/runs` | List runs |
| GET | `/api/runs/{id}` | Run detail |
| GET | `/api/runs/{id}/events` | SSE stream |
| GET | `/api/stats` | `get_stats()` |
| GET | `/api/jobs` | Filtered job list |
| GET | `/api/jobs/recent` | Recently discovered/scored |

## CLI

```bash
applypilot serve              # API + built UI if present
applypilot serve --port 9477 --no-open
```

Dev: `applypilot serve` + `cd dashboard/web && npm run dev` (Vite proxies `/api`).

## Phase 2

Same run controller pattern for `apply`, `refer`, `inbox` with `run_type` discriminator and workflow-specific event sources.

## Security

Optional `APPLYPILOT_DASHBOARD_TOKEN` for mutating routes. Log redaction for API keys in subprocess output.
