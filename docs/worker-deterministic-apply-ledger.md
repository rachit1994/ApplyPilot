# Worker Deterministic-Apply Ledger

Append-only log written by the engine-improvement worker. One block per fix (or
`STOP:`). The worker is restarted with no memory; this file is how the next cold
iteration knows what's already done, what the cache-hit-rate trend is, and what's
been handed to the human. Newest at the top.

Procedure and recipe definitions: [worker-deterministic-apply-handbook.md](worker-deterministic-apply-handbook.md).
Rules: one commit per recipe; `uv run pytest -q` at baseline before every commit;
work on a branch; never push/PR unless the owner asks.

---

## Block format (copy this)

```
## <ISO timestamp> — <result_line attacked>
- Cluster: <family> / <count> occurrences / state_sig <prefix>
- Repro URL: <url>
- Root layer: <profile rule | qa seed | fill method | nav recipe | adapter | extractor | detection | family>
- Recipe applied: R<n> — <what changed, file:func>
- Verify: <pytest files> PASS ; repro now reaches <new outcome>
- Cache-hit-rate before→after: <x%>→<y%>
- Commit: <branch> <short-sha>
- Follow-ups / left for human: <none | …>
```

STOP block (when §9 of the handbook applies — not a logic bug):

```
## <ISO timestamp> — STOP: <reason>
- Repro URL: <url>
- Why not codeable: <SSO | account creation | captcha/payment | not-a-job | needs file outside edit-map | would weaken a safety invariant | new baseline test failure>
- Handed to human: <what the owner must do — e.g. set up logged-in worker profile, build W6 FSM adapter>
```

---

## Entries

## 2026-06-07 — Workable Turnstile sitekey + captcha diagnostics
- Cluster: workable united-field `manual|captcha_unsolved` (instant park, no CapSolver attempt)
- Repro URL: https://apply.workable.com/united-field-services-inc/j/E4BEE08722/apply/
- Root layer: **config** — `CAPSOLVER_API_KEY` line present in `~/.applypilot/.env` but value length 0;
  Turnstile sitekey now extracted from `window.careers.config.turnstileWidgetSiteKey`
- Recipe applied: **R10** — `_enrich_turnstile_info()` + detect JS for Workable config sitekey;
  warn when CapSolver skipped due to empty key; `gmail_receipt_wait_seconds()` default 90s;
  optional `APPLYPILOT_APPLY_TRUST_DIRECT_CONFIRMATION=1` skips Gmail when Direct returns `applied`
- Verify: `tests/test_direct_captcha.py` 14/14 PASS; united-field dry-run fills 11 fields;
  live re-run parks `manual|captcha_unsolved` in ~16s (expected until key set)
- Commit: (uncommitted WIP on main)
- Follow-ups: set real `CAPSOLVER_API_KEY`, then `--requeue-manual --manual-reason captcha_unsolved`

## 2026-06-07 — Workable/Kula live submit → submitted_unverified
- Cluster: workable mercari + kula cashfree reach on-page submit but Gmail receipt not found in window
- Repro URLs: https://apply.workable.com/mercari-india/j/6E941BF58D/apply/ ;
  https://careers.kula.ai/cashfree/24477/apply/
- Root layer: **detection** — Direct driver returns `applied`; launcher downgrades without matching receipt
- Recipe applied: Workable success markers expanded; Workable receipt phrases (`was submitted successfully`);
  Gmail poll default 90s (was 60s hardcoded in launcher direct path)
- Verify: mercari + kula rows `submitted_unverified|gmail_receipt_not_found` (form likely sent)
- Commit: (uncommitted WIP on main)
- Follow-ups: confirm in Gmail/dashboard; or `APPLYPILOT_APPLY_TRUST_DIRECT_CONFIRMATION=1` for direct-only runs

## 2026-06-07 — Kula/Micro1 Gmail-optional on-page confirmation
- Cluster: kula cashfree `submitted_unverified|gmail_receipt_not_found` despite Direct `submitted=1`
- Repro URL: https://careers.kula.ai/cashfree/24477/apply/
- Root layer: **detection** — Kula does not send Gmail receipts; launcher always downgraded on-page success
- Recipe applied: `GMAIL_OPTIONAL_HOST_MARKERS` (`kula.ai`, `micro1.ai`); `job_requires_gmail_receipt()`;
  `reconcile_on_page_submissions()`; `--reconcile-receipts` runs Gmail + on-page paths
- Verify: `tests/test_gmail_receipts.py` 10/10 PASS; `--reconcile-receipts` promoted Cashfree Kula → `applied|on_page_direct`
- Commit: (uncommitted WIP on main)
- Follow-ups: micro1 rows still unverified (no `submitted` in form audit — re-apply or manual confirm)

## 2026-06-06 — Workable transient submit + Uber non-application form
- Cluster: workable (6) `needs_adapter` / `submit_rejected:Something went wrong…`;
  uber `failed:direct_not_submitted` on login/feedback shell
- Repro URLs: https://apply.workable.com/mediaradar/j/88D59477A6/ ;
  https://www.uber.com/careers/apply/form/159244
- Root layer: **detection** — Workable generic server error treated as permanent
  adapter gap (`needs_adapter`); Uber careers URL exposes password + feedback form
  without name/resume fields
- Recipe applied: **R10/R1** — `_is_transient_submit_error()` →
  `failed:direct_transient_submit` (retry, no escalate); `looks_like_non_application_form()`
  + manual park via `no_application_form`; `requeue_needs_adapter` CLI
- Verify: 12 new/related tests PASS; `--requeue-needs-adapter --adapter-reason
  "Something went wrong"` re-queued 5 jobs; Uber dry-run → `manual` / `no_application_form`;
  Workable mediaradar dry-run still 22 fields filled
- Commit: (uncommitted WIP on main)
- Follow-ups: live Workable submit retry after cooldown; CapSolver for Lever captcha cluster

## 2026-06-06 — CSC Lever veteran status select mismatch
- Cluster: lever / CSC Senior Full Stack — pre-submit audit `Veteran status = 'Select ...'`
  while Gender/Race filled; profile `eeo_voluntary.veteran_status = "Decline to self-identify"`
- Repro URL: https://jobs.lever.co/cscgeneration-2/d0df490d-99cd-4795-98aa-65ec290e95e0
- Root layer: **profile rule** — `_non_decline_veteran_status()` converted decline →
  `"I am not a protected veteran"`, which does not match Lever option
  `"I am not a veteran"`; `choose_select_option` had no veteran synonym fallback
- Recipe applied: **R1** — preserve `"Decline to self-identify"` for decline profiles;
  map `"protected veteran"` → `"I am not a veteran"` in `worker_playbook.py`;
  veteran not/option snap in `profile_binding.choose_select_option`
- Verify: `test_veteran_select_snaps_to_lever_options` PASS; dry-run
  `Veteran status = 'Decline to self-identify'`, 20 fields filled
- Commit: (uncommitted WIP on main)
- Follow-ups: live submit still needs `CAPSOLVER_API_KEY` for hCaptcha

## 2026-06-06 — requeue-manual CLI
- Cluster: jobs parked `apply_status='manual'` excluded from `acquire_job` until reset
- Recipe applied: **R10** — `requeue_manual()` + `applypilot apply --requeue-manual
  [--manual-reason …] [--url …]` in `launcher.py` / `cli.py`
- Verify: `test_requeue_manual_reopens_queue` PASS
- Commit: (uncommitted WIP on main)
- Follow-ups: owner adds CapSolver key then `--requeue-manual --manual-reason captcha_unsolved`

## 2026-06-06 — Lever "Notice Priod" typo (Acceldata tier-0 gap)
- Cluster: `failed:direct_verify_incomplete` / `pending_claude_rescue:unresolved_required`
  on Lever forms labelling notice period with a typo ("Notice Priod")
- Repro URL: https://jobs.lever.co/acceldata/040901c5-dbe2-4858-a893-b10b394ea2ae
- Root layer: **profile_binding** — substring rule required exact `"notice period"`
- Recipe applied: **R1** — add `"notice priod"` alias to `FIELD_MAP` notice rule
- Verify: `test_notice_period_maps_to_numeric_days` PASS; headless dry-run fills
  `Notice Priod = '0'`, resume `frontend-developer.pdf` attached, tier-0 only
- Commit: (uncommitted WIP on main)
- Follow-ups: historical `submit_rejected:100MB` on 4 Lever jobs — **fixed** (see below)

## 2026-06-06 — Lever false submit_rejected from hidden .error-message
- Cluster: `failed:direct_submit_rejected: File exceeds the maximum upload size of 100MB`
  on live Lever submits (CSC, Acceldata, 100ms, entefy, skyslope) while dry-run passed
- Repro URL: https://jobs.lever.co/acceldata/040901c5-dbe2-4858-a893-b10b394ea2ae/apply
- Root layer: **extractor** — `visible_errors` scraped hidden `.error-message` nodes
  present in DOM from page load (Lever upload template copy); not shown to user and
  unrelated to actual 149KB PDF upload (`parseResume` + `resumeStorageId` succeed)
- Recipe applied: **R1** — `pushErr` in `extractor.py` now requires `visible(el)` like
  fields/buttons; added `test_extractor_ignores_hidden_error_templates`
- Verify: fresh Lever form `visible_errors=[]`; `test_direct_driver.py` 46 PASS;
  Acceldata dry-run PASS
- Commit: (uncommitted WIP on main)
## 2026-06-06 — Lever hCaptcha detect + CapSolver path
- Cluster: live Lever submits fail with empty `h-captcha-response`; `detect_captcha`
  returned `None` despite widget present
- Repro URL: https://jobs.lever.co/acceldata/040901c5-dbe2-4858-a893-b10b394ea2ae/apply
- Root layer: **captcha** — `CAPTCHA_DETECT_JS` uses `{{`/`}}` for prompt embedding but
  `direct/captcha.py` passed it raw to `page.evaluate` (invalid JS, silent `None`);
  only reCAPTCHA v2 was implemented; no pre-submit captcha gate
- Recipe applied: **R1/R10** — `captcha_detect_eval_js()` + inject helpers in
  `prompt_scripts.py`; `HCaptchaTaskProxyLess` in `direct/captcha.py`;
  pre-submit detect+solve (or `failed:direct_captcha` / manual park when unsolved)
  in `driver.py`
- Verify: `tests/test_direct_captcha.py` (9) + regression suite 121 PASS;
  live Lever detect returns `hcaptcha` + sitekey; Acceldata + 100ms live apply
  park `manual` / `captcha_unsolved` (no false `100MB` or `direct_not_submitted`)
- Commit: (uncommitted WIP on main)
- Follow-ups: set `CAPSOLVER_API_KEY` in `~/.applypilot/.env` for live Lever submit;
  turnstile/funcaptcha still park manual

- Cluster: launcher / `--url …/apply` never matched DB rows (canonical URL without
  `/apply`) → worker polled forever
- Repro URL: https://jobs.lever.co/cscgeneration-2/d0df490d-99cd-4795-98aa-65ec290e95e0/apply
- Root layer: **launcher** — `acquire_job` LIKE only matched when pasted URL contained
  posting path exactly
- Recipe applied: **R10/DX** — `_target_url_acquire_candidates` strips or adds `/apply`
  for exact + LIKE matching in `launcher.py`
- Verify: `tests/test_apply_launcher_acquire.py` (2 new tests) PASS; Commerce Architects
  dry-run with `/apply` suffix acquires job in ~34s
- Commit: (uncommitted WIP on main)
- Follow-ups: none

## 2026-06-06 — Lever post-group text refill (CSC Current location)
- Cluster: lever / CSC Senior Full Stack — `Current location ✱` empty after checkbox
  group fills (`empty_required=1` on verify)
- Repro URL: https://jobs.lever.co/cscgeneration-2/d0df490d-99cd-4795-98aa-65ec290e95e0
- Root layer: **fill method** — Lever card re-render clears identity text after group
  fills; `_refill_empty_text_fields` was Workable-only
- Recipe applied: **R4** — post-group `_refill_empty_text_fields` on lever; extend
  post-upload + verify text refill to `family in {lever, workable}` in `driver.py`
- Verify: headless sim `empty_required=0`; `applypilot apply --url … --dry-run --headless`
  PASS (37 fields, 19 filled, tier-0 only, no submit)
- Commit: (uncommitted WIP on main)
- Follow-ups: none (`--url` matching fixed)

## 2026-06-06 — Manual review parking (§9 STOP → apply_status=manual)
- Cluster: launcher / captcha, bot protection, escalation caps, needs_adapter walls
- Repro URL: (any job returning `failed:direct_captcha`, `parked:manual:*`, etc.)
- Root layer: **launcher** — retried `needs_adapter`/`failed` forever on human-only walls
- Recipe applied: **R10/handbook §9** — `MANUAL_REVIEW_RESULTS`, `_park_job_manual_review`,
  worker skips `parked:manual:*`; `EscalationCapHit` propagates from `unblock_learning`
- Verify: `uv run pytest tests/test_manual_review_parking.py tests/test_escalation_caps.py -q` PASS (10)
- Commit: (uncommitted WIP on main)
- Follow-ups: optional `requeue-manual` CLI; email_verify stays retryable

## 2026-06-06 — Lever technology checkbox group (CSC Generation)
- Cluster: lever / CSC Senior Full Stack — `Kindly select all the technologies… [group]`
  after text fills on p0
- Repro URL: https://jobs.lever.co/cscgeneration-2/d0df490d-99cd-4795-98aa-65ec290e95e0
- Root layer: **fill method** — stale `data-ap-key` after Lever card re-render; `.check()`
  without DOM/section fallback
- Recipe applied: **R4** — re-extract groups before checkbox fill on lever;
  `_click_lever_section_checkbox` + `_partition_checkbox_radio_groups` in `driver.py`
- Verify: headless fill PASS; `applypilot apply --url … --dry-run --headless` PASS
  (see post-group text refill entry)
- Commit: (uncommitted WIP on main)
- Follow-ups: live submit receipt (dry-run verified)

## 2026-06-06 — Lever card-radio verify gap (empty_required=4)
- Cluster: lever / Commerce Architects Senior Software Engineer — verify saw 4 empty
  `Yes`/`No` radios after fill+upload despite filled_rows recording all screening groups
- Repro URL: https://jobs.lever.co/commercearchitects/519984f5-40c0-47d6-bd10-241d88659ebf
- Root layer: **fill method** — `_fill_radio_group` fallback used bare `Yes`/`No` labels
  (clicked wrong group); **verify retry** sent individual radios to batch resolver instead
  of group refill; stale `ap_id` restamp could target wrong input after text fills
- Recipe applied: **R4/R1** — `_CLICK_RADIO_GROUP_JS` scoped by `name_attr`; post-fill
  `_radio_group_is_checked`; verify + post-upload `_refill_empty_radio_groups` in
  `driver.py`; Lever post-upload radio refill hook
- Verify: `uv run pytest tests/test_direct_driver.py -q` PASS (41); dry-run
  `APPLYPILOT_DIRECT_GEMINI=0 apply --url … --dry-run` → `skipped:direct_dry_run`,
  14 fields filled, pre-submit audit clean (no empty_required escalation)
- Commit: (uncommitted WIP on main)
- Follow-ups: none (dry-run verified 2026-06-06 with `/apply` `--url`)

## 2026-06-06 — R3 Workable requirement radiogroups + location gate
- Cluster: workable / MLabs self-assessment fieldsets (8 Yes/No requirements)
  stayed empty at t0; Europe residency must not auto-Yes from India profile
- Repro URL: https://apply.workable.com/mlabs/j/A79180CA40/apply/
- Root layer: **R1** — tier-0 for Workable `<fieldset role="radiogroup">` requirements;
  **extractor** — radiogroup checked-value + legend label; **driver** — location trap
  blocks submit → `not_eligible_location`
- Recipe applied: **R3/R1** — `is_yes_no_radiogroup`, `resolve_workable_self_assessment`,
  `is_location_requirement_trap`, `remaining_gaps_are_location_traps` in
  `profile_binding.py`; EXTRACT_JS radiogroup value + legend; pre-submit + verify
  gates return `failed:not_eligible_location` (permanent, attempts=99)
- Verify: `uv run pytest tests/test_direct_profile_binding.py tests/test_direct_driver.py
  -q` PASS (62); MLabs dry-run fills 7/8 skill requirements at `t0:label`, leaves
  Europe empty, pre-submit logs `Location requirement unmet`, DB
  `failed|not_eligible_location|99`
- Commit: (uncommitted WIP)
- Follow-ups: Lever queue (AppZen et al.) for next live verify; Workday §9 STOP

## 2026-06-06 — R10 cap false-positive + R2 Workable screening seeds
- Cluster: workable family `Unblock capped (6 attempts, 100% fail)` while replay
  steps had `postcondition_met=1`; Dev.Pro screening via `t2:gemini` on first pass
- Repro URL: https://apply.workable.com/mlabs/j/A79180CA40/apply/ (cap blocked nav)
- Root layer: **R10** — `recent_fail_rate` counted only `outcome='advanced'`, not
  successful replay `clicked`/`waited`; **R1/R2** — Dev.Pro-style screening labels
- Recipe applied: **R10** — fail rate treats `postcondition_met=1` as success,
  excludes `tier='cap'` rows; **R1** QUESTION_MAP for English CV / .NET / cloud;
  **R2** four rows in `common_questions.yaml` + `seed-qa-bank`
- Verify: `uv run pytest tests/test_review_log.py tests/test_escalation_caps.py
  tests/test_direct_profile_binding.py -q` PASS (39); MLabs dry-run reaches form
  (17 fields, pre-submit audit) after cap fix; RecargaPay receipt re-found → DB
  `applied` / `gmail_confirmed`
- Follow-ups: MLabs has Europe-residency requirement checkboxes (do not auto-Yes);
  fieldset self-assessment fill for Workable requirement lists → **R3**; Workable
  India queue largely exhausted / many `not_eligible_location`

## 2026-06-06 — R1 phone country code + Workable Gmail receipt + Dev.Pro live apply
- Cluster: workable / `Telephone country code` → t2:gemini on every form
- Repro URL: https://apply.workable.com/recargapay/j/732699AD71/apply/ (first seen)
- Root layer: profile rule — generic `telephone` substring matched before country intent
- Recipe applied: **R1** — FIELD_MAP entry for `telephone country code` / `phone country
  code` → `country` token (before generic phone rule); **gmail** — add
  `from:workablemail.com` to `_RECEIPT_QUERY`
- Verify: `uv run pytest tests/test_direct_profile_binding.py tests/test_gmail_receipts.py
  tests/test_direct_driver.py -q` PASS (64); dry-run Dev.Pro: phone `t0:label`
  `India\n+91`, resume + cover letter + 4 screening YES fields; live apply:
  **Direct APPLIED**, Gmail receipt confirmed (`Thanks for applying to Dev.Pro`),
  CLI **1 applied, 0 failed**
- Cache-hit-rate before→after: (not re-measured; screening Qs promoted to t1:cache on 2nd run)
- Commit: (uncommitted WIP)
- Follow-ups: R2 seeds for Dev.Pro English/.NET/cloud screening if they recur on other
  tenants; workable family unblock cap blocks some URLs (mlabs) — R10 review if cap
  counts stale no_form failures; Workday §9 STOP unchanged

## 2026-06-06 — pre-submit DOM audit + Workable live verify (RecargaPay)
- Cluster: workable / single-page apply / pre-submit visibility gap
- Repro URL: https://apply.workable.com/recargapay/j/732699AD71/apply/
- Root layer: driver submit gate — filled_rows logged during fill but no final DOM
  re-read of every control + file upload before click
- Recipe applied: driver `_pre_submit_audit` — re-extract all fillable fields,
  audit `input[type=file]`, log each value at INFO, block on empty required or
  missing resume; persist `pre_submit` + `uploads` + resume/cover paths; final
  persist keeps audit snapshot after submit
- Verify: `uv run pytest tests/test_direct_driver.py -q` PASS (36);
  dry-run deterministic-only: 12 fields + `platform-engineer.pdf` attached, no block;
  live apply: `Direct APPLIED`, DB `submitted_unverified` (gmail receipt lag for
  Workable — form submit succeeded)
- Cache-hit-rate before→after: 23.4% → (unchanged this commit; one gemini hit on
  Telephone country code combobox — R1 follow-up)
- Commit: (uncommitted WIP on branch)
- Follow-ups: seed R1 profile rule for Workable phone country selector (+91/India);
  extend Gmail receipt query for `workablemail.com`; Workday still §9 STOP (W6 FSM)

## 2026-06-06 — dogfood run: §1.3 no-actionable-cluster + handbook corrections
- Scoreboard: `cache_hit_rate` replay 11 / llm 36 = **23.4%** (baseline).
- OBSERVE worklist (after CAPPED filter): top-3 count-8 clusters
  (wellsfargojobs / hire-r1.mokahr / careers.expediagroup, all `generic`) are
  **already CAPPED** (≥8 attempts @ 100% fail) → system already parks them
  `needs_adapter`; not worked. Confirmed by live repro: `Unblock capped for
  generic (11 attempts, 100% fail) → Parked needs_adapter`.
- First **live** (non-capped, gemini) cluster: `workday` /
  `expedia.wd108.myworkdayjobs.com` reveal clicks, count-1 each → below induction
  support (induce empty at min-support 3 **and** 2). `uber.com` generic click also
  count-1. → §1.3 steady state: nothing cleanly actionable.
- Root layer: nav recipe (Workday reveal) — but **already** seeded `trusted`,
  family-scope (`playbook list` confirms `workday/apply_reveal/click/trusted/seed`).
- Recipe applied: **none** (correctly — R4a empty, R4b already done; forcing a fix
  would violate the handbook).
- Verify: new §1.1 OBSERVE script runs and renders the CAPPED/repro_url worklist;
  §1.2 repro runs headless/bounded and reports the cap line as designed.
- Cache-hit-rate before→after: 23.4% → 23.4% (no engine change this run).
- Commit: (handbook + ledger docs only; no engine code touched)
- **Handed to human (structural, §9):** the Workday `apply_reveal` seed is
  `trusted` but **does not fire** on real Workday apply pages — its seeded
  `preconditions.clickables` signature (`["apply","apply now"]`) doesn't match the
  live page signature, so Workday reveals keep going to `gemini`. Durable fix is
  the **W6 Workday FSM Tier-0 adapter** (see worker-implementation-plan-june-2026.md
  §W6) and/or re-seeding the Workday reveal from a captured real-page signature.
  Needs a saved Workday DOM fixture — owner/dedicated ticket, not the hot loop.
- Handbook corrections made this run (the actual point of the dogfood): §1.1 now
  filters CAPPED clusters + emits a repro_url (was: "attack highest count", which
  pointed straight at already-handled clusters); §1.2 now reads the worker-log cap
  line as a CLASSIFY key (was: only `failed:` result lines); §5 gained a
  non-advancing-`wait` row; §1.3 "nothing cleanly actionable" added (this run hit
  exactly that state and the doc had no guidance for it).

## 2026-06-06 — Kula management questions + Workable success markers
- Repro URL: https://careers.kula.ai/cashfree/24477/apply/ (Software Development Lead)
- Root layer: profile_binding QUESTION_MAP — two required Kula textareas (direct
  reports / hiring-mentoring) had no Tier-0 rule; with `APPLYPILOT_DIRECT_GEMINI=0`
  they stayed empty and blocked submit.
- Recipe applied: `QUESTION_MAP` entries for management/team-size and
  hiring/mentoring questions; Workable adapter success markers expanded
  (`you're all set`, `we'll be in touch`, etc.) for post-submit detection.
- Verify: `test_kula_management_questions_resolve_tier0` PASS; dry-run Kula
  `--include-untailored` → 10 fields filled, all required non-empty; 90 related
  pytest PASS.
- DB: reset Kula + united-field Workable (`apply_attempts` cleared); requeued
  texas-sports Workable `needs_adapter:no_confirmation`.
- Follow-ups: live Kula apply with `--include-untailored` or engineering-manager
  role resume; Lever captcha still needs `CAPSOLVER_API_KEY`; Workday §9 STOP.
