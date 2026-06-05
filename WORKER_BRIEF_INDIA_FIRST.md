# ApplyPilot — Worker LLM Brief: India-First, Reply-First, Deterministic-First

> Audience: the worker LLMs that will write the code.
> This file is **strategy and direction, not implementation**. It tells you *what to build and why*, in priority order, with acceptance criteria and guardrails. Do not start coding a work package until the one above it is verified.
>
> Author's note: the human asked us to "take a step back and think." So this brief deliberately **reframes the goal** before listing tasks. Read the diagnosis first — it changes what "done" means.

---

## 0. The reframe (read this or everything below is noise)

The product has been measured by the wrong number.

- **Wrong north star:** "applications submitted." This rewards spraying forms.
- **Right north star:** **interview replies from Indian employers per week.**

Everything in this brief optimizes the second number. An apply that no human ever reads is a cost, not a win. The current system has 9 applies — all hand-held by Claude Code — and we don't even know if any got a reply, because we never close the loop.

Three principles follow from the reframe. Every work package serves one of them:

1. **Deterministic-first.** Claude is the *last resort*, not the default. Every rupee/dollar spent on Claude is a signal that a deterministic adapter is missing. Treat Claude usage as a bug count, not a feature.
2. **India-first.** The market is India only, for now. The portals, the ATS systems, the salary logic, the eligibility filters — all of it must target India *first*, other markets *never* (until told otherwise).
3. **Reply-first.** We optimize for channels where real humans reply. That means instrumenting reply-rate and then *steering volume toward what works* and away from what doesn't.

---

## 1. Diagnosis — why apply is not trustable

Grounded in the actual code, not guesses:

### 1.1 The entire stack is shaped for the US/global market, not India
`src/applypilot/apply/eligibility.py` is the proof:
- `ATS_URL_MARKERS` = greenhouse, lever, ashby, workday, icims, smartrecruiters, jobvite, bamboohr, applytojob, recruitee, teamtailor, breezy, rippling, paylocity. **Every one is a Western ATS.**
- The eligibility logic is built around *US-residency* and *visa-sponsorship* blocking (`US_RESIDENCY_REQUIRED_PATTERNS`, `NO_SPONSORSHIP_PATTERNS`) — i.e. it was designed for a non-US candidate applying to US companies. That is the *opposite* of "India-only."
- `direct_adapter_priority_sql()` shows direct (deterministic) adapters exist for exactly **3 systems + YC**: Greenhouse, Lever, Ashby, workatastartup. Nothing else.
- Priority boards = Greenhouse, Lever, Ashby, LinkedIn, Wellfound.

**There is not a single Indian portal or Indian ATS anywhere in the stack.** No Naukri, Instahyre, Hirist, Cutshort, Foundit, IIM Jobs, or the ATS systems Indian companies actually run on (Keka, Darwinbox, Zoho Recruit, Freshteam/Freshworks, greytHR, SmartRecruiters-India, Workday/SuccessFactors for enterprises).

### 1.2 That directly causes "9 applies, all via Claude"
The pipeline (in `launcher.py`) is: **deterministic adapter first → Claude rescue if no adapter.** Since Indian jobs match *no* adapter, **every Indian job falls to the Claude path.** Claude is:
- expensive (~$0.15/apply, see `memory/apply-cost-and-blockers.md`),
- unreliable on real submits (headless Chrome crashes on Greenhouse; needs a *visible* browser — `memory/direct-apply-submit-reliability.md`),
- and apparently still needs a human babysitting it.

So the low number isn't a tuning problem. **The deterministic engine never fires for the target market.**

### 1.3 We half-learn what works — but the loop isn't closed
`mark_result` / `apply_outcomes` records `applied / failed / submitted_unverified`, but **not** whether a reply came back. The Gmail integration is used only to confirm the *submission receipt*.

**However — partial machinery already exists, do not rebuild it.** There is a whole `src/applypilot/inbox/` module that already classifies recruiter messages by intent (`apply_request / rejection / status_update / spam / education_pitch / other`) using **Gemini** (cheap, not Claude). Today it is aimed at the **LinkedIn "Other" inbox tab** (`inbox/classifier.py`, `inbox/intents.py`, `inbox/scanner.py`). What's missing is: (a) tying those classified replies back to specific applications, (b) covering Gmail recruiter replies the same way, and (c) a **reply-rate-by-source** report. So point 4 is ~40% built — the job is to *extend and wire it up*, not start over.

### 1.4 Reliability is unproven
Submit verification exists (`RESULT_JSON`, gmail receipt), but the headless-crash issue and the Claude-dependence mean we have no trustworthy, repeatable "applied and verified" path for Indian jobs.

---

## 2. Hard truth about Indian reply-rates (informs priority)

Before building, internalize how the Indian market actually produces replies. This is *why* the work is ordered the way it is.

- **In India, most real responses are recruiter-initiated, not application-initiated.** On Naukri, Instahyre, LinkedIn, recruiters *search* candidate profiles and reach out. A strong, fresh, keyword-rich profile that surfaces in recruiter search produces more replies than 200 cold form-fills.
- **Referrals are the single highest-reply channel** for experienced roles. A referred application at a product company replies far more often than a cold ATS submit.
- **Cold ATS form-spray has low reply rates everywhere**, India included. Volume on company career pages is necessary but should not be the *only* bet.
- **Therefore "optimize for where people get replies" is partly a strategy shift, not just an engineering one:** invest in (a) profile/visibility on Naukri+LinkedIn+Instahyre, (b) referral/direct-recruiter outreach, and (c) *targeted* applies to companies actively hiring — not indiscriminate volume.

Workers: do not silently "fix" this by just adding more form-fillers. The reply-rate instrumentation (WP-2) must come early so we can *prove* which channels deserve volume.

---

## 2b. Existing assets — reuse, do not rebuild

Before writing anything, know what's already here (verified against the tree):

- **Direct adapter framework:** `src/applypilot/apply/direct/` — `fingerprint.py`, `resolver.py`, `driver.py`, `throttle.py`, `adapters/base.py`. New Indian ATS adapters slot into this; **don't invent a new framework.** Existing adapters: `greenhouse.py`, `lever.py`, `ashby.py`, `workatastartup.py` (these are the *only* four — that's the gap).
- **Reply classification:** `src/applypilot/inbox/` (classifier/intents/scanner/store/runner) — already classifies recruiter intent via **Gemini**. LinkedIn-only today; extend to Gmail + per-application linkage.
- **Referral / outreach:** `referral_template`, `referral_resume`, `referral_message`, `openoutreach` client+runtime. Scaffolding exists; needs targeting + India-fit.
- **Cost telemetry:** `record_llm_usage` in `database.py` + per-worker cost in `dashboard.py` — the budget governor (WP-2) reads these; don't add a parallel meter.
- **Verification:** `apply/verification.py` + `RESULT_JSON` + `gmail_auth` receipts — every new adapter must emit the *same* verification shape.
- **Eligibility/scoring:** `apply/eligibility.py`, `apply/salary.py`, `apply/experience.py`, company-first ranking — correct the US assumptions in place (WP-4), keep the structure.

## 3. Work packages (priority order — do not reorder without sign-off)

Each package: **Goal · Why · Build · Acceptance · Guardrails.** "Acceptance" is the bar for calling it done. Reliability beats breadth — a package isn't done until it's *verified working on a real Indian job*.

### WP-0 (P0) — Research spike: India source & ATS inventory *(do this first, it's mostly not code)*
**Goal:** A written, evidence-backed map of (a) the Indian job portals worth integrating, (b) the ATS systems Indian companies' career pages actually run on, and (c) for each, the realistic automation path (official API / easy-apply / form adapter / manual-only) and an *estimated reply-rate tier*.
**Why:** We are about to build adapters. Building them for the wrong portals repeats the original mistake. Decide *where* before *how*.
**Build:** A markdown report `docs/india-source-map.md` covering at minimum: Naukri, LinkedIn (India), Instahyre, Hirist, Cutshort, Foundit (ex-Monster), Wellfound-India, IIMJobs/Hirect, and the ATS systems: Keka, Darwinbox, Zoho Recruit, Freshteam, greytHR, SmartRecruiters, Workday/SuccessFactors (enterprise). For each: login/auth model, bot-detection risk, whether a deterministic form adapter is feasible, and reply-rate tier (high/med/low) with reasoning.
**Acceptance:** Human can read it and pick the 3–4 portals/ATS to build adapters for next, with a one-line justification each.
**Guardrails:** No scraping that violates a portal's ToS in a way that gets the user's real account banned — flag those as "manual/assisted only." This is the user's actual job hunt; a banned Naukri/LinkedIn account is a real-world harm.

### WP-1 (P0) — Reply-rate instrumentation (close the loop)
**Goal:** Record, per application, whether a *human reply* came back, and from which channel/source — and surface a weekly reply-rate by source.
**Why:** This is the missing optimization signal (point 4). Without it we cannot "optimize for platforms that reply." Build it early so every other WP can be judged by it.
**Reuse, don't rebuild:** start from the existing `src/applypilot/inbox/` module (classifier/intents/scanner already classify recruiter intent via Gemini). Extend it; don't write a parallel system.
**Build:**
- Reuse the existing intent taxonomy from `inbox/intents.py`. Add a Gmail scanner alongside the current LinkedIn one so recruiter mail is classified the same way.
- Tie classified messages back to a specific application (match on company/recruiter/thread). Store on the job row (e.g. `reply_status`, `reply_at`, `reply_channel`).
- A simple report: applies, verified-applies, replies, interview-invites — **bucketed by `site`/source** — over a rolling window.
**Acceptance:** Running the report shows reply counts per source for the last N days, derived from real inbox data, not guesses. A source with 0 replies after a meaningful sample is visibly flagged.
**Guardrails:** Gmail access stays read-only for classification (the existing `_GMAIL_DISALLOWED_TOOLS` posture). Never auto-reply or auto-archive. False "interview_invite" positives are worse than misses — bias toward precision.

### WP-2 (P0) — Claude budget governor + "deterministic-or-skip" mode
**Goal:** Make Claude genuinely last-resort and *bounded*. Add (a) a hard per-run Claude spend/attempt cap, and (b) a mode that applies *only* via deterministic adapters and **queues everything else for later instead of burning Claude**.
**Why:** Point 2 — Claude is costly and should only run when there is no alternative. Right now it's the default path for the whole target market, which is exactly backwards.
**Build:**
- Config: `apply_claude_max_per_run`, `apply_claude_max_cost_usd_per_run`. When hit, Claude path stops; deterministic path continues.
- A `--deterministic-only` apply mode: deterministic adapters run; non-adapter jobs are parked with a clear status (`needs_adapter`) rather than handed to Claude.
- Cost telemetry already exists (`record_llm_usage`) — surface a per-run running total and stop when the cap trips.
**Acceptance:** A run with `--deterministic-only` spends **$0 on Claude** and still makes progress on adapter-covered jobs. A normal run halts Claude at the configured cap and reports how many jobs were parked as `needs_adapter`.
**Guardrails:** Parking a job for "no adapter" must be reversible (re-queued automatically once an adapter ships). Don't mark `needs_adapter` as permanent (`attempts=99`).

### WP-3 (P1) — Indian ATS / portal direct adapters (the real fix)
**Goal:** Deterministic Playwright adapters for the top India targets chosen in WP-0, so Indian jobs stop falling to Claude.
**Why:** This is the structural fix for "9 applies." It converts the target market from the expensive Claude path to the cheap deterministic path. This is where the bulk of trust comes from.
**Build (in WP-0 priority order; likely):**
- One adapter per chosen Indian ATS (e.g. Keka, Darwinbox, Zoho Recruit, Freshteam, SmartRecruiters) following the existing `apply/direct/adapters` + `fingerprint.ats_family` pattern.
- Easy-apply automation for the portals where it's safe (e.g. LinkedIn Easy Apply, Instahyre/Cutshort quick-apply) — only where WP-0 said it won't risk an account ban.
- Wire each new family into `ATS_URL_MARKERS`, `direct_adapter_priority_sql()`, and the priority/where clauses in `eligibility.py`.
**Acceptance:** For each shipped adapter, **at least one real Indian job is submitted and verified end-to-end with $0 Claude spend**, on the user's machine, with a visible browser. Reliability over count: 5 rock-solid verified submits beat 50 "submitted_unverified."
**Guardrails:**
- Use a **visible (non-headless) browser** for real submits (per `memory/direct-apply-submit-reliability.md`).
- Respect per-site throttles/caps already in `apply/direct/throttle.py` — do not hammer a portal and get the account flagged.
- Every adapter must produce the same structured verification (`RESULT_JSON` / receipt) the Claude path does, so verification stays uniform.

### WP-4 (P1) — India-correct eligibility & salary logic
**Goal:** Replace US-centric eligibility with India-correct logic.
**Why:** The current filters waste effort on the wrong axis (US residency/visa) and may mis-handle Indian salary (LPA), locations (Bengaluru/Hyderabad/NCR/remote-India), and seniority. Wrong filters = wrong jobs in the queue = wasted applies and missed replies.
**Build:**
- Make US-residency/visa filters **no-op or opt-in** when the candidate is India-based.
- India salary handling in LPA; India location normalization; India notice-period/experience norms if relevant.
- Keep the *structure* of `classify_apply_target` — just correct the assumptions.
**Acceptance:** A representative Indian job set classifies sensibly (no false `not_eligible_location` on "Remote - India" or "Bengaluru"); LPA salary thresholds enforced correctly.
**Guardrails:** Don't delete the US logic — gate it behind candidate-country so the system stays multi-market-capable later. Changing eligibility silently re-queues/skip jobs; report a before/after count.

### WP-5 (P2) — Discovery sources pivot to India
**Goal:** Feed the queue from India-first sources instead of (only) Western ATS-native scraping.
**Why:** Discovery currently pivoted to "ATS-native sources" (Greenhouse/Lever/Ashby) — Western. The queue can only be as India-relevant as its inputs.
**Build:** India discovery sources per WP-0 (Naukri search, LinkedIn-India, Instahyre, Wellfound-India, Indian-company career pages on the ATS families from WP-3). Company-first ranking already exists — reuse it.
**Acceptance:** Majority of newly discovered jobs are India-based roles on automatable surfaces; volume sufficient to keep deterministic adapters busy.
**Guardrails:** Same account-safety rule as WP-0/WP-3. De-dupe across portals (same job on Naukri + company site).

### WP-6 (P2) — Referral & recruiter-outreach channel (highest reply-rate)
**Goal:** A semi-automated path to (a) identify referral routes and (b) draft targeted recruiter/referrer outreach — because in India this is where replies actually come from (Section 2).
**Why:** Point 4 taken seriously. If referrals/recruiter-DMs reply 5× more than cold ATS forms, that's where marginal effort should go.
**Reuse, don't rebuild:** referral/outreach scaffolding already exists — `referral_template`, `referral_resume`, `referral_message`, and the `openoutreach` client/runtime (see the matching `tests/test_referral_*` and `tests/test_openoutreach_*`). Build on these; the gap is targeting + India-fit + measuring against WP-1, not net-new plumbing.
**Build:** Start small and human-in-the-loop: for a target company, surface likely referrers/recruiters (LinkedIn) and *draft* a message for the user to send via the existing outreach path. Do **not** auto-send at scale.
**Acceptance:** For a target company the system produces a usable, personalized outreach draft + the right person to send it to. Measured against WP-1 reply-rate.
**Guardrails:** **No mass-DMing / no auto-send** — that gets accounts banned and is spammy. Human approves and sends. This is assistive, not autonomous.

### WP-7 (P3) — Reliability hardening & honest status
**Goal:** Make "applied" mean applied. Default real submits to a visible browser, tighten verification, and make `submitted_unverified` rare.
**Why:** Trust. The user said it plainly: "apply is still not trustable."
**Build:** Visible-browser default for submits; verification audit on a sample; convert silent failures into actionable statuses.
**Acceptance:** On a 20-job sample, the status the system reports matches reality on manual spot-check; `submitted_unverified` rate is low and each one has a concrete reason.
**Guardrails:** Never upgrade `submitted_unverified` → `applied` without real proof (receipt/confirmation). Under-claiming is fine; over-claiming is not.

---

## 4. Definition of done for the whole effort

We will call apply "trustable" when **all** of these hold:

1. A normal apply run can process a batch of **Indian** jobs **without Claude** (deterministic adapters cover the common Indian ATS) and with `$0` Claude spend on the covered share.
2. Claude spend per run is **bounded by config** and only fires when no adapter exists — and that "no adapter" set is shrinking, tracked weekly.
3. Every "applied" is **verified**, and we can show a **reply-rate per source** from real inbox data.
4. We are demonstrably steering volume toward the sources that reply and away from the ones that don't.
5. The user can run it overnight and trust the morning numbers without spot-checking every row.

---

## 5. Anti-goals (do not do these)

- ❌ Don't chase a big "applications submitted" number. Optimize replies.
- ❌ Don't make Claude the default path for any market. Deterministic-first, always.
- ❌ Don't add more Western ATS or US/visa logic. India-first until told otherwise.
- ❌ Don't auto-send mass DMs/emails or do anything that risks banning the user's real Naukri/LinkedIn/Instahyre account. This is their actual career.
- ❌ Don't mark jobs as `applied` without verification, or park "no adapter yet" jobs as permanent failures.
- ❌ Don't build breadth before one real, verified, $0-Claude Indian submit exists. Get one thing fully right first.
