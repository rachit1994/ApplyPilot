## Learned User Preferences
- Prefer plain, simple English explanations when the technical details get confusing.
- Prefer minimal interruptions during long-running debugging or execution; keep updates only when necessary.
- Want end-to-end verification that ApplyPilot actually runs and applies to jobs, not just code changes or theory.
- Prefer onboarding docs that are ADHD-friendly, checklist-based, and explicit about which files to read first and what each folder does.
- Prefer feature ideas and product direction to stay single-user and local-machine first, not team or SaaS workflows.
- Prefer visible Chrome apply with slow pacing (`applypilot apply --watch` and related flags), plus an optional transparency mode for target job, crawl sources, form values, and resume before each apply.
- Prefer professional, production-quality dashboard UI over MVP stubs when building control surfaces.
- Auto-scroll new log lines inside the Live logs panel only when near the bottom; do not auto-scroll the whole dashboard page.
- Dashboard pipeline layout should scroll on `<main>` as one region (no nested body scroll wrappers); keep logs and jobs panels tall (~72vh).
- Jobs table on the dashboard should default to newest-first with dates visible on each row.
- Want a dedicated dashboard Applications view for jobs actually submitted via apply, including what was filled on the form and any apply errors.
- When expanding discover, prioritize adding many programmatic sources first; use AI browser discover (reuse apply Chrome + Claude stack) only for sites explicitly marked `mode: agent` in `sites.yaml`.

## Learned Workspace Facts
- ApplyPilot is a local-first, single-user Python CLI for automated job discovery, scoring, tailoring, and application workflows.
- `applypilot run` follows six stages: `discover`, `enrich`, `score`, `tailor`, `cover`, and `pdf`.
- `applypilot apply` is a separate browser automation flow under `src/applypilot/apply/`; it is not part of `STAGE_ORDER`.
- `applypilot apply` launches visible Chrome by default; pass `--headless` to hide the window.
- The primary local data directory is `~/.applypilot`, including the main SQLite DB at `~/.applypilot/applypilot.db` unless `APPLYPILOT_DIR` overrides it.
- `LLM_URL` takes precedence over Gemini or OpenAI keys for scoring and tailoring flows, while auto-apply uses Claude Code plus browser automation.
- The `discover` stage runs JobSpy, Workday employer APIs, and Smart extract in parallel; boards/queries are in `~/.applypilot/searches.yaml`, Workday companies in `config/employers.yaml`, and direct sites in `config/sites.yaml`.
- `docs/teach/` is the repo's onboarding track and is intended to align with `docs/rules.md`.
- `applypilot serve` (default `127.0.0.1:9477`) serves the React control dashboard in `dashboard/web/` via FastAPI REST and SSE for pipeline runs.
- Dashboard v1 starts and monitors `applypilot run` only; apply, refer, and inbox from the dashboard still require the CLI.
- Dashboard log lines use level coloring derived from Python log prefixes (INFO as amber, not error red when stderr mis-tags INFO).
- Dashboard Applications page lists apply outcomes parsed from apply logs (status, form fields, errors) via `/api/applications`.
- Referral connect/message needs OpenOutreach REST on `http://127.0.0.1:8741/v1`; use `applypilot openoutreach start` (syncs `OPENOUTREACH_API_KEY` from `~/.applypilot/.env`) before `refer` or pipeline `refer` stage.
