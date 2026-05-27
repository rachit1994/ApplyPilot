# Applied Applications page — design spec

**Date:** 2026-05-25  
**Status:** Implemented (v1)

## Goal

Give a single dashboard place to triage every auto-apply attempt: what was filled on the form, why it failed or was downgraded, submit proof from `RESULT_JSON`, and the raw log — without reading terminal Claude output.

## Navigation

| Page | URL | Role |
|------|-----|------|
| Home | (no tab) | Summary; unverified banner → Applications |
| Jobs | `?tab=jobs` | Pipeline explorer |
| Apply | `?tab=apply` | Run controls, workers, live logs only |
| Applications | `?tab=applications` | Audit ledger (master–detail) |

Filter deep link: `?tab=applications&filter=unverified` (alias for `submitted_unverified`).

Legacy: `?page=applications` still resolves to the Applications page.

## API

### `GET /api/applications`

| Param | Purpose |
|-------|---------|
| `include_failed=true` | Include `failed` and `manual` rows (Applications UI always passes this) |
| `status` | Server-side filter: `applied`, `submitted_unverified`, `failed`, `manual` |
| `site`, `search` | Optional filters |
| `limit` | Default list cap (UI uses 300) |

### `GET /api/applications/detail?url=…`

Unchanged route; enriched `log_detail.parsed`:

- `result_json` — parsed `RESULT_JSON` block (submit button, URLs, confirmation copy)
- `verification` — `{ decision, reasons, confidence }` from `verification.evaluate()` when proof exists
- Existing: `fields`, `fill_actions`, `empty_required`, `visible_errors`, `result_line`

**Parser note:** Form snapshot is taken from the last `browser snapshot {` block in the log, not from `post_submit_snapshot` inside `RESULT_JSON` (often empty).

## UI layout

- Scroll region on `<main>`: `min(72vh, 100vh - 8rem)` per AGENTS.md
- **Left:** filterable list (newest first), status chip, summary line
- **Right:** `ApplicationDetailPanel` — outcome, proof, form table, fill actions, collapsible log
- Header stat pills: applied, needs verification, failed (`pipeline.apply_errors`), manual (`extra.apply_manual`)

### Detail sections (top → bottom)

1. Outcome — status, confidence, bullet reasons from `apply_error` / verification
2. Submit proof — from `result_json`
3. Form snapshot table — label, value, type, empty; highlights for `empty_required`
4. Agent actions — `fill_actions` monospace list
5. Raw log — excerpt + log path; Confirm / Retry / open URLs

## Out of scope (v1)

- Multiple apply attempts per job in SQLite (still latest `apply_log_path` only)
- HTTP serving of screenshots
- Referrals / inbox

## Verification

- `pytest tests/test_dashboard.py tests/test_apply_log_parser.py`
- Manual: `applypilot serve` → `?tab=applications`, filter unverified/failed, confirm detail panel
