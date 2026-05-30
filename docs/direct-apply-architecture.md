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
rule table. Match on lower-cased `label` (plus `name`/`autocomplete` attributes when
present). Values come from **`worker_playbook.build_playbook_tokens()`** — reuse it, do
not duplicate profile parsing. Covers: name, email, phone, address, URLs, work auth,
salary, EEO, and the standard yes/no screening set.

### Tier 1 — Q&A bank (SQLite cache) · covers most screening Qs after warm-up · $0
A `qa_bank` table maps a **normalized question key** → stored answer. Pre-seeded once
(your step 1) by batch-answering a canonical question set with Gemini. After ~50–100
real forms, almost every screening question is a cache hit. Each Tier-2 answer is written
back here, so the bank self-warms.

### Tier 2 — Gemini batch resolve (Flash-Lite) · novel forms only · ~$0.001/form
Collect **all** fields Tier 0/1 couldn't answer **in one form** and send **one** Gemini
call: profile + resume + the list of `{label, type, options}` → strict JSON `{ap_id:
answer}`. Reuse `llm.get_client()` and log via `record_llm_usage`. Write every answer
back to the Q&A bank. One cheap call per *novel* form, not per field, not per job.

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
it can describe a form but can't drive it. Extend it minimally:

- During the `querySelectorAll('input,select,textarea')` walk, stamp each element with a
  unique attribute: `el.setAttribute('data-ap-id', String(i))`.
- Add `apId: i` to each returned field object. Also return each field's `options` (for
  `select`/radio groups) and `required` flag.

The Driver then locates any field with the site-agnostic selector `[data-ap-id="<i>"]`.
This is the entire trick that makes "no hardcoding per website" work: one generic
stamping pass produces stable locators on **any** ATS, no per-site selectors ever.

---

## 7. Q&A bank — schema, normalization, pre-seed

**Schema** (add to `database.py::init_db`, `CREATE TABLE IF NOT EXISTS`, same idempotent
pattern as `llm_usage_events`):

```
qa_bank(
  question_key   TEXT PRIMARY KEY,   -- normalized key
  question_text  TEXT,               -- last-seen raw label
  answer         TEXT,
  answer_type    TEXT,               -- text | select | bool
  scope          TEXT,               -- 'generic' | 'company'
  source         TEXT,               -- 'seed' | 'gemini' | 'manual'
  hit_count      INTEGER DEFAULT 0,
  created_at     TEXT,
  updated_at     TEXT
)
-- index on hit_count for telemetry
```

**Normalization** (`question_key`): lowercase → strip punctuation → collapse whitespace →
drop the company name and job title tokens (so generic questions collapse across postings).
Classify each question:
- **generic** (e.g. "are you authorized to work", "years of experience") → cache and reuse
  across all jobs.
- **company-specific free-text** (e.g. "why do you want to work here") → store a single
  Gemini-generated **template** with `{{company}}` / `{{role}}` placeholders; substitute at
  fill time. One template, infinite reuse, still personalized.

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

The biggest anti-detection win is **already in place**: the worker uses a real, headed
Chrome with a persistent profile (`chrome.launch_chrome`), so real cookies, UA, and
fingerprint are reused. Build on that:

- **Typing:** `locator.press_sequentially(value, delay=randint(60,140))` for text fields —
  never instant `fill()` on visible inputs.
- **Clicking:** `scroll_into_view_if_needed()` → `hover()` → short pause → `click()`.
- **Pacing:** Gaussian sleep between fields (~0.6s ± 0.25). Randomize the order of
  independent fields. Occasional no-op scroll.
- **Global rate limit:** minimum jittered spacing between submits (e.g. 30–90s). This both
  mimics humans and prevents hammering one domain. Pull the spacing from `apply_settings`.
- **One tab, one domain at a time.** No parallel hammering of the same host.
- Cap effective WPM so fills never exceed plausible human speed.

---

## 10. Exact codebase implementation

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

### Changed files (small, surgical)
- **`database.py`** — add `qa_bank` table in `init_db` (idempotent). Optional
  `field_resolution_log` for telemetry.
- **`apply_settings.py`** — add `apply_engine()` → `"direct" | "claude"` (env
  `APPLYPILOT_APPLY_ENGINE`, default `direct` once stable); add pacing config
  (`human_pace_min/max`, `submit_spacing`).
- **`launcher.py::run_job`** — at the top, branch: if `apply_settings.apply_engine() ==
  "direct"`, call `direct.driver.apply_via_playwright(...)` and return its result; else
  the current Claude path. **Nothing else in `run_job` / `worker_loop` changes** — the
  result contract is identical.
- **`cli.py`** — add `--engine {direct,claude}` and `--seed-qa-bank`.
- **`config/common_questions.yaml`** — new curated seed question list.

### Reused as-is (no duplication)
`chrome.launch_chrome` + CDP port · `prompt_scripts.FORM_VERIFY_JS` (extended) ·
`worker_playbook.build_playbook_tokens` · `llm.get_client` + `record_llm_usage` ·
`eligibility` + `salary` checks · `playbook_results` result vocabulary · the entire
`worker_loop` / `mark_result` / dashboard pipeline.

---

## 11. Result contract (must stay identical)

`apply_via_playwright` returns exactly the strings `run_job` returns today:
`applied`, `submitted_unverified:<reason>`, `expired`, `captcha`, `login_issue`,
`failed:<reason>`, `skipped`. This guarantees `_resolve_apply_result`, `mark_result`,
permanent-failure classification, and the dashboard all keep working with zero changes.

---

## 12. Rollout plan

1. **Phase 1 — bridge:** extend `FORM_VERIFY_JS` (§6); build `extractor.py` + `driver.py`
   for the happy path (Greenhouse/Lever/Ashby, the bulk of the backlog) with Tier 0 only.
   Everything not happy-path → escalate to Claude. Ship behind `--engine direct`.
2. **Phase 2 — resolver:** add `qa_bank` + `gemini_resolver`; pre-seed; wire Tiers 1–2.
   Rescue rate should drop sharply.
3. **Phase 3 — humanize + pacing** (§9); tune anti-block; raise throughput.
4. **Phase 4 — shrink rescue:** mine the escalation log weekly; add Tier-0 rules and
   Tier-1 entries for recurring rescues. Optionally add Tier 1.5 (embeddings, Option 4).

Default `apply_engine` flips to `direct` after Phase 2 proves out; Claude stays wired as
the rescue path forever.

---

## 13. Expected before / after

| Metric | Today (Claude per form) | After (Driver + Resolver) |
|---|---|---|
| Claude calls per apply | 1 full agent loop (40–80 turns) | 0 for ~85–95% of jobs; 1 rescue loop for the rest |
| Gemini calls per apply | 0 | ~0 (cache hit) to 1 cheap batch (novel form) |
| Cost per apply | ~$1+ | ~$0 (cached) / ~$0.001 (novel) / Claude only on rescue |
| Throughput ceiling | Claude quota (~7 applies) | Anti-bot pacing, not quota — hundreds/day |
| Dominant failure mode | LLM misreads DOM, fills wrong field | Eliminated on deterministic path; rescue keeps the ceiling |
| Quality | baseline | **maintained or better** (no DOM-misread; same Claude on hard forms) |

---

## 14. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Selector stamping misses a custom widget (canvas/shadow DOM) | `should_escalate` catches it → Claude rescue; log → add rule |
| Gemini gives a wrong answer to a novel question | Tier 0 owns all *factual* fields; Gemini only sees genuinely novel ones; answers cached + auditable in `qa_bank` |
| Anti-bot still blocks | Real persistent profile + human pacing (§9); per-domain rate limit; rescue path; never headless |
| Q&A cache returns a stale/wrong generic answer | `scope` separates generic vs company; manual override (`source='manual'`); hit_count surfaces outliers |
| Multi-step ATS (Workday) brittle | Phase-1 escalates these to Claude; codify per-step loop only after observing real flows |
