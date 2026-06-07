## Learned User Preferences
- Prefer plain, simple English explanations when the technical details get confusing.
- Prefer minimal interruptions during long-running debugging or execution; keep updates only when necessary.
- Want end-to-end verification that ApplyPilot actually runs and applies to jobs, not just code changes or theory.
- Prefer onboarding docs that are ADHD-friendly, checklist-based, and explicit about which files to read first and what each folder does.
- Prefer feature ideas and product direction to stay single-user and local-machine first, not team or SaaS workflows.
- Prefer visible Chrome apply with slow pacing (`applypilot apply --watch` and related flags), plus an optional transparency mode for target job, crawl sources, form values, and resume before each apply.
- Prefer professional, production-quality dashboard UI; the pipeline section should show the exact in-progress sub-step and quantitative progress (counts/percent), not only high-level phase labels.
- Auto-scroll new log lines inside the Live logs panel only when near the bottom; do not auto-scroll the whole dashboard page.
- Dashboard pipeline layout should scroll on `<main>` as one region (no nested body scroll wrappers); keep logs and jobs panels tall (~72vh).
- Jobs table on the dashboard should default to newest-first with dates visible on each row.
- Want a dedicated dashboard Applications view for jobs actually submitted via apply, including what was filled on the form and any apply errors.
- When expanding discover, prioritize adding many programmatic sources first; use AI browser discover (reuse apply Chrome + Claude stack) only for sites explicitly marked `mode: agent` in `sites.yaml`.
- For UI redesign, overhaul, or frontend refactoring tasks:
  - Do not use highly fragmented parallel background agents that edit overlapping files. Have a single integrator or execute page-level changes sequentially to avoid drift and merge conflicts.
  - First execute a complete, exact CSS parity pass (e.g., matching the style classes in `index.css` to the reference file like `finalized.html`) before implementing page layouts.
  - Ensure visual acceptance and high-fidelity parity with the reference design specs by verifying the results visually in a browser (e.g., running `applypilot serve` and reviewing pages/routes/logs/details).
  - Never trade off performance or regress existing behavior (such as virtualization on large lists/tables like Jobs, RunPlanModal run controls, active/real KPIs, auto-scrolling) for aesthetic updates.
  - Keep database, API/backend logic, and test files out of scope for a UI-only brief unless they are strictly required to resolve compiler errors or support type definitions.

## Database safety (non-negotiable)

Agents must **never wipe or replace** the user's ApplyPilot Postgres data unless the user explicitly asks for that destructive action in the current message.

Forbidden on the user's live Postgres database (default `postgresql://127.0.0.1:5432/applypilot`, or whatever `APPLYPILOT_DATABASE_URL` points at):

- `DELETE FROM jobs` (or any table) without an isolated test database
- `TRUNCATE`, `DROP TABLE`, or destructive migration against production DSN
- Debug or verification scripts that clear rows then insert test fixtures

For pytest, manual experiments, or API debugging, **always** use an isolated database:

```bash
export APPLYPILOT_DIR=$(mktemp -d)
# pytest creates ephemeral applypilot_test_* databases automatically via conftest.py
```

If you need sample rows in tests, rely on the autouse `isolated_db` fixture in `tests/conftest.py`, not the user's live Postgres.

## Learned Workspace Facts
- ApplyPilot is a local-first, single-user Python CLI for automated job discovery, scoring, tailoring, and application workflows.
- `applypilot run` follows six stages: `discover`, `enrich`, `score`, `tailor`, `cover`, and `pdf`.
- `applypilot apply` is a separate browser automation flow under `src/applypilot/apply/` (not in `STAGE_ORDER`); it launches visible Chrome by default (`--headless` to hide).
- The primary local data directory is `~/.applypilot` (profile, resumes, templates, `.env`).
- Primary database is **Postgres** at `APPLYPILOT_DATABASE_URL` (default `postgresql://127.0.0.1:5432/applypilot`); init with `applypilot db init`, status via `applypilot db status`.
- `LLM_URL` takes precedence over Gemini or OpenAI keys for scoring and tailoring flows, while auto-apply uses Claude Code plus browser automation.
- Tailor/cover use hybrid routing: B-grade jobs use archetype templates under `~/.applypilot/templates/` when present (`applypilot tailor-archetype`, `render-templates`); A-grade (`profile.json` → `tailor.a_grade`: `min_score`, `target_companies`) or missing/low-density templates fall back to full LLM tailor.
- The `discover` stage runs JobSpy, Workday employer APIs, and Smart extract in parallel; boards/queries are in `~/.applypilot/searches.yaml`, Workday companies in `config/employers.yaml`, and direct sites in `config/sites.yaml`.
- Worker apply docs live under `docs/worker-deterministic-apply-handbook.md` (deterministic engine) and `docs/worker-apply-playbook.md` (form-filler); see handbook intro for the full kept doc set.
- `applypilot serve` (default `127.0.0.1:9477`) serves the React dashboard via FastAPI REST and SSE; v1 can start and monitor `applypilot run` only—apply, refer, and inbox still require the CLI.
- `applypilot run` emits `stage_progress` run events (per-stage pending/total counts) for the dashboard pipeline progress UI.
- Dashboard Live logs and Jobs lists virtualize rows with `@tanstack/react-virtual` to keep the DOM small on long runs.
- Dashboard colors INFO log lines amber (not error red when stderr mis-tags INFO); Applications lists apply outcomes via `/api/applications`.
- Referral connect/message needs OpenOutreach REST on `http://127.0.0.1:8741/v1`; use `applypilot openoutreach start` (syncs `OPENOUTREACH_API_KEY` from `~/.applypilot/.env`) before `refer` or pipeline `refer` stage.
