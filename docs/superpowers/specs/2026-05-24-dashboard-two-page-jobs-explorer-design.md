# Dashboard: two-page Home + Jobs explorer

**Date:** 2026-05-24  
**Status:** Implemented

## Goal

Collapse the dashboard to two pages:

| Page | Purpose |
|------|---------|
| **Home** | Summary metrics, pipeline cards, compact run bar (pipeline + apply), optional live logs |
| **Jobs** | Server-paginated, filterable job table; resume/cover paths always visible; row → drawer |

Run controls live on Home only. Jobs is read-only triage (no per-row apply actions in v1).

## Navigation

- `DashboardPage = "home" | "jobs"`
- Nav rail: Home, Jobs
- URL: `?tab=jobs` plus job filter query params (see below). Legacy `?page=jobs` still opens Jobs. Pagination uses numeric `page=1`, `page=2`, etc.

## Home

- Health row links to Jobs with pre-filled filters (`stage=applied`, `needs_check`, `ready`, etc.)
- Ghost / failed-run banners
- `StatsRow`, pipeline summary cards (pending counts from `/api/stats`) → **View in Jobs** with stage slug
- `HomeRunBar`: multi-select pipeline stages, apply options, stop, collapsible `LogConsole` when a run is active
- CLI fallback one-liner (includes `applypilot inbox` note)

## Jobs explorer

### Filters (URL-synced)

| Param | API |
|-------|-----|
| `stage` | `GET /api/jobs?stage=` slug (`discovered`, `ready`, `needs_check`, …) |
| `min_score` | `min_score` |
| `site` | `site` |
| `search` | `search` |
| `sort` | `sort` |
| `apply_status` | `apply_status` (optional) |
| `limit` | `limit` (default 50) |
| `page` | client offset = `(page-1)*limit` |

Legacy `pipeline_stage` (`tailored` / `ready` / `applied`) remains on the API for compatibility.

### Pagination

- Server `limit` + `offset`, response `total`
- UI: Prev/Next, “Page N · X–Y of total”

### Columns

**Always:** score, stage badge, title (link), site, location, activity, `tailored_resume_path`, `cover_letter_path` (truncated + copy).

**Stage-aware optional groups** (when filter is All or matches group):

| Group | Shown when filter |
|-------|-------------------|
| Discover | All, Discovered |
| Enrich | All, Enriched, Enrich error |
| Score | All, Scored, Tailor exhausted |
| Tailor | Tailored, Cover, Ready, Applying, Needs check, Applied, Failed, Manual |
| Cover | Cover, Ready, Applying, … |
| Apply | Ready, Applying, Needs check, Applied, Failed, Manual |

Logic: `dashboard/web/src/utils/jobsTableColumns.ts`.

## Backend

- `src/applypilot/server/job_pipeline_stage.py` — CASE expression + slug/label mapping aligned with `jobPipeline.ts`
- `src/applypilot/server/jobs.py` — expanded SELECT, `stage` filter, `apply_status`, `site`
- `JobRow` schema extended with enrich/tailor/cover/apply fields

## Out of scope (v1)

- Inbox / Referrals / Sites pages in nav
- Per-row apply / re-tailor on Jobs table
- Column picker UI (fixed rules from stage filter)

## Verification

```bash
uv run applypilot serve
cd dashboard/web && npm run build
uv run pytest tests/test_dashboard.py
```

- Home: summary + run bar; Jobs: paginated table with resume/cover columns
- Home “Needs verification” → Jobs with `?tab=jobs&stage=needs_check` (syncUrl writes `tab`; filter-only URLs also open Jobs)
- Stage filter changes optional columns; total count stays server-accurate
