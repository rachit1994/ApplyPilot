# Apply quota — next phase (post quick-wins)

Quick-wins shipped in May 2026:

- Default apply model **Haiku** with **Sonnet** fallback on retriable failures
- **Prompt slimming** (conditional CAPTCHA / VERIFY / Gmail MCP)
- **Session reuse** per worker (`--resume` / `--session-id`, no forced `--no-session-persistence`)

Rollback via env:

| Variable | Effect |
|----------|--------|
| `APPLYPILOT_APPLY_MODEL` | Primary model (default `haiku`) |
| `APPLYPILOT_APPLY_FALLBACK_MODEL` | Escalation model (default `sonnet`) |
| `APPLYPILOT_APPLY_PROMPT_SLIM=0` | Full legacy prompt |
| `APPLYPILOT_APPLY_SESSION_REUSE=0` | Per-job ephemeral sessions |
| `APPLYPILOT_APPLY_GMAIL_MCP=1` | Always load Gmail MCP |

Telemetry: `llm_usage_events.metadata_json` includes `prompt_slim`, `session_reuse`, `cache_read_tokens`, `num_turns`.

## Phase A — Deterministic prefill

Before Claude runs:

1. Navigate to `application_url` with Playwright (shared browser module).
2. Fill standard fields from `profile.json` + tailored resume text (name, email, phone, LinkedIn, work auth).
3. Upload resume PDF via file input when present.
4. Hand off to Claude only for: screening questions, multi-step ATS quirks, CAPTCHA, login walls.

**Acceptance:** ≥30% reduction in Claude tool turns on Greenhouse/Lever/Ashby without lower `applied` rate.

## Phase B — `src/applypilot/browser/`

Independent browser control layer:

- `browser/session.py` — CDP attach, tab management
- `browser/forms.py` — label→value mapping, batch fill
- `browser/prefill.py` — orchestration used by apply launcher

Apply launcher calls browser prefill, then Claude with a **short** handoff prompt (job-specific only).

## Phase C — Hybrid gate (optional)

Cheap model or rules-only gate **before** any Claude subprocess:

- Pass: likely fillable ATS, resume PDF exists, not manual_ats / blocked
- Defer: LinkedIn Easy Apply only, contractor marketplace, missing resume
- Fail permanent: expired, location/salary pre-filter

Only **pass** rows spawn Claude. Defer stays in DB with `apply_not_before` or `manual`.

## Metrics to watch

Compare batches (same job set) before/after:

- `applied` + `submitted_unverified` rate
- Claude `num_turns` and `cost_usd` per successful application (from `llm_usage_events`)
- `cache_read_tokens` / `input_tokens` ratio when session reuse is on
- Quota fast-fail rate (`failed:claude_quota_exhausted`)

## Non-goals (this phase)

- Replacing Claude Code CLI with Agent SDK (separate spike)
- Team/SaaS multi-user scheduling
