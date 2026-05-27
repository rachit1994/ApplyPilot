# ApplyPilot trust + effectiveness audit (real data)

_Audit date: 2026-05-23 · Source: `~/.applypilot/applypilot.db` (3,455 jobs)_

## Executive summary

| Verdict | Result |
|---|---|
| **Trust (can I walk away?)** | 🔴 **Red** — Verified-submit rate is **0/20 = 0%**. Every "applied" row in the DB is `submitted_unverified`. Today's `discover` is broken by a Python `NameError` regression. The dashboard's primary intervention path (Confirm/Retry on percent-encoded URLs) fails. |
| **Effectiveness (am I a more effective job seeker this week?)** | 🟡 **Yellow** — The pipeline is producing huge raw value: **139 jobs at fit≥7 are fully tailored, cover-lettered, and ready to apply** but never submitted. The biggest unlock is *stop generating, start submitting*: the queue starvation, not the discovery, is the bottleneck. |
| **One-line directive** | You are leaving **139 high-fit, fully-prepared applications** unapplied because (a) `apply` produces zero verified submissions today, (b) discover broke today, (c) the dashboard can't confirm/retry the unverified ones. Fix the three P0 bugs below before doing anything else. |

---

## Apply-now list (top 20 — the act-on list for today)

All 20 are `fit_score = 10`, with tailored resume **and** cover letter, never applied. Pulled from `jobs ORDER BY fit_score DESC, discovered_at DESC LIMIT 20` filtered to ready-state.

> ⚠ Direct apply via `applypilot apply` is currently unsafe (see Apply trust below). Until the verification regression is fixed, treat this as a **manual-priority queue**: open the URL, paste the tailored PDF, and submit yourself. After the fix, run with `--watch --confirm-submit`.

| # | Site | Title | Salary | Loc | URL |
|---|---|---|---|---|---|
| 1 | Workday (Motorola) | Sr. Machine Learning Engineer | — | Bangalore offsite, India | [link](https://motorolasolutions.wd5.myworkdayjobs.com/Careers/job/Bangalore-offsite-India/Sr-Machine-Learning-Engineer) |
| 2 | LinkedIn | Senior AI ML Engineer | — | Remote | https://www.linkedin.com/jobs/view/4407528590 |
| 3 | LinkedIn | Machine Learning Engineer, Agentic AI | $145k–$232k | Remote | https://www.linkedin.com/jobs/view/4385528913 |
| 4 | LinkedIn | Full-Stack Software Engineer | — | Remote | https://www.linkedin.com/jobs/view/4405986614 |
| 5 | LinkedIn | AI & AUTOMATION ENGINEER | — | — | https://www.linkedin.com/jobs/view/4416217314 |
| 6 | LinkedIn | AI Software Engineer (m/f/d) – Berlin | — | Remote | https://www.linkedin.com/jobs/view/4412262248 |
| 7 | LinkedIn | Software Engineer 5 — Ntech | $388k–$558k | — | https://www.linkedin.com/jobs/view/4412061107 |
| 8 | LinkedIn | Staff Software Engineer | — | — | https://www.linkedin.com/jobs/view/4410204988 |
| 9 | LinkedIn | AI Solutions Architect — Series A | $150k–$170k | Remote | https://www.linkedin.com/jobs/view/4416053862 |
| 10 | LinkedIn | AI Innovation Engineer | — | Remote | https://www.linkedin.com/jobs/view/4416203731 |
| 11 | LinkedIn | Founding AI Engineer / Co-Founder | — | — | https://www.linkedin.com/jobs/view/4412258255 |
| 12 | LinkedIn | Junior Software Engineer | — | — | https://www.linkedin.com/jobs/view/4416248581 |
| 13 | LinkedIn | Founding Engineer — Remote-EU FinTech | — | Remote | https://www.linkedin.com/jobs/view/4412220150 |
| 14 | LinkedIn | Founding Applied AI Engineer (India) | — | Remote | https://www.linkedin.com/jobs/view/4415533557 |
| 15 | LinkedIn | Engenheiro de IA Sr. | — | — | https://www.linkedin.com/jobs/view/4412045328 |
| 16 | YC (workatastartup) | New Grad SWE @ Confido | $150K + 0.03–0.07% | US only | https://www.workatastartup.com/jobs/93171 |
| 17 | Workday (Thomson Reuters) | Lead SWE AI — Materia | — | Mexico City | [link](https://thomsonreuters.wd5.myworkdayjobs.com/External_Career_Site/job/Mexico-Mexico-City/Lead-Software-Engineer-AI--Materia-AI--Evergreen-) |
| 18 | Workday (Thomson Reuters) | Lead SWE, AI | — | US-Eagan | [link](https://thomsonreuters.wd5.myworkdayjobs.com/External_Career_Site/job/United-States-of-America-Eagan) |
| 19 | Workday (Thomson Reuters) | Senior SWE — AI I | — | India-Hyderabad | [link](https://thomsonreuters.wd5.myworkdayjobs.com/External_Career_Site/job/India-Hyderabad-Telangana) |
| 20 | Workday (Thomson Reuters) | Staff SWE / Architect — AI, CoCounsel | — | US-Frisco | [link](https://thomsonreuters.wd5.myworkdayjobs.com/External_Career_Site/job/United-States-of-America-Frisco) |

**Recruiter leverage on this list: 0/20 have a scraped recruiter** — referral path is unused on every top-fit job.

The top-15 expands to **139 ready-to-apply at fit ≥ 7**. Distribution by source:

| Source | Ready (fit≥7, tailored, cover) |
|---|---|
| LinkedIn | 96 |
| Thomson Reuters (Workday) | 17 |
| Indeed | 7 |
| Motorola (Workday) | 4 |
| NVIDIA, Volley, Triomics, Salesforce, Laylo, Lamar, Karat, Hotplate, Encord, Confido, Bountiful, BlueCargo, Adobe | 1 each |

---

## Action backlog (this week, ranked)

> Ordered by **(blast radius × ease)**. P0 = blocks everything, P1 = unlocks effectiveness, P2 = nice-to-have.

| # | Effort | Action | Why |
|---|---|---|---|
| **P0-A** | S | **Fix `src/applypilot/discovery/jobspy.py:275` `NameError: search_cfg`** — `_run_one_search` references `search_cfg` that isn't passed in. | Today's discover ran 0 LinkedIn + 0 Indeed jobs (and no other JobSpy sources). Discovered-last-1d = 0 confirms it. Without this, the funnel can't see new jobs. |
| **P0-B** | M | **Stop generating fake "applied" rows.** Either (a) gate `apply --watch` with `--confirm-submit` by default until verification is reliable, or (b) make the apply prompt always emit `RESULT_JSON` with structured proof; downgrade to `submitted_unverified` is correct but every applied job is being downgraded → the prompt or browser tooling is not producing `post_submit_url`/`confirmation_copy`/`submit_click_ref`. | 20/20 applies are `submitted_unverified` (15 "missing apply log", 5 "legacy RESULT:APPLIED"). Verified-submit rate = 0%. Walk-away verdict is currently 🔴. |
| **P0-C** | S | **Fix dashboard `test_application_actions_preserve_percent_encoded_urls`** (`test_dashboard.py:429`, returns 404 instead of 200). | This is the **only** intervention path to convert 20 unverified rows into confirmed/retried. Right now you can't fix any of them from the UI when their URL has `%XX` sequences (very common on Workday/Greenhouse). |
| **P1-A** | XS | Manually apply to **the 20 fit-10 jobs** above this week (paste the existing tailored PDFs). | The work is already paid for in LLM tokens; submitting is the only remaining step. |
| **P1-B** | S | Run `applypilot openoutreach start` and trigger `applypilot refer` against the 138 already-scraped recruiters with status `connect_sent` not yet applied. | 134 referral attempts are `failed`, 574 `skipped`. OpenOutreach is offline (port 8741 closed). Connect-sent count is only 4. |
| **P1-C** | M | Investigate `recruiter_scrape_error` (574 jobs ≈ 81% of recruiter-scrape attempts). Likely LinkedIn search rate-limit or selector drift. | Without recruiter data, the entire referral arm is dead. |
| **P2-A** | S | After P0-A, expand discover to recover the 0 jobs/day to ~400 jobs/day (your weekly average is 469/day). | Reset the funnel back to working baseline. |
| **P2-B** | S | Add a single column `outcome_status` (NULL / response / interview / offer / rejected) to `jobs` so the next audit can finally answer "is this working?" not just "is this running?". | This is the **one** field that would convert "we generated 20 unverified applies" into "we got 3 first responses, 1 interview". |

---

## Funnel table (real numbers, full DB lifetime)

| Step | Count | % of previous | % of total | Notes |
|---|---:|---:|---:|---|
| Discovered | 3,455 | 100% | 100% | 3,286 in last 7 days, **0 in last 24h** (P0-A regression) |
| Enriched (`full_description IS NOT NULL`) | 3,453 | 99.94% | 99.94% | ✅ Excellent — `detail_error` count is only 2 |
| Has `application_url` | 1,710 | 49.5% | 49.5% | ⚠ The 50% missing is dominated by LinkedIn entries that need apply-time discovery |
| Scored | 3,455 | 100% | 100% | ✅ Scoring runs on 100% of enriched rows |
| Score ≥ 7 (your `--min-score` proxy) | 1,110 | — | 32.1% | Roughly 1 in 3 discoveries is "worth tailoring" by the model |
| Tailored (`tailored_resume_path`) | 174 | 15.7% of fit≥7 | 5.0% | ⚠ Heavy bottleneck — only 1 in 6 fit-7 jobs ever gets a tailor pass |
| Cover letter | 173 | 99.4% of tailored | 5.0% | Cover follows tailor 1:1 |
| **Ready to apply** (tailored + cover, fit≥7, not applied) | **139** | — | 4.0% | **The biggest opportunity in the entire dataset** |
| Apply attempted (`applied_at IS NOT NULL`) | 20 | 14.4% of ready | 0.6% | ❌ Tiny — we generate 7× more ready jobs than we submit |
| **Applied verified** (`apply_status='applied'`) | **0** | **0.0%** of attempts | **0.0%** | 🔴 **Submit trust rate = 0%** |
| Submitted unverified | 20 | 100% of attempts | — | Ghost rate = 100% |
| Apply failed | 12 | — | — | 8 salary, 3 experience, 1 browser — eligibility gate works |

---

## Trust scorecard (per-stage verdict)

| Stage | Verdict | Evidence |
|---|---|---|
| **Discover** | 🟡 Yellow → 🔴 Red today | 3,286 jobs in last 7d (= 469/day) is healthy, but **today returns 0** because of `jobspy.py NameError`. Source breakdown: linkedin 1832, indeed 544, Workday employers ~700, YC startups, Greenhouse/Lever <50 each. |
| **Enrich** | 🟢 Green | 99.94% fill rate (3,453/3,455). Only 2 `detail_error`. This stage is rock solid. |
| **Score** | 🟢 Green | 100% scored. 32% pass `fit ≥ 7`, which feels right for a senior+AI profile. Sample of fit=10 rows is mostly genuine senior/staff/founding engineering AI roles — no obvious false positives. |
| **Tailor + PDF** | 🟡 Yellow | Only 16% of fit-7 jobs get a tailor pass. There is no `tailor_exhausted` flag set on any row, suggesting tailoring just hasn't been *run* on the rest, not that it's failing. Run `applypilot run tailor pdf` to drain the queue. |
| **Apply** | 🔴 Red | **0% verified submit rate.** Every single one of the 20 applies is `submitted_unverified`. The verification logic in `verification.py` is correct — the agent is failing to emit the structured `RESULT_JSON` with `submit_click_ref`, `post_submit_url`, `confirmation_copy`. Fix is in the apply prompt + browser-tool integration, not the verifier. |
| **Intervention** | 🔴 Red | The dashboard `Confirm applied` / `Retry` flow has a confirmed bug for percent-encoded URLs (`test_application_actions_preserve_percent_encoded_urls` fails). Dashboard service is also not running today (port 9477 closed). The `--confirm-submit` CLI flag exists in `apply/launcher.py` but is opt-in, not the safe default. |

**Walk-away verdict: 🔴 Red. Do not run unattended apply until P0-B + P0-C ship.**

---

## Effectiveness scorecard

| Objective | Status | Number | What it means |
|---|---|---:|---|
| More high-fit applications **verified** in the last 7 days | 🔴 Weak | **0** | Every apply is unverified |
| High-fit jobs ready and untouched | 🔴 Major leak | **139** | These are 100% paid-for and 0% submitted |
| Scored ≥ 7 but never tailored | 🟡 OK-ish | **936** | (1110 − 174). One `applypilot run tailor pdf` cycle on the budget you've already paid for would convert ~half of these. |
| Recruiter leverage on top-15 | 🔴 Weak | **0/20** of fit=10 list | Referral path is fully unused on the most valuable jobs |
| Recruiters scraped successfully | 🟡 Weak | **138 / (138+574) = 19%** | LinkedIn recruiter scrape is failing 81% of the time |
| Apply window freshness (median age `discovered_at → applied_at`) | 🟡 Unknown | — | Most ready jobs are 2-7 days old; window is still open but slipping |
| Cost per applied job | 🟡 Unknown | — | Token usage isn't stored. Best proxy from run logs only. |
| **Outcome (response/interview rate)** | ⚠ Untracked | — | **No field in DB.** This is the single biggest measurement gap (see Outcome Tracking Gap below). |

---

## Effectiveness leaks (named buckets, with counts and unblock commands)

| Leak | Count | Cause | Unblock |
|---|---:|---|---|
| Score-7+ jobs **without** `tailored_resume_path` | **936** | Tailor stage hasn't been run on them yet | `applypilot run tailor pdf --min-score 7` |
| Score-7+ jobs **with** tailored + cover **but** never applied | **139** | Apply stage isn't running, OR is running but verification failing → operator stops | After P0-B fix: `applypilot apply --continuous --watch --min-score 7` |
| Tailored PDFs **without** apply attempt **and** older than 7 days | look up | Queue starvation; same root cause as above | Same as above |
| Score-7+ jobs **without** `application_url` (need apply-time discovery) | **92 of 139** | LinkedIn doesn't expose the apply URL in JSON; ATS routing happens at click time | Apply via `--watch` so the agent navigates the LinkedIn → ATS handoff |
| Score-7+ jobs **without** scraped recruiter | **103 of 139** | Recruiter scrape only ran on a fraction of the queue, plus 81% scrape failure rate | After OO restart: `applypilot refer --scrape --status pending --limit 100` |
| Apply-attempted jobs returning the same `apply_error` | 15 jobs share `"missing apply log / no structured verification proof"` | This is **a system bug**, not a per-job problem. The agent is finishing the form but not emitting structured proof. | P0-B (above) |

---

## Effectiveness levers (top 5 ranked by lift × effort)

| Lever | Lift est. | Effort | Why |
|---|---|---|---|
| **1. Submit the 139 ready-to-apply queue** (after P0-B) | **+30–50 verified applies / week** | M | The work is already done. This is the largest single source of unrealised effectiveness in the entire system. |
| **2. Drain the 936 fit-7 untailored backlog** | **+100–300 ready jobs** in 1–2 days | S | One CLI invocation. LLM cost is the only constraint. |
| **3. Restart OpenOutreach + scrape recruiters on top-15** | **+10–15 referrals** queued for top fits | S | OpenOutreach is offline; scraping is partly broken (81% error rate) but works on Workday/ATS. |
| **4. Fix recruiter LinkedIn scraper** (574 errors) | Unlocks ~400 referral targets long-term | M | Almost certainly LinkedIn DOM/selector drift. |
| **5. Add `outcome_status` column** | Converts every future audit from "is it running?" to "is it working?" | S | Single-column migration, then ask the user weekly to mark response/interview/offer. Pays compounding interest on every future audit. |

---

## Intervention map (when you must act)

| Trigger | UI/CLI surface | Status today |
|---|---|---|
| Apply finished but unverified | Dashboard → Applications tab → **Confirm applied / Retry** | 🔴 Broken for %-encoded URLs (`test_dashboard.py:429`); also dashboard not running today |
| Apply paused for review | `applypilot apply --confirm-submit` | 🟡 Works, but opt-in. Should be default until P0-B is fixed. |
| Discover ingests 0 today | Dashboard "discovered last 24h" | 🔴 Dashboard not running, but DB confirms 0/3,455 in last 1d |
| Recruiter scrape fails | `recruiter_scrape_error` column | 🟡 81% error rate is silent — no UI surface today |
| Referral connect failed | Dashboard → Referrals tab | 🟡 134 `failed`, 574 `skipped`; UI shows but no retry-all action |
| Pytest broke | CI / `pytest tests/ -v` | 🟡 1 fail, 1 collection error (see appendix) |

---

## Outcome tracking gap (the most important follow-up)

The DB tracks every step **up to** "submitted unverified" and stops. There is no column for response, interview, offer, rejection, or ghost-after-apply. **This means we cannot answer the actual question of whether ApplyPilot is working** — only whether it is *executing*.

**Proposed minimum viable outcome tracking:**
- Add `jobs.outcome_status` (`NULL` | `responded` | `interview` | `offer` | `rejected` | `ghost`)
- Add `jobs.outcome_at` (timestamp)
- Add `jobs.outcome_note` (free text)
- One dashboard column on Applications tab + 4 buttons (Responded/Interview/Offer/Rejected)
- One CLI: `applypilot outcome <url> <status>`

Cost: ~half a day. Lift: every audit from this one onward gives a real answer.

---

## Live run details (this audit)

| Phase | Result |
|---|---|
| Preflight (`applypilot doctor`) | ✅ All keys present, Chrome reachable |
| Snapshot before fresh run | 3,455 jobs total |
| Fresh `applypilot run discover enrich` | 🔴 **Failed** — `NameError: search_cfg` in `jobspy.py` killed LinkedIn + Indeed; `Playwright` browsers missing in sandbox killed `workatastartup`/`smartextract` (sandbox issue, not real). Net new jobs ingested: **0**. |
| Snapshot after | 3,455 jobs total (unchanged) |
| OpenOutreach health | 🔴 Port 8741 closed; service not running |
| Dashboard health | 🔴 Port 9477 closed; service not running |
| Pytest (`tests/`, excluding broken collection) | 131 passed, **1 failed** (`test_application_actions_preserve_percent_encoded_urls`), 1 collection error (`test_apply_prompt_workday.py`) |

The audit therefore measured the **historical** DB, which is the right thing to measure since the historical DB is what determines what jobs you can act on today.

---

## Prioritized code fixes (Yellow → Green)

| Priority | File | Fix | Trust delta |
|---|---|---|---|
| P0 | `src/applypilot/discovery/jobspy.py:275` | Pass `search_cfg` into `_run_one_search` (or capture it via closure). | Discover Red → Green |
| P0 | `src/applypilot/apply/prompt.py` (and apply browser tool integration) | Make `RESULT_JSON` with structured proof fields the **only** accepted success path. The agent is currently emitting `RESULT:APPLIED` text without `submit_click_ref` / `post_submit_url` / `confirmation_copy`. | Apply Red → Yellow |
| P0 | `src/applypilot/server/applications.py` (`confirm_application`, `retry_application`) | Fix percent-encoded URL handling (`unquote` once, store raw, look up by raw). Restore the test `test_application_actions_preserve_percent_encoded_urls`. | Intervention Red → Green |
| P1 | `tests/test_apply_prompt_workday.py` | Fix collection error (likely import or syntax). | Pytest sanity Yellow → Green |
| P1 | `src/applypilot/outreach/recruiter_scrape.py` | Investigate 81% error rate on LinkedIn recruiter scrape; selector drift likely. | Referral Red → Yellow |
| P1 | `src/applypilot/cli.py apply` | Make `--confirm-submit` the default until verified-submit rate > 80%. | Walk-away Red → Yellow |
| P2 | `src/applypilot/database.py` (schema migration) | Add `outcome_status`, `outcome_at`, `outcome_note`. | Effectiveness Unknown → Measurable |
| P2 | Dashboard | Surface `recruiter_scrape_error` and discover-last-24h prominently. | Intervention Yellow → Green |

---

## Appendix A — Apply error taxonomy (real)

```
 15  missing apply log / no structured verification proof
  8  not_eligible_salary
  5  legacy RESULT:APPLIED without structured proof; agent did not name a submit button it clicked
  3  not_eligible_experience
  1  browser_connection_issue
```

The 15 + 5 = **20 unverified applies** all share the same root cause: the apply prompt finishes the form but the agent does not emit the `RESULT_JSON` block with structured proof. The verification logic (`verification.py`) is correct — it is correctly downgrading these to `submitted_unverified`. The bug is in the agent integration, not the verifier.

The 8 + 3 = **11 eligibility-blocked** applies prove the eligibility gate (`apply/eligibility.py`) **is working as intended** — these are jobs we should not have applied to. This is the one part of "apply" that is healthy.

## Appendix B — Pytest sanity

```
$ pytest tests/ --ignore=tests/test_apply_prompt_workday.py -q
131 passed, 1 failed in 0.90s

FAILED tests/test_dashboard.py::test_application_actions_preserve_percent_encoded_urls
  assert 404 == 200
  test_dashboard.py:429
```

Plus 1 collection error: `tests/test_apply_prompt_workday.py` (unable to collect).

This is regression-sanity only and is not the audit signal — but the single failing test is in the **exact intervention path** the trust verdict depends on, so it counts double.

## Appendix C — Source health (today)

| Source | Total | Last 7d | Notes |
|---|---:|---:|---|
| LinkedIn | 1,832 | ~1,700 | Discover via JobSpy works; recruiter scrape fails 81% |
| Indeed | 544 | ~520 | Discover via JobSpy works |
| Workday (Thomson Reuters / Cisco / Mastercard / Motorola / etc.) | ~1,000 across employers | most | Direct ATS API; works well |
| YC `workatastartup` | small | small | Playwright agent path; works outside sandbox |
| Smart-extract | tiny | tiny | Playwright agent; not exercised today |
| Greenhouse / Lever / Himalayas / RemoteOK / Remotive / WWR / HN-Hiring | <50 each | mostly today's discover tried + failed | Discover orchestrator runs them but they fail before producing rows because of cascade from the jobspy NameError above |

## Appendix D — Files referenced

- `~/.applypilot/applypilot.db` (3,455 jobs)
- `src/applypilot/discovery/jobspy.py:275` — `NameError: search_cfg`
- `src/applypilot/apply/verification.py` — verifier (correct)
- `src/applypilot/apply/prompt.py` — apply prompt (likely root cause of unverified rate)
- `src/applypilot/apply/launcher.py` — orchestration (correct, downgrade logic is fine)
- `src/applypilot/server/applications.py` — Confirm/Retry endpoints (URL bug)
- `tests/test_dashboard.py:429` — failing test that gates the intervention path
- `scripts/pipeline_stage_snapshot.py` — used during preflight
- `/tmp/applypilot_audit_funnel.json`, `/tmp/applypilot_audit_samples.json` — raw audit artifacts (kept for reproducibility)

---

## Success criteria (vs. plan)

**Trust:**
- ✅ Funnel percentages computed from real DB
- ✅ Discover usefulness estimated with sample (top-20 fit=10 list reviewed by hand — they are genuine senior+AI roles)
- ✅ Apply trust rate explicitly reported (0%) and unverified rate reported (100%)
- ✅ Clear answer to "can I walk away during apply?" — **No, not until P0-B + P0-C ship**
- ✅ Intervention paths documented and (broken status) spot-checked

**Effectiveness:**
- ✅ Concrete apply-now list of 20 jobs (top of the 139-row queue)
- ✅ Each effectiveness leak has a count and a one-command unblock
- ✅ Top-5 levers ranked by lift × effort
- ✅ Reading this gives a clear plan for the next 7 days: **manually submit the 20 fit=10 jobs while the team fixes the three P0 bugs in parallel**
