# Enrich → Tailor Funnel Collapse (May 2026)

**Status:** Investigation report (May 2026 DB snapshot). **Partial visibility shipped** since first draft (`tailor_exhausted` stat, Jobs Explorer stage/filter). **Core tailor fixes (Tier 1–3) not shipped** — attempt accounting, `tailor_error`, horizon counters, CLI reset flags still open.

**One-line summary:** the pipeline scores thousands of jobs but tailors only a small fraction. Four causes stack: default **sequential** runs process at most **20 tailor jobs per invocation**, most streaming runs never finish tailor (Ctrl+C / errors), a hardcoded **5-attempt cap** drops high-score jobs from the queue, and live run progress **hides dead jobs** even though Jobs Explorer can surface them. The gap looks like "tailoring is broken" when it's mostly "tailoring barely runs, quits early, and gives up too easily."

---

## TL;DR

- **8,811 jobs in the DB. 7,755 scored. 179 tailored. 25 applied.** Even at fit_score 10, only 23% of jobs were tailored; at score 8, only 3.5%. The funnel doesn't lose jobs to the score threshold — it loses them at tailor.
- **Cause A: sequential mode only tailors 20 jobs per run.** `run_tailoring(..., limit=20)` and `_run_sequential` call it **once** — no loop. `applypilot run tailor` (default) clears at most 20 eligible jobs unless you rerun many times or use `--stream` (loops until backlog drained).
- **Cause B: streaming tailor runs almost never finish.** 12 tailor-including runs in the last 14 days; 7 were Ctrl+C'd (`stopped`), 4 errored (`failed`), only 1 completed. 1,673 high-score jobs sat at `tailor_attempts = 0` because no completed run reached them.
- **Cause C: 5-attempt cap silently kills jobs.** 289 high-score jobs hit `tailor_attempts >= 5` and drop out of `_count_pending("tailor")`. Each batch increment counts ALL failure modes equally — API timeouts, validation hiccups, judge rejections — so transient LLM errors can permanently retire a job. Cap is **hardcoded `< 5`** in `database.py` / `pipeline.py`; `config.DEFAULTS["max_tailor_attempts"]` exists but is **not wired** into queries.
- **Cause D: inconsistent failure visibility.** No `tailor_error` column (failures live in logs / `*_REPORT.json` on disk). **Partial UI exists:** `/api/stats` exposes `tailor_exhausted` and `untailored_eligible`; Jobs Explorer labels/filters **Tailor exhausted** jobs. But live `stage_progress` tailor `pending` uses `_count_pending` (excludes dead jobs), while Home idle cards use `untailored_eligible` (includes dead) — so numbers disagree depending on where you look.
- **Two-line acute mitigation:** reset dead jobs via SQL, then run **`applypilot run tailor --stream --min-score 7`** (or loop sequential runs) overnight without Ctrl+C. Ship Tier 1 alongside or the dead pile returns.
- **Proper fix, ranked:** (1) only count "real" failures toward the attempt cap, (2) add a `tailor_error` column + dashboard surface, (3) make tailor checkpointed/resumable so a Ctrl+C doesn't strand work, (4) sweep dead jobs back into the queue with a `--reset-dead-tailor` flag.

---

## What's broken: evidence

### The funnel, top to bottom (May 2026 DB snapshot — re-run `scripts/pipeline_stage_snapshot.py` for live counts)

```
Stage              Count    % of total    Notes
─────────────  ─────────  ──────────────  ───────────────────────────────────
discovered      8,811      100.0%
enriched        7,768       88.2%        16 unscored have no full_description
scored          7,755       88.0%        score 1-10 distribution shown below
tailored          179        2.0%        ← FUNNEL COLLAPSES HERE
cover letter      175        2.0%        cover is just tailor +1 step
applied            25        0.3%        20 applied + 25 submitted_unverified
                                          (from the prior ghost-fix doc)
```

### Score distribution among ENRICHED jobs (this is what tailor sees)

```
fit_score    enriched    tailored    coverage
─────────    ────────    ────────    ────────
10              266         62        23.3%
 9              717         80        11.2%
 8              788         28         3.6%
 7              436          7         1.6%
 6            1,012          2         0.2%
 5              864          0         0.0%
 4            1,104          0         0.0%
 3              903          0         0.0%
 2            1,073          0         0.0%
 1              589          0         0.0%
```

The default `min_score=7` cutoff is correct: scores 1-6 (5,545 jobs) are skipped by design. But of the 2,207 jobs at score ≥ 7 that SHOULD be tailored, only 177 (8%) are.

### What's eating the 2,030 score-≥7 untailored jobs?

```
tailor_attempts    count    interpretation
──────────────     ─────    ─────────────────────────────────────────────────
0                  1,673    NEVER ATTEMPTED — no completed tailor run reached them
1                     31    in retry purgatory
2                     26    in retry purgatory
3                      7    in retry purgatory
4                      4    in retry purgatory
5                    289    PERMANENTLY DEAD — over the max_tailor_attempts cap
                            (245 of these are LinkedIn jobs)
```

Two distinct populations: 1,673 untouched + 289 dead. **Dead jobs are invisible to live tailor `pending` counts** but filterable in Jobs Explorer (`tailor_exhausted`).

### Reconcile with trust audit (May 23)

`docs/superpowers/specs/2026-05-23-applypilot-trust-audit.md` blamed low tailor coverage on "tailor hasn't been run" (936 untailored, no exhausted rows at audit time). This doc's May 24 DB snapshot splits that pile into **never attempted** (0 attempts) vs **exhausted** (≥5 attempts). Both can be true across time: backlog grows when runs stop early; exhausted rows appear once the 5-attempt cap fires. Code now surfaces exhausted jobs via `get_stats()["tailor_exhausted"]` and `STAGE_TAILOR_EXHAUSTED` in `job_pipeline_stage.py` — the audit's "no flag" claim is stale for current dashboard/API, not for per-job error text.

### Recent runs explain the "untouched" pile

```
status      runs (last 14d, stages include tailor)
─────────   ─────────────────────────────────────
completed                1
failed                   4
stopped                  7
─────                  ──
total                   12
```

**11 of 12 tailor-including runs did not finish.** Stops happen because tailor is slow (it's LLM-bound) and the user Ctrl+C's when something else looks broken (the apply hang, the discover stage being slow, etc.). When a tailor run is killed mid-batch, no upstream signal tells the user "you still have 1,500 high-score jobs in queue." The dashboard happily reports "100% of the latest batch tailored" with no horizon view.

### Where the 289 dead jobs come from

```
site                 dead jobs
─────────────        ─────────
linkedin                245
Thomson Reuters          22
indeed                   20
Ciena                     1
BMO                       1
```

LinkedIn dominates (84% of the dead pile). Two likely reasons:
- LinkedIn job descriptions in the DB are often shorter / lower-quality than other sources, so the LLM can't extract enough good content to tailor cleanly without triggering validator banned-words.
- LinkedIn title patterns ("Senior X / Lead Y") trigger the judge's seniority checks repeatedly across attempts.

This is a pattern worth surfacing, not just a count — see "What I'd actually ship" below.

---

## Why it happens: the architecture

```
                CURRENT TAILOR FLOW

  Sequential (default)                    Streaming (--stream)
  ─────────────────────                   ──────────────────────
  _run_sequential                         _run_stage_streaming
    → run_tailoring(limit=20) ONCE          → loop: run_tailoring(limit=20)
    → max 20 jobs / invocation              → until pending=0 or Ctrl+C

  Both paths call run_tailoring → get_jobs_by_stage("pending_tailor", limit=20)
  WHERE fit_score >= 7 AND full_description IS NOT NULL
    AND tailored_resume_path IS NULL AND COALESCE(tailor_attempts, 0) < 5
  Each batch: tailor_resume (up to 4 internal tries) then tailor_attempts += 1
  for every job in the batch (success or failure).
```

### Why "0 attempts" jobs pile up: sequential batch limit + incomplete runs

**Sequential default (most `applypilot run tailor` invocations):**

- `_run_sequential` calls `_run_tailor` → `run_tailoring(min_score=7, limit=20)` **once**.
- One invocation = at most **20** jobs tailored, regardless of backlog size.
- To drain ~1,962 jobs sequentially you'd need ~98 separate runs (or a shell loop).

**Streaming mode (`--stream`):**

- `_run_stage_streaming` loops while `pending > 0` and upstream isn't done.
- LLM-bound work is slow (~10s/job). Tailoring 2,000 jobs ≈ 5.5 hours wall-clock.
- User hits Ctrl+C when something else looks stuck (apply hang, slow discover) → `_stop_event` exits the loop → pending jobs stay at `tailor_attempts = 0`.
- Next full pipeline run may prioritize discover/enrich/score on new jobs, expanding backlog further.

### Why "5-attempts dead" jobs pile up: every failure counts the same

`scoring/tailor.py:564-572` increments `tailor_attempts` AFTER every batch call regardless of failure reason:

```python
for r in results:
    if r["status"] in _success_statuses:
        UPDATE jobs SET tailored_resume_path=?, tailored_at=?,
                        tailor_attempts = tailor_attempts + 1
    else:
        UPDATE jobs SET tailor_attempts = tailor_attempts + 1
```

`tailor_resume()` itself runs an internal retry loop (`for attempt in range(max_retries + 1)` with `max_retries=3`, so up to 4 internal attempts). Each internal attempt opens a fresh conversation. If all 4 internal attempts fail, the batch-level result is "failed_validation" / "failed_judge" / "error" — and the batch increments `tailor_attempts` by 1.

So one batch call burns ~4 LLM calls AND ~1 attempt-counter slot. After 5 batch calls the job is dead. That's ~20 LLM calls per job before it's gone — sounds like a lot, but:

- **Transient API errors look identical to permanent failures.** A Gemini rate-limit error or a 503 burns the same 4-internal-retries + 1-attempt-slot as a job whose description genuinely can't be tailored.
- **Validation strictness affects the count.** With `validation_mode="strict"`, banned-word violations trigger internal retries. With `normal` mode they're warnings only, but the LLM judge can still fail on the last retry.
- **Judge nuance:** on the final internal retry, a judge failure can become `approved_with_judge_warning` — that **succeeds** and saves `tailored_resume_path`. Not every judge disagreement burns an attempt slot at the batch level.
- **No retry-with-different-prompt strategy.** Each batch call uses the same prompt + same job text + same resume. If the model's first 4 attempts can't satisfy the validator, the next batch's 4 attempts won't either.

### Why progress numbers disagree

| Surface | Tailor "pending" / backlog source | Includes dead (attempts ≥ 5)? |
|---------|-----------------------------------|----------------------------------|
| Live run `stage_progress` (SSE) | `_count_pending("tailor")` | No |
| Home idle cards (`stageCounts.ts`) | `untailored_eligible` from `/api/stats` | Yes |
| Idle progress fallback (`stageProgress.ts`) | `untailored_eligible` | Yes |
| Jobs Explorer filter `tailor_exhausted` | `tailor_attempts >= 5`, no path | Dead only |
| `applypilot status` | `untailored_eligible` row | Yes |

`pending` in live tailor progress is defined by the same WHERE clause as the batch pull (`tailor_attempts < 5`). Once a job hits 5 attempts it is neither `done` nor `pending` in SSE — it's dropped from that math. The 289 dead jobs don't appear in "X left" during a run even though Home may show a much larger untailored count.

There's still no `tailor_error` column. When a job fails or dies, the reason isn't in the DB — grep logs or read `~/.applypilot/tailored_resumes/*_REPORT.json`.

---

## Specific code references

**Canonical stage order** (source of truth): `discover → enrich → score → tailor → pdf → refer → cover` in `pipeline.py` (`STAGE_ORDER`). `applypilot apply` is separate. Workflow mapping: `docs/job-workflow-may-2026.md` (tailor → pdf → cover).

- **`scoring/tailor.py:458`** — `run_tailoring(min_score: int = 7, limit: int = 20, ...)` — default batch size 20; pipeline never passes a higher limit.
- **`scoring/tailor.py:561-572`** — unconditional `tailor_attempts + 1` on success **and** failure (except success also sets path).
- **`scoring/tailor.py:347-440`** — `tailor_resume` internal retry loop (up to 4 attempts); `approved_with_judge_warning` is a success path.
- **`database.py:452-455`** — `get_jobs_by_stage("pending_tailor")`: hardcoded `COALESCE(tailor_attempts, 0) < 5`.
- **`database.py:312-322`** — `get_stats()`: `untailored_eligible` (score≥7, no path) and `tailor_exhausted` (attempts≥5, no path).
- **`database.py`** — `tailor_attempts INTEGER DEFAULT 0`; no `tailor_error TEXT` column.
- **`config.py:204`** — `"max_tailor_attempts": 5` in DEFAULTS — **not used** by pending queries (still literal `5`).
- **`config.py:199`** — `"min_score": 7` — reasonable; not the root cause.
- **`pipeline.py:329-340`** — tailor `stage_progress` snapshot (`pending` excludes dead jobs).
- **`pipeline.py:538-568`** — `_run_sequential`: one runner call per stage (20 tailor jobs max).
- **`pipeline.py:433-510`** — `_run_stage_streaming`: loops until pending=0 or stop (Ctrl+C).
- **`server/job_pipeline_stage.py`** — `STAGE_TAILOR_EXHAUSTED`, filter slug `tailor_exhausted`.
- **`cli.py:112`** — `--min-score` exposed; no `--reset-dead-tailor`, no tailor `--limit` on `run`.
- **`scripts/pipeline_stage_snapshot.py`** — prints `untailored_7+` (not `tailor_exhausted`); quick CLI funnel check.
- **No `--reset-dead-tailor`** — `--reset-failed` exists for apply only.

---

## Fix plan (3 tiers + acute mitigation)

None of the Tier 1–3 logic changes have been applied. Pick what to ship in a follow-up.

### Acute mitigation (10 minutes, minimal code)

Recover untouched + dead jobs into the queue, then drain with **streaming** (or many sequential reruns).

```bash
# 0. Snapshot current funnel (optional)
python scripts/pipeline_stage_snapshot.py
applypilot status   # includes "Pending tailoring (7+)" = untailored_eligible

# 1. Reset the 289 dead jobs so they get another try.
sqlite3 ~/.applypilot/applypilot.db "
  UPDATE jobs
     SET tailor_attempts = 0
   WHERE fit_score >= 7
     AND full_description IS NOT NULL
     AND tailored_resume_path IS NULL
     AND COALESCE(tailor_attempts, 0) >= 5;
"

# 2. Drain backlog — MUST use --stream (loops) or repeat sequential runs.
#    Default sequential run only processes 20 jobs total.
applypilot run tailor --stream --min-score 7
```

At ~10s/job × ~1,962 jobs ≈ 5.5 hours wall-clock. Run overnight; don't Ctrl+C.

**Sequential alternative** (if you can't use `--stream`): loop until `untailored_eligible` stops dropping:

```bash
while true; do
  applypilot run tailor --min-score 7 || break
  python scripts/pipeline_stage_snapshot.py
done
```

This is a band-aid without Tier 1. LinkedIn-heavy dead jobs may hit the cap again.

### Tier 1: stop counting transient failures (~1 hour, ~50 lines, huge recovery)

Goal: only count *deterministic* failures toward the 5-attempt cap. Transient LLM errors get unlimited retries (with backoff), the way they should.

**Change 1 — distinguish failure modes in `run_tailoring` (`scoring/tailor.py:564-572`):**

```python
# Failure modes that count toward the attempt cap:
COUNTED_FAILURES = {
    "failed_validation",   # LLM produced text but validator rejected
    "failed_judge",        # LLM judge said the result was a fabrication
    "exhausted_retries",   # tailor_resume's 4 internal attempts all failed
}

# Failure modes that should NOT count (transient / external):
UNCOUNTED_FAILURES = {
    "error",               # exception thrown — API timeout, network, parse
    "rate_limited",        # NEW: explicit rate-limit detection
    "context_too_long",    # NEW: input bigger than model limit (config issue)
}

for r in results:
    if r["status"] in _success_statuses:
        conn.execute(
            "UPDATE jobs SET tailored_resume_path=?, tailored_at=?, "
            "tailor_attempts = COALESCE(tailor_attempts,0)+1, "
            "tailor_error = NULL "
            "WHERE url=?",
            (r["path"], now, r["url"]),
        )
    elif r["status"] in COUNTED_FAILURES:
        conn.execute(
            "UPDATE jobs SET tailor_attempts = COALESCE(tailor_attempts,0)+1, "
            "tailor_error = ? "
            "WHERE url=?",
            (f"{r['status']}: {r.get('reason', '')[:200]}", r["url"]),
        )
    else:  # UNCOUNTED_FAILURES
        # Log but do NOT increment attempts. Record the error so the dashboard
        # can show "stuck on transient error, retry next pass."
        conn.execute(
            "UPDATE jobs SET tailor_error = ? "
            "WHERE url=?",
            (f"transient: {r['status']}: {r.get('reason', '')[:200]}", r["url"]),
        )
```

**Change 2 — add the `tailor_error` column:**

```python
# database.py — in the migrations block, idempotent:
def _ensure_tailor_error_column(conn):
    cols = {row[1] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()}
    if "tailor_error" not in cols:
        conn.execute("ALTER TABLE jobs ADD COLUMN tailor_error TEXT;")
```

**Change 3 — wire `max_tailor_attempts` from config** (replace hardcoded `5` in `database.py`, `pipeline.py`, `job_pipeline_stage.py`).

**Change 4 — surface `tailor_error` on the dashboard** (same pattern as `apply_error`).

**Change 5 — optional: loop tailor in sequential mode** or expose `--limit` on `applypilot run tailor` so one-shot runs aren't capped at 20 by surprise.

**Why this is Tier 1:** the 245 dead LinkedIn jobs are almost certainly mixed transient + structural failures. Even if 50% of them are recoverable, that's ~120 jobs added back to the queue per run instead of vanishing. Combined with the acute SQL reset, this should immediately raise the score-≥7 coverage from 8% to 60%+ over a few full tailor runs.

### Tier 2: resumable tailor + horizon view (~2-3 hours)

Goal: prevent the Ctrl+C → stranded-backlog cycle. Make it safe to interrupt and resume tailor.

**Change 1 — track a "current run" cursor.**

Add a `tailor_run_cursor` table (or single-row state table) that the streaming loop updates after every batch with the last URL processed. On resume, the next run starts from that cursor instead of re-querying. Most importantly: the dashboard can show "tailor: 1,673 jobs remaining in backlog (across all queued, not just last batch)."

**Change 2 — show backlog horizon in the dashboard.**

The current `detail: "{done} tailored · {pending} left"` is per-pass. Add a separate counter:

```python
return {
    "stage": "tailor",
    "done": done,
    "pending_this_pass": pending,                  # current batch view
    "backlog_total": _count_tailor_backlog(),      # NEW: all queued + dead
    "backlog_dead": _count_tailor_dead(),          # NEW: tailor_attempts >= cap
    "detail": (
        f"{done} tailored · {pending} this pass · "
        f"{backlog_total} total backlog ({backlog_dead} dead)"
    ),
}
```

The user sees `124 tailored · 12 this pass · 1,962 total backlog (289 dead)` and knows there's still real work to do. Today the user sees `124 tailored · 12 this pass` and assumes the system is caught up.

**Change 3 — graceful Ctrl+C: finish the current batch, then exit.**

The current `_stop_event.wait()` cuts hard. Add a "soft stop" that finishes the batch (so jobs in flight commit their results) before exiting. The Run banner can show "Stopping after current batch... (8 jobs in progress)."

**Why this is Tier 2:** addresses the "11 of 12 runs didn't finish" root cause. Doesn't fix tailor reliability, but makes the failure recoverable.

### Tier 3: dashboard control surface for the dead pile (~1 hour)

Goal: let the user act on the dead/transient pile from the dashboard, not by hand-rolling SQL.

**Add CLI flags + dashboard buttons:**

- `applypilot run tailor --reset-dead` — resets `tailor_attempts` for jobs at the cap (the acute SQL above, productized)
- `applypilot run tailor --reset-transient` — clears `tailor_error LIKE 'transient:%'` so they get picked up sooner
- `applypilot run tailor --backlog-only` — runs the full backlog, ignores upstream stages, suitable for an overnight catch-up run
- Dashboard: a "Tailor backlog" widget on the Pipeline page showing total / pending / dead, with one-click reset for dead.

The dashboard work overlaps with `docs/dashboard-redesign-requirements-may-2026.md` (the per-stage detail panels mentioned there should cover this naturally).

**Why this is Tier 3:** these are mechanical UX adds. Cheap once Tier 1 + Tier 2 are in. Without Tier 1, "reset dead" just re-burns 289 jobs on the same transient errors that killed them the first time.

---

## What I'd actually ship

Order matters here, because each step affects the next:

1. **Acute SQL reset** (5 minutes, no code).
2. **Tier 1 today** (1 hour, ~50 lines). Stops the bleeding for new jobs. Without this, the reset is a band-aid that recreates the problem.
3. **Overnight tailor run** — `applypilot run tailor --stream --min-score 7` to clear backlog (not default sequential 20-job cap).
4. **Tier 2 this week** (~3 hours). Makes future tailor runs interrupt-safe and gives the dashboard a real horizon.
5. **Tier 3 alongside the dashboard redesign** (when that's queued).

Combined effect: the score-≥7 tailor coverage should go from 8% (today) to 70%+ within one full overnight run, and stay there even when the user interrupts runs.

---

## NOT in scope

- Raising `min_score` below 7. The score-1-6 jobs (5,545 of them) are correctly excluded; tailoring them would burn LLM tokens on jobs the user won't apply to anyway.
- Changing the LLM provider. The current provider chain (LLM_URL > Gemini > OpenAI per `llm.py`) is fine; the bottleneck is the attempt-counting logic, not the model.
- Reworking the resume tailoring prompt. Some 245 LinkedIn failures might be prompt-fixable, but that's a separate piece of work (see "What I'd actually ship" + see if Tier 1 alone resurrects most of them first).
- Pipeline-level retries (separate from per-job retries). The streaming loop already retries on next pass; the gap is at job-attempt accounting, not at the pipeline level.
- Caching tailored resumes across jobs. Each job gets its own tailored resume by design; the cost is well-spent when the result is correct.

---

## What already exists (reuse, don't rebuild)

- `tailor_resume`'s internal `max_retries=3` retry loop with avoid_notes feedback — already smart; batch-level counting is the problem.
- `get_jobs_by_stage("pending_tailor", min_score, limit)` — right query shape; cap and limit need product knobs.
- `get_stats()["tailor_exhausted"]` + `untailored_eligible` — use for horizon/backlog widgets.
- `STAGE_TAILOR_EXHAUSTED` / Jobs Explorer filter `tailor_exhausted` — dead-pile visibility (shipped May 2026).
- `apply_error` column + dashboard surface — same pattern to copy for `tailor_error`.
- `applypilot apply --reset-failed` — same UX pattern for `--reset-dead-tailor`.
- `pipeline.py` streaming loop — correct for backlog drain; sequential mode needs explicit loop or higher default limit.
- `scripts/pipeline_stage_snapshot.py` — quick enrich/tailor funnel counts from CLI.

---

## What shipped vs still open (May 2026)

| Item | Status |
|------|--------|
| `tailor_exhausted` in `get_stats()` / `/api/stats` | Shipped |
| Jobs Explorer stage **Tailor exhausted** + filter | Shipped |
| `untailored_eligible` on Home stage cards | Shipped (includes dead jobs) |
| Live `stage_progress` horizon (backlog_total / dead) | Not shipped |
| `tailor_error` column | Not shipped |
| Failure-mode-aware attempt counting | Not shipped |
| Wire `max_tailor_attempts` from config | Not shipped |
| `--reset-dead-tailor` / `--backlog-only` CLI | Not shipped |
| `tests/test_tailor_attempt_counting.py` | Planned, not in repo |
| `tests/test_stage_progress.py` | Shipped (enrich/score snapshots only; no tailor test) |

---

## Failure-mode table (after Tier 1 + Tier 2)

| Failure | Today | After Tier 1 | After Tier 2 |
|---|---|---|---|
| LLM returns invalid JSON | counts as 1 attempt | counts as 1 (failed_validation) | same |
| LLM rate-limit (429) | counts as 1 attempt | does NOT count, tailor_error="transient: rate_limited" | next pass picks it up automatically |
| Validator banned-word | counts as 1 attempt | counts as 1 (failed_validation) | same |
| Judge rejection | counts as 1 attempt | counts as 1 (failed_judge) | same |
| Network timeout / DNS fail | counts as 1 attempt | does NOT count | next pass picks it up |
| Job description too short | counts as 1 attempt | counts as 1, surfaces as tailor_error="short_description" | dashboard surfaces the pattern; user can adjust enrich |
| Sequential `applypilot run tailor` (no `--stream`) | max 20 jobs per invocation | same unless loop/limit fix shipped | same |
| Streaming tailor interrupted (Ctrl+C) | pending jobs stay at 0 attempts | same | soft-stop + horizon shows backlog |

---

## Verification plan once the fix ships

```bash
# A) Reset and rerun on the dead pile (after Tier 1 ships tailor_error).
sqlite3 ~/.applypilot/applypilot.db "
  UPDATE jobs SET tailor_attempts = 0, tailor_error = NULL
   WHERE fit_score >= 7 AND tailored_resume_path IS NULL
     AND COALESCE(tailor_attempts,0) >= 5;
"
applypilot run tailor --stream --min-score 7
# Expect: majority of reset dead jobs get paths; failures show tailor_error in API.

# B) Transient failure does NOT burn an attempt (Tier 1) — run one batch via Python:
# python -c "from applypilot.scoring.tailor import run_tailoring; run_tailoring(min_score=7, limit=1)"
# with invalid API key in env; expect tailor_error set, tailor_attempts unchanged.

# C) Backlog counts align (after Tier 2 horizon):
sqlite3 ~/.applypilot/applypilot.db "
  SELECT COUNT(*) FROM jobs
   WHERE fit_score >= 7 AND full_description IS NOT NULL
     AND tailored_resume_path IS NULL;
"
# Compare to dashboard backlog_total and applypilot status untailored_eligible.

# D) Regression: streaming tailor still writes paths.
applypilot run tailor --stream --min-score 7
# Watch logs for approved paths; confirm tailored_resume_path + tailored_at in DB.
```

---

## DEBUG REPORT

```
DEBUG REPORT
════════════════════════════════════════════════════════════
Symptom:         Huge gap between enrich (7,768) and tailor (179) in the
                 pipeline funnel. Only 2% of scored jobs get tailored;
                 even score-10 jobs are only 23% tailored.

Root cause:      Four stacking failures (May 2026 code review).
                 (A) Sequential pipeline runs tailor once with limit=20.
                 (B) Streaming runs often Ctrl+C'd before backlog drains.
                 (C) Batch-level tailor_attempts +1 on all failures; cap 5
                     hardcoded (config max_tailor_attempts unused).
                 (D) No tailor_error; live pending excludes dead jobs while
                     Jobs Explorer can show tailor_exhausted.

Fix:             Partial visibility shipped; Tier 1–3 + acute path in this doc.
                 - Acute: SQL reset + applypilot run tailor --stream
                 - Tier 1: counted vs transient failures; tailor_error
                 - Tier 2: horizon counters, soft Ctrl+C, resume cursor
                 - Tier 3: --reset-dead, dashboard backlog ops

Evidence:        - DB funnel snapshot in this doc (dated)
                 - tailor_attempts histogram
                 - runs table: 11/12 tailor runs stopped or failed
                 - scoring/tailor.py:458 limit=20, :561-572 increments
                 - pipeline.py sequential vs streaming
                 - get_stats tailor_exhausted / job_pipeline_stage

Regression test: tests/test_tailor_attempt_counting.py — PLANNED with Tier 1
                 (not in repo). tests/test_stage_progress.py covers enrich/score only.

Related:         - docs/apply-hang-fix-may-2026.md
                 - docs/apply-ghost-fix-may-2026.md
                 - docs/superpowers/specs/2026-05-23-applypilot-trust-audit.md
                 - docs/dashboard-redesign-requirements-may-2026.md
                 - docs/job-workflow-may-2026.md

Status:          INVESTIGATION CURRENT — doc corrected against codebase May 2026.
                 Partial dashboard visibility shipped; core tailor logic unchanged.
                 Acute mitigation runnable with --stream + SQL reset.
════════════════════════════════════════════════════════════
```
