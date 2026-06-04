# Pipeline stages (implementation reference)

Default order from `applypilot run`:

**discover → enrich → filter → score → tailor → pdf → refer → cover**

Separate from this pipeline: **`applypilot apply`** (browser submit). Optional one-time prep: **`role_resumes`**.

---

## Optional: `role_resumes`

**Purpose:** Build role-family resume PDFs under `role_resumes/` (not per-job).

**Runs when:** You pass `role_resumes` explicitly, or prep is incomplete.

**Logic:** Infer applicable roles from profile + master resume → generate missing PDFs only → skip if all exist.

---

## 1. `discover`

**Purpose:** Find new jobs and insert rows into SQLite.

**Sources (enabled in discover config):** Greenhouse, Lever, Ashby, JobSpy, Workday, feeds (RemoteOK, Remotive, Himalayas, WWR, HN Hiring, Work at a Startup), SmartExtract sites from `sites.yaml`, career targets, funded startups. Agent-mode sites use browser discovery; most use programmatic extract.

**Per job at insert:**
- Drop if `discover_job_passes()` fails (location/salary/title rules in discovery filters).
- Dedupe by content hash; merge sources on duplicate URL.
- If discover already has a long description, set `full_description` + `detail_scraped_at` (may skip enrich later).

**Output columns:** `url`, `title`, `location`, `salary`, short `description`, optional `full_description`, `application_url`, `site`, `discovered_at`.

---

## 2. `enrich`

**Purpose:** Fill full job text and a real apply link.

**Processes:** Jobs where `detail_scraped_at IS NULL`. Skips sites: Glassdoor, Google, Workopolis.

**Steps:**
1. Fix relative URLs using `sites.yaml`.
2. Backfill apply URLs from description text; optional LinkedIn “Apply on company website” pass.
3. WelcomeToTheJungle: resolve slug URLs via Algolia.
4. Headless browser per site → for each job: **JSON-LD → CSS selectors → LLM** (last resort).
5. Write `full_description`, `application_url`, `detail_scraped_at`, and `detail_error` on failure.

**Note:** Retryable failures (`timeout`, HTTP 408/429/5xx) clear `detail_scraped_at` and are retried up to 3 pipeline passes (plus 3 in-page goto attempts per pass). Permanent errors and exhausted retries set `detail_scraped_at` so the job is skipped.

---

## 3. `filter`

**Purpose:** Cheap rejection before LLM scoring.

**Processes:** `fit_score` and `pre_fit_score` both null, and job has `full_description` OR was enrich-attempted (`detail_scraped_at` set).

**Checks** (each togglable in `searches.yaml` → `filter.checks` or `profile.json` → `fit_filters.checks`; disable all via `filter.enabled: false` or `APPLYPILOT_DISABLE_PRE_FILTER`):

| Check | Rejects when |
|-------|----------------|
| `title_junior_or_intern` | Intern/junior/entry title |
| `title_exec_non_eng` | CFO/CMO/VP sales-style title |
| `title_adjacent_role` | Sales/solutions/PM/CS title |
| `title_allowlist` | Title missing `include_titles` match |
| `location` | Location fails accept/reject patterns |
| `salary_floor` | Below regional salary floor |
| `blocked_keywords` | JD contains blocked keyword |
| `description_junior_signal` | JD reads junior (unless senior title) |
| `profile_keyword_overlap` | Long JD but weak role/skill overlap |

**On reject:** Sets low `pre_fit_score`, writes `fit_score` + `scored_at` (job is “done” for score stage).

**On keep:** Sets `pre_fit_score` only; job moves to score.

---

## 4. `score`

**Purpose:** LLM fit score **1–10** and role binding for downstream stages.

**Processes:** `full_description` present and `fit_score` null (unless `--rescore`).

**Steps:**
1. Pick **one** resume per job (role-aware: best matching role PDF or base resume).
2. Run pre-filter again (same checks as filter stage).
3. Optional **embedding filter**: low resume↔JD similarity → cap score below 7, skip LLM.
4. LLM scores survivors → `fit_score`, `score_reasoning`, `scored_at`, `score_role_key`.

**Default tailor threshold:** `fit_score >= 7` (CLI `--min-score`).

---

## 5. `tailor`

**Purpose:** Ensure each high-score job has `tailored_resume_path`.

**Processes:** `fit_score >= min_score`, has full description, no tailored path yet, `< 5` tailor attempts.

**Steps:**
1. **`bind_role_resume_paths`:** If a role PDF fits the job, set `tailored_resume_path` (no LLM).
2. **`run_tailoring` loop** for jobs still needing work:
   - **A-grade** jobs (high score / target companies): full LLM tailor.
   - **B-grade** with template: archetype template from `~/.applypilot/templates/`.
   - Otherwise: full LLM tailor.
3. Repeat until no jobs need per-job tailor (safety cap: 500 passes).

**Skip LLM tailor when:** Role resume already matches JD well enough (`job_needs_per_job_tailor` is false).

---

## 6. `pdf`

**Purpose:** Turn tailored `.txt` resumes (and cover text) into PDFs on disk.

**Processes:** Files in `~/.applypilot/tailored_resumes/` where sibling `.pdf` is missing (batch default: 50 files).

**Logic:** Parse structured resume text → HTML template → headless Chromium PDF.

---

## 7. `refer`

**Purpose:** Referral **prep only** in pipeline (no send).

**Runs when:** `~/.applypilot/outreach.yaml` has `enabled: true`.

**Sub-steps:** `scrape` (LinkedIn recruiters) → `draft` (message from template).

**Does not run in pipeline:** `connect` / `message` (need OpenOutreach; use `applypilot refer` or dashboard).

---

## 8. `cover`

**Purpose:** Generate cover letter files for apply-ready jobs.

**Processes:** `fit_score >= min_score`, has `tailored_resume_path` + full description, no `cover_letter_path`, `< max` cover attempts.

**Logic:** LLM cover letter per job; batches until none left (default batch 300).

---

## After the pipeline: `apply`

**Not a pipeline stage.** Separate queue: tailored resume + apply URL, not yet applied.

Uses Claude Code + visible Chrome (by default). Eligibility, captcha, email verify, and site adapters live under `src/applypilot/apply/`.

---

## Quick “who is pending?” cheat sheet

| Stage | Pending means |
|-------|----------------|
| enrich | pending detail clause (never scraped, or retryable `detail_error` under attempt cap) |
| filter | No `fit_score` or `pre_fit_score`, has description or enrich attempt |
| score | `full_description` set, `fit_score` null |
| tailor | Score ≥ threshold, no `tailored_resume_path`, attempts < 5 |
| pdf | Tailored `.txt` without matching `.pdf` |
| cover | Score ≥ threshold, tailored resume, no cover letter path |
| apply | Tailored resume + apply URL, not applied |
