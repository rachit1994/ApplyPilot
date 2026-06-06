# Direct Apply — Hardening Tasks to Reach Cost-Effective 200–300 Applies/Day

**Audience:** worker LLMs implementing code. The design/decisions below are settled —
your job is to implement, test, and verify. Do not redesign without a stated reason.

**Goal of this work:** raise the deterministic ($0-Claude) Direct Apply engine's
*self-sufficiency* so the escalation-to-Claude rate falls toward <5%, making
200–300 applies/day affordable. Today the engine works on "clean" Greenhouse
forms but escalates (or parks) on anti-bot walls, a few field types, and any ATS
other than Greenhouse. Each Claude escalation costs ~$0.15 and burns Claude
quota, so every job the deterministic engine can finish itself is pure margin.

---

## 0. How to use this document

- Tasks are independent unless a dependency is stated. Suggested order: **T1, T2,
  T5, T6** first (highest volume/cost leverage), then **T3, T4** (more ATS
  families), then **T7, T8** (long-tail fields).
- Each task has: **Problem → Evidence → Root cause → Files → Design →
  Acceptance → Tests → Risks.** Implement to the Acceptance criteria; add the
  Tests; keep `ruff` clean.
- After each task, run the existing suite (see §2) and the live smoke test for
  the relevant ATS.

---

## 1. System overview — what exists and what already works

The Direct Apply engine lives in `src/applypilot/apply/direct/`. It connects to
the worker's headed Chrome over CDP and fills/submits ATS forms deterministically.
Claude is the *rescue tier* only.

**Confirmed working (real submissions, $0 Claude, screenshots verified):**
- Native Greenhouse (`job-boards.greenhouse.io/<co>/jobs/<id>`) — e.g. Anthropic.
- Custom-domain Greenhouse (`careers.datadoghq.com/...?gh_jid=`, Airbnb) — via an
  embed-URL rewrite to `boards.greenhouse.io/embed/job_app?token=<gh_jid>`.
- react-select comboboxes (Yes/No screening, country, etc.), phone in E.164 with
  intl-tel country detection, resume upload, success/rejection detection.

**Engine flow** (`direct/driver.py::apply_via_direct`):
1. `_canonical_apply_url(url, family)` → rewrite custom-domain Greenhouse to the embed form.
2. `page.goto`, detect expired markers, `_reveal_form` (click "Apply" if the form isn't present).
3. `extractor.extract_fields(page)` → `FormState` of `Field`s (stamps `data-ap-key`).
4. Split fields: `file` (upload), `combobox` (react-select), `regular` (text/select/checkbox).
5. `resolver.resolve(regular, tokens)` → answers; fill each. Comboboxes filled one-by-one via `_fill_combobox` (open → read live options → resolve → click).
6. Upload resume/cover. Verify no required non-combobox field is empty.
7. Detect email-verification wall; submit; classify result (applied / rejected / not_submitted / needs_verification) with a screenshot.
8. Record `apply_outcomes` row + persist `apply_form_filled` (per-company field values shown in the dashboard).

**The Resolver tiers** (`direct/resolver.py`): `override:user` (DB corrections) →
Tier-0 profile rules (`profile_binding.py`) → Tier-1 Q&A cache (`qa_bank.py`) →
Tier-2 one Gemini batch call for required leftovers. `choose_select_option`
snaps answers to real options (exact → startswith → word-boundary → option-in-answer → substring).

**Escalation** (`launcher.py::_try_direct_apply`): runs the driver in a daemon
thread under a hard wall-clock timeout (`apply_settings.direct_job_timeout`,
default 100s; on timeout it kills Chrome on the port to free the orphan and
*parks*, escalate=False). A clean direct failure with `escalate=True` returns
`None` so `_run_job_with_optional_fallback` falls through to the Claude path —
only when `APPLYPILOT_DIRECT_ESCALATE=1`.

---

## 2. Ground rules (READ BEFORE CODING)

**Database safety (non-negotiable — from `AGENTS.md`):** never wipe/mutate the
live DB (`~/.applypilot/applypilot.db`). For any test or experiment that writes,
set an isolated dir first:
```bash
export APPLYPILOT_DIR=$(mktemp -d)
```
Never `DELETE/DROP/TRUNCATE` the user DB. The reusable test fixture pattern is in
`tests/test_dashboard.py` (`temp_db`).

**Iron rule of the engine:** *never submit on uncertainty.* If a required field
can't be resolved or a form can't be confirmed, return a `failed:direct_*`
result with `escalate=True` (so Claude can rescue) — never click submit with a
wrong/half-filled form. A wrong submission to a real employer is a permanent
quality defect; an escalation costs one retry.

**Quality checks:**
```bash
uv run ruff check src/applypilot/apply/direct/
APPLYPILOT_DIR=$(mktemp -d) uv run pytest tests/test_direct_driver.py \
  tests/test_direct_resolver.py tests/test_direct_profile_binding.py -q
```

**Run ONE apply for live verification** (visible-form companies that pass the
India/H1B eligibility gate: Anthropic, Datadog, Airbnb; remote/India roles):
```bash
# dry-run fills but does NOT submit (safe):
applypilot apply --engine direct --dry-run --include-untailored --plain --limit 1 \
  --url "<application_url>"
# real submit:
applypilot apply --engine direct --include-untailored --plain --limit 1 --url "<url>"
```
Inspect evidence: the post-submit screenshot path is logged
(`~/.applypilot/logs/direct_*.png`) and the outcome is in `apply_outcomes`
(`sqlite3 ~/.applypilot/applypilot.db "SELECT * FROM apply_outcomes ORDER BY id DESC LIMIT 1"`).
The per-company filled values are in `jobs.apply_form_filled` (JSON).

**Connecting to the worker's Chrome in a throwaway script** (for DOM inspection):
```python
from applypilot.apply import chrome
proc = chrome.launch_chrome(0, port=9222, headless=True); import time; time.sleep(3)
from playwright.sync_api import sync_playwright
pw = sync_playwright().start()
b = pw.chromium.connect_over_cdp("http://127.0.0.1:9222", timeout=20000)
pg = b.contexts[0].new_page(); pg.set_default_navigation_timeout(45000)
# ... pg.goto(...), inspect ...
pw.stop(); chrome.cleanup_worker(0, proc)
```
Always `lsof -ti :9222 | xargs -r kill -9` between runs.

---

## 3. Code map

| File | Responsibility |
|---|---|
| `direct/driver.py` | State machine `apply_via_direct`; `_canonical_apply_url`, `_fill_field`, `_fill_combobox`, `_read_open_options`, `_MARK_COMBO_JS`, submit/verify detection, `_persist_form_filled`, `_screenshot` |
| `direct/extractor.py` | `EXTRACT_JS` (stamps fields, reads label via `aria-labelledby`, flags `combobox`), `FormState`, `parse_form_state` |
| `direct/profile_binding.py` | `Field` dataclass; `FIELD_MAP`/`ATTR_MAP`/`QUESTION_MAP` (Tier-0 rules); `choose_select_option` |
| `direct/resolver.py` | `resolve()` tier orchestration; `_user_override`; `_gemini_batch` (Tier-2) |
| `direct/qa_bank.py` | Tier-1 SQLite answer cache |
| `direct/fingerprint.py` | `ats_family(url)`, `apex_domain(url)`, `ADAPTER_FAMILIES` |
| `direct/throttle.py` | `check_caps(url)` per-family/per-domain daily caps from `apply_outcomes` |
| `direct/adapters/__init__.py` | `get_adapter(family)`; `_REGISTRY` (dispatched: greenhouse) + `_STAGED` (lever, ashby — built, NOT dispatched) |
| `direct/adapters/{base,greenhouse,lever,ashby}.py` | `Adapter` descriptors (apply/submit button texts, success/expired markers) |
| `apply/launcher.py` | `_try_direct_apply` (thread+timeout, records outcome, escalation), `_run_job_with_optional_fallback`, `acquire_job` + `acquire_job_order_sql` + `_acquirable_jobs_where`, `mark_result`, `worker_loop` |
| `apply/apply_settings.py` | `apply_engine`, `direct_escalate_to_claude`, `max_per_ats_family_per_day`, `max_per_apex_domain_per_day`, `direct_job_timeout`, `direct_gemini_enabled` |
| `apply/gmail_auth.py` | Gmail REST read: `_access_token()`, `_headers()`, `_search_messages(query, limit)`, `list_recent_messages()`, `search_application_receipt()`; creds at `~/.gmail-mcp/credentials.json` |
| `apply/prompt_scripts.py` | **Already contains** reCAPTCHA detection + CapSolver solve JS (sitekey v2/v3, createTask/getTaskResult, token injection). Reuse for T1 captcha. |
| `database.py` | `record_apply_outcome`, `apply_outcomes` schema, `field_overrides` (`get/set/list/delete_field_override`) |

---

## T1 — Email verification code (+ captcha) in the direct engine  ★ highest leverage

**Problem.** Some employers gate the Submit button behind an emailed
verification code and/or a reCAPTCHA. The deterministic engine can't pass them,
so those jobs park or escalate to Claude (cost). This is the single biggest
driver of escalation rate.

**Evidence.** Airbnb Greenhouse form shows: *"A verification code was sent to
{email}. To submit your application, enter the 8-character code to confirm
you're a human."* + a `Security code` input + reCAPTCHA, with Submit disabled.
The driver currently detects the text (`failed:direct_needs_verification`,
`driver.py`) and escalates.

**Root cause.** No code-reading or captcha-solving in `direct/`.

**Files.** New `direct/email_verify.py`; edit `direct/driver.py`; reuse
`apply/gmail_auth.py` and `apply/prompt_scripts.py`; maybe `apply_settings.py`
(new toggles).

**Design.**
1. **Read the code from Gmail.** New `email_verify.py::fetch_verification_code(
   *, company_hint: str, since_epoch_s: float, max_wait_s: float = 90) -> str | None`.
   - Use `gmail_auth._search_messages(query, limit)` with a Gmail query like
     `newer_than:1h (subject:(verification OR code OR confirm) OR from:greenhouse)`.
     Filter to messages after `since_epoch_s` and matching `company_hint`/ATS sender.
     `gmail_auth` already handles OAuth/refresh — reuse `_access_token`, `_headers`,
     and the message-listing helpers; add a "get full message body" call if the
     summaries don't include the body (the code is in the body/snippet).
   - Extract the code with a configurable regex; default to the form's stated
     length. Greenhouse/Airbnb codes are typically `\b[A-Z0-9]{6,8}\b`. Pull the
     expected length from the field's `maxlength`/label ("8-character") when present.
   - Poll: re-query every ~5s up to `max_wait_s` (the email can lag the form).
2. **Driver integration.** In `apply_via_direct`, when the verification wall is
   detected (the existing `_VERIFY_MARKERS` block):
   - Record the submit-attempt time *before* the code is requested. On some
     forms the code email is sent on page load; on others only after a first
     submit click. Handle both: if no code field is visible, click Submit once
     to trigger the email, then look for the code field.
   - Locate the code input (label contains "security code"/"verification code",
     or `input` near the verification text). Fill the fetched code.
   - Then run the captcha step (below), then Submit, then the normal success
     detection.
   - If the code can't be fetched within `max_wait_s`, fall back to the current
     `failed:direct_needs_verification` (escalate=True). Never submit blank.
3. **Captcha.** Reuse the CapSolver JS already in `prompt_scripts.py`
   (sitekey detection + `createTask`/`getTaskResult` + `g-recaptcha-response`
   injection). Expose it to the driver: `page.evaluate(<that JS>, {api_key})`.
   - Gate on `CAPSOLVER_API_KEY` (already in `.env.example`); if unset, skip
     captcha solving and escalate. **Do not** treat invisible reCAPTCHA v3 as a
     blocker (it submits fine — see the false-positive note in `driver.py`); only
     solve when a v2 checkbox/challenge sitekey is detected.
4. **Settings.** Add `apply_settings.email_verification_enabled()` (default True)
   and `captcha_solving_enabled()` (default = `CAPSOLVER_API_KEY` present).

**Acceptance.**
- A real submit on an Airbnb/Greenhouse job that shows the code wall completes to
  `applied` at $0 Claude (Gemini-only), confirmed by the "Thank you for applying"
  screenshot — without escalating.
- If Gmail creds are missing or the code doesn't arrive in time, the job cleanly
  returns `failed:direct_needs_verification` (escalate=True), never a blank submit.

**Tests.**
- Unit: `fetch_verification_code` regex extraction over saved sample email bodies
  (6- and 8-char codes; pick the most recent; ignore unrelated emails). Mock
  `gmail_auth._search_messages`.
- Unit: code-length inference from field `maxlength`/label.
- Mark live submit as a manual/opt-in smoke (don't auto-submit in CI).

**Risks.** Gmail query false matches (wrong code) → constrain by sender + recency
+ company. CapSolver latency/cost (~$0.001/solve) — acceptable, but cap retries.

---

## T2 — Investigate & fix the Cloudflare / "form still present" + spurious `not_eligible_location`

**Problem.** Cloudflare Greenhouse jobs consistently end `failed:direct_not_submitted`
("form still present" after submit), and several were later marked
`apply_status='failed', apply_error='not_eligible_location', apply_attempts=99`
*after* a direct attempt — which is wrong (they reached the form, so they passed
the eligibility gate at acquire time).

**Evidence.** Overnight log: repeated `Direct NOT confirmed (form still present)
https://boards.greenhouse.io/cloudflare/jobs/...`. DB: `cloudflare/jobs/7793013`
ended `failed | not_eligible_location | 99`.

**Root cause (to confirm).** Two separate bugs likely:
1. *not_submitted:* a required field Cloudflare validates isn't being filled (or a
   custom widget the extractor misses), so submit silently no-ops. Inspect the
   Cloudflare embed form DOM; capture the post-submit `visible_errors` more
   aggressively (Greenhouse renders field errors as `[aria-invalid]` + an error
   node adjacent to the field, which the current `visible_errors` selector may miss).
2. *not_eligible_location with attempts=99:* find where a *direct* attempt can
   lead to `_persist_ineligible_job` / `not_eligible_location`. Likely the job is
   re-acquired on a later pass and the eligibility gate (`eligibility.classify_apply_target`,
   `_filters.location_passes`) is non-deterministic or the location string has
   multiple parts; OR a stale-lock requeue path mislabels it. Trace
   `apply_error='not_eligible_location'` writers (`launcher._persist_ineligible_job`).

**Files.** `direct/driver.py` (error capture), `direct/extractor.py`
(`EXTRACT_JS` error/`aria-invalid` capture), `apply/eligibility.py` +
`discovery/_filters.py` (location gate), `apply/launcher.py` (where 99/not_eligible is set).

**Design.**
- Strengthen post-submit error capture: in `EXTRACT_JS`, also collect text from
  `[aria-invalid="true"]` siblings and Greenhouse's `.field-error`/`*[id$="-error"]`
  nodes; surface as `visible_errors` so `failed:direct_submit_rejected` (with the
  real reason) replaces the vague `not_submitted`.
- Reproduce one Cloudflare job in `--dry-run` and dump which required fields the
  verify step still considers empty (the driver already logs this); fix the
  specific field handling (likely a custom widget or a checkbox group).
- Fix the eligibility mislabel: make `location_passes` deterministic for
  multi-location strings ("Remote - US; London; Bangalore" should pass if ANY
  part passes), and ensure a direct attempt never routes back through
  `_persist_ineligible_job`.

**Acceptance.** A Cloudflare job either (a) applies, or (b) fails with a *specific*
captured reason (`failed:direct_submit_rejected:<error>`), and is never
mislabeled `not_eligible_location` after reaching the form.

**Tests.** Unit for `location_passes` multi-part strings; extractor fixture with
`aria-invalid` error nodes → populates `visible_errors`.

---

## T3 — Ashby adapter (`jobs.ashbyhq.com`)  [currently hangs]

**Problem.** Ashby is staged but NOT dispatched (`adapters/__init__.py::_STAGED`)
because the driver *hangs* on Ashby's DOM (different from Greenhouse react-select).
Ashby has ~30 eligible jobs (OpenAI, Ramp, Harvey, Linear, …).

**Root cause (to confirm).** Ashby uses its own field components, not
`.select__control`/`.select__menu`. `_fill_combobox`/`_read_open_options` are
Greenhouse-specific; on Ashby they may spin or wait on locators that never
resolve. The thread-timeout guard catches it but the job parks.

**Files.** Inspect & implement in `direct/` — likely a small Ashby-specific
combobox/option strategy; `adapters/ashby.py` (already has the descriptor);
register Ashby in `_REGISTRY` once verified.

**Design.**
1. Inspect a live Ashby application form (`jobs.ashbyhq.com/<co>/<id>/application`)
   with the throwaway-script pattern (§2). Identify: how fields are labelled, how
   select/dropdown options are structured, the file-upload input, and the submit
   button + success page ("Thank you for your interest in <co>").
2. Generalize the combobox layer so it dispatches by ATS: keep the Greenhouse
   `.select__*` path; add an Ashby path (Ashby commonly uses native `<select>` or
   `[role=listbox]` with `[role=option]` — confirm). Prefer extending
   `_read_open_options`/`_MARK_COMBO_JS` with Ashby selectors over a parallel code
   path, but a per-family strategy object is acceptable if cleaner.
3. Ensure every locator call has a bounded timeout so Ashby can never hang
   (the thread guard is a backstop, not the primary mechanism).
4. Register `ashby` in `_REGISTRY`.

**Acceptance.** A real Ashby submit (an eligible OpenAI/Ramp role) reaches
`applied` at $0, screenshot-confirmed; no hang (job completes < `direct_job_timeout`).

**Tests.** Saved Ashby DOM fixture → `extract_fields` finds the expected fields;
combobox option read returns the real options (not empty); adapter dispatch test.

---

## T4 — Lever adapter (`jobs.lever.co`)

**Problem.** Lever is staged, not dispatched. (Note: 0 eligible Lever jobs in the
current DB, but the source is enabled — implement for completeness/coverage.)

**Files.** `adapters/lever.py` (descriptor exists), `adapters/__init__.py`,
possibly `direct/driver.py` for the apply-reveal (`/<co>/<id>/apply`).

**Design.** Lever forms are comparatively simple (mostly native inputs + a file
upload; the "Apply for this job" button routes to `/<co>/<id>/apply`). Verify the
apply-reveal navigation, field labels, the resume input, submit button
("Submit application"), and the `/thanks` success page. Register `lever` once
verified.

**Acceptance.** Real Lever submit reaches `applied` at $0 (use a public Lever
test posting or a real eligible one), screenshot-confirmed.

**Tests.** Lever DOM fixture extraction + adapter dispatch.

---

## T5 — Queue diversification (stop one company from dominating a run)

**Problem.** `acquire_job` clusters many roles from the *same company* in a row
(e.g. 12 Airbnb jobs). If that company is hard, a whole run is wasted on it, and
the per-apex-domain cap (25) is hit while other companies go untouched.

**Evidence.** Overnight runs processed 11–12 consecutive Airbnb / Cloudflare jobs.

**Root cause.** `acquire_job_order_sql()` orders by ATS priority, then
`fit_score DESC`, then `url` — which groups a company's jobs together.

**Files.** `apply/launcher.py::acquire_job_order_sql`, `_acquirable_jobs_where`,
`acquire_job`. Reuse `fingerprint.apex_domain`.

**Design.** Add round-robin/fairness across apex domains so the worker spreads
applies across companies:
- Option A (SQL-only, preferred): in the `ORDER BY`, add a leading term that
  deprioritizes domains already heavily attempted *today*, e.g. order by a
  subquery count of today's `apply_outcomes`/attempts for that apex domain
  (ascending), then existing terms. Keep it deterministic and index-friendly.
- Option B: maintain a small in-memory "recently attempted domains" ring in
  `worker_loop` and skip a job whose domain was the last N acquired (re-queue it).
- Respect the per-apex-domain cap (25) as the hard stop; diversification is about
  *ordering*, not raising caps.

**Acceptance.** Over a 30-job run on a mixed queue, no single apex domain accounts
for more than ~`max_per_apex_domain_per_day` attempts, and at least K distinct
companies are attempted (assert K grows vs. the current clustering).

**Tests.** Unit on the ordering/selection given a seeded mixed queue (temp DB):
the first N acquired span ≥ M distinct domains.

---

## T6 — Throttle cap should idle the worker, not mark jobs `failed`

**Problem.** When `throttle.check_caps` returns blocked, `_try_direct_apply`
returns `failed:direct_family_cap`/`direct_domain_cap`, which `worker_loop` marks
as a job **failure** (`apply_attempts += 1`). In `--continuous` mode at the cap,
this churns the queue, penalizing capped jobs (eventually `attempts=3`, lost for
the day) instead of pausing.

**Files.** `apply/launcher.py::_try_direct_apply` (cap branch), `worker_loop`
(result handling), maybe `apply_settings`.

**Design.** Treat a cap hit as *defer*, not *fail*:
- Release the job lock without incrementing attempts (don't call `mark_result`
  with a failure for cap reasons), and either: idle the worker until the next
  family/domain slot or local midnight, or skip to the next acquirable job whose
  family/domain is under cap. A clean approach: have `acquire_job` exclude jobs
  whose family/domain is already at cap (join the same counting logic as
  `throttle`), so the worker naturally moves to under-cap work and idles only
  when everything is capped.
- When the entire eligible queue is capped, the worker should poll/idle (like the
  existing empty-queue path), not spin.

**Acceptance.** In `--continuous` at the family cap, capped jobs are NOT marked
failed and NOT attempt-incremented; the worker applies under-cap work or idles.
Caps still hard-stop submissions at the configured numbers.

**Tests.** Unit (temp DB): seed `apply_outcomes` to the family cap, assert
`acquire_job` returns only under-cap jobs (or None → idle), and that a capped job
is not failure-marked.

---

## T7 — Location/City autocomplete (type-to-search combobox)

**Problem.** Fields like "Location (City)" are react-select **async** comboboxes:
options only appear after typing. `_fill_combobox` opens them, sees zero static
options, returns `error` → `unresolved_required` → escalate/park.

**Files.** `direct/driver.py::_fill_combobox`.

**Design.** When an opened combobox has no options:
- Resolve a *text* value for the field first (treat it as text via
  `profile_binding.resolve_field` on a copy with `tag='input'`, so FIELD_MAP
  `city`/`country`/`location` → token value). If empty, leave/escalate.
- Type that value into the combobox input (`press_sequentially`), wait for the
  async menu, then click the best `_OPTION_SELECTOR` match (or the first option).
  Confirm a selection rendered (a tag/value chip appears).

**Acceptance.** A Greenhouse form with a city autocomplete fills to a real option
and submits; no `unresolved_required` for location on profiles that have a
city/country set.

**Tests.** Driver unit with a fake page exposing type→options behavior (or a saved
fixture); resolver returns the city token for the location field.

---

## T8 — Multi-select comboboxes (select-all-that-apply)

**Problem.** Some fields accept multiple values (`--is-multi` react-select). The
engine picks one option, which is usually sufficient (min-1) but not always
correct. Gemini may also return multiple values (`"English, Hindi"`) —
`choose_select_option` now snaps the first match (good enough for single-select).

**Files.** `direct/driver.py::_fill_combobox`, `direct/extractor.py` (flag
`--is-multi`), `direct/resolver.py`.

**Design.** Detect `select__control--is-multi`; for multi-selects, split the
resolved answer on `[,/;]`/" and " and click each matching option (menu stays
open in react-select multi), then close. For required multi-selects, at least one
valid selection must land.

**Acceptance.** A multi-select required field (e.g. "languages you speak") gets ≥1
valid selection and the form submits.

**Tests.** `choose_select_option` already covered; add a driver-level fixture for
multi-click if feasible.

---

## 9. Definition of done for the overall goal

The engine is "cost-effective 200–300/day capable" when, on a mixed eligible
queue across ≥3 ATS families:
- **Escalation rate < ~5%** (measure: `apply_outcomes` `escalated=1` / total over a
  100-job run), i.e. the deterministic engine finishes ≥95% itself at $0 Claude.
- **No single company dominates** a run (T5) and caps *defer* rather than fail (T6).
- Per-family caps (75) across 4 families give the 300/day headroom; raising
  volume is then a caps/IP-reputation decision, not an engine limitation.

**Measurement harness to add (optional but useful):** a `scripts/` or CLI report
that prints, for the last 24h of `apply_outcomes`: applied / escalated / parked
counts, escalation %, per-family and per-company breakdown, and Gemini+Claude $
from `llm_usage_events`. This is the dashboard for whether the goal is met.

---

## 10. Reference: confirmed-working facts (don't re-derive)

- **Greenhouse embed form:** `https://boards.greenhouse.io/embed/job_app?token=<gh_jid>`
  renders the real application form for any `gh_jid` (works for custom-domain
  employers). `job-boards.greenhouse.io/embed/...` does **not**.
- **Greenhouse react-select:** control = `.select__control`; hidden input =
  `.select__input[role=combobox]`; open menu options = `.select__menu .select__option`.
  Read options ONLY inside `.select__menu` (a bare `[role=option]` also matches the
  phone-country picker's 200+ items → wrong snap). Open by setting a probe attr on
  the control found via `aria-labelledby` text match (`_MARK_COMBO_JS`), not the
  stamped `data-ap-key` (React wipes it).
- **Phone:** use E.164 (`+<cc><national>`); type with `press_sequentially` so
  intl-tel-input detects the country. Setting the form's "Country" select also
  syncs the phone country — so `choose_select_option` must match "India" to
  "India +91", never "British Indian Ocean Territory +246" (exact/startswith wins).
- **Invisible reCAPTCHA v3** is present on every Greenhouse form and does NOT block
  submit — do not treat its presence as a verification wall.
- **Success detection:** a real submit removes the form (no submit button + <2
  fillable fields) or shows a success marker / confirmation URL. "Form still
  present, no error" = NOT submitted (park), not a success.
- **Eligibility gate** (`apply/eligibility.py`, `discovery/_filters.py`): the
  India/H1B profile rejects US-only roles; test with remote/India roles
  (Anthropic, Datadog, Airbnb have eligible ones).

---

## 11. Out of scope / explicitly deferred

- Workday adapter (multi-step; separate effort — see `docs/maxed-apply-pipeline-jun-2026.md` Phase C).
- IP rotation / proxies (cost cap excludes; 75/family/day is the single-IP ceiling).
- Dashboard React changes — the Applications view already renders
  `apply_form_filled`; the correction loop already has a CLI (`correct-field`) and
  API (`/api/field-overrides`). Add a UI button only if separately requested.
