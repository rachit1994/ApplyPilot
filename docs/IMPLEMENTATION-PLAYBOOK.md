# ApplyPilot — Implementation Playbook for AI Agents

**Audience:** any AI coding agent (Codex, Cursor, Claude, Aider, etc.) picking up unfinished work without the prior conversation context. Read this whole file before touching code. It will save you and the user a lot of time.

**Your job:** implement the open tiers in the 8 investigation docs under `docs/*-may-2026.md`. They were written doc-only on purpose — the human asked for proposals, not patches. Now they want them shipped.

**Where to start:**
1. Read this playbook end-to-end (5-10 minutes).
2. Read `AGENTS.md` in the repo root (user preferences).
3. Open `docs/STATUS-BOARD.md` if it exists; otherwise read the status table below.
4. Pick the highest-priority OPEN row that isn't already in flight.
5. Re-read that specific doc fully before touching code.
6. Ship one tier at a time. One PR per tier. Update the doc's status line when done.

---

## Read this first (the 60-second version)

ApplyPilot is a single-user, local-first Python CLI + React dashboard for automated job discovery, scoring, tailoring, and application. Runs on the user's Mac, hits Gemini / Claude / local LLMs, drives Chrome via Playwright MCP for the apply step. All data in `~/.applypilot/`.

Pipeline stages: `discover → enrich → score → tailor → cover → pdf → refer`. Apply is a separate flow (`applypilot apply`).

The user has tested end-to-end on real jobs. The pipeline now reaches real ATS forms but submits 0 verified applications because the last-mile blockers (email verification codes, etc.) aren't handled. The 8 investigation docs trace each leak and propose tiered fixes.

**What's already shipped (May 2026):**
- `apply-hang-fix-may-2026.md`: Tier 1 (quota fast-fail) + Tier 2 (reader-thread inactivity/wall timeouts) — live.
- `discover-relevance-fix-may-2026.md`: Tier 0 (universal discover filters) + Tier 1 (pre-score rule gate) — live.
- `enrich-tailor-gap-fix-may-2026.md`: partial — `tailor_exhausted` stat, Jobs Explorer stage/filter. Core tier work not shipped.
- `apply-ghost-fix-may-2026.md`: partial — `submitted_unverified` status surfaced; core verifier work not shipped.

**What's open (the high-value queue):**
- Email-code automation (apply-full-autonomy Blocker 1) — the single highest-impact fix.
- Templated tailoring (templated-tailor-fix all tiers) — ~80% LLM cost reduction.
- Tailor attempt accounting + horizon counters (enrich-tailor-gap Tier 1+2).
- Apply ghost-fix Tier 1 (verification record) + Tier 2 (post-submit screenshot + nightly verifier).
- Apply-autonomy Blockers 2-5 (multi-step checkpoint, aggregator filter, liveness check, SSO routing).
- Dashboard redesign (separate brief at `dashboard-redesign-requirements-may-2026.md`).

The full table is in **STATUS BOARD** below.

---

## The user (Rachit) — what to know before you change anything

These are non-negotiable preferences pulled from `AGENTS.md` and observed across the prior 7 investigations. Violating any of them produces angry rework.

1. **Plain, simple English.** No "I have identified a potential issue in the authentication flow." Say: "`auth.ts:47` returns undefined when the session cookie expires. Users hit a white screen."
2. **End-to-end verification > theory.** A fix isn't done because the tests pass. It's done when `applypilot run` or `applypilot apply` produces the expected real-world outcome. Show the proof in the PR description (DB query, log excerpt, screenshot).
3. **Minimal interruptions during long-running execution.** Don't ask "should I continue?" mid-fix. If something genuinely blocks (missing credential, ambiguous architecture decision), STOP and ask once with concrete options.
4. **ADHD-friendly, checklist-based.** Outputs and PRs should be scannable. Bullets, tables, code blocks. Not paragraphs of prose.
5. **Single-user, local-machine first.** No SaaS features. No multi-user. No cloud sync (unless explicitly added later). The dashboard runs at `127.0.0.1:9477`.
6. **Visible Chrome apply.** Default is `applypilot apply --watch` with visible Chrome and pace. Headless is opt-in.
7. **Professional, production-quality dashboard UI.** The pipeline section must show the exact in-progress sub-step and quantitative progress (counts/percent), not high-level phase labels.
8. **Newest-first** on jobs table, with dates visible per row.
9. **Auto-scroll log lines only when near the bottom.** Never auto-scroll the whole dashboard page.
10. **No emoji in headings or files** unless explicitly requested. No "AI mystique" branding.

What the user has been doing across this series:
- They run live tests (real Anthropic credentials, real Chrome, real ATS forms).
- They report what blocked them, with specific URLs/companies/log excerpts.
- They want a doc that diagnoses the issue and proposes tiered fixes.
- They (or you, the next agent) ship the fixes.
- They confirm via a single status line in the doc's header: "Tier 1+2 implemented (May 2026). ..."

You are now in step 4. Ship the fixes.

---

## The codebase — 60-second orientation

```
src/applypilot/
├── cli.py                         # typer CLI entry — every command goes through here
├── pipeline.py                    # orchestrator: sequential + streaming run modes
├── config.py                      # DEFAULTS, paths, profile loader, sites.yaml loader
├── database.py                    # SQLite schema, get_jobs_by_stage, status migrations
├── llm.py                         # LLM client factory (LLM_URL > Gemini > OpenAI)
├── view.py                        # CLI status views
├── apply/                         # Apply flow (separate from STAGE_ORDER)
│   ├── launcher.py                # Spawns claude subprocess + Chrome; the hot file
│   ├── prompt.py                  # The Claude apply prompt (40KB; surgical edits only)
│   ├── chrome.py                  # Worker Chrome profile lifecycle
│   ├── eligibility.py             # classify_apply_target — pre-Chrome gate
│   ├── apply_log_parser.py        # Extracts RESULT lines, form snapshots from logs
│   ├── salary.py                  # Regional salary minimums + parsing
│   ├── experience.py              # is_too_junior_role
│   └── dashboard.py               # Worker chip state for live render
├── discovery/
│   ├── runner.py                  # Unified discover entry (10 sources)
│   ├── jobspy.py                  # JobSpy wrapper — ONLY source with exclude_titles
│   ├── workday.py, workatastartup.py, smartextract.py, hn_hiring.py, watchlist.py
│   └── feeds/                     # remoteok, remotive, himalayas, wwr
├── scoring/
│   ├── scorer.py                  # Gemini-based scoring (currently no pre-filter)
│   ├── tailor.py                  # Resume tailoring — has the 5-attempt cap issue
│   ├── cover_letter.py            # Cover letter generation
│   ├── pdf.py                     # .txt → .pdf rendering
│   └── validator.py               # BANNED_WORDS, LLM_LEAK_PHRASES, judge
├── enrichment/                    # Detail-page scraping
├── inbox/                         # Recruiter reply classification
├── outreach/                      # OpenOutreach integration for referrals
├── orchestration/                 # Run tracker + events
└── server/                        # FastAPI app for the dashboard

dashboard/web/                     # React + Vite + Tailwind dashboard
├── src/App.tsx                    # Top-level layout
├── src/components/                # ApplicationsPage, JobsTable, LogConsole, etc.
└── src/api.ts                     # API client

~/.applypilot/                     # User data (NOT in repo)
├── applypilot.db                  # SQLite DB
├── profile.json                   # Personal info, skills_boundary, target_roles
├── searches.yaml                  # Discover queries + exclude_titles + locations
├── resume.txt + resume.pdf        # Base resume
├── tailored_resumes/              # Per-job tailored outputs
├── cover_letters/                 # Per-job cover letters
├── chrome-workers/                # Persistent Chrome profiles per worker
└── logs/                          # Apply session logs (claude_*.txt, worker-N.log)

docs/                              # Investigation docs — your work queue
├── IMPLEMENTATION-PLAYBOOK.md     # This file
├── apply-ghost-fix-may-2026.md
├── apply-hang-fix-may-2026.md     # Tier 1+2 shipped
├── apply-full-autonomy-may-2026.md
├── enrich-tailor-gap-fix-may-2026.md
├── discover-relevance-fix-may-2026.md   # Tier 0+1 shipped
├── templated-tailor-fix-may-2026.md
├── dashboard-redesign-requirements-may-2026.md
├── dashboard-mockups/             # Where dashboard HTML variants live (mostly empty)
├── job-workflow-may-2026.md       # Pre-existing context doc
└── funded-startup-targeting-may-2026.md
```

**Hot files (touched by multiple open fixes — coordinate carefully):**
- `src/applypilot/apply/launcher.py` — apply-ghost-fix, apply-full-autonomy, apply-hang-fix
- `src/applypilot/apply/prompt.py` — apply-ghost-fix, apply-full-autonomy
- `src/applypilot/scoring/tailor.py` — enrich-tailor-gap-fix, templated-tailor-fix
- `src/applypilot/pipeline.py` — enrich-tailor-gap-fix
- `dashboard/web/src/App.tsx` + components — dashboard-redesign + most other docs surface state here

**Don't touch (out of scope unless the doc says so):**
- Anything under `src/applypilot/inbox/` (recruiter reply path, separate concern)
- Anything under `src/applypilot/outreach/` (referrals, separate)
- `src/applypilot/scoring/pdf.py` (renderer works; both old and new flows use it)

---

## Working agreements (non-negotiable)

1. **One PR per tier.** Don't bundle Tier 1 of one doc with Tier 2 of another. Reviewers (human or AI) need to evaluate one change at a time. The user can choose to merge a PR independently of other open work.
2. **One commit per logical unit inside a PR.** New file + its test = one commit. Wiring it into the caller = a second commit. Easier to revert if regression.
3. **Tests are mandatory.** Every fix that adds logic needs tests. Patterns:
   - Pure functions: pytest unit tests with table-driven cases.
   - Code touching the DB: pytest with a tmp_path SQLite DB.
   - LLM-bound code: mock `get_client()` to return a deterministic response.
   - Subprocess-bound code: mock `subprocess.Popen` with a `FakePopen` (see hang-fix Tier 2 plan).
4. **Update the doc's status line when shipping.** The first line under the title (`**Status:** ...`) should reflect reality. Example:
   ```markdown
   **Status:** Tier 1 implemented (2026-05-26). Tier 2-3 still open.
   ```
5. **No ghost commits.** Don't "fix unrelated whitespace" in the same commit. Don't refactor adjacent code.
6. **The launcher.py / prompt.py rule:** these files are 1000+ lines each and three other agents may be touching them. If you must edit, make the smallest possible diff. Prefer adding new functions over editing existing ones. Prefer prompt SECTIONS (independent appended blocks) over inline edits.
7. **End-to-end check before claiming DONE.** "Tests pass" is not enough. The user wants:
   - `applypilot run <stage> --limit 5` produces the expected DB state.
   - `applypilot apply --watch --limit 1 --url <known-url>` shows the expected behavior in the dashboard.
   - Screenshot or log excerpt in the PR description.
8. **Don't change `AGENTS.md`** unless adding to "Learned User Preferences" with explicit user consent.
9. **Don't ship things the user didn't approve.** If the doc has a recommended option (the "What I'd actually ship" section), follow it. If the doc presents two valid alternatives, ask once. Don't auto-decide.
10. **No emoji in files.** No purple gradients. No "Welcome to ApplyPilot" copy. The user has hit these patterns before and will reject the PR.

---

## STATUS BOARD — pick from here

This is the work queue. Rows marked OPEN are unclaimed (or claimed but not done — check git log for in-flight work).

Numbered by priority. Lower number = higher value.

| # | Doc | Tier | What | Files | Effort (CC) | Status |
|---|---|---|---|---|---|---|
| 1 | `apply-full-autonomy-may-2026.md` | Blocker 1 | **Gmail MCP auth + email-code prompt section + verification_code_used field** | `apply/gmail_auth.py` (new), `apply/prompt.py`, `cli.py`, `apply/verification.py` (extend) | ~3 hrs | OPEN |
| 2 | `templated-tailor-fix-may-2026.md` | Tier 1 (bootstrap + classifier) | **8 archetype classifier + bootstrap CLI + 8 hand-curated templates** | `scoring/templates.py`, `scoring/keyword_extractor.py`, `cli.py`, `config/templates_archetypes.yaml` | ~3 hrs + 1 hr human review | DONE (code); bootstrap `.txt` files on user machine still manual |
| 3 | `templated-tailor-fix-may-2026.md` | Tier 2 (routing) | **Routing fork in tailor.py + cover_letter.py: B-grade → template, A-grade → LLM** | `scoring/tailor.py`, `scoring/cover_letter.py`, `profile.json` (optional `tailor.a_grade`) | ~2 hrs | DONE |
| 4 | `apply-ghost-fix-may-2026.md` | Tier 1 (verification gate) | **RESULT_JSON + ApplyVerifier; downgrade unverifiable to submitted_unverified** | `apply/verification.py` (new), `apply/prompt.py` (replace MANDATORY FINAL LINE), `apply/apply_log_parser.py` (extract_result_json), `apply/launcher.py` (call verifier) | ~2 hrs | OPEN |
| 5 | `apply-full-autonomy-may-2026.md` | Blocker 4 + 5 | **HTTP liveness check + SSO routing pre-Chrome** | `apply/liveness.py` (new), `apply/launcher.py` (worker_loop pre-launch hook), `config/sites.yaml` (expand manual_ats) | ~2 hrs | OPEN |
| 6 | `apply-full-autonomy-may-2026.md` | Blocker 3 | **Geo-exclusion detector + aggregator/contractor list expansion** | `apply/eligibility.py` (add detect_geo_exclusion), `config/sites.yaml` | ~2 hrs | OPEN |
| 7 | `enrich-tailor-gap-fix-may-2026.md` | Tier 1 (attempt accounting) | **Distinguish COUNTED vs UNCOUNTED failures; add tailor_error column** | `scoring/tailor.py`, `database.py` (migration), `server/jobs.py` (surface error) | ~1.5 hrs | OPEN |
| 8 | `enrich-tailor-gap-fix-may-2026.md` | Tier 2 (resumable + horizon) | **tailor_run_cursor + soft Ctrl+C + dashboard horizon counter** | `pipeline.py`, `scoring/tailor.py`, `server/runs.py`, `dashboard/web/src/components/PhaseStepper.tsx` | ~3 hrs | BLOCKED by #7 |
| 9 | `apply-ghost-fix-may-2026.md` | Tier 2 (screenshot + nightly verifier) | **Post-submit screenshot saved; daily verifier visits applied URLs and downgrades ghosts** | `apply/post_verify.py` (new), `cli.py` (apply verify subcommand), `apply/prompt.py` (require screenshot) | ~3 hrs | BLOCKED by #4 |
| 10 | `apply-full-autonomy-may-2026.md` | Blocker 2 | **Multi-step CHECKPOINT protocol + mandatory reCAPTCHA v3 detect after submit + stuck-detection** | `apply/prompt.py`, `apply/apply_log_parser.py` (extract_checkpoints), `apply/launcher.py` | ~3 hrs | OPEN |
| 11 | `discover-relevance-fix-may-2026.md` | Tier 2 (embedding gate) | **Local sentence-transformer cosine similarity gate before scoring** | `scoring/embedding.py` (new), `scoring/pre_filter.py` (already shipped — extend), `requirements` (add sentence-transformers) | ~3 hrs + 80MB model download | OPEN |
| 12 | `discover-relevance-fix-may-2026.md` | Tier 3 (batched scoring) | **Score N jobs per Gemini call** | `scoring/scorer.py` | ~1 hr | LOW PRIORITY |
| 13 | `dashboard-redesign-requirements-may-2026.md` | All | **Pipeline page redesign + Applications ledger + Sites/Connections page** | `dashboard/web/src/**` | ~20 hrs human / ~2 days CC | LARGE; pick separately |

**How to choose:**
- New agent? Start with **#5 (liveness check)** — small, well-scoped, no overlap with other open work, immediate visible win.
- Have an afternoon and want big impact? **#1 (Gmail MCP / email codes)** — lifts autonomy from ~0% to ~50%.
- Have multiple days? Pair **#2 → #3 (templating)** for the 80% cost reduction.
- Cosmetic / UX work? **#13** — but read the requirements doc first; it's a real design exercise.

**Dependencies:**
- #3 (template routing) depends on #2 (templates exist).
- #8 (horizon counter) depends on #7 (`tailor_error` column).
- #9 (nightly verifier) depends on #4 (verification record exists).
- Everything else is parallelizable.

---

## How to pick up work — the protocol

### Step 1: claim a row

If using a coordination tool (issue tracker, branch namespace), claim by creating a branch `agent/{your-name}/playbook-{N}` and pushing an empty commit with the row number. Otherwise, just announce in your output: "Picking up Playbook row #5 (liveness check)."

If no row is announced and no branch exists, assume it's available.

### Step 2: re-read the doc

Open the specific `docs/*-may-2026.md` doc for your row. Read it entirely — the "What I'd actually ship" section is the design intent. The "Fix plan" section has the concrete file changes.

If the doc's status line says "Tier X shipped," check the git log for evidence:
```bash
git log --oneline -20 -- src/applypilot/<relevant-path>
```
If the prior tier isn't actually in main, the status line is stale; re-do your scope from current ground truth.

### Step 3: verify the doc's snapshots match reality

The investigation docs were written against a specific point-in-time DB and codebase. Things may have changed.

Quick verification:
```bash
# Funnel snapshot
sqlite3 ~/.applypilot/applypilot.db "
  SELECT COUNT(*) AS total,
         SUM(CASE WHEN fit_score IS NOT NULL THEN 1 ELSE 0 END) AS scored,
         SUM(CASE WHEN tailored_resume_path IS NOT NULL THEN 1 ELSE 0 END) AS tailored,
         SUM(CASE WHEN applied_at IS NOT NULL THEN 1 ELSE 0 END) AS applied
  FROM jobs;
"

# Apply outcome distribution
sqlite3 ~/.applypilot/applypilot.db "
  SELECT apply_status, COUNT(*) FROM jobs
   WHERE apply_status IS NOT NULL GROUP BY apply_status;
"

# Recent runs
sqlite3 ~/.applypilot/applypilot.db "
  SELECT id, started_at, status, stages_json
    FROM runs ORDER BY started_at DESC LIMIT 5;
"
```

If the funnel looks wildly different from the doc, mention it in your PR description — the user will appreciate the recalibration.

### Step 4: implement

Follow the "Fix plan" section in the doc literally. The doc author thought about the design tradeoffs. If you genuinely think there's a better approach, ask the user first — don't silently deviate.

Implementation order inside a tier:
1. Add the new module(s) first, with tests.
2. Wire it into the caller as a second commit.
3. Add CLI surface if needed as a third commit.
4. Update the dashboard surface (if applicable) as a fourth commit.
5. Run tests. Run a real end-to-end command. Capture output for the PR description.

### Step 5: verify end-to-end

Before claiming DONE, run the verification commands from the doc's "Verification once shipped" section. Capture:
- Before/after DB query results
- A real log excerpt showing the new behavior
- A screenshot of the dashboard if UI was affected

Paste these into the PR description.

### Step 6: update the doc + ship

Edit the doc's status line:
```markdown
**Status:** Tier 1 implemented 2026-MM-DD by {agent}. Tier 2-3 still open.
```

Optionally add a "What we learned" subsection at the bottom of the doc if you discovered something the original author missed.

Open the PR. Include:
- Title: `feat({stage}): doc-XYZ-tier-N - <one-line summary>`
- Description: links to the doc, the verification evidence, the test run output, any deviations from the doc.
- Tag the next blocked row in the status board so the user knows what unblocks next.

### Step 7: hand back

The user has been reviewing and merging via their own flow. Don't push to main directly. Don't merge your own PR. Wait for confirmation.

If they ask for changes, address them in the same PR. Don't open a new one for review feedback.

---

## Communication — leaving breadcrumbs

The user is doing serial reviews across multiple agents and conversation sessions. They appreciate explicit signals:

**In commit messages:**
```
feat(apply): Blocker 1 - Gmail MCP authentication + email code prompt section

Implements docs/apply-full-autonomy-may-2026.md Blocker 1.
- New: src/applypilot/apply/gmail_auth.py (login + status commands)
- Modified: src/applypilot/apply/prompt.py (new EMAIL VERIFICATION section)
- Modified: src/applypilot/apply/verification.py (add verification_code_used field)

End-to-end test:
  applypilot gmail login → token saved to ~/.applypilot/.gmail-token
  applypilot apply --url <stripe-url> → reached submit, fetched code,
    typed code, RESULT_JSON status="applied" with verification_code_used="ABC12345"
  DB: apply_status='applied' (not submitted_unverified)
```

**In PR descriptions** — always include:
- The doc path + row number
- One-line summary of what changed
- Before/after for the user-visible behavior
- The single most-important screenshot or log excerpt
- Any deviation from the doc with rationale

**When you hit something the doc didn't anticipate:**
- STOP and add a comment to the doc itself.
- Don't silently make a design decision. Ask via PR description: "The doc proposes X but Y is also valid because Z. Recommend X. Proceeding unless told otherwise."

**When you finish and the next row is now unblocked:**
- Add a one-line note to the PR: "Unblocks Playbook row #8."

---

## Verification standards — what DONE looks like

Per the user's preference for end-to-end proof, none of these alone is enough:
- ✗ "Tests pass."
- ✗ "The function returns the expected value."
- ✗ "The PR builds."
- ✗ "I checked manually." (without a specific log/screenshot)

These ARE enough:
- ✓ "I ran `applypilot apply --url <X>` and the DB row went from `failed:no_result_line` to `applied`. Log excerpt: [...]"
- ✓ "I ran `applypilot run tailor --limit 5` and produced 5 tailored resumes via templates with 0 LLM calls (Gemini billing logs attached)."
- ✓ "The dashboard now shows 'Pre-filtered: 47' on the score stage. Screenshot attached."

The bar is: a third party reading your PR description should be able to verify your claim by running one command on their machine.

---

## Quick reference cards

### DB status enum (jobs.apply_status)

```
NULL                   → never attempted (default)
in_progress            → worker has the lock, currently applying
applied                → real submit confirmed
submitted_unverified   → claimed applied but Python verifier couldn't confirm
failed                 → permanent or recoverable failure (see apply_error)
manual                 → routed to user; CLI/dashboard surface only
pause_for_human        → mid-apply, needs user input (MFA, email code with no Gmail MCP, etc.)
dry_run                → ran in --dry-run mode; didn't actually submit (NEW status from ghost-fix)
```

### DB status enum (jobs.apply_error for failed status)

```
not_eligible_location    → onsite outside accept list, no remote
not_eligible_salary      → posted pay below floor
not_eligible_experience  → role is junior/intern
not_eligible_geo         → posting excludes user's country (NEW from full-autonomy)
not_a_job_application    → contractor marketplace / profile builder
sso_required             → SSO wall; should never be retried
account_required         → requires account creation; manual
manual ATS               → in manual_ats list (sites.yaml)
expired                  → posting is closed
captcha                  → CAPTCHA defeated CapSolver
login_issue              → could not sign in / create account
unsafe_permissions       → site requested camera/mic/screen
unsafe_verification      → site wanted selfie/ID/biometric
claude_quota_exhausted   → Anthropic API quota hit (NEW from hang-fix, already shipped)
inactivity_timeout       → no stream-json line for N seconds (NEW from hang-fix)
wall_timeout             → exceeded apply_timeout (NEW from hang-fix)
stuck_on_step_N          → multi-step form stuck (NEW from full-autonomy Blocker 2)
tool_budget_exceeded     → agent hit max tool calls (NEW from full-autonomy Blocker 2)
page_did_not_load        → snapshot showed empty form twice (NEW)
email_code_not_received  → Gmail MCP found no matching email (NEW from full-autonomy Blocker 1)
```

### CLI cheat sheet

```bash
# Run the full pipeline
applypilot run                                    # all stages, sequential
applypilot run --stream                           # streaming (loop each stage until done)
applypilot run discover enrich score              # specific stages
applypilot run tailor --min-score 7 --stream      # tailor only, loop until backlog drained

# Apply
applypilot apply                                  # default: 1 job, visible Chrome
applypilot apply --watch                          # slow pacing, keep open, confirm submit
applypilot apply --continuous --workers 3         # 3 parallel workers, polls forever
applypilot apply --url <specific-url>             # target one URL
applypilot apply --headless                       # invisible Chrome (rare)
applypilot apply --reset-failed                   # re-queue retryable failures
applypilot apply --triage                         # classify-only, no Chrome
applypilot apply --gen --url <url>                # generate the prompt, print CLI command for manual debug

# Server (dashboard)
applypilot serve                                  # http://127.0.0.1:9477
applypilot serve --plain                          # log to stdout for nohup

# Outreach / referrals (separate concern)
applypilot openoutreach start                     # background outreach API
applypilot refer                                  # send connection requests / messages

# Inbox
applypilot inbox scan
applypilot inbox classify
applypilot inbox apply-fixed-reply

# Debugging
applypilot apply --mark-applied <url>             # manual override
applypilot apply --mark-failed <url> --fail-reason <reason>
```

### Useful queries during development

```bash
# Funnel
sqlite3 ~/.applypilot/applypilot.db "
  SELECT
    COUNT(*) AS total,
    SUM(CASE WHEN full_description IS NOT NULL THEN 1 ELSE 0 END) AS enriched,
    SUM(CASE WHEN fit_score IS NOT NULL THEN 1 ELSE 0 END) AS scored,
    SUM(CASE WHEN tailored_resume_path IS NOT NULL THEN 1 ELSE 0 END) AS tailored,
    SUM(CASE WHEN applied_at IS NOT NULL THEN 1 ELSE 0 END) AS applied
  FROM jobs;
"

# Apply outcomes by status
sqlite3 ~/.applypilot/applypilot.db "
  SELECT apply_status, apply_error, COUNT(*)
    FROM jobs WHERE apply_status IS NOT NULL
   GROUP BY apply_status, apply_error
   ORDER BY 3 DESC;
"

# Last 10 apply attempts with their result
ls -t ~/.applypilot/logs/claude_*.txt | head -10

# Worker log tail
tail -100 ~/.applypilot/logs/worker-0.log

# Recent runs
sqlite3 ~/.applypilot/applypilot.db "
  SELECT id, started_at, finished_at, status, current_stage, stages_json
    FROM runs ORDER BY started_at DESC LIMIT 10;
"
```

### Environment variables

```
APPLYPILOT_DIR                  # override ~/.applypilot location (rare)
APPLYPILOT_RUN_ID               # set by orchestrator; emit_run_event uses it
LLM_URL                         # local llama.cpp / Ollama; precedence over Gemini/OpenAI
LLM_MODEL                       # override model name for any provider
GEMINI_API_KEY                  # default scoring/tailor provider
OPENAI_API_KEY                  # fallback
CAPSOLVER_API_KEY               # CAPTCHA solving in apply
OPENOUTREACH_API_KEY            # referrals (synced from ~/.applypilot/.env)
APPLYPILOT_DISABLE_PRE_FILTER   # env override to bypass scoring pre-filter (from discover-relevance-fix)
APPLYPILOT_APPLY_INACTIVITY_TIMEOUT  # override apply inactivity watchdog
```

### Where things live in `~/.applypilot/`

```
applypilot.db                   # SQLite (~50MB typical)
profile.json                    # personal, skills_boundary, work_authorization, compensation
searches.yaml                   # discover queries, exclude_titles, locations
resume.txt + resume.pdf         # base resume (input to tailor)
tailored_resumes/<...>.txt/.pdf # per-job tailored output
cover_letters/<...>.txt/.pdf    # per-job cover letters
chrome-workers/worker-N/        # persistent chrome profile per worker
apply-workers/worker-N/         # per-job scratch directory (reset each apply)
logs/
  worker-N.log                  # rolling worker log (all jobs concatenated)
  claude_TIMESTAMP_wN_*.txt     # per-job session log
.mcp-apply-N.json               # per-worker MCP config (generated)
.env                            # env vars sourced by config.load_env()
```

---

## What NOT to do (patterns that have already burned someone)

1. **Don't trust agent free-text claims of success.** This is the lesson of `apply-ghost-fix-may-2026.md`. If you're adding any new "agent says X" check, also add a Python-side verification of the structured proof.
2. **Don't `for line in proc.stdout:` without an inactivity watchdog.** This is the lesson of `apply-hang-fix-may-2026.md`. If you ever spawn a subprocess that emits stream-json, use the reader-thread + queue pattern from the hang-fix doc.
3. **Don't increment retry counters on transient errors.** The lesson of `enrich-tailor-gap-fix-may-2026.md`: distinguish API timeouts (don't count) from validation failures (do count).
4. **Don't add filters to one discover source only.** Lift filters into `discovery/_filters.py` (or similar) and apply to all 10 sources.
5. **Don't open `gmail.com` in worker Chrome.** It's logged out. Use the Gmail MCP. This is the central learning from the live test on May 25.
6. **Don't use `--dry-run` mode and emit `RESULT:APPLIED`.** Either the agent submitted or it didn't. The prompt should say `RESULT_JSON:{"status":"dry_run", ...}` instead.
7. **Don't auto-decide.** If a doc presents two valid options and the user hasn't picked, ask via PR description before merging.
8. **Don't write giant docs without status lines.** Future agents need to know at a glance: shipped vs open.
9. **Don't introduce em dashes (—) in user-visible strings.** AGENTS.md and the gstack voice rules explicitly ban them.
10. **Don't add SaaS features, multi-user features, mobile apps, or cloud sync.** Single-user local-first.

---

## When the user is testing live, support them

The user often runs `applypilot apply --watch` on a specific URL to verify your fix. Make this easy:

- Your fix should work even with `--watch --pace 2 --confirm-submit` (the slow human-tracking mode).
- The worker chip in the dashboard should reflect the new behavior in real time.
- If your fix introduces a new status, the dashboard chip color should match the semantic (green=ok, amber=needs check, red=failed, blue=in progress, gray=manual).
- If your fix can fail in a recoverable way, log a clear reason so the user sees it without grep.

---

## How to handle ambiguity

If the doc says "do X" and you're unsure how, FOLLOW THIS:

1. Re-read the surrounding context in the doc. Often the answer is in an earlier section.
2. Search the codebase for similar existing patterns (`grep` for analogous function names).
3. Check `AGENTS.md` "Learned Workspace Facts" for project-specific conventions.
4. Look at the test directory (`tests/`) to see how similar code is tested.
5. If still unsure, surface the decision in the PR description with two options and a recommendation. DON'T silently pick.

If the doc is silently wrong about something (file path doesn't exist, function has been renamed), fix the doc as part of your PR.

---

## What success looks like at the end of the queue

After all 13 open rows ship, the system should:

- Apply autonomously to ~75% of queued jobs (Greenhouse / Lever / Workday / Ashby with email codes handled).
- Cost ~$10/month on LLM (down from ~$100) — templating handles 80% of tailoring, pre-filters drop 90% of bad scoring.
- Surface every failure mode with a specific reason on the dashboard, not "failed without signal."
- Recover gracefully from quota, hangs, dead pages, expired jobs, SSO walls.
- Show real-time pipeline + apply state at the level the user wants ("filling 'Why Anthropic?' field, worker 2, 23s in").
- Never silently retry junk; every retry is justified, every dead row has a reason.

The user's lived experience moves from "I hit Ctrl+C because something looks stuck" to "I check in once a day and approve the 5 jobs that need a human, the rest happened on their own."

---

## When you hand back to the user

End your session with a structured handback. The user reads this and decides what's next:

```
HANDBACK
════════════════════════════════════════════════════════════
Playbook row(s) completed: [N, M]
Doc(s) updated:            [path1, path2]
PR(s) opened:              [link or branch name]
End-to-end verified:       [yes / no / partial — explain]
Tests added:               [count + paths]
Tests run:                 [pytest output snippet]
Surprises / deviations:    [anything that didn't match the doc]
Unblocks next:             [Playbook row N]
Recommended next pick:     [Playbook row N — one-line reason]
════════════════════════════════════════════════════════════
```

That's all. The user takes it from there.

Good luck. The fixes in this queue genuinely move the needle. Ship carefully and the system gets meaningfully better with every PR.
