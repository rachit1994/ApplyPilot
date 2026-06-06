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
