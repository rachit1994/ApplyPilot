## Learned User Preferences
- Prefer plain, simple English explanations when the technical details get confusing.
- Prefer minimal interruptions during long-running debugging or execution; keep updates only when necessary.
- Want end-to-end verification that ApplyPilot actually runs and applies to jobs, not just code changes or theory.
- Prefer onboarding docs that are ADHD-friendly, checklist-based, and explicit about which files to read first and what each folder does.
- Prefer feature ideas and product direction to stay single-user and local-machine first, not team or SaaS workflows.
- Prefer watching apply in visible Chrome with slow pacing (`applypilot apply --watch` and related flags) so form fills can be tracked and reviewed before submit.
- Wants a user-facing transparency/debug mode showing target job, crawl sources, form values, and resume before each apply; should be toggleable off for normal runs.
- Prefer professional, production-quality dashboard UI over MVP stubs when building control surfaces.
- Do not auto-scroll the dashboard log console when new log events arrive.

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
