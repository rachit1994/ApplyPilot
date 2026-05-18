# LinkedIn Inbox Job-Opportunity Reply

**Date:** 2026-05-18  
**Status:** Implemented (v1)  
**Scope:** Independent lifecycle — not wired to `jobs`, `discover`, `apply`, or `refer`.

## Goal

Scan the LinkedIn messaging **Other** tab, classify inbound threads about job openings, draft hybrid Gemini replies, and send only when the latest message is inbound and we have not already sent an inbox-job reply.

## Architecture

| Layer | Responsibility |
|-------|----------------|
| **OpenOutreach** | Session, Other-tab discovery (browser + Voyager), message fetch, `POST /v1/actions/sync-inbox`, send via existing `actions/message` |
| **ApplyPilot** | SQLite `inbox_*` tables, classify/draft/send gates, `applypilot inbox` CLI |

## v1 constraints

- **Folder:** `other` only (Focused / Archived = phase 2).
- **Resume:** Text-only replies (no PDF upload automation).
- **Safety:** `send` and `run` default to `--dry-run`; use `--send` to post.
- **Campaign:** `OPENOUTREACH_INBOX_CAMPAIGN` or `OPENOUTREACH_CAMPAIGN` in env.

## Data model (ApplyPilot SQLite)

- `inbox_threads` — conversation metadata and latest inbound text
- `inbox_messages` — optional message cache
- `inbox_opportunities` — classification results
- `inbox_replies` — draft/send state

**Send gate:** skip if not job-related, outbound is latest, or `reply_status = sent`.

## OpenOutreach API

`POST /v1/actions/sync-inbox`

```json
{
  "since_days": 14,
  "limit": 50,
  "include_messages": true,
  "use_browser": true
}
```

Returns `{ "folder": "other", "threads": [...], "source": "browser"|"voyager" }`.

Spike notes: `OpenOutreach/docs/inbox-other-voyager.md`.

## ApplyPilot CLI

```bash
applypilot inbox scan
applypilot inbox classify
applypilot inbox draft
applypilot inbox send          # dry-run default
applypilot inbox run --send    # full pipeline, live send
```

Config: copy `config/inbox.example.yaml` → `~/.applypilot/inbox.yaml`, set `enabled: true`.

## Operations

1. Start OpenOutreach: `runapi --no-daemon` (port 8741).
2. Set `GEMINI_API_KEY`, `OPENOUTREACH_API_KEY`, campaign in admin UI.
3. `applypilot inbox run` (dry-run) → review candidates.
4. `applypilot inbox run --send --limit 5` when ready.

## v2 (best-in-class gaps)

**Status:** Implemented in single PR on top of v1.

### Intent taxonomy

`inbox_opportunities.intent`: `apply_request`, `rejection`, `status_update`, `spam`, `education_pitch`, `other`.

- LLM returns multi-label JSON; keyword pre-pass can override for rejection/education.
- `is_job_related` / send eligibility only when `intent == apply_request` and `confidence >= threshold`.

### ATS hard signal

`apply_url`, `ats_vendor` on `inbox_opportunities` (Greenhouse, Lever regex).

- ATS URL + apply language in latest inbound boosts confidence to ≥0.92 (never overrides rejection/education/spam).

### Composite ranking

`fit_score` = `round(confidence * 6)` + ATS (+2) + title (+1) + company (+1), clamped 1–10. Recency is tie-break only.

### Explicit approval

`inbox_replies.approved_at`, `approved_by`.

```bash
applypilot inbox list
applypilot inbox approve <public_id> [--draft-on-approve]
applypilot inbox send --send --approved-only   # default for live send
applypilot inbox unapprove <public_id>
```

### Audit log

`inbox_audit_events` — append-only: `classified`, `gated`, `approved`, `unapproved`, `send_attempt`, `send_ok`, `send_fail`.

```bash
applypilot inbox audit [--limit 50] [--urn URN] [--public-id slug]
```

### OpenOutreach pagination

`ActionSyncInboxRequest`: `scroll_passes` (default 8), `max_pages` (default 20).

- Browser: scroll until 3 stale passes with no new URNs or cursor exhausted.
- Voyager (`use_browser=false`): `fetch_conversations` cursor loop.

ApplyPilot config: `sync_scroll_passes`, `sync_max_pages` in `inbox.yaml`.

## Implementation handoff

Use **writing-plans** or **ce-work** for phase-2 items (Focused/Archived tabs, `--folder` flag, Workday/Ashby ATS).
