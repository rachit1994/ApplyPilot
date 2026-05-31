# Direct Apply Architecture — Scaling to 2000+ Applications

**Status:** proposal · **Goal:** apply at scale without burning Claude quota, without
hardcoding per website, without degrading quality.

---

## 1. The problem, stated precisely

Today every application = one `claude` agent loop driving a browser through MCP.
That conflates two completely different jobs:

- **Browser mechanics** — navigate, find Apply, click, type, upload, read form state,
  detect "done". This is 100% deterministic. It needs zero intelligence.
- **Answer intelligence** — what value goes in each field. This is *mostly* a fixed
  lookup (name, email, work auth, EEO) and *occasionally* a novel screening question.

Using a premium agentic LLM to do the *mechanics* is what blows the quota. The agent
spends 40–80 turns clicking buttons — and its #1 failure mode is **misreading the DOM
and filling the wrong field**, which is also the main quality problem.

**Core insight: separate mechanics from intelligence.** Drive the browser with
deterministic Python/Playwright. Resolve answers with a cheap, cached, tiered system.
Use Claude only to *rescue* the rare job the deterministic path can't finish.

---

## 2. Options considered

| # | Approach | No per-site hardcode? | Cost | Speed | Quality | Verdict |
|---|----------|:--:|:--:|:--:|:--:|---|
| 1 | **Per-ATS hardcoded adapters** (Greenhouse/Lever/Workday templates) | ❌ | 🟢 free | 🟢 fast | 🟡 great on covered ATS, blind on long tail | Rejected — explicitly disallowed; breaks when ATS change DOM; long tail uncovered |
| 2 | **Pure heuristic matcher, no LLM** (label→profile rules only) | ✅ | 🟢 free | 🟢 fast | 🔴 leaves novel screening Qs blank/wrong | Rejected — degrades quality on custom questions |
| 3 | **Driver + Tiered Resolver + Claude rescue** (your proposal, formalized) | ✅ | 🟢 ~free at scale | 🟢 fast | 🟢 maintained/improved | **RECOMMENDED** |
| 4 | **Embedding semantic field matcher** | ✅ | 🟡 model + vector store | 🟢 fast | 🟢 good | Defer — extra infra for marginal gain over (3); can layer in later as Tier 1.5 |

**Why 3 wins:** it is the only option that satisfies all three constraints (no hardcoding,
low cost, high speed) *and* preserves quality. Options 1 and 2 each fail a hard constraint;
option 4 adds an embedding model and vector store for a benefit that Tier-1 caching +
Gemini batch already deliver. Option 4 stays on the table as a future optimization layer.

**Honest framing on Option 1.** The §10 learning loop is, in effect, per-ATS adapters
*built declaratively over time* — the same idea as Option 1, but learned from observed
DOM rather than hand-written, and stored as data (selectors, mappings, multi-step plans)
rather than code. The constraint we are honoring is "no human writes a per-site template
upfront", not "the system never specializes per site". Once a provider is frozen, it
behaves exactly like a hardcoded adapter — that is the win, not a contradiction.

---

## 3. Recommended architecture: Driver / Resolver split

```
                    ┌──────────────────────────────────────────────┐
                    │  worker_loop (launcher.py, UNCHANGED contract) │
                    └───────────────────────┬──────────────────────┘
                                            │ engine == "direct"
                                            ▼
        ┌───────────────────────────────────────────────────────────────────┐
        │                    DRIVER  (deterministic Python)                   │
        │  Playwright connect_over_cdp → existing headed Chrome (real profile)│
        │  navigate → STOP check → click Apply → EXTRACT fields → for each    │
        │  field ask RESOLVER → fill (human-like) → verify → submit → done    │
        └───────────────┬───────────────────────────────────┬───────────────┘
                        │ field labels + types               │ stuck / weird flow
                        ▼                                     ▼
        ┌───────────────────────────────────┐   ┌───────────────────────────┐
        │            RESOLVER                │   │   TIER 3 — CLAUDE RESCUE   │
        │ Tier 0  Profile binding (rules)    │   │ reuse existing run_job()   │
        │ Tier 1  Q&A bank cache (SQLite)    │   │ Claude agent, ~5–15% jobs  │
        │ Tier 2  Gemini batch (Flash-Lite)  │   └───────────────────────────┘
        └───────────────────────────────────┘
```

The Driver returns the **same result strings** as today (`applied`, `failed:<reason>`,
`expired`, `captcha`, …) so everything downstream (`_resolve_apply_result`, `mark_result`,
the dashboard) is untouched.

---

## 4. The Resolver — answer intelligence in tiers

Each tier is tried in order; first hit wins. The Driver hands the Resolver the list of
extracted fields; the Resolver returns `{ap_id: answer}`.

### Tier 0 — Profile binding (deterministic rules) · covers ~70% of fields · $0
Port the FIELD MAP and QUESTION MAP from `docs/worker-apply-playbook.md` into a Python
rule table. Values come from **`worker_playbook.build_playbook_tokens()`** — reuse it,
do not duplicate profile parsing. Covers: name, email, phone, address, URLs, work
auth, salary, EEO, and the standard yes/no screening set.

**Match precedence (collision handling).** Bare label matching is unsafe — "Name"
could be the candidate's full name, the company they worked at, or the referrer's
name. Resolve in this order:
1. **HTML attributes first.** `name`, `autocomplete` (e.g. `autocomplete="email"`,
   `name="referrer_email"`), `type=email|tel|url|date`. These are author-set, stable,
   and rarely ambiguous.
2. **Label + section header.** A "Name" label under a fieldset labeled "Referrer
   Information" binds to `referrer_name`, not `full_name`. The §7 `section_header`
   token is the same one used to disambiguate the Q&A bank — reuse it here.
3. **Bare label.** Only when (1) and (2) provide no signal. If multiple rules match
   the bare label with no disambiguator, the rule table returns "unresolved" rather
   than guessing; the field falls through to Tier 1/2/3 where the LLM has more
   context. **Guessing is a worse failure than escalating.**

Porting note: the FIELD MAP / QUESTION MAP in `docs/worker-apply-playbook.md` are
prose-and-table English. Translating to executable Python rules is a careful pass —
budget for it explicitly. The output is an ordered list of rules, each
`(matcher_fn, token_key, confidence)`; first match by precedence above wins.

### Tier 1 — Q&A bank (SQLite cache) · covers most screening Qs after warm-up · $0
A `qa_bank` table maps a **normalized question key** → stored answer. Pre-seeded once
(your step 1) by batch-answering a canonical question set with Gemini. After ~50–100
real forms, almost every screening question is a cache hit. Each Tier-2 answer is written
back here, so the bank self-warms.

### Tier 2 — Gemini batch resolve (Flash-Lite) · novel forms only · ~$0.001/form
Collect **all** fields Tier 0/1 couldn't answer **in one form** and send **one** Gemini
call: profile + resume + the list of `{label, type, options, section_header}` → strict
JSON `{key: answer}` (keyed by §6 `key`, not `apId`, so multi-step forms are safe).
Reuse `llm.get_client()` and log via `record_llm_usage`. Write every answer back to
the Q&A bank with full disambiguation context. One cheap call per *novel* form, not
per field, not per job.

**Retry budget.** Gemini rate-limits and transient 5xx will happen at peak. Bounded
retry: `gemini_retry_max=2` with exponential backoff (2s, 4s); on third failure,
**escalate the whole form to Tier 3** rather than blocking the pipeline indefinitely.
Pull both from `apply_settings`.

### Tier 3 — Claude rescue (escalation) · stuck jobs only · target 5–15%
When the Driver cannot proceed deterministically (see §8 triggers), hand the **whole job**
to the existing Claude path (`launcher.run_job` in legacy/playbook mode). This preserves
today's quality ceiling for genuinely hard forms while keeping Claude usage rare.

---

## 5. The Driver — deterministic state machine

Exact step order (mirrors the playbook, executed in Python instead of by an LLM):

1. **Connect** Playwright to the running Chrome over CDP
   (`chromium.connect_over_cdp("http://localhost:{port}")`). Reuse the worker's existing
   `launch_chrome` + persistent profile — do **not** spawn a new browser.
2. **Navigate** to `job_url`; wait for `networkidle` (bounded).
3. **STOP CHECK** — run the §STOP table from the playbook against `bodyText`
   (reuse `eligibility` + salary/location helpers in Python). On match → return that result.
4. **Find & click Apply** — match button text (`Apply`, `Apply Now`, …). If a form is
   already present, skip.
5. **EXTRACT** — run the extended extractor (§7) → structured fields **with selectors**.
6. **RESOLVE** — Resolver returns `{ap_id: answer}` for every fillable field.
7. **FILL** — for each field, dispatch by element type:
   - text/email/tel/textarea → human-like typing (§9)
   - select → open, click option by text; fuzzy-fallback (`Decline` / `Prefer not` / `No`)
   - radio/checkbox → click matching option
   - file → `set_input_files(resume_pdf_path)` (and cover letter if a field exists)
   - date widgets → use `dateWidgets` hints; never leave `MM`
8. **VERIFY** — re-extract; if `emptyRequired > 0` or `visibleErrors`, re-resolve those
   fields (max 2 passes). Multi-page forms: fill → verify → click Next → re-extract.
9. **SUBMIT** — click submit; only when `emptyRequired == 0` and no `visibleErrors`.
10. **DONE CHECK** — re-extract; map `bodyText` via the §DONE table → `applied`,
    `needs_email_code`, `captcha`, or `failed:stuck`.
11. Any unresolved/stuck/exception condition → **escalate to Tier 3** (§8).

---

## 6. The selector bridge (the one real piece of new DOM work)

`FORM_VERIFY_JS` today returns `{label, tag, type, value, empty}` but **no locator** — so
it can describe a form but can't drive it. The extension is a **contract change**, not a
tweak: every caller of `FORM_VERIFY_JS` must accept the new field shape. Plan accordingly.

### 6.1 What gets extracted
Walk every input-bearing context and emit one field record per fillable element:

- `tag`, `type`, `value`, `empty`, `required`, `label` (as today).
- `options` — for `select`/radio/checkbox groups, the list of `{value, text}`.
- `apId` — a stable per-form ordinal (see §6.3).
- `key` — a content-derived stable key (see §6.3 fallback).
- `frame` — frame path (`[]` for top, `[0,2]` for nested) so the Driver can resolve
  locators across iframes.

### 6.2 Walking the real DOM (the part the original sketch handwaved)
A flat `document.querySelectorAll('input,select,textarea')` on the top page misses most
of the production failure modes. The extractor MUST handle:

- **iframes.** Recursively descend `frames`/`contentDocument`. Workday and many
  Greenhouse/Lever embeds live in nested iframes — without frame walking the extractor
  returns an empty form on these and the Driver clicks Submit on nothing. Track each
  frame's path so the Driver can `page.frame_locator(...)` it back.
- **Shadow DOM.** When traversing each node, also descend `element.shadowRoot` if
  present. Many modern web components (autocomplete, custom selects, file pickers) hide
  their real `<input>` inside a shadow root.
- **Hidden-but-controlled inputs.** Many file inputs and date pickers are visually
  hidden behind a styled label; do not skip `display:none` inputs — instead record both
  the input and its associated trigger element.
- **Custom widgets built from `<div>`s.** Combobox/listbox patterns with
  `role="combobox"` / `role="listbox"` / `role="option"` are fillable but invisible to
  the `input,select,textarea` query. Include `[role="combobox"], [role="listbox"],
  [role="radiogroup"]` in the walk and emit them as synthetic fields with their
  options enumerated from `[role="option"]` children.
- **Canvas / out-of-DOM widgets.** Cannot be extracted. Mark the form as
  `extractor:partial` so §8 can escalate immediately instead of submitting half-filled.

### 6.3 Stable locators that survive re-render
`setAttribute('data-ap-id', i)` works for vanilla forms. It **silently breaks** on
React/Vue controlled inputs: the framework re-mounts the element on the next render and
the attribute is gone. The Driver then locates a stale (or wrong) field. This is the
single highest silent-bug risk in the whole design.

Mitigations, applied together:

1. **Re-stamp immediately before fill.** Every fill operation runs a tiny
   re-stamping pass first (`window.__apStamp(apId, key)`) so even if React wiped
   the attribute since extraction, the locator resolves correctly. Cheap; idempotent.
2. **Use a derived `key` as the primary identity, ordinal as fallback.** `key` is a
   stable content hash of the field's invariant properties:
   `sha1(normalized_label + name_attr + autocomplete_attr + frame_path + index_in_fieldset)`.
   The Driver prefers `[data-ap-key="<hash>"]`; falls back to `[data-ap-id="<i>"]`
   only when key collisions exist within the form.
3. **Verify after fill.** Read back the field value via the same key/id and assert it
   matches what was filled. On mismatch, re-stamp and retry once; second mismatch →
   escalate.

### 6.4 Multi-step forms
After clicking Next, the new step's DOM is a fresh form: `apId` ordinals reset, fields
appear that didn't exist at extraction. The §5 step-8 loop must:

- Re-run the extractor (with re-stamping) on each step.
- Key the Resolver cache **by `key` (content-derived), never by `apId`**, so the
  step-1 cache doesn't accidentally serve a step-3 field with the same ordinal.
- Persist per-step extracted state in the `apply_outcomes` row so the learner sees the
  whole flow, not just the first page.

### 6.5 What this section guarantees
With (1)+(2)+(3) above, "no hardcoding per website" holds for every form whose fields
the extractor can see. Forms whose fields the extractor cannot see (canvas widgets,
shadow-DOM patterns we haven't taught it about) are explicit escalations to Tier 3,
not silent miss-fills. That is the safety property: **never fill the wrong field**.

---

## 7. Q&A bank — schema, normalization, pre-seed

**Schema** (add to `database.py::init_db`, `CREATE TABLE IF NOT EXISTS`, same idempotent
pattern as `llm_usage_events`):

```
qa_bank(
  question_key   TEXT PRIMARY KEY,   -- normalized key
  question_text  TEXT,               -- last-seen raw label
  answer         TEXT,
  answer_type    TEXT,               -- text | select | bool | number | template
  section_header TEXT,               -- nearest <legend>/<h*>/aria-labelledby (disambiguates Email-under-Referrer vs Email-under-Personal)
  name_attr      TEXT,               -- input name/autocomplete attr at write time (disambiguation aid)
  scope          TEXT,               -- 'generic' | 'company'
  source         TEXT,               -- 'seed' | 'gemini' | 'manual'
  hit_count      INTEGER DEFAULT 0,
  created_at     TEXT,
  updated_at     TEXT
)
-- index on hit_count for telemetry
```

**Normalization** (`question_key`) — naive lowercase+strip+drop-company over-collapses
and serves wrong answers. The canonical example: "Total years of experience" and "Years
of experience with Python" both reduce to `years of experience`. The first should return
e.g. `"8"`; the second should return `"4"`. A single shared answer is wrong in both
directions.

The key must therefore include **surrounding context**, not just the label:

```
question_key = sha1(
  norm(label)
  + "|" + norm(nearest_section_header)   # <legend>, preceding <h2/h3>, or aria-labelledby
  + "|" + norm(name_attr or autocomplete_attr or "")
  + "|" + answer_type                    # text / select / bool / number
)
```

- `nearest_section_header` is what disambiguates "Email" under "Personal Information"
  from "Email" under "Referrer Information". Without it, the cache *will* leak a
  referrer's email into the candidate's field, and recruiters *will* notice.
- The `name`/`autocomplete` attribute disambiguates "Name" (full name vs company name
  vs referrer name) because ATS-generated forms almost always set sensible `name`
  attributes even when their visible labels are ambiguous.
- `answer_type` prevents a text answer being served to a select field with a fixed
  option list.

Classification of each question:
- **generic** (e.g. "are you authorized to work", any factual yes/no) → cache the
  literal answer; reuse across all jobs with the same `question_key`.
- **scalar with context** (e.g. "years of experience with X") → cache per
  `(label, section_header, name_attr)` triple; the section/name context is what makes
  this safe.
- **company-specific free-text** (e.g. "why do you want to work here", "why this role")
  → **cache the prompt template, never the rendered answer.** Every fill goes through
  Gemini at fill time with the live `{company, role, jd_summary}` context. Marginal
  cost (~$0.0001 per answer) is the price of not having recruiters bin the application
  for boilerplate. The `qa_bank` row for these stores `answer_type='template'` and
  `answer` is the Gemini prompt template, not an answer string.

The Resolver enforces this distinction: it returns cached answers only for
`answer_type in ('text','select','bool','number')`. For `answer_type='template'`, it
unconditionally re-renders via Gemini in the Tier-2 batch, never serving cached prose.

**Pre-seed (your step 1):** new CLI `applypilot apply --seed-qa-bank` reads
`config/common_questions.yaml` (a curated ~80-question list), batch-answers via one Gemini
call, writes rows with `source='seed'`. Run once; the bank is warm from job #1.

---

## 8. Escalation to Claude — exact triggers (Tier 3)

Escalate the whole job to the existing Claude `run_job` when **any** of:

- Apply button not found after navigation + bounded waits.
- `emptyRequired > 0` after 2 resolve passes (a required field nothing could identify).
- `visibleErrors` persist after a submit attempt.
- Login/SSO wall that is not a plain email+password form.
- CAPTCHA detected (v1: rescue; v2: port the existing CapSolver flow to Python).
- Known-hard multi-step flow (e.g. Workday with > N steps) — optional, behind a flag.
- Any Playwright exception / navigation timeout.

Every escalation is **logged with its reason**. The rescue log is the backlog for new
Tier-0 rules and Tier-1 entries — over time the rescue rate shrinks toward zero.

---

## 9. Human-behavior layer (anti-block)

The biggest *per-form* anti-detection win is **already in place**: the worker uses a
real, headed Chrome with a persistent profile (`chrome.launch_chrome`), so real cookies,
UA, and fingerprint are reused. That solves fingerprint-based detection. It does
**not** solve volume-based detection — which is the binding constraint at 2000/day.

### 9.1 Per-form behavior (fingerprint defenses)
- **Typing:** `locator.press_sequentially(value, delay=randint(60,140))` for text fields —
  never instant `fill()` on visible inputs.
- **Clicking:** `scroll_into_view_if_needed()` → `hover()` → short pause → `click()`.
- **Pacing:** Gaussian sleep between fields (~0.6s ± 0.25). Randomize the order of
  independent fields. Occasional no-op scroll.
- **One tab, one domain at a time.** No parallel hammering of the same host.
- Cap effective WPM so fills never exceed plausible human speed.

### 9.2 Volume defenses (the real throughput ceiling)
At 2000/day from a single residential IP, IP reputation services (Cloudflare,
DataDome, PerimeterX) will throttle and serve captchas regardless of how human the
*per-form* behavior looks. 200 hits/day to `boards.greenhouse.io` from one IP is the
fingerprint that triggers them, not the typing cadence. Per-form pacing is necessary
but not sufficient.

- **Per-ATS-family daily cap.** This is the actual throughput gate, not "anti-bot
  pacing". Settable in `apply_settings`, default conservative (e.g. 75/day per ATS
  family per IP — greenhouse / lever / ashby / workday / icims / etc. counted
  separately). Queue spillover defers to the next day, never bursts past the cap.
- **Per-domain cap inside the family cap.** Some companies host their own
  Greenhouse-embedded boards — those count against the family cap and against a
  separate `max_per_apex_domain_per_day` (default 25).
- **Global submit spacing:** minimum jittered 30–90s between any two submits,
  regardless of domain. Pull from `apply_settings`.
- **IP diversity (gate for >~300/day total).** A single residential IP genuinely
  cannot do 2000/day without triggering reputation services, no matter how clever the
  pacing. Real scaling beyond a few hundred applies/day requires either (a) a pool of
  residential proxies rotated per-ATS-family-session, or (b) running multiple
  worker profiles on physically separate machines / network egresses. The plan
  acknowledges this rather than hides it: until the IP pool exists, 2000/day is the
  *aspirational* ceiling and the *operational* ceiling is whatever the per-ATS caps
  sum to on the available IP count.
- **Captcha is not free.** At higher volume, captcha rate rises super-linearly. Tier-3
  rescue stays the v1 answer; v2's CapSolver port (a real port — the current flow is
  JS embedded in Claude prompts, not Python) is on the critical path once captchas
  exceed a threshold (e.g. >5% of applies).

### 9.3 Throughput model (concrete)
With one residential IP, default caps, and ~4 ATS families covering the bulk of the
backlog: ~300 applies/day operational ceiling, scaling roughly linearly with each
additional IP. 2000/day target ⇒ ~6–7 IPs in rotation. This is the cost the
"throughput ceiling: hundreds/day" line in §14 was hiding; calling it out here so the
infrastructure decision happens before the apply queue overruns it.

---

## 10. Self-improving provider learning loop (how the system "wins")

> **Better-idea note (you asked me to push back if warranted).** Your instinct —
> *remember per provider, fix what failed, store/auto-test, stop using the LLM next
> time* — is right and worth building. But the literal "LLM writes Python adapters,
> auto-saves and auto-runs them" is reframed below, because:
> 1. **The recurring failure is missing *knowledge*, not missing *code*.** ~90% of
>    repeat failures are a new selector, a new field→answer mapping, or a provider quirk
>    ("Workday needs a Next click between sections"). That is **data**, which can be
>    learned, diffed, replay-tested, and frozen safely.
> 2. **Auto-running unreviewed generated code against live employer forms** is the one
>    thing that *would* degrade reliability — it violates the no-degrade constraint.
>
> So: **learn declarative provider profiles by default; gate code-generation hard.**
> The system still "wins" — LLM use trends to zero per provider — but via learned data,
> not a self-rewriting codebase.

### 10.1 Provider identity — what "the same type" means
Key every learned artifact by a **provider fingerprint**:
`ats_family` (from `eligibility.ATS_URL_MARKERS` — greenhouse/lever/ashby/workday/…)
**+ a DOM signature** (a hash of the form's field-name/attribute conventions, e.g.
Greenhouse `data-qa`, Workday `data-automation-id`). Same fingerprint = "same type".
A fingerprint can have a `template_version` so a provider's DOM redesign is detected as a
new variant rather than silently corrupting the old profile.

### 10.2 What gets learned (data, auto-applied, zero LLM next time)
- **`provider_profile`** — per fingerprint: known selectors, option-normalization quirks,
  the multi-step plan (section order, Next-button text), file-upload idiosyncrasies.
- **`qa_bank` entries** — already in §7; new answers fold in here.
- **field-binding deltas** — new label→profile rules promoted into Tier 0.

When a fingerprint has a frozen profile, the Driver applies it directly and **skips the
Resolver's LLM tiers entirely**.

### 10.3 The loop
1. **Observe.** Every apply emits an `apply_outcome` row: fingerprint, which fields
   resolved via which tier, validation errors hit, whether it submitted, whether it
   escalated and why. (The §8 rescue log is the primary training signal.)
2. **Diagnose (batched, async — never in the hot path).** A `learner` job groups outcomes
   by fingerprint, finds repeat failures, and makes **one** LLM call to propose a
   **profile delta** (new selector / mapping / quirk) — *data*, not code.
3. **Validate by replay.** The extractor already captures full form state; store it as a
   **DOM fixture**. Sampling policy (storage discipline): keep **all failures and
   escalations**; sample successful fixtures at ~1-in-20. Otherwise at 2000/day × ~50KB
   per fixture = ~100MB/day, ~36GB/year — unnecessary growth for diminishing learner
   value. The proposed delta is tested against saved fixtures (assert: all required
   fields resolve, no predicted validation errors, terminal selector present). This
   tests mechanics/mappings — **not** a real submission (you can't spam employers).
4. **Canary.** A passing delta runs in **shadow-trust** before promotion. Two gates
   must both pass, because they prove different things:
   - **Fill-time gate (fast).** First K=10 live applies: apply normally, plus a cheap
     Gemini cross-check of the fill before submit. K successes → delta is *fill-correct*.
   - **Outcome gate (slow, load-bearing).** A fill that looks right is not a fill that
     worked. The real outcome signal is the employer's response (acknowledgment email,
     status change in the ATS, or after a long no-response window, an inferred-success
     timeout). Promotion requires K_outcome=10 applies that pass the outcome gate over
     a 7-day window. Conflating "fill passed cross-check" with "apply succeeded" is the
     subtle way a learning loop bakes in failure modes — the outcome gate prevents it.
   Cross-check + outcome both green → eligible for §10.5 promotion. Either red → delta
   stays in shadow-trust or is discarded.
5. **Freeze.** Trusted profile is marked frozen; the LLM is skipped for that fingerprint.

### 10.4 Code generation — the gated exception only
Reserve real codegen for providers that need new **control flow** no declarative profile
can express (rare). Then it is hard-gated, never the default:
- The LLM implements a **fixed `ProviderStrategy` interface** (not free-form code).
- Output is written to a **quarantine dir**, never imported live on creation.
- It must pass the §10.3 replay suite **and** the canary phase.
- Final load requires the **promotion gate to approve** (next item).
This is exactly your *"unless the harness says it is useful and the system is not able to
apply itself"* clause — the gate is that arbiter.

### 10.5 Promotion gate ("the harness says it's useful")
A delta/strategy is promoted (and frozen) only when **all** hold:
replay tests pass · fill-time gate passes (K=10 cross-checked fills) · outcome gate
passes (K_outcome=10 confirmed acknowledgments over 7 days) · provider `autonomy_rate`
and `success_rate` clear thresholds. Otherwise it stays in shadow-trust or is
discarded. Promotion is the single chokepoint where automation is allowed to start
trusting itself.

### 10.6 Win metric & regression handling
- **`autonomy_rate(provider)` = applies completed with zero LLM calls / total.** The
  loop's explicit job is to drive this → ~100% per provider. Track it on the dashboard.
- **Regression with hysteresis = no thrash.** A frozen provider with a falling
  `success_rate` auto-unfreezes at the **unfreeze floor** (default 80%); but it can
  only **re-freeze** after rebuilding past the **refreeze floor** (default 90%), not
  by drifting back to 81%. Without this gap, a partially-broken ATS sitting at ~78%
  would thrash unfreeze→re-learn→78%→unfreeze in a tight loop, burning Gemini and
  Claude budget for no improvement.
- **Re-learn rate cap.** Cap re-learn attempts per fingerprint at 3/day. Beyond that,
  flag the fingerprint as `degraded` on the dashboard and stop spending learner
  budget on it until a human looks — this is the signal that the ATS redesign is
  beyond the learner's current capabilities and probably needs the §10.4 codegen path
  (or a human-authored selector hint).
- This is what makes the system *keep* winning instead of silently breaking when an
  ATS redesigns, **without** turning the learner into a runaway cost when it can't
  win.

Net effect: a brand-new provider costs a few LLM calls while it's learned; a *solved*
provider costs **zero** forever (until it changes). Intelligence is spent once per novel
pattern, not once per application.

---

## 11. Exact codebase implementation

### New modules (`src/applypilot/apply/direct/`)
| File | Responsibility (interface contract) |
|---|---|
| `driver.py` | `apply_via_playwright(job, port, *, profile) -> tuple[str,int,Path|None]` — the §5 state machine. Same return shape as `run_job`. |
| `extractor.py` | `extract_fields(page) -> FormState` — wraps the extended §6 JS; returns fields with `ap_id`, `options`, `required`. |
| `resolver.py` | `resolve(fields, profile, job) -> dict[str,str]` — orchestrates Tiers 0→1→2. |
| `profile_binding.py` | Tier 0 rule table (port of FIELD MAP / QUESTION MAP). Values from `build_playbook_tokens`. |
| `qa_bank.py` | `lookup(key)`, `store(key, answer, …)`, `normalize(label, job)`. |
| `gemini_resolver.py` | `batch_resolve(unresolved, profile, job) -> dict` — one `llm.get_client()` call + `record_llm_usage`. |
| `humanize.py` | typing/hover/pacing helpers (§9). |
| `escalation.py` | `should_escalate(state) -> str|None`; `rescue(job, port) -> result` (calls existing `run_job`). |
| `fingerprint.py` | `provider_fingerprint(job, form_state) -> str` — ATS family + DOM signature (§10.1). |
| `provider_profile.py` | load/apply a frozen profile for a fingerprint; `autonomy_rate(fp)`, `success_rate(fp)`. |
| `learner.py` | async/batched §10.3 loop: outcomes → one LLM call → profile delta → replay → canary → freeze. Runs as a CLI job, **never in the apply hot path**. |
| `replay.py` | record DOM fixtures; run a delta/strategy against fixtures; assert required-fields-resolved / no-predicted-errors. |
| `strategy_registry.py` | quarantine + promotion-gated loader for generated `ProviderStrategy` plugins (§10.4–10.5). |

### Changed files (small, surgical)
- **`database.py`** — add (idempotent `CREATE TABLE IF NOT EXISTS`): `qa_bank` (§7),
  `provider_profile`, `apply_outcomes` (training signal), `learned_strategies` (quarantine
  registry + promotion state), `dom_fixtures` (replay corpus). Confirm WAL mode is on
  (`PRAGMA journal_mode=WAL`) so concurrent workers writing back to `qa_bank` and
  `apply_outcomes` don't serialize behind each other and trip `database is locked`
  errors under load.
- **`apply_settings.py`** — add `apply_engine()` → `"direct" | "claude"` (env
  `APPLYPILOT_APPLY_ENGINE`, default `direct` once stable); pacing config
  (`human_pace_min/max`, `submit_spacing`); per-IP volume caps
  (`max_per_ats_family_per_day`, `max_per_apex_domain_per_day` — §9.2); learning
  thresholds (`canary_k`, `canary_k_outcome`, `outcome_window_days`,
  `unfreeze_floor`, `refreeze_floor`, `relearn_attempts_per_day`,
  `autonomy_floor`, `success_floor`); resolver backoff config
  (`gemini_retry_max=2`, `gemini_backoff_base_s=2`).
- **`launcher.py::run_job`** — at the top, branch: if `apply_engine() == "direct"`, call
  `direct.driver.apply_via_playwright(...)`; else the current Claude path. The Driver also
  emits the `apply_outcomes` row. **Nothing else in `run_job` / `worker_loop` changes** —
  result contract is identical.
- **`prompt_scripts.py::FORM_VERIFY_JS`** — **field-shape contract change**, not a
  tweak. Current return is `{label,tag,type,value,empty}` per field; the §6 extension
  adds `apId`, `key`, `frame`, `options`, `required` plus the iframe/shadow walk.
  Every consumer of `FORM_VERIFY_JS` must accept the new shape; audit
  `launcher.py`, `worker_playbook.py`, and the playbook prompts before flipping.
- **`cli.py`** — add `--engine {direct,claude}`, `--seed-qa-bank`, `--learn`
  (run the §10.3 loop), `--provider-status` (show autonomy/success per fingerprint).
- **`config/common_questions.yaml`** — curated seed question list.

### Reused for learning (no duplication)
`prompt_scripts.FORM_VERIFY_JS` (extended) doubles as the **DOM-fixture recorder**;
the §8 escalation log is the **training signal**; `llm.get_client` + `record_llm_usage`
power the single batched learner call and meter its cost.

### Reused as-is (no duplication)
`chrome.launch_chrome` + CDP port · `prompt_scripts.FORM_VERIFY_JS` (extended) ·
`worker_playbook.build_playbook_tokens` · `llm.get_client` + `record_llm_usage` ·
`eligibility` + `salary` checks · `playbook_results` result vocabulary · the entire
`worker_loop` / `mark_result` / dashboard pipeline.

---

## 12. Result contract (must stay identical)

`apply_via_playwright` returns exactly the strings `run_job` returns today:
`applied`, `submitted_unverified:<reason>`, `expired`, `captcha`, `login_issue`,
`failed:<reason>`, `skipped`. This guarantees `_resolve_apply_result`, `mark_result`,
permanent-failure classification, and the dashboard all keep working with zero changes.

---

## 13. Rollout plan

1. **Phase 1 — bridge:** extend `FORM_VERIFY_JS` (§6); build `extractor.py` + `driver.py`
   for the happy path (Greenhouse/Lever/Ashby, the bulk of the backlog) with Tier 0 only.
   Everything not happy-path → escalate to Claude. Ship behind `--engine direct`.
2. **Phase 2 — resolver:** add `qa_bank` + `gemini_resolver`; pre-seed; wire Tiers 1–2.
   Rescue rate should drop sharply.
3. **Phase 3 — humanize + pacing** (§9); tune anti-block; raise throughput.
4. **Phase 4 — learning loop (§10):** record `apply_outcomes` + DOM fixtures; build
   `learner.py` (data deltas only) + replay + canary + freeze. Add `--learn` and
   `--provider-status`. This is what shrinks the rescue rate toward zero automatically.
5. **Phase 5 — gated codegen (§10.4), optional:** only if specific providers still need
   new control flow after Phase 4. Behind quarantine + promotion gate. Skip if Phase 4
   already drives autonomy high — most providers will never need it.

Default `apply_engine` flips to `direct` after Phase 2 proves out; Claude stays wired as
the rescue path forever. Phases 4–5 run continuously in the background, not as a one-off.

---

## 14. Expected before / after

| Metric | Today (Claude per form) | After (Driver + Resolver) |
|---|---|---|
| Claude calls per apply | 1 full agent loop (40–80 turns) | 0 for ~85–95% of jobs; 1 rescue loop for the rest |
| Gemini calls per apply | 0 | ~0 (cache hit) to 1 cheap batch (novel form) |
| Cost per apply | ~$1+ | ~$0 (cached) / ~$0.001 (novel) / Claude only on rescue |
| Throughput ceiling | Claude quota (~7 applies) | **IP reputation + per-ATS-family cap (§9.2)**, not LLM quota. ~300/day per IP; 2000/day target needs ~6–7 IPs in rotation. |
| Dominant failure mode | LLM misreads DOM, fills wrong field | Eliminated on deterministic path; rescue keeps the ceiling |
| Quality | baseline | **maintained or better** (no DOM-misread; same Claude on hard forms) |
| LLM cost **trend** over time | flat (every apply pays) | **decays toward $0** — once a provider is frozen (§10.6), applies to it cost zero LLM until its DOM changes |
| Per-provider autonomy_rate | n/a | tracked; learning loop drives it → ~100% |

---

## 15. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Selector stamping misses a custom widget (canvas) | Extractor marks form `extractor:partial` → §8 escalates immediately, never half-fills |
| **Shadow DOM / iframe forms invisible to extractor** (Workday, Greenhouse embeds) | §6.2 walks `frames` recursively + descends `shadowRoot`; `[role=combobox\|listbox\|radiogroup]` enumerated as synthetic fields |
| **React/Vue re-render drops `data-ap-id` between extract and fill** (silent wrong-field bug) | §6.3 re-stamps immediately before every fill; content-derived `key` is primary identity, ordinal is fallback; post-fill verify confirms the right field got the right value |
| Gemini gives a wrong answer to a novel question | Tier 0 owns all *factual* fields; Gemini only sees genuinely novel ones; answers cached + auditable in `qa_bank` |
| **Q&A bank over-collapses ("Email" under Referrer = "Email" under Personal)** | §7 normalization keys on `(label, section_header, name_attr, answer_type)`; the section/attr context is what makes reuse safe |
| **Company-specific templates produce boilerplate slop** ("Why do you want to work at {{company}}?") | §7: `answer_type='template'` rows cache the *prompt template*, never the rendered answer; Gemini re-renders at fill time with live `{company, role, jd}` context (~$0.0001/answer) |
| Anti-bot still blocks at volume | §9.1 per-form humanization + §9.2 per-ATS-family / per-domain caps; **IP diversity is the real throughput gate** above ~300/day per IP; rescue path stays wired |
| **IP reputation throttle/captcha at 2000/day on one IP** | §9.2 acknowledges this is the binding constraint; operational ceiling = per-IP cap × number of IPs; residential proxy rotation or multi-machine egress required for 2000/day |
| Q&A cache returns a stale/wrong generic answer | `scope` separates generic vs company; manual override (`source='manual'`); hit_count surfaces outliers |
| Multi-step ATS (Workday) brittle | Phase-1 escalates these to Claude; §6.4 keys resolver cache by content `key` (not ordinal) so step-1 fills don't contaminate step-3; codify per-step loop only after observing real flows |
| **Generated code is unsafe / wrong** (§10.4) | Default path learns *data*, not code; codegen is a gated exception only; fixed `ProviderStrategy` interface; quarantine + replay + canary + promotion gate; never auto-run live unreviewed |
| **Can't truly auto-test a real submission** (you'd spam employers) | Replay tests validate *mechanics + mappings* against recorded DOM fixtures, not live submits; the canary phase (§10.3) cross-checks the first K live applies with a cheap LLM before trusting |
| **A frozen provider silently breaks** when the ATS redesigns | `success_rate` floor auto-unfreezes the fingerprint → re-learn → re-freeze (§10.6); hysteresis (`unfreeze_floor=80%` vs `refreeze_floor=90%`) and `relearn_attempts_per_day=3` prevent thrash on partially-broken ATS; `template_version` isolates the redesign from the old profile |
| **Canary trusts a fill-time cross-check and bakes in failure** (fills look right but apply was never read) | §10.3 requires *both* the fill-time gate (K=10 cross-checked fills) and the outcome gate (K_outcome=10 confirmed acknowledgments over 7 days) — promotion needs both green |
| **DOM fixture storage grows unbounded** at 2000/day | §10.3 sampling: keep all failures + escalations; sample successes 1-in-20. ~5GB/year instead of ~36GB |
| Gemini rate-limit stalls the apply pipeline | §4 Tier-2 retry budget (2 retries, exponential backoff); on third failure escalate the form to Tier 3 — pipeline never blocks indefinitely |
| Concurrent SQLite writes (workers × `qa_bank` + `apply_outcomes`) trip "database is locked" | §11 confirms WAL mode in `database.py`; writes are short-lived; failure path falls through to in-memory dedupe and retry on next apply |
| Learner LLM cost grows with backlog | It runs **batched and async**, one call per fingerprint-cluster of failures — not per apply; metered via `record_llm_usage`; per-fingerprint daily attempt cap (§10.6) bounds worst case |
