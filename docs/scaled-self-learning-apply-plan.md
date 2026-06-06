# Scaled Self-Learning Apply — Engineering Plan

Status: planned (reviewed via /plan-eng-review)
Branch: main
Design input: [docs/self-learning-apply-architecture.md](self-learning-apply-architecture.md)

## Goal

Run ~300 real job applications/day on the local machine (M1/16GB), handling any
form type and any browser interaction, on a cheapest-first escalation ladder:
hand-built top-10 ATS adapters and a local $0 cache (exact + similarity) do the
bulk, Gemini handles novel states (text, then vision only when the DOM is blind),
Claude is the rare last resort, and a human queue clears the genuinely-hard tail.
Every non-$0 action and every LLM suggestion is logged so the owner can review it,
spot duplicates, and promote good fixes into permanent $0 behavior. The
deterministic layer gets more flexible over time as one-off LLM fixes graduate
into the learned cache and, nightly, into reusable workflows.

## Locked decisions (from review)

| # | Decision | Choice |
|---|----------|--------|
| Step0 | Build scope | Learning spine + review log + **top-10 ATS Tier-0 adapters** (the 80/20 $0 lever, revised after prior-art survey). Defer only the long-tail adapters (let them graduate from data) + account-creation. |
| 5 | Decision substrate | Behavior-tree **Fallback** ladder (`py_trees`-style): tiers are pluggable children, escalate on miss. DOM-first, vision-last. ML tier deferred as a future child. |
| 9 | Memory + matching | Exact hash (1a) + **local-embedding nearest-neighbor CBR** (1b, all-MiniLM, `sqlite-vss`); adopt Stagehand action-caching + Agent-Workflow-Memory induction rather than inventing. |
| 1 | Replay trust | Confidence-gated replay (promote after K≥2 successes, auto-retire on failure). **Submit is NEVER replayed from cache** — fires only after deterministic validation. Owner can pin/ban. |
| 2 | Owner review surface | Extend the React dashboard now (a "Learning" tab), backed by review-log + playbook tables. Thin CLI hooks for scripting. |
| 3 | Scale model | 2-3 visible Chrome worker pool, jittered pacing, reuse `throttle.py` per-apex-domain (25/day) + per-family (75/day) caps. |
| 4 | Action module | One `apply/direct/actions.py` dispatch table; executor + recorder + replayer share it. Dedupes today's two identity-hint copies. Contract carries typed page-state + field objects + **postconditions** (Codex #9) so the extraction does not regress ATS-specific safety. |
| 6 | Build order | Replay-now behind the confidence gate (kept over Codex's record-only-first). |
| 7 | Signature scope | **Narrow default**: `ats_family + apex_host + step_name + state_flags`. Separate evidence-gated "generalize to family-wide" promotion after the same action succeeds on N≥3 distinct hosts. Schema carries `signature_version` + preconditions (Codex #2/#3). |
| 8 | Promotion proof | **Receipt-weighted**: Gmail receipt (`apply_status='applied'`) = strong; page-state advance = weak; submit-rejected = negative. Promote on 1 receipt-confirmed run OR K≥3 weak-positive with zero negatives (Codex #6). |

### Codex outside-voice refinements folded in (no separate decision)

- **#1 Workday is gated before the driver.** `launcher.py:1865` parks non-adapter,
  non-`unknown` families before `apply_via_direct()` runs. A Workday seed is dead
  until that gating lets generic+unblock attempt adapter-less families. New **T0**.
- **#4 Broaden the submit carve-out.** Not just `submit()` — NO side-effecting nav
  (`next_page`, `apply`, `login_provider`, OAuth, `goto`) is replayed from cache
  until its entry is trusted, and `goto` actions carry an **origin allowlist**
  (same apex/ATS only) so a cached navigation can never jump off-site.
- **#8 Worker pool already exists** (`launcher.py:2533` ThreadPoolExecutor). T6 is
  not "build a pool" — it is shared rate-limiting, Chrome profile isolation, a
  global Gemini backoff, and SQLite write-contention handling.
- **#10 `field_strategy` key** follows the qa_bank lesson: `label+section+name+type`
  + `ats_family`, never a vague `field_sig`.
- **#11 `review_log` is the rich event schema**, not a thin row (see schema below).
- **Reality check (Codex #7):** the cache is necessary, not sufficient, for 300/day.
  The actual ceiling is job supply, auth/session state, rate limits, verification
  emails, CAPTCHA/Cloudflare, and submission confirmation. The plan tracks those as
  first-class park reasons; the cache only removes the LLM-cost and navigation-repeat
  tax, it does not by itself guarantee 300 completions.

## What already exists (reuse, do not rebuild)

| Capability | Where | Plan use |
|---|---|---|
| Greenhouse/Lever/Ashby adapters | `apply/direct/adapters/*` | The Tier-0 pattern; 3 of the top-10 ATS already done — extend, don't invent |
| Field-answer Tier-1 cache | `apply/direct/qa_bank.py` | Template for `playbook.py` (1a) + `field_strategy`; keep as-is for field answers |
| Tiered resolve (rules→cache→Gemini) | `apply/direct/resolver.py` | Add field_strategy write-back |
| Gemini navigation tier | `apply/direct/unblock.py` (built today) | Add replay-before-Gemini + record |
| Deterministic fill/submit + multi-step | `apply/direct/driver.py` (built today) | Route primitives through `actions.py` |
| Per-job filled-field record | `jobs.apply_form_filled` column | Superseded/extended by `review_log` |
| Outcome ledger | `apply_outcomes` table | Feeds `last_verified_at` confidence |
| Owner field corrections (Tier -1) | `field_overrides` + `correct-field` CLI | Extend to pin/ban nav recipes |
| Worker pool, orchestration, parking, never-stop | `apply/launcher.py` (ThreadPoolExecutor :2533) | Pool EXISTS; add jitter + shared rate-limit + global backoff (Codex #8) |
| Claude budget governor | `apply/apply_budget.py` | Tier-3 gate, unchanged |
| Gemini client + cost + usage ledger | `llm.py` + `llm_usage_events` | Cost telemetry per tier |
| Per-family/per-domain daily caps | `apply/direct/throttle.py` | The 300/day governor |

## Architecture

### Tiered resolution (one model, three decision classes)

```
                         ┌─────────── decision classes ───────────┐
                         │  WHAT to answer   HOW to fill   HOW to  │   cost / speed
                         │  a field          a field       navigate│
  Tier -1  owner pin/ban │  field_overrides  field_overrides  playbook(pinned)   $0   instant, wins
  Tier  0  ATS adapter   │  ──── hand-built top-10 ATS deterministic path ────   $0   fastest (80/20)
  Tier  0r rules         │  profile_binding  driver rules    actions defaults     $0   instant
  Tier  1a exact cache   │  qa_bank          field_strategy  nav_playbook(hash)   $0   O(1) lookup
  Tier  1b similar cache │  ── local-embedding nearest-neighbor case (CBR) ──     $0   ~5ms local NN
  Tier  2t Gemini (text) │  novel field/quirk/state (DOM snapshot)         ~$0.003-0.01  WRITE-BACK
  Tier  2v Gemini (vision)│ DOM-blind only: shadow-DOM/canvas/iframe (Set-of-Marks) ~$0.01-0.03 slower, WRITE-BACK
  Tier  3  Claude        │  ── only when Gemini fails / quota ──            rare,  WRITE-BACK
  Tier  4  human queue   │  ── owner clears the genuinely-hard tail (RPA-style) ──   review-time
                         └─────────────────────────────────────────┘
  First hit wins. DOM-first, vision-LAST (vision is slower + costlier). Tiers 2/3
  ALWAYS write back to Tiers 0r/1 → cheaper and faster every run. The $0 tiers
  (-1..1b) should serve the large majority of decisions once warm.
```

### Per-job control flow

```
acquire job (launcher pool, 2-3) ──► open Chrome (visible, own profile)
       │
       ▼
   ┌─────────────────────  PAGE LOOP (multi-step)  ─────────────────────┐
   │  snapshot ─► build state: signature(hash) + local embedding         │
   │     │                                                               │
   │     ▼   DECIDE-NEXT-ACTION  (behavior-tree Fallback: cheapest first)│
   │   ┌──────────────────────────────────────────────────────────────┐ │
   │   │ T0  ATS adapter (Workday/GH/Lever/...) ─hit─► actions.execute  │ │  $0
   │   │ T-1 owner pin   ───────────────────────hit─► actions.execute  │ │  $0
   │   │ T1a exact playbook hash ───────TRUSTED─hit─► actions.execute  │ │  $0
   │   │ T1b local-NN similar case ─sim≥θ, adapt─────► actions.execute  │ │  $0 ~5ms
   │   │ T2t Gemini (DOM snapshot) ──────────────────► record(trial)    │ │  ~$0.005
   │   │ T2v Gemini vision (only if DOM blind) ──────► record(trial)    │ │  ~$0.02
   │   │ T3  Claude (Gemini quota/fail) ─────────────► record(trial)    │ │  rare
   │   │ T4  park → owner human queue (RPA-style) ───────────────────── │ │
   │   └───────────────────────────┬──────────────────────────────────┘ │
   │     every non-$0 tier ────────┴──► review_log (suggestion + before/ │
   │                                    after + outcome + cost)          │
   │     ▼                                                               │
   │  is_form_ready? ──no──► (loop: navigate/login/cookies/next)         │
   │     │ yes                                                           │
   │     ▼                                                               │
   │  field fill (resolver: T0 rules→T1a qa_bank→T1b sim→T2 Gemini)+upload│
   │  identity guard + required-field VALIDATION                         │
   │     │                                                               │
   │     ├─ advance button? ──► actions.next_page ──► (loop next page)   │
   │     └─ final page ──► submit()  ◄── NEVER from cache; only after    │
   │                                     deterministic validation passes │
   └─────────────────────────────────────────────────────────────────────┘
       │
       ▼
   outcome (applied / parked:reason) ─► apply_outcomes + feedback(receipt-weighted)
       │                                         │
       └─ park & continue on any tier exhaustion └─ promote/retire/generalize entries
```

### Self-learning loop (model-free, tabular)

```
  resolve(state):                                         (Fallback, cheapest-first)
     T0  ATS adapter matches family+step ──► action        $0
     T1a exact hash trusted/trial        ──► replay         $0   (verify advanced)
     T1b local-NN case  sim ≥ θ          ──► reuse + adapt   $0   (re-map locator)
     else (miss/retired/sim<θ)           ──► Gemini → record(trial)   ~$0.005, logged
        Gemini DOM-blind                 ──► Gemini vision → record(trial)
        Gemini quota/fail                ──► Claude → record(trial)   rare

  feedback(receipt-weighted):
     success_receipt ≥ 1  OR  success_weak ≥ K(=3) with 0 negatives ──► promote 'trusted'
     same action succeeds on N≥3 distinct hosts ──► generalize scope 'host'→'family'
     recent_fail_rate > 0.5                      ──► retire (auto-heal, relearn)
  end-to-end 'applied' (Gmail receipt) ──► stamp last_verified_at on every step used
  owner ──► pin | ban | correct  |  nightly induction folds repeated Gemini chains
            into reusable workflows (AWM)
```

## Techniques adopted (tuned for $0 / speed / M1-16GB)

Prior art exists for every piece; we adopt the validated version instead of
inventing. Each technique below is chosen for **lowest cost + lowest latency on a
local 3-worker M1**, not maximum generality.

| Technique | From | Why it's the $0/fast choice here | Tier |
|---|---|---|---|
| **Top-10 ATS adapters (80/20)** | RPA practice; commercial apply tools | ~10 ATS (Workday, Greenhouse, Lever, iCIMS, Taleo, SuccessFactors, Ashby, SmartRecruiters, Jobvite, BambooHR) carry most postings. Hand-built deterministic paths are $0, fastest, most reliable. Single biggest cost lever. | 0 |
| **Action caching + self-healing replay** | Stagehand (Browserbase) | Cache the resolved selector/action; replay $0; call LLM only when the cached locator breaks. Exactly our replay-then-escalate, productionized. | 1a |
| **Local-embedding CBR retrieval** | Synapse; case-based reasoning | "Seen something similar?" via a LOCAL sentence-embedding (all-MiniLM-L6-v2, ~80MB, ~5ms/embed on M1) + `sqlite-vss`/`hnswlib` NN. $0, no API, generalizes across tenants more safely than a shared hash. | 1b |
| **Workflow induction (offline)** | Agent Workflow Memory (Wang 2024); Voyager skill library | Nightly batch job mines `review_log` trajectories, induces reusable multi-step workflows, promotes stable ones to `nav_playbook`. Compounding self-learning at $0 inference; training runs off the hot path. | 1 |
| **DOM-first, vision-LAST** | SeeAct / Set-of-Marks / OmniParser | Vision (VLM) is slower + costlier, so it is the LAST escalation, fired ONLY when DOM extraction is blind (shadow-DOM, canvas, iframe). Most pages never touch it. | 2v |
| **Prompt slimming / compiled prompts** | DSPy; existing `prompt_slim` | Smallest prompt that still resolves; fewer tokens per Gemini call on the calls we cannot avoid. | 2t |
| **Behavior-tree fallback substrate** | `py_trees`; BehaviorTree.CPP | The escalation ladder is a Fallback (OR) node; tiers are pluggable children. Adding the vision or ML tier later is inserting a child, not rewriting control flow. | all |
| **Deferred: imitation/bandit policy** | ExpeL; CC-Net; Vowpal Wabbit | A learned action-ranker trained on logs. Earns its keep only after thousands of episodes; slots in as one Fallback child. Not built first. | (later) |

### Cost/speed ordering rule (the whole $0 thesis)

```
per decision:  cheapest + fastest first, escalate only on miss
  Tier 0  ATS adapter   ── $0, ~0ms decision (deterministic selector)
  Tier 0r rules         ── $0, ~0ms
  Tier 1a exact hash    ── $0, O(1) SQLite PK
  Tier 1b local NN      ── $0, ~5ms (local embed, no network)
  Tier 2t Gemini text   ── ~$0.003-0.01, ~1-3s  (network RTT dominates, not compute)
  Tier 2v Gemini vision ── ~$0.01-0.03, ~3-6s   (screenshot + larger response)
  Tier 3  Claude        ── ~$0.15 + burns weekly cap, seconds
  Tier 4  human queue   ── owner time, async
GOAL: after warm-up, >90% of decisions resolve in Tiers 0..1b ($0, sub-10ms).
Gemini fires only on genuinely novel states; vision only when the DOM is unreadable.
```

### M1 / 16GB system tuning

- **One shared local embedding model** (MiniLM) loaded once per process, reused by
  all 3 workers via an in-process cache; never re-load per job. ~80MB resident.
- **Lazy-load the vision path.** Never load a VLM/screenshot pipeline unless Tier 2v
  fires. Keeps the steady-state RAM footprint to Chrome (3 × ~0.5GB) + Python.
- **SQLite in WAL mode**, one connection per worker, short write txns; the playbook
  and review_log writes must not block the fill loop (Codex #8 contention point).
- **3 visible Chrome workers max** on 16GB (each ~0.5GB + page). 4+ risks swap; M1
  has 8 cores so CPU is not the limit, RAM and browser wall-clock are.
- **Embeddings batched** off the hot path (compute the state embedding once per
  snapshot, reuse for both exact-sig and NN). The nightly induction job is the only
  heavy compute and runs when no apply workers are active.

## Data model (SQLite, mirrors qa_bank)

```sql
CREATE TABLE nav_playbook (
  state_sig        TEXT,               -- sha1(sig_version|ats_family|apex_host|step_name|state_flags|preconditions)
  sig_version      INTEGER,            -- bump to invalidate a whole signature generation (Codex #3)
  scope            TEXT,               -- 'host' (narrow, default) | 'family' (generalized after N≥3 hosts)
  ats_family       TEXT,
  apex_host        TEXT,               -- NULL when scope='family'
  step_name        TEXT,               -- nullable; for known multi-step ATS
  preconditions    TEXT,               -- JSON: state_flags the recipe asserts (has_form/has_pw/already_applied/...)
  action_type      TEXT,               -- one primitive from actions.py
  action_args      TEXT,               -- JSON
  side_effecting   INTEGER,            -- 1 = stateful nav (next/apply/login/goto/submit): replay only when trusted
  goto_allowlist   TEXT,               -- JSON apex/ATS origins a cached goto may target (Codex #4)
  status           TEXT,               -- 'trial' | 'trusted' | 'retired' | 'banned' | 'pinned'
  promote_score    REAL,               -- receipt-weighted (Codex #6)
  success_weak     INTEGER DEFAULT 0,  -- page-state advances
  success_receipt  INTEGER DEFAULT 0,  -- Gmail-confirmed 'applied' runs
  distinct_hosts   INTEGER DEFAULT 0,  -- for family-wide generalization gate (N≥3)
  fail_count       INTEGER DEFAULT 0,
  source           TEXT,               -- 'gemini' | 'claude' | 'seed' | 'owner'
  created_at TEXT, last_used_at TEXT, last_verified_at TEXT,
  PRIMARY KEY (state_sig, scope)       -- one row per (signature, scope); a state may hold >1 action across scopes
);

CREATE TABLE field_strategy (
  field_sig     TEXT, ats_family TEXT,
  fill_method   TEXT,                  -- 'value'|'click_label'|'react_select'|'press_sequentially'
  match_rule    TEXT,                  -- JSON option-match rule
  status        TEXT, success_count INT DEFAULT 0, fail_count INT DEFAULT 0,
  PRIMARY KEY (field_sig, ats_family)
);

CREATE TABLE review_log (                -- the owner's audit + dedupe surface (rich event schema, Codex #11)
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT, job_url TEXT, ats_family TEXT, apex_host TEXT,
  state_sig TEXT, scope TEXT,            -- dedupe key: GROUP BY state_sig = clusters
  step_index INTEGER,                    -- multi-step page number
  url_before TEXT, url_after TEXT,       -- before/after navigation (Codex #5/#11)
  frame_info TEXT,                       -- iframe/origin context
  tier TEXT,                             -- 'replay'|'gemini'|'claude'|'deterministic'
  action_type TEXT, action_args TEXT, locator TEXT,
  llm_suggestion TEXT,                   -- raw Gemini/Claude JSON (what it suggested)
  outcome TEXT,                          -- 'advanced'|'no_change'|'redirect_login'|'wrong_tab'|'error'
  postcondition_met INTEGER,             -- did the recipe's asserted postcondition hold
  receipt_status TEXT,                   -- '' | 'applied' | 'submitted_unverified'
  screenshot_path TEXT, failure_reason TEXT, cost_usd REAL
);
-- qa_bank, field_overrides already exist.
```

Signature correctness (the whole game, same lesson as `qa_bank.question_key`):
**narrow by default** — `sig_version | ats_family | apex_host | step_name |
state_flags | preconditions` — so a recipe is reused only on the same company/step
it was learned on. Generalization to family-wide (drop `apex_host`) is a SEPARATE,
evidence-gated promotion after the same action succeeds on N≥3 distinct hosts
(decision 7, Codex #2/#3). Cross-tenant reuse before that proof goes through the
softer **local-embedding similarity** tier (1b), not a shared hash, so a
DOM/locale difference degrades to "low similarity → escalate" instead of a
confident wrong replay.

## Action vocabulary — `apply/direct/actions.py` (the reusable functions)

Closed set so any recorded step is replayable with no LLM. Executor, recorder,
and replayer all dispatch through this one table:

```
Navigation: click(text) · accept_cookies() · login_provider(name) · goto(url)†
            · scroll() · wait_for_form() · next_page()†
Fill:       fill(field_sig,value) · select(field_sig,value) · check(field_sig)
            · set_phone(field_sig,e164) · upload(field_sig, resume|cover)
Terminal:   submit()                      ◄ NEVER cached; only after validation
Detect:     is_form_ready() · detect_login() · detect_verification_wall()

† side-effecting nav (next_page/apply/login/goto): replayed only when its entry is
  TRUSTED; goto carries an origin allowlist (same apex/ATS). submit() is never
  served from cache at all (Codex #4). Each primitive declares a postcondition the
  executor verifies, so a replay that did not actually advance is recorded as a
  failure, not a success (Codex #9).
```

## Owner review (React dashboard "Learning" tab)

- **Action timeline**: `review_log` rows, newest first, filter by tier/family/outcome.
- **Dedupe clusters**: `GROUP BY state_sig` with count — "Gemini suggested clicking
  'Apply now' on mokahr 12 times" surfaces as one promotable cluster.
- **Suggestion diff**: raw `llm_suggestion` vs the action actually taken.
- **Actions**: Promote (→trusted/pinned), Ban (→never replay), Correct (replace
  action). Writes to `nav_playbook.status` + `source='owner'`.
- Thin CLI mirror for scripting: `applypilot playbook list|review|promote|ban|correct`.

## Scale model (300/day local)

- 2-3 visible Chrome workers (memory: headless crashes real Greenhouse submits),
  each its own persistent profile so logins survive across days.
- Jittered pacing between actions/jobs; reuse `throttle.py` caps (25/apex-domain,
  75/family per day) so 300 spreads across companies, not concentrated on one IP.
- Continuous mode drains the queue; parked jobs retried after cooldown.
- Never-stop: any tier exhaustion (Gemini 429, Claude budget) parks the job and
  the pool keeps draining others (extends today's `GeminiQuotaExhausted` path).

## Failure modes (each new codepath)

| Codepath | Realistic prod failure | Test? | Error handling? | Owner sees? |
|---|---|---|---|---|
| playbook replay on stale recipe | site redesign → action clicks wrong thing | ★★★ retire-on-fail | auto-retire → relearn | yes (review_log outcome=no_change) |
| signature collision | two different problems → same sig → wrong replay | ★★★ collision test | confidence gate + retire | yes |
| cached submit (must never happen) | half-filled app submitted | ★★★ carve-out test | submit never cached + validation gate | n/a (prevented) |
| Gemini 429 mid-run | crash / hard stop | ★★ quota test | GeminiQuotaExhausted → park → continue | yes (parked) |
| advance-button mis-detect | clicks 'Submit' thinking it's 'Next' | ★★ | `_ADVANCE_DENY` excludes submit/apply/create-account | yes |
| CBR similar-case false match | reuses a neighbor recipe on a too-different page | ★★★ θ-threshold test | similarity ≥ θ gate + postcondition verify → fail→escalate | yes (review_log) |
| ATS adapter drift | site redesign breaks the Tier-0 adapter | ★★ | post-fill validation fails → fall through to Gemini, alert owner | yes (rising adapter-fail) |
| vision mis-click | VLM picks the wrong mark | ★★ | postcondition verify; vision is last-resort + low volume | yes |
| 300/day IP flag | Workday shadow-bans IP | manual | per-domain/family caps + jitter | yes (rising park rate) |

Critical-gap rule: a cached `submit()` would be silent + irreversible, so the
carve-out test is mandatory, not optional.

## Cost model (the thesis)

```
per-decision cost by tier:
  Tier 0 ATS adapter / 0r rules / 1a hash / 1b local-NN  =  $0      (target: >90% of decisions warm)
  Tier 2t Gemini text     ≈ $0.003-0.01   (flash-lite $0.04/$0.16 per M)   only on novel states
  Tier 2v Gemini vision   ≈ $0.01-0.03    DOM-blind pages only
  Tier 3  Claude          ≈ $0.15 + burns weekly cap                       rare last resort

warm-up curve (per job, amortized):
  day 1 (cold, no adapters)   ~$0.02-0.05/job   (Gemini drives most navigation)
  after top-10 ATS seeded     ~$0.005-0.015/job (80% hit a $0 adapter, Gemini on tail)
  steady state (warm cache)   <$0.002/job avg   (mostly $0 replays; Gemini only genuinely-new)

300/day steady state:  well under $1/day total; the ATS adapters + cache do the work,
Gemini is a tail expense, Claude is exceptional. Speed, not cost, becomes the ceiling.
```

## NOT in scope (deferred, with rationale)

- **Long-tail per-ATS adapters**: let them graduate from `nav_playbook` data once a
  family proves trusted + high-volume. (Revises the original blanket defer: the
  **top-10 ATS** are now IN scope as Tier-0 hand-built adapters — the 80/20 $0 lever
  — prioritized by observed `review_log` volume, starting with Workday since 4 of the
  13 sample jobs funnel there and GH/Lever/Ashby already exist.)
- **Full computer-vision stack** (always-on VLM grounding): vision is a gated LAST
  resort (Tier 2v) for DOM-blind pages only, not a default perception layer.
- **Imitation/bandit ML policy**: deferred Fallback child; needs thousands of logged
  episodes before it beats heuristics+LLM. Logs are structured now to train it later.
- **Automated account creation** (email+password+OTP signup): security-sensitive,
  stateful; rely on persistent logged-in profiles + login_provider(google) for now.
- **CAPTCHA expansion**: CapSolver path already exists in `captcha.py`; no new work.
- **Distributed / multi-machine**: explicitly local-only per the goal.
- **Dashboard write-heavy editing of recipes**: phase-1 dashboard is review + promote/ban;
  full recipe editing deferred to CLI `correct`.

## Implementation Tasks

- [ ] **T0 (P1)** — launcher adapter-gating — let generic+unblock attempt
  adapter-less, non-`unknown` families (Workday) instead of parking at
  `launcher.py:1865`, gated behind deterministic-only. Prereq for any Workday
  recipe/seed (Codex #1).
  - Files: `apply/launcher.py`, `apply/direct/driver.py`. Verify: a Workday job reaches `apply_via_direct` in deterministic-only mode.
- [ ] **T1 (P1)** — actions.py — extract one primitive dispatch table; migrate
  unblock + driver + multi-step to it; dedupe identity hints.
  - Surfaced by: Code Quality Issue 4. Files: `apply/direct/actions.py`, `unblock.py`, `driver.py`. Verify: existing dry-run still fills micro1/kula.
- [ ] **T2 (P1)** — playbook.py — `nav_playbook` table + signature/lookup/record/
  feedback/confidence + submit carve-out.
  - Surfaced by: Arch Issue 1. Files: `apply/direct/playbook.py`, `database.py`. Verify: collision + carve-out + promote/retire unit tests.
- [ ] **T3 (P1)** — wire replay-before-Gemini into unblock + record/write-back.
  - Surfaced by: Arch design. Files: `unblock.py`. Verify: cache-hit-makes-zero-LLM test (mock Gemini).
- [ ] **T4 (P1)** — review_log.py + write from every tier; dedupe_clusters query.
  - Surfaced by: Arch Issue 2. Files: `review_log.py`, `database.py`. Verify: cluster count test.
- [ ] **T5 (P2)** — field_strategy table + write-back from `_fill_field` (learn
  the okta acknowledge=click_label class).
  - Surfaced by: design. Files: `resolver.py`, `driver.py`, `database.py`. Verify: checkbox click_label learned + replayed.
- [ ] **T6 (P2)** — scale hardening (pool already exists at `launcher.py:2533`,
  Codex #8): shared cross-worker rate-limiting, Chrome profile isolation, a global
  Gemini backoff on 429, SQLite write-contention handling (WAL + retry), jitter.
  - Surfaced by: Arch Issue 3 + Codex #8. Files: `launcher.py`, `throttle.py`, `database.py`. Verify: quota→global-backoff→park→continue; 3 workers no SQLite "database is locked".
- [ ] **T7 (P2)** — dashboard Learning tab (timeline, clusters, promote/ban) +
  CLI `applypilot playbook`.
  - Surfaced by: Arch Issue 2. Files: `dashboard/web/*`, `server/app.py`, `cli.py`. Verify: E2E promote → entry trusted.
- [ ] **T8 (P2)** — seed `config/nav_playbooks.yaml` for Workday/Greenhouse/Ashby
  steps (status=seed/trusted, decays like any entry).
  - Surfaced by: design. Files: `config/nav_playbooks.yaml`, `playbook.py`. Verify: seeded Workday step replays.
- [ ] **T9 (P1, the 80/20 $0 lever)** — Tier-0 Workday adapter (highest volume:
  4/13 sample jobs). Deterministic multi-step path (My Information → Experience →
  Questions → Review → Submit) reusing the existing adapter pattern.
  - Surfaced by: prior-art survey (RPA 80/20). Files: `apply/direct/adapters/workday.py`, `adapters/__init__.py`. Verify: a real Workday form fills + validates end-to-end, $0.
- [ ] **T10 (P2)** — local-embedding CBR tier (Tier 1b): MiniLM sentence-embed of
  state snapshot + `sqlite-vss`/`hnswlib` nearest-neighbor; similar-case reuse with
  locator re-mapping. Shared model instance, lazy-loaded once.
  - Surfaced by: techniques (Synapse/CBR). Files: `apply/direct/similarity.py`, `playbook.py`. Verify: a near-miss Workday tenant reuses a neighbor recipe with 0 LLM calls.
- [ ] **T11 (P3)** — gated vision tier (Tier 2v): only when DOM extraction returns
  `partial`/no-actionable-elements, screenshot + Set-of-Marks → Gemini-vision picks a
  mark. Lazy-loaded; never on the default path.
  - Surfaced by: techniques (SeeAct/Set-of-Marks). Files: `apply/direct/vision.py`, `unblock.py`. Verify: a shadow-DOM page (Uber-style) yields one actionable click via vision.
- [ ] **T12 (P3)** — offline workflow induction: nightly batch mines `review_log`
  trajectory clusters, induces reusable multi-step workflows, proposes promotions to
  the owner queue (AWM-style). Runs only when no apply workers active.
  - Surfaced by: techniques (Agent Workflow Memory). Files: `apply/direct/induction.py`, CLI hook. Verify: a repeated 3-step Gemini sequence is induced into one promotable workflow.

## Parallelization (worktrees)

| Lane | Tasks | Shared modules | Notes |
|---|---|---|---|
| A (spine) | T0 → T1 → T2 → T3 | launcher/actions/playbook/unblock | Sequential — the escalation spine |
| B (memory) | T4 → T10 → T12 | review_log/database/similarity/induction | Parallel to A after schema lands |
| C (adapters) | T9 (+ T5) | adapters/ (isolated) | Independent — the 80/20 $0 lever, ship early |
| D (UI) | T7 | dashboard/web | After T2+T4 tables exist |
| E (vision) | T11 | vision/ (isolated) | P3, after spine; lazy-loaded, off default path |

Launch A (spine) and C (Workday adapter) in parallel — C is isolated under
`adapters/` and is the highest near-term $0 win. B starts once `database.py` schema
lands. T6 (scale hardening) folds into Lane A's tail. D/UI depends on T2+T4 tables.
Conflict flag: A and B both touch `database.py` — keep all schema additions in one
migration to avoid a merge conflict.

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 0 | — | — |
| Codex Review | outside voice | Independent 2nd opinion | 1 | issues_found | 12 findings; 6 folded in, 3 tensions resolved, 3 noted |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 | CLEAR (PLAN) | 7 decisions, 1 critical gap (cached submit → carve-out test mandatory) |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | — | — |
| DX Review | `/plan-devex-review` | Developer experience gaps | 0 | — | — |

- **CODEX:** 12 findings. Folded as refinements: #1 Workday gating (new T0), #4 broaden
  carve-out + goto allowlist, #8 pool exists (T6 reframed), #9 typed action contract,
  #10 field_strategy key, #11 rich review_log schema.
- **CROSS-MODEL:** 3 tensions, owner-resolved — build order (kept replay-now over
  Codex's record-only-first), signature scope (narrow + evidence-gated widening, per
  Codex), promotion proof (receipt-weighted, per Codex). #7 (cost not the only
  bottleneck) captured as the Reality-check note; #12 (record-only-first) declined.
- **POST-REVIEW REVISION (prior-art survey):** added the cheapest-first **tier ladder**
  (ATS adapter → exact hash → local-embedding CBR → Gemini text → Gemini vision →
  Claude → human queue), the **top-10 ATS Tier-0 adapters** as the 80/20 $0 lever
  (T9 Workday first), **local-embedding CBR** (T10), **gated vision** (T11), and
  **offline workflow induction** (T12). Techniques adopted from Stagehand,
  Agent-Workflow-Memory, Synapse/CBR, SeeAct/Set-of-Marks, py_trees. Whole doc
  re-aligned to this direction (control-flow, learning loop, signature, failure modes).
- **UNRESOLVED:** 0
- **VERDICT:** ENG CLEARED — ready to implement. Parallelize Lane A (spine T0→T1→T2→T3)
  + Lane C (Workday adapter T9, isolated, biggest near-term $0 win). Dashboard tab
  (T7) touches UI; consider `/plan-design-review` before building it.
