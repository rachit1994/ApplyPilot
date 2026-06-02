# Max-Out Apply Pipeline — June 2026

**Goal:** maximize applies/day submitted without IP blocks, on a single Mac mini
with a single residential IP, holding total Claude cost ≤ $20/mo (shared with
other tasks).

**Success metric:** number of applies in `apply_status = 'applied'` per 24h,
with zero `cloudflare_blocked` / `site_blocked` / forced-captcha rate >5%.

**Honest ceiling at this configuration:** ~200–300 applies/day sustained.
Above that, the binding constraint is residential-IP reputation, not compute,
not LLM cost. To go further requires an IP rotation strategy, which is
explicitly out of scope per the cost cap.

---

## 1. Scope decisions (locked)

| # | Decision | Rationale |
|---|---|---|
| D1 | Single Mac mini M1, single residential IP, Claude ≤ $20/mo | User constraint |
| D2 | Hardcode adapters for Greenhouse, Lever, Ashby, **Workday** | Workday is 7/8 of past failures; can't afford rescue-while-learn cycle on $20 budget |
| D3 | Include LinkedIn URL pre-pass + bulk score + bulk tailor | Without input pipeline expansion, apply queue dries in minutes (11 tailored today) |

These override §2 and §10 of `docs/direct-apply-architecture.md`, which rejected
hardcoded adapters in favor of a learning loop. The learning loop becomes a
v2 add-on, not v1.

---

## 2. Ceiling math

Bottleneck order from binding (innermost) to slack (outermost):

```
  ┌─────────────────────────────────────────────────────────────────┐
  │ TIER 0 — IP reputation (binding constraint)                      │
  │   Per-ATS-family cap        : ~75/day per family per IP          │
  │   Per-apex-domain cap       : ~25/day per company per IP         │
  │   Min jittered submit spacing: 30–90s                            │
  │   Realistic sustainable     : ~300/day single residential IP     │
  └─────────────────────────────────────────────────────────────────┘
      ▲ never binds with 4 families + spacing
  ┌─────────────────────────────────────────────────────────────────┐
  │ TIER 1 — Anti-bot per-form fingerprint (rarely binds)            │
  │   Mitigated by human cadence, hover, scroll, tab isolation       │
  └─────────────────────────────────────────────────────────────────┘
      ▲
  ┌─────────────────────────────────────────────────────────────────┐
  │ TIER 2 — Compute (huge slack on M1, 16GB)                        │
  │   4 parallel headed Chromes × 30–60s/apply = 5,760–11,520/day    │
  └─────────────────────────────────────────────────────────────────┘
      ▲
  ┌─────────────────────────────────────────────────────────────────┐
  │ TIER 3 — LLM cost (huge slack with Direct Apply)                 │
  │   85–95% applies = 0 Claude tokens; Gemini ~$0.001/novel form    │
  │   Monthly cost at 300/day × 30 = 9,000 applies:                  │
  │     Gemini: ~$5 (assume 10% novel forms × $0.001)                │
  │     Claude rescue: ~$3–8 (assume 1–2% rescue rate)               │
  │     Bulk score+tailor: ~$5–15                                    │
  │     TOTAL ≈ $13–28/mo — at or just over budget                   │
  └─────────────────────────────────────────────────────────────────┘
      ▲
  ┌─────────────────────────────────────────────────────────────────┐
  │ TIER 4 — Input pipeline (today: this is the actual bottleneck)   │
  │   3,558 unscored, 11 tailored                                    │
  │   After backfill: ~500–1,000 apply-ready                         │
  └─────────────────────────────────────────────────────────────────┘
```

**Phase-by-phase ceiling progression:**

| After phase | Sustained applies/day | Why |
|---|---|---|
| Today | ~7 then dies | Claude session quota burns at 1.24M tokens/apply |
| Phase A (input backfill) | ~7 then dies | Apply pipeline still Claude-bound; backlog grown |
| Phase B (Direct Apply core, 3 adapters) | ~150–200 | Greenhouse/Lever/Ashby only; conservative caps |
| Phase C (Workday adapter + anti-block) | **~250–300** | Full 4-family coverage + cap discipline |
| Phase D (learning loop, post-launch) | ~280–320 | Same ceiling; reduces escalations + cost |

---

## 3. Architecture

```
                    ┌──────────────────────────────────────────────┐
                    │  worker_loop  (launcher.py — UNCHANGED top)   │
                    │  branches on apply_engine() ∈ {direct,claude} │
                    └────────────────────┬────────────────────────┘
                                          │ engine == "direct"
                                          ▼
        ┌────────────────────────────────────────────────────────────────┐
        │                        DRIVER  (deterministic)                 │
        │  1. CDP connect to existing headed Chrome (chrome.launch_chrome)│
        │  2. Tier-0 STOP check (eligibility, salary, location)           │
        │  3. ATS fingerprint → pick adapter                              │
        │       ┌────────────┬─────────┬────────┬──────────┐              │
        │       ▼            ▼         ▼        ▼          ▼              │
        │   Greenhouse    Lever     Ashby   Workday    (none)             │
        │   adapter      adapter   adapter  adapter   → rescue            │
        │       │            │         │        │          │              │
        │       └─────┬──────┴─────────┴────────┘          │              │
        │             ▼                                     ▼              │
        │     ┌──────────────────┐               ┌──────────────────┐    │
        │     │ Extract fields    │              │ Tier 3: Claude    │    │
        │     │ + content-keyed   │              │ rescue (cap'd)    │    │
        │     │ locator stamp     │              │ <2% of applies    │    │
        │     └──────┬───────────┘               └──────────────────┘    │
        │            ▼                                                    │
        │     ┌──────────────────────────────────────────────┐            │
        │     │           RESOLVER (tiered)                  │            │
        │     │  Tier 0 — profile binding (rules, ~70% fields)│           │
        │     │  Tier 1 — Q&A bank SQLite cache (~25%)        │           │
        │     │  Tier 2 — Gemini batch resolve (~5% novel)    │           │
        │     └──────────────────────────────────────────────┘            │
        │            ▼                                                    │
        │     Fill (humanized) → Verify → Submit → DONE check             │
        │            ▼                                                    │
        │     emit apply_outcome row (for v2 learner + dashboard)         │
        └────────────────────────────────────────────────────────────────┘

   Concurrent workers (4× on M1) — each pinned to ONE ATS family:
   ┌──────────┬──────────┬─────────┬──────────┐
   │ W0: GH   │ W1: Lvr  │ W2: Ash │ W3: Wd   │  ← prevents any one
   │ 75/day   │ 75/day   │ 75/day  │ 75/day   │     ATS seeing >75/day
   │ port 9222│ 9223     │ 9224    │ 9225     │     from single IP
   └──────────┴──────────┴─────────┴──────────┘
   Global submit spacing 30–90s jittered across all workers (shared lock).
```

### Why 4 workers when 1 IP

It's not for compute. The IP cap binds at the *per-ATS-family* level
(~75/day each). Running 4 workers in parallel, each pinned to a different
family, lets us sustain ~300/day total without any one fingerprint exceeding
75/day. A single worker rotating across families would do the same volume
but burst on each — the family-pinning prevents burst signatures.

---

## 4. Phased implementation

### Phase A — Input pipeline backfill (1–2 days, ~$10–15 Gemini)

**Goal:** queue depth goes from 11 → ~500 apply-ready jobs.

| Step | Files | Notes |
|---|---|---|
| A1. LinkedIn URL pre-pass | new `src/applypilot/discovery/linkedin_resolve.py`; reuses `apply/apply_url_extract.py::coerce_application_url` | Headless Playwright, no LLM. Follow LinkedIn → "Apply on company website" → final URL. Batch over the 3,614 rows, write `application_url` + `ats_vendor`. Throttle politely (5–10s between requests); LinkedIn's own bot wall is the constraint here. |
| A2. Bulk score backfill | extend existing `cli.py run score` to handle the 3,558 unscored | Already wired to Gemini. Just run it. ~$5. |
| A3. Bulk tailor backfill | extend existing `cli.py run tailor cover pdf` for `fit_score ≥ 5` | ~$10. Produces tailored resumes for top ~500 jobs. |
| A4. WAL mode on SQLite | one `PRAGMA journal_mode=WAL` in `database.py::init_db` | Prevents `database is locked` once 4 workers write to qa_bank concurrently. |

**Exit criterion:** `count(jobs where tailored_resume_path is not null and applied_at is null) ≥ 500`.

### Phase B — Direct Apply core (3–5 days)

**Goal:** Driver/Resolver + Greenhouse + Lever + Ashby adapters live behind `--engine direct`.

```
src/applypilot/apply/direct/
├── driver.py              # state machine §5 of architecture doc
├── extractor.py           # extended FORM_VERIFY_JS (iframes, shadow DOM, role=combobox)
├── resolver.py            # tier orchestration
├── profile_binding.py     # Tier 0 rule table (port FIELD MAP / QUESTION MAP)
├── qa_bank.py             # Tier 1 cache (SQLite)
├── gemini_resolver.py     # Tier 2 batch resolve
├── humanize.py            # typing/hover/pacing
├── adapters/
│   ├── __init__.py        # fingerprint → adapter dispatch
│   ├── greenhouse.py      # boards.greenhouse.io selectors
│   ├── lever.py           # jobs.lever.co selectors
│   └── ashby.py           # jobs.ashbyhq.com selectors (GraphQL submit path optional)
└── escalation.py          # Tier 3 rescue (calls existing run_job)
```

**DB additions** (`database.py::init_db`, idempotent `CREATE TABLE IF NOT EXISTS`):
- `qa_bank` — schema from §7 of architecture doc (label + section + name_attr keyed)
- `apply_outcomes` — minimal: `url`, `fingerprint`, `result`, `elapsed_ms`, `tier_resolved_via`, `escalated`, `created_at`. Powers v2 learner and the success-metric dashboard.

**Launcher branch** ([launcher.py:931](src/applypilot/apply/launcher.py:931)):

```python
if apply_settings.apply_engine() == "direct":
    from applypilot.apply.direct.driver import apply_via_playwright
    return apply_via_playwright(job, port=port, worker_id=worker_id, profile=profile)
# else: existing Claude path stays as rescue fallback
```

**`apply_settings.py` additions:**
```python
def apply_engine() -> Literal["direct","claude"]:
    return _env_str("APPLYPILOT_APPLY_ENGINE", "direct")

def max_per_ats_family_per_day() -> int:
    return int(_env_str("APPLYPILOT_MAX_PER_ATS_FAMILY_PER_DAY", "75"))

def max_per_apex_domain_per_day() -> int:
    return int(_env_str("APPLYPILOT_MAX_PER_APEX_DOMAIN_PER_DAY", "25"))

def submit_spacing_seconds() -> tuple[int,int]:
    return (30, 90)  # min, max — jittered uniform

def worker_ats_family_binding(worker_id: int) -> str | None:
    # W0→greenhouse, W1→lever, W2→ashby, W3→workday; None = no pin
    ...

def claude_rescue_daily_budget_usd() -> float:
    return float(_env_str("APPLYPILOT_CLAUDE_RESCUE_DAILY_BUDGET", "0.50"))
```

**Pre-seed Q&A bank:** new `cli.py --seed-qa-bank` reads `config/common_questions.yaml`
(curated ~80 questions covering work auth, EEO, salary, name/email, common screening).
One Gemini batch call. Run once.

**Exit criterion:** `applied:greenhouse + applied:lever + applied:ashby > 50` total
on the backfilled queue, with `failed:claude_quota_exhausted = 0`.

### Phase C — Workday adapter + anti-block discipline (3–4 days)

**Workday adapter** — `direct/adapters/workday.py`. Workday uses stable
`data-automation-id` attributes; the multi-step flow is predictable
(My Information → My Experience → Application Questions → Voluntary Disclosures
→ Self Identify → Review). Per-step extractor + resolver pass. Save state
per step in `apply_outcomes`. Implement file upload (resume + cover) via
their standard hidden `<input type="file">`. Handle the "create account"
wall by detecting it and escalating to manual.

**Anti-block layer** (`direct/humanize.py` + new `direct/throttle.py`):

```python
# direct/throttle.py
class IpReputationGate:
    """Enforces per-ATS-family / per-apex-domain daily caps and global spacing.
       SQLite-backed counters reset at local midnight."""

    def claim_slot(self, ats_family: str, apex_domain: str) -> ClaimResult:
        # returns one of: ALLOW, DEFER_FAMILY_CAP, DEFER_DOMAIN_CAP, DEFER_SPACING
        # caller waits, retries, or releases the job
```

```
Per-form humanization layer (already partial in playbook prompts):
- Text fields: locator.press_sequentially(value, delay=randint(60,140))
- Click sequence: scroll_into_view_if_needed → hover → uniform(0.1,0.4) → click
- Inter-field pause: gauss(0.6, 0.25) clipped to [0.2, 1.5]
- Random order of independent fields when safe
- Occasional no-op scroll (1 in ~5 forms)

Tab/profile isolation per ATS family:
- Each worker's Chrome profile dir is family-specific
  (chrome-workers/worker-0-greenhouse, etc.)
- Cookies, fingerprint surfaces, local storage stay scoped per family
- Re-use across applies within the family (warm trust signals)
```

**Time-of-day distribution:**
Worker loop respects `APPLYPILOT_APPLY_HOURS` (default `08:00-19:00 local`).
Outside the window, workers idle. Prevents 2am burst signature.

**Claude rescue budget cap:**
Daily token-cost check before any Tier-3 escalation; if today's cost
> `claude_rescue_daily_budget_usd()`, mark job `failed:budget_exhausted` and
move on. Powered by `llm_usage_events` aggregation (already recorded by
`record_llm_usage`).

**Exit criterion:** 7 consecutive days at ≥150 applies/day with 0 cloudflare/site
block events and captcha rate <5%.

### Phase D — Learning loop (v2, not blocking launch)

Add `direct/learner.py`, `direct/replay.py`, `direct/provider_profile.py` from
§10 of the architecture doc. Provider profiles freeze per fingerprint; the
escalation rate trends to ~0% per learned vendor. This is *cost reduction*,
not ceiling increase — defer until Phase C is stable.

---

## 5. Caching & hardcoding catalog (every lever, ranked)

| Cache | Hit rate (steady state) | Storage | Saves |
|---|---|---|---|
| **Per-job `application_url` resolution** (LinkedIn → ATS) | 100% after backfill | `jobs.application_url` column | ~3s + 1 page load per apply |
| **Per-ATS adapter (Greenhouse/Lever/Ashby/Workday)** | 100% on covered ATSes | code | full Claude agent loop (~$0.10–1) |
| **Q&A bank — generic questions** (work auth, EEO, name/email) | ~95% after warm-up | `qa_bank` SQLite | 1 Gemini call per field |
| **Q&A bank — scalar with context** (years of experience with X) | ~70% | `qa_bank` keyed on (label, section, name_attr, type) | 1 Gemini call per field |
| **Q&A bank — company templates** (why this role, why this company) | template cached, answer re-rendered | `qa_bank` row with `answer_type='template'` | nothing per call (always re-renders), but prevents boilerplate slop |
| **Tailored resume PDF** | already cached per job | filesystem | already in place |
| **Resume PDF for company-specific cover** | reused | filesystem | already in place |
| **Provider profile freeze** (v2) | 100% per frozen ATS | `provider_profile` table | last few Gemini calls per vendor |
| **DOM fixture corpus** (v2, sampled 1-in-20 success + all failures) | learner replay validation | `dom_fixtures` table | enables safe profile delta promotion |

**Hardcoded paths (no LLM whatsoever in steady state):**
- ATS family detection: URL pattern match (already in `eligibility.ATS_URL_MARKERS`)
- All form fields on covered ATSes: deterministic selectors
- Profile values: from `worker_playbook.build_playbook_tokens()` (already exists)
- File upload: standard `set_input_files()` on each adapter
- Submit detection: adapter-specific success URL/text patterns

---

## 6. Anti-IP-blocking discipline (the success-metric directly)

Ranked by leverage against your single residential IP:

| Lever | Default | Override |
|---|---|---|
| Per-ATS-family daily cap | 75 | `APPLYPILOT_MAX_PER_ATS_FAMILY_PER_DAY` |
| Per-apex-domain daily cap | 25 | `APPLYPILOT_MAX_PER_APEX_DOMAIN_PER_DAY` |
| Global submit spacing | uniform(30,90)s | hardcoded; tune in `direct/throttle.py` |
| Per-form humanization | on | `APPLYPILOT_HUMANIZE_ENABLED` |
| Tab/profile per ATS family | on | structural — worker→family pin |
| Operating-hours window | 08:00–19:00 local | `APPLYPILOT_APPLY_HOURS` |
| CAPTCHA threshold for backoff | 3 captchas in a row on same ATS family → pause family 24h | hardcoded |
| Captcha rate alert | >5% over 50 applies → halt run, dashboard warning | hardcoded |

**No proxy rotation, no NordLayer routing, no User-Agent spoofing.** Real Chrome
profile + real cookies + real IP are higher-trust signals than any anti-detect
trick. The discipline is volume shaping, not impersonation.

---

## 7. NOT in scope

| Item | Why deferred |
|---|---|
| Residential proxy pool | Cost cap excludes ~$100/mo proxy bill |
| NordLayer-based IP rotation | NordLayer exits are datacenter — flagged faster than home IP; net negative |
| iCIMS, Taleo, SmartRecruiters, BambooHR adapters | Long-tail; mark `manual_only`; add only if data shows them in your top-20 destinations |
| CapSolver Python port | Defer until captcha rate exceeds 5% in production — may never trigger on covered ATSes |
| Per-ATS learning loop / declarative profile freeze | v2 cost-reduction, not ceiling-lift |
| New discovery sources (HN, WAAS, funded-startup) | Existing 3,671-job pool is 30× the daily ceiling |
| Workday Tier-3 escalation to Claude | Workday adapter direct; no rescue |
| Multi-machine egress | Out of single-Mac scope |
| Gmail-MCP verification code reading | Already wired; no changes |
| Cover letter regeneration | Existing pipeline works |
| Web dashboard redesign | Existing dashboard sufficient |

---

## 8. What already exists (reused, not rebuilt)

| Capability | Lives in | Status |
|---|---|---|
| Chrome lifecycle + CDP + persistent profile | [apply/chrome.py](src/applypilot/apply/chrome.py) | reused as-is |
| Form-verify JS / field extractor | [apply/prompt_scripts.py::FORM_VERIFY_JS](src/applypilot/apply/prompt_scripts.py) | extend with iframe/shadow walk + content-key + options enum |
| Profile-token rendering | [apply/worker_playbook.py::build_playbook_tokens](src/applypilot/apply/worker_playbook.py) | reused — Tier 0 values come from here |
| Eligibility / salary / location gates | [apply/eligibility.py](src/applypilot/apply/eligibility.py), [apply/salary.py](src/applypilot/apply/salary.py) | reused at Driver step 3 (STOP check) |
| ATS family detection | `apply/eligibility.py::ATS_URL_MARKERS` | reused for fingerprint base |
| URL coercion for LinkedIn-style apply links | [apply/apply_url_extract.py](src/applypilot/apply/apply_url_extract.py) | reused in Phase A1 |
| LLM client + usage telemetry | [llm.py::get_client](src/applypilot/llm.py), `database.py::record_llm_usage` | reused for Gemini Tier-2 and for budget cap enforcement |
| Apply result vocabulary | [apply/playbook_results.py](src/applypilot/apply/playbook_results.py) | reused — Driver returns identical strings |
| Quota backoff + parked retry | `launcher._park_job_for_retry`, `_pause_worker_for_quota` | reused as safety net for the rare Claude rescue |
| Dashboard / state / events | [apply/dashboard.py](src/applypilot/apply/dashboard.py), `server/` | extended with `apply_outcomes` aggregations |
| Stale-lock release | `launcher.release_stale_locks` | reused; reduce timeout from 45min → 10min for faster recovery |

**Code already partially solving the problem:** the playbook prompts already
have the right shape — STOP table, FIELD MAP, QUESTION MAP, DONE table. The
work is porting them from English-in-prompt to Python rules + executable
Playwright. Not greenfield.

---

## 9. Failure modes (per new codepath)

| Codepath | Realistic failure | Test? | Error handling? | User sees? |
|---|---|---|---|---|
| LinkedIn URL pre-pass | LinkedIn shows a login wall mid-batch | unit test on the dedup logic; integration on a small batch | back off and resume; mark `application_url=null, apply_status=manual` if walled 3× | dashboard counter `linkedin_walled` |
| Greenhouse adapter | Greenhouse changes a selector | snapshot DOM fixture in tests | escalate to rescue; alert on dashboard if >5/day | `failed:adapter_drift:greenhouse` |
| Lever adapter | Lever multi-page resume parser auto-fills wrong fields | per-field assert after fill | verify pass detects mismatch → re-resolve or escalate | `failed:verify_mismatch` |
| Ashby adapter | Ashby GraphQL endpoint returns 4xx | covered in adapter unit test | fall back to form-fill path | tier_resolved_via=form |
| Workday adapter | Multi-step form has a step the adapter doesn't know about | step-detection unit test | escalate at unknown step | `failed:workday_unknown_step` |
| Resolver Tier 1 cache | Wrong cached answer because section_header missing | normalization test on collision case | `answer_type` mismatch detected at fill → re-resolve | tier_resolved_via=gemini |
| Resolver Tier 2 Gemini | Rate limit / 5xx | retry test | 2 retries with backoff, then escalate | `failed:resolver_unavailable` |
| Tier 3 rescue | Claude budget exhausted mid-job | budget gate test | mark `failed:budget_exhausted`; don't burn the job permanently — retry tomorrow | dashboard counter |
| Throttle gate | All 4 ATS families at cap | unit test on counter rollover | worker idles until next family slot opens or midnight | dashboard `idle:family_cap` |
| Captcha streak detector | 3 captchas in a row on Greenhouse | unit test on streak logic | pause Greenhouse for 24h; workers re-bind | dashboard alert |
| `apply_outcomes` write | Concurrent worker write under load | concurrency test (4 threads) | WAL mode + short transactions | none |

**Critical gap surfaced:** Tier-3 rescue + budget cap interaction. If 5 jobs in
a row need rescue and one rescue consumes today's $0.50 daily Claude budget, the
next 4 jobs immediately fall through to `failed:budget_exhausted` without any
attempt. That isn't a bug, but it does mean rescue is binary per day. Test that
the dashboard surfaces this clearly so the user can manually intervene.

---

## 10. Test coverage diagram

```
src/applypilot/apply/direct/
├── driver.py
│   ├── apply_via_playwright()
│   │   ├── [★★★ TEST] happy path (mocked extractor + resolver, real DOM fixture)
│   │   ├── [★★★ TEST] STOP-table early returns (salary/location/expired)
│   │   ├── [★★  TEST] multi-step Next-button loop
│   │   ├── [★★★ TEST] escalation on adapter failure
│   │   └── [★★  TEST] budget cap on rescue
├── extractor.py
│   ├── walk_frames() — recursion into iframes + shadowRoot
│   │   ├── [★★★ TEST] vanilla Greenhouse form
│   │   ├── [★★★ TEST] Workday nested iframe form
│   │   ├── [★★  TEST] role=combobox synthetic field emission
│   │   └── [GAP] [→FIXTURE] canvas-widget detection → partial flag
├── resolver.py
│   ├── resolve() — tier orchestration
│   │   ├── [★★★ TEST] Tier 0 hit (full coverage rule table)
│   │   ├── [★★★ TEST] Tier 1 cache hit + collision (Email under Referrer vs Personal)
│   │   ├── [★★  TEST] Tier 2 single batch call
│   │   └── [★★  TEST] Tier 2 retry + escalate after N
├── qa_bank.py
│   ├── normalize_key() — (label, section, name_attr, answer_type)
│   │   ├── [★★★ TEST] "Total years of experience" vs "Years with Python" distinct
│   │   └── [★★★ TEST] template rows never serve cached prose
├── adapters/
│   ├── greenhouse.py — fingerprint, fill order, submit detection
│   │   ├── [★★★ TEST] fixture: 3 real Greenhouse forms (different companies)
│   │   └── [★★  TEST] adapter-drift sentinel (selector missing → escalate)
│   ├── lever.py
│   │   └── [★★★ TEST] fixture: 3 real Lever forms
│   ├── ashby.py
│   │   └── [★★★ TEST] fixture: 3 real Ashby forms
│   └── workday.py
│       ├── [★★★ TEST] fixture: 5 real Workday forms (different step counts)
│       └── [★★★ TEST] step-detection unit test (per-step section IDs)
├── throttle.py
│   ├── IpReputationGate.claim_slot()
│   │   ├── [★★★ TEST] per-family cap enforced across 4 workers
│   │   ├── [★★★ TEST] per-domain cap (one company)
│   │   ├── [★★★ TEST] global spacing jitter
│   │   └── [★★★ TEST] midnight rollover
├── humanize.py
│   └── [★★  TEST] timing distributions (gauss + uniform bounds)
└── escalation.py
    ├── [★★★ TEST] budget cap blocks rescue when exceeded
    └── [★★  TEST] should_escalate triggers (all §8 conditions)

src/applypilot/discovery/linkedin_resolve.py
├── [★★★ TEST] LinkedIn → ATS URL extraction on 5 saved HTML fixtures
├── [★★  TEST] login-wall detection
└── [★★  TEST] dedup logic (don't re-resolve already-resolved)

E2E (slow, opt-in via marker):
├── [★★★ E2E] Full apply on a Greenhouse demo job (write to a sandbox)
├── [★★★ E2E] Full apply on a Lever demo job
└── [★★  E2E] Multi-worker concurrent run with throttle gate

COVERAGE TARGET: every adapter has 3+ real-form fixtures.
REGRESSION RULE: each fixture survives any selector change before promotion.
```

---

## 11. Performance / cost ledger (steady-state, 300 applies/day, 30-day month)

| Item | Volume | Cost |
|---|---|---|
| Gemini Tier-2 resolves | ~10% of forms × 9,000 applies = 900 calls × $0.001 | ~$1 |
| Gemini company-template renders | ~9,000 × $0.0001 (assuming each apply has 1–2 templated answers) | ~$1–2 |
| Claude rescue | 1–2% × 9,000 applies = 90–180 rescues × ~$0.05 each (capped by `claude_rescue_daily_budget_usd`) | ~$5–10 |
| Bulk score backfill | one-time | ~$5 |
| Bulk tailor backfill | one-time | ~$10 |
| Incremental score/tailor on new discoveries | ~50/day × Gemini | ~$1 |
| **Total month 1** | | **~$23–29** |
| **Total ongoing months** | | **~$7–13** |

Month 1 is at risk of exceeding the $20 cap because of the one-time backfills.
Mitigation: spread bulk tailor across 2 months, or accept $25 once.

Compute: peak CPU ~40% across 4 cores with 4 headed Chromes; peak memory
~10–12 GB (well under 16 GB). M1's 4 performance cores handle this comfortably.

---

## 12. Open risks & unresolved

| Risk | Mitigation in plan | Residual |
|---|---|---|
| Single IP gets flagged by Cloudflare anyway at 250+/day | Per-family + per-domain caps + spacing + family-pinning | medium — only real fix is IP diversity |
| Workday adapter complexity blows scope | Time-box Workday to 3 days; if it slips, ship Phase B without it (~200/day instead of 300) | known tradeoff |
| LinkedIn detects the URL pre-pass crawler | Polite spacing (5–10s), real Chrome profile, run during LinkedIn-active hours | small batch fallback if walled |
| `apply_form_filled` JSON schema drift between Claude path and Direct path | Pin to existing `apply_log_parser.form_filled_from_log_text` shape | low |
| Tier-3 escalation budget interacts badly with multi-worker (concurrent rescues) | Daily budget check is atomic SQL aggregation on `llm_usage_events`; locks across workers | tested in Phase B |
| Recruiter spots template-rendered cover letter as Gemini-generated | Gemini Flash is good at this; keep it short; templates curated by user | qualitative |

---

## 13. Implementation tasks (T-numbered, derived from this plan)

- [ ] **T1 (P1, human: ~4h / CC: ~30min)** — `database.py` — add WAL mode + create `qa_bank`, `apply_outcomes` tables
  - Surfaced by: §4 Phase A4, §3 architecture
  - Files: `src/applypilot/database.py`
  - Verify: `pytest tests/test_database_concurrent_writes.py`

- [ ] **T2 (P1, human: ~1d / CC: ~2h)** — `discovery/linkedin_resolve.py` — LinkedIn → ATS URL backfill
  - Surfaced by: §4 Phase A1; backlog shape (3,614 LinkedIn URLs)
  - Files: `src/applypilot/discovery/linkedin_resolve.py`, extend `cli.py`
  - Verify: backfill resolves ≥80% of 3,614 rows; run `applypilot discover resolve-urls --limit 50` smoke

- [ ] **T3 (P1, human: ~1h / CC: ~10min)** — bulk score + bulk tailor runner
  - Surfaced by: §4 Phase A2/A3
  - Files: extend `cli.py run score|tailor` for `--all-unscored` flag
  - Verify: `count(jobs where tailored_resume_path is not null) ≥ 500` after run

- [ ] **T4 (P1, human: ~2d / CC: ~6h)** — `apply/direct/extractor.py` — extended `FORM_VERIFY_JS` with iframes/shadow/content-key
  - Surfaced by: §3 architecture, §6 of architecture doc
  - Files: `src/applypilot/apply/direct/extractor.py`, audit all consumers of `FORM_VERIFY_JS`
  - Verify: `pytest tests/test_extractor_fixtures.py` against ≥10 saved DOM fixtures

- [ ] **T5 (P1, human: ~1d / CC: ~3h)** — `apply/direct/resolver.py` + `profile_binding.py` + `qa_bank.py`
  - Surfaced by: §3 architecture, §7 architecture doc
  - Files: as listed
  - Verify: Tier 0 covers ≥70% of fields on Greenhouse fixture; Tier 1 collision tests pass

- [ ] **T6 (P1, human: ~2d / CC: ~8h)** — adapters: Greenhouse, Lever, Ashby
  - Surfaced by: §4 Phase B
  - Files: `src/applypilot/apply/direct/adapters/{greenhouse,lever,ashby}.py`
  - Verify: 3 real-form fixtures per adapter pass end-to-end fill (without submit)

- [ ] **T7 (P1, human: ~1d / CC: ~3h)** — `apply/direct/driver.py` + launcher branch
  - Surfaced by: §3 architecture
  - Files: `src/applypilot/apply/direct/driver.py`, edit `launcher.py:931`
  - Verify: `APPLYPILOT_APPLY_ENGINE=direct applypilot apply --limit 5` produces ≥3 applied

- [ ] **T8 (P1, human: ~1d / CC: ~4h)** — `apply/direct/throttle.py` IpReputationGate
  - Surfaced by: §6, §3 worker pinning
  - Files: `src/applypilot/apply/direct/throttle.py`
  - Verify: 4-worker concurrent test respects per-family cap

- [ ] **T9 (P1, human: ~3d / CC: ~1d)** — Workday adapter (Phase C)
  - Surfaced by: §4 Phase C, 7/8 past failures are Workday
  - Files: `src/applypilot/apply/direct/adapters/workday.py`
  - Verify: 5 Workday fixtures (varying step counts) pass

- [ ] **T10 (P1, human: ~4h / CC: ~30min)** — humanize.py + tab/profile isolation per family
  - Surfaced by: §6
  - Files: `src/applypilot/apply/direct/humanize.py`, edit `chrome.py::setup_worker_profile`
  - Verify: timing distribution unit test; 4 workers' profile dirs are family-tagged

- [ ] **T11 (P2, human: ~4h / CC: ~1h)** — Claude rescue budget cap
  - Surfaced by: §9 critical gap, §6
  - Files: `apply/direct/escalation.py`, query `llm_usage_events`
  - Verify: budget-exhausted simulation test

- [ ] **T12 (P2, human: ~4h / CC: ~1h)** — pre-seed Q&A bank CLI
  - Surfaced by: §5 caching table; §4 Phase B exit criterion
  - Files: `cli.py --seed-qa-bank`, `config/common_questions.yaml`
  - Verify: post-seed query returns ≥80 rows with source='seed'

- [ ] **T13 (P2, human: ~1h / CC: ~15min)** — operating-hours window
  - Surfaced by: §6
  - Files: `apply_settings.py`, `launcher.worker_loop`
  - Verify: worker idles outside the window

- [ ] **T14 (P2, human: ~6h / CC: ~2h)** — apply_outcomes-backed dashboard panels (success rate, IP-block counters, captcha streak)
  - Surfaced by: success metric measurement
  - Files: extend `server/` views; new aggregations
  - Verify: live dashboard shows non-zero counters during a real run

- [ ] **T15 (P3, follow-up)** — Phase D learning loop (provider_profile + learner + replay)
  - Surfaced by: §4 Phase D
  - Files: `apply/direct/{learner,replay,provider_profile,strategy_registry}.py`
  - Verify: defer — separate plan once Phase C is stable

---

## 14. Parallelization across worktrees (for actual implementation)

| Lane | Steps | Why grouped |
|---|---|---|
| **A — input** | T1, T2, T3 | DB schema + Phase A backfills; all touch `database.py`/`cli.py`/`discovery/`; sequential within lane |
| **B — driver core** | T4, T5, T6, T7 | All under new `apply/direct/`; T7 depends on T4–T6 |
| **C — anti-block** | T8, T10, T13 | Touch `apply_settings.py` + `direct/`; can start after T7 lands |
| **D — Workday** | T9 | Independent module under `direct/adapters/`; can run parallel with C |
| **E — ops/safety** | T11, T12, T14 | Touch dashboards + LLM telemetry; parallel with everything |

Conflict flag: lanes A and B both touch `database.py` (A for schema, B for `qa_bank` reads). Serialize T1 before T5/T6.

Execution order: A (T1 first) → B in parallel after T1 → C+D+E in parallel after B → ship.

---

## Review Summary

- Step 0 scope challenge: **scope reduced via 3 decisions** (single IP, hardcoded top-4 adapters, include input pipeline)
- Architecture: ASCII diagrams in §3; binding constraint identified (IP reputation, not LLM cost)
- Code quality: 12 new modules; all under one new package `apply/direct/` — coherent boundary, not sprawl. Reuses 11 existing modules verbatim.
- Tests: coverage diagram in §10. Fixture-driven approach for adapters (real DOM corpora). E2E gated on a marker.
- Performance: §11 cost ledger ($23–29 month 1, $7–13/mo steady state) — at the edge of $20 cap; user advised.
- NOT in scope: §7 (10 items deferred with rationale).
- What already exists: §8 (11 reused modules listed).
- Failure modes: §9 — 11 codepaths × failure × mitigation; 1 critical gap surfaced (rescue+budget interaction → mitigated by dashboard).
- Unresolved decisions: none — all 3 scope gates closed in this review.
- Outside voice: skipped (single-session inline review).

**Verdict:** READY TO IMPLEMENT. Recommend Lane A as the first PR (no risk to existing apply path).
