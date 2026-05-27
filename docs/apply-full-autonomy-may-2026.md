# Apply Without Humans — Path to Full Autonomy (May 2026)

**Status:** Investigation report grounded in the May 25 live-pipeline test. No code changed. Doc-only per standing instruction.

**One-line summary:** the pipeline now actually fills and submits real ATS forms — the last-mile blocker is **email verification codes**, which Greenhouse / Lever / Workday / Ashby all use as the final step. The Stripe attempt got 100% of the way to "Submit application," then Greenhouse triggered an 8-character email code, the agent tried to open `gmail.com` in the worker Chrome (logged out), and gave up. Fix the email-code path and most "successful filled, no submit" cases convert to real applies. Fix three smaller things (liveness check, broader manual-ATS list, multi-step diagnostics) and the system reaches ~70-80% autonomous submission across the queue.

---

## Where we are after the May 25 live test

### What worked

- Discover, enrich, score, tailor, cover letter — all completed end-to-end on real jobs.
- Apply launched Chrome + Claude, navigated to live ATS forms, filled every field, uploaded resume + cover letter PDFs.
- Process-isolation, npx PATH, relative apply-URL resolution, `--ats-only` matching `Greenhouse:*`, upload-from-worker-dir, and the tailoring prompt fixes — all shipped, all behaved correctly.
- The submit click happened on the Stripe Greenhouse form. The agent reached it cleanly.

### What stopped each attempt

| # | Company | URL/site | What the agent did | Final blocker |
|---|---|---|---|---|
| 1 | Stripe — Staff Engineer, Data & AI | Greenhouse | Filled form, uploaded resume + CL, clicked Submit | **Email verification code (8 chars) — agent opened gmail.com in worker browser, was logged out, paused for human** |
| 2 | Airbnb — Senior SWE, BizTech | Greenhouse | Filled fields, uploaded resume | **Stuck around Greenhouse/reCAPTCHA/form flow — failed without specific signal** |
| 3 | Lemon.io | Remote OK aggregator | Tried to apply | **Rejected: India excluded + contractor marketplace** (should have been filtered earlier) |
| 4 | Kraken | Remote OK aggregator | Tried to apply | **Job expired** (should have been caught pre-Chrome) |
| 5 | Fluxon | Remote OK aggregator | Tried to apply | **Account / Google SSO required** (Remote OK isn't an ATS — wraps the real apply URL behind a wall) |

Result: 0 verified submissions, but the pipeline is functional end-to-end. The blockers are now real ATS surface area, not infrastructure.

### Direct evidence from the Stripe log

```
~/.applypilot/logs/claude_20260525_142327_w0_Greenhouse:Stripe.txt (last lines)

  Location dropdown showing "Bengaluru, Karnataka, India" - selecting it now.
  Now running VERIFY PAGE STATE to check all fields before submitting.
  All fields verified. No errors. Running CAPTCHA DETECT before submitting.
  No CAPTCHA. All fields complete. Clicking "Submit application" now.
  A verification code was sent to the email. I need to retrieve it. Opening Gmail
  in a new tab to get the code.
  Gmail isn't logged in on this browser. Switching back to the application tab
  and pausing for the human to enter the verification code.
  RESULT_JSON:{"status":"pause_for_human"}
```

The agent IGNORED the Gmail MCP that's wired into the prompt and went visual (open gmail.com). The Gmail MCP path was mentioned ONCE in the prompt (step 5f, inside the LOGIN section) — and not at all for POST-SUBMIT verification.

Even if the prompt had said the right thing, the gmail-autoauth-mcp server isn't authenticated on this machine (no `~/.gmail-mcp/`, no Google credential file findable for the gongrzhe MCP). So the agent would've crashed on the first `mcp__gmail__search_emails` call anyway.

This is the central fix.

---

## The 5 blockers, in autonomy-impact order

### Blocker 1 — Email verification codes (THE BIG ONE)

**Frequency:** essentially every Greenhouse / Lever / Workday / Ashby application post-submit. Some sites do it BEFORE submit (Greenhouse Stripe). Most major ATSes use it. This is the new captcha.

**Why it's the most important:** every other blocker is rare or site-specific. Email verification is the default behavior for the entire ATS ecosystem the user is targeting.

**Why the agent fails today, twice:**
1. The prompt only mentions Gmail MCP in the LOGIN flow (step 5f). It doesn't tell the agent to use it for POST-SUBMIT verification. The agent defaulted to "open gmail.com in browser" which is the human's mental model.
2. Gmail MCP (`@gongrzhe/server-gmail-autoauth-mcp`) doesn't appear authenticated on the system. No token file found in standard paths.

**Fix design — three pieces:**

**1.1. Authenticate Gmail MCP, once.**

Add a CLI command: `applypilot gmail login`. It runs the auth flow in the user's real browser, saves the token to a known path the launcher's MCP config can read. A health-check command (`applypilot gmail status`) confirms the token works by listing the last 3 emails.

**1.2. Rewrite the prompt's verification-code section.**

Replace the single line in step 5f with a dedicated section the agent reads BEFORE clicking submit, so it primes the right tool path:

```
== EMAIL VERIFICATION (run when ANY post-submit "check your email" appears) ==

Many ATS systems (Greenhouse, Lever, Ashby, Workday, iCIMS) send a 4-8 character
code by email after you click Submit/Apply. You MUST handle this with the Gmail
MCP, NOT by opening gmail.com in the browser.

Step 1. Note the time you clicked submit. Wait 30 seconds.
Step 2. Use mcp__gmail__search_emails with query:
        from:(noreply OR donotreply OR no-reply OR verify) newer_than:5m
        Pick the most-recent matching message. If none, wait 30s and retry up to 4 times.
Step 3. Use mcp__gmail__read_email to read the body of that message.
Step 4. Extract the verification code: a contiguous 4-8 character string,
        typically alphanumeric and uppercase. Common patterns:
          - "Your verification code is: ABC12345"
          - "Confirm your email with code 1234"
          - A standalone block with just the code on its own line
Step 5. Switch back to the application tab (browser_tabs select), find the code
        input field, type the code, click Continue/Verify/Submit.
Step 6. Re-snapshot. If you see "Application submitted" / "Thanks for applying"
        / "Confirmation" / the URL changed to /confirmation or /thanks, emit
        RESULT_JSON status:"applied" with the full proof object.

NEVER open gmail.com in the browser. NEVER ask the human to paste the code.
If Gmail MCP returns no matching emails after 4 retries (2 min total), emit
RESULT_JSON status:"failed" reason:"email_code_not_received".
```

**1.3. Make the email-code step part of the verification record.**

Add to RESULT_JSON shape (from the prior ghost-fix doc): `verification_code_used` field. The Python verifier checks: if the form had an email-code step, a value must be present. Catches the agent silently skipping the code.

**Effort:** ~2 hours for prompt + MCP auth + Python verifier additions. ~50 lines of code.

**Impact:** Unblocks the Stripe-style "filled but couldn't submit" case. Based on the test, this is the single highest-impact fix. Roughly **every Greenhouse / Lever / Ashby attempt** today fails at this step.

### Blocker 2 — Multi-step + invisible CAPTCHA + form-flow stuck (Airbnb pattern)

**Frequency:** common on bot-aggressive sites and on multi-page Greenhouse / Workday flows.

**What happened on Airbnb:** filled fields, uploaded resume, then "got stuck around Greenhouse/reCAPTCHA/form flow." The agent ran out of useful tool calls. No diagnostic signal in the log to localize the failure.

**Why it stuck:**
- Multi-step Greenhouse forms transition by clicking Continue → page changes → previously visible fields are gone. If the agent's snapshot is stale, ref lookups fail silently.
- Invisible reCAPTCHA (v3) often fires AFTER submit; CapSolver handles v2 well, v3 needs a `pageAction` value the agent has to extract from page scripts. The current prompt mentions this once but doesn't enforce it.
- "Form-flow stuck" with no specific error means the agent looped on the same page without progressing. The prompt's "Same page after 3 attempts -> RESULT:FAILED:stuck" rule is advisory, not enforced.

**Fix design — instrument the multi-step path:**

**2.1. Step-change detection.**

Add a CHECKPOINT-ish protocol (proposed in ghost-fix Tier 3c). Every time the URL or page title changes, the agent emits:

```
CHECKPOINT:{"step":N,"of":M,"url":"...","title":"..."}
```

The Python launcher tracks these. If 3 consecutive snapshots produce no checkpoint advance, kill the run with `failed:stuck_on_step_N`. The error message includes the page title and last 3 actions so the user can see exactly where Airbnb stalled.

**2.2. Mandatory reCAPTCHA v3 path.**

Today's prompt has the v3 handling but as one of many CAPTCHA types. After observing the Airbnb pattern, make v3 the assumed default on Greenhouse: after Submit click, AUTOMATICALLY run CAPTCHA DETECT regardless of what the snapshot showed. Many Greenhouse forms have an invisible v3 that fires only on submit.

**2.3. Form-flow snapshot diffing.**

After each "Continue" click, snapshot before and after. Diff: did fields go away? did new fields appear? if `fieldCount` is unchanged and URL is unchanged, the click did nothing — the agent must investigate (re-snapshot, find the real button, try a different ref).

**Effort:** ~3 hours. Prompt additions + checkpoint parser in Python. ~100 lines.

**Impact:** Probably converts ~50% of "filled but stuck" failures into either real submissions or actionable error reasons (not just "failed without signal"). Less impactful than Blocker 1 but cheaper to ship.

### Blocker 3 — Aggregator / contractor / non-ATS marketplaces should be filtered earlier

**Frequency:** Remote OK / Wellfound / Lemon.io / similar sites surface jobs that route through wrappers, not ATS forms. The current pipeline lets them through to apply.

**What happened on Lemon.io:** the agent reached the "this is India and we don't hire from India" page. The agent also could have seen "this is a contractor marketplace" but instead spent Chrome+Claude time finding out.

**What happened on Fluxon (via Remote OK):** Remote OK wraps the apply behind a Google SSO wall. The agent couldn't proceed.

**Why this is wasted spend:** apply is the MOST expensive step in the pipeline (Claude tokens, Chrome, MCP, optional Capsolver). Spending it on jobs that should have been pre-filtered is the highest unit-cost waste in the system.

**Fix design:**

**3.1. Expand `manual_ats` and `contractor_marketplaces` in `sites.yaml`.**

Currently `manual_ats` has only `ibegin.tcsapps.com` and `linkedin.com`. Add Remote OK (it's a job board, not an ATS — the actual apply URL is upstream), Wellfound (mostly OK but SSO-heavy), Lemon.io (contractor marketplace pretending to be a job board), and any site the user wants to manually triage.

```yaml
# config/sites.yaml — proposed additions
manual_ats:
  - "ibegin.tcsapps.com"
  - "linkedin.com"
  - "remoteok.com"           # aggregator, real apply URL is wrapped
  - "remoteok.io"
  - "wellfound.com"          # heavy Google SSO requirement
  - "angellist.com"
  - "ycombinator.com/jobs"   # different from WaaS; routes through login
  - "indeed.com"             # Easy Apply forms are not real ATS forms
  - "glassdoor.com"

contractor_marketplaces:
  - "turing.com"
  - "developers.turing.com"
  - "mercor.com"
  - "toptal.com"
  - "upwork.com"
  - "fiverr.com"
  - "gun.io"
  - "lemon.io"               # ← caught by today's test
  - "andela.com"
  - "arc.dev"
  - "scale.com/applied"      # for AI training gigs vs real eng roles
  - "outlier.ai"             # AI training contractor
```

**3.2. Per-source classification at discover.**

The discover-relevance doc (Tier 0) already proposes universal `exclude_titles` + `include_titles` at every source. Add a `marketplace_blocklist` check at the same point. If the source is Remote OK / Wellfound / similar, mark the row with `strategy="aggregator"` so apply can recognize it.

**3.3. Geo-eligibility pre-check in `classify_apply_target`.**

The user's profile has `personal.country = "India"`. Some ATSes (Stripe, Atlassian, etc.) post jobs that explicitly exclude India. Today the agent discovers this only after navigating to the form. Add a check: if the job description contains phrases like "US/Canada only" or "EU residents only" and the user's country isn't in the list, mark `apply_status = "manual"` with reason `not_eligible_geo` BEFORE launching Chrome.

```python
# apply/eligibility.py — new
GEO_EXCLUDE_PATTERNS = [
    (r"\b(US|United States|USA)\s+(only|residents?|citizens?)\b", "US-only"),
    (r"\b(EU|European Union)\s+(only|residents?)\b", "EU-only"),
    (r"\b(UK|United Kingdom)\s+(only|residents?)\b", "UK-only"),
    (r"\bmust be (currently )?(based|located|residing) in\b", "location-specific"),
    (r"\bnot (open to|hiring in|available in) India\b", "India-excluded"),
    # ... etc
]

def detect_geo_exclusion(description: str, user_country: str) -> str | None:
    """Return a reason string if the description excludes the user's country."""
    # ... regex check; cheap, deterministic, runs at score or pre-apply ...
```

**Effort:** ~2 hours. Mostly YAML and a regex module. ~100 lines.

**Impact:** Eliminates 5-10% of today's wasted Chrome+Claude launches. The savings compound because the user has been seeing low-confidence-feel runs where most jobs fail for these reasons.

### Blocker 4 — Expired jobs should be detected before Chrome launches

**Frequency:** ~5-10% of jobs go stale between discover and apply (especially with continuous discovery — a job discovered Monday may be closed by Friday).

**What happened on Kraken:** Chrome launched, Claude navigated, page said "no longer accepting applications," Claude emitted RESULT:EXPIRED. Cost: ~30 seconds of wall time + ~$0.005 in Claude tokens + a Chrome instance churn.

**Fix design:**

**4.1. HTTP liveness check before `launch_chrome`.**

Add a one-shot HEAD-or-GET-with-tiny-body to the application URL right before launching Chrome. Cost: ~200ms, $0 in LLM. If the response is:
- 404 / 410 / 451 → mark expired immediately, skip Chrome
- 302 to a "job not found" path → same
- Page text contains "no longer accepting" / "this position has been filled" / "expired" / "closed" → mark expired
- 200 with form-like content → proceed to Chrome+Claude

```python
# apply/liveness.py — new
EXPIRED_PHRASES = (
    "no longer accepting", "this position has been filled",
    "position has been closed", "no longer available",
    "this job has expired", "applications are closed",
    "we are no longer hiring", "posting has expired",
)

def check_apply_url_alive(url: str, timeout: float = 8.0) -> tuple[bool, str | None]:
    """Return (is_alive, reason_if_dead). Pure HTTP; no Chrome."""
    import httpx
    try:
        r = httpx.get(url, timeout=timeout, follow_redirects=True,
                      headers={"User-Agent": "ApplyPilot-Liveness/1.0"})
        if r.status_code in (404, 410, 451):
            return False, f"http_{r.status_code}"
        body = r.text[:50_000].lower()
        for phrase in EXPIRED_PHRASES:
            if phrase in body:
                return False, "expired_text"
        return True, None
    except Exception as e:
        # On error, assume alive — let Claude figure it out
        return True, None
```

Wire it in `worker_loop` between `acquire_job` and `launch_chrome`. On `not is_alive`, call `mark_result(job_url, "failed", reason=reason, permanent=True)` and continue.

**Effort:** ~1 hour. Single file, well-bounded. ~80 lines.

**Impact:** Saves Chrome+Claude launch on the 5-10% of expired jobs. Each save is ~30s + a Claude call.

### Blocker 5 — SSO / account-required pages need detection + manual routing

**Frequency:** RemoteOK + Wellfound + some company career sites (Stripe sometimes does it on their own portal).

**What happened on Fluxon (Remote OK):** the wrapper required Google SSO. Per safety rules, the agent must NOT use the user's personal Google account inside a controlled Chrome profile (and shouldn't try to). The agent correctly bailed.

**Fix design:**

**5.1. SSO-page detection pre-Chrome.**

The liveness check from Blocker 4 can extend this: if the response URL contains `/auth/google` / `/oauth/` / `accounts.google.com` / `login.microsoftonline.com`, mark the job as `apply_status = "manual"` with reason `sso_required`. Don't launch Chrome.

**5.2. Honor the existing `blocked_sso` list more aggressively.**

The prompt already mentions `blocked_sso` from `config.load_blocked_sso`. Verify that list includes Google, Microsoft, Apple, Okta, Auth0 patterns. If a job's apply URL matches at discover time, mark it `manual` immediately.

**5.3. Surface a "manual queue" in the dashboard.**

The Applications page should show `manual` rows in a dedicated section: "12 manual applies waiting — click any row to open the URL in your real browser." The user does these by hand in a 10-minute weekly batch. This is part of the dashboard redesign doc (`dashboard-redesign-requirements-may-2026.md`).

**Effort:** ~1 hour. Mostly piggy-backs on Blocker 4's liveness checker. ~50 lines.

**Impact:** Eliminates ~3-5% of wasted Chrome launches. Bigger win is honest UX: the user sees "manual: 12" instead of "failed: 12" and knows what to do.

---

## The architecture for full autonomy

Stacking all five fixes, the new flow:

```
                AUTONOMY PATH (post-fix)

  acquire_job (DB picks tailored job)
       │
       ▼
  classify_apply_target (existing + geo-exclusion check)
       │
       ▼
  check_apply_url_alive  ← NEW (Blocker 4 + 5)
       │
       ▼
  launch_chrome + run_job
       │
       ▼
  Claude agent fills form ... clicks Submit
       │
       ▼
  Greenhouse/Lever sends email code
       │
       ▼
  Agent calls mcp__gmail__search_emails  ← NEW prompt (Blocker 1)
       │
       ▼
  Agent extracts code, fills, clicks Verify
       │
       ▼
  Snapshot confirms "thanks for applying"
       │
       ▼
  RESULT_JSON status:"applied" with full proof + verification_code_used
       │
       ▼
  Python verifier accepts ✓
       │
       ▼
  DB: apply_status='applied', applied_at=now, log_path=..., screenshot=...
```

If any step fails, the result is structured: `expired` / `sso_required` / `geo_excluded` / `manual` / `email_code_not_received` / `stuck_on_step_N` / `pause_for_human` — never a generic "failed without signal."

---

## What's realistically reachable without humans

Honest estimate after all five fixes ship:

| Category | % of typical queue (estimate) | Autonomy outcome |
|---|---|---|
| Greenhouse with email code | ~25% | Autonomous via Gmail MCP |
| Lever with email code | ~10% | Autonomous via Gmail MCP |
| Ashby with email code | ~5% | Autonomous via Gmail MCP |
| Workday multi-step | ~10% | Autonomous after Blocker 2 (login warmer + checkpoint) |
| Work at a Startup (logged in) | ~10% | Already autonomous |
| Email-only "send resume to X@" | ~5% | Already autonomous via Gmail MCP send |
| Direct ATS, no email gate | ~10% | Already autonomous |
| **Subtotal: AUTONOMOUS** | **~75%** | Can submit without a human |
| Aggregators (Remote OK, Wellfound) | ~5% | Marked manual; user does in 10-min weekly batch |
| Contractor marketplaces | ~2% | Filtered out at discover; never queued |
| Expired jobs | ~5% | Detected pre-Chrome; dropped |
| Geo-excluded jobs | ~3% | Filtered at score; never queued |
| **Subtotal: HONESTLY ROUTED** | **~15%** | Not autonomous, but not wasted Chrome+Claude time either |
| Novel ATS / weird MFA / phone OTP | ~5% | pause_for_human (already in prompt) |
| Identity verification (selfie, ID) | ~3% | NEVER autonomous; safety rule forbids; pause_for_human or skip permanently |
| Sites with bot-hostile CAPTCHAs CapSolver can't handle | ~2% | RESULT:CAPTCHA; user does it manually |
| **Subtotal: REQUIRES HUMAN** | **~10%** | Stays human-in-the-loop |

The target: **75% truly autonomous, 15% explicitly routed elsewhere, 10% needs you**. Today's number is closer to 0% autonomous (the test showed 0 verified submissions in this batch).

Realistic timeline if you ship the fixes in order:
- Blocker 1 (email codes) alone: jumps you from ~0% to ~40-50% autonomous overnight.
- Blockers 1+4+5 together (email + liveness + SSO routing): ~50-60%.
- All five: ~75%.

---

## What requires humans even at the end state

Some things should never be automated. Be explicit about them so they don't get accidentally targeted:

- **Identity verification.** Selfie capture, government ID upload, biometric anything. Already in the prompt's "NEVER DO THESE" list. Stays there.
- **Brand new MFA on a never-seen ATS.** First-time setup of TOTP / WebAuthn. Pause for human, save state, resume after user completes the gate.
- **Phone OTPs.** Possible to automate with Twilio if the user opts in and pays for a number, but out of scope for this doc. Default: pause_for_human.
- **Custom assessments / coding tests as part of the apply.** Honor system: if the listing wants a HackerRank link to test results, that's the user's day-job interview prep, not autopilot work. Skip with reason `requires_assessment`.
- **"Drag the puzzle piece" CAPTCHAs CapSolver can't solve.** Try once; on failure, RESULT:CAPTCHA and the user does it.
- **Sites that detect Playwright and bot-block (LinkedIn Easy Apply, Indeed Apply).** These are in `manual_ats` for good reason. Don't try.
- **Companies the user has personal relationships with.** A future feature could flag "applying via referral instead?" Out of scope.

These should account for ~10% of the queue. The rest is automatable with the fixes in this doc.

---

## Fix priority and effort

| # | Blocker | Files touched | Effort (CC) | Effort (human-equivalent) | Autonomy gain |
|---|---|---|---|---|---|
| 1 | Email codes + Gmail MCP auth | prompt.py + cli.py + new gmail_auth.py | ~3 hrs | ~2 days | +40-50% |
| 4 | Liveness check pre-Chrome | new apply/liveness.py + launcher.py | ~1 hr | ~half day | +5-10% |
| 5 | SSO + manual routing | apply/liveness.py + sites.yaml | ~1 hr | ~half day | +3-5% |
| 3 | Aggregator/marketplace filter + geo-eligibility | sites.yaml + apply/eligibility.py | ~2 hrs | ~1 day | +5-10% |
| 2 | Multi-step checkpoint + reCAPTCHA v3 default | prompt.py + apply_log_parser.py + launcher.py | ~3 hrs | ~2 days | +5-15% |

Ship order: **1 → 4 → 5 → 3 → 2.** Blocker 1 is the dominant fix (the Stripe pattern). Blockers 4 and 5 are cheap and stop wasting expensive Chrome time. Blocker 3 is a content/config update. Blocker 2 is the most subtle and worth doing last when you can observe failures with better logging.

Total estimated effort: ~10 hours of CC time, ~6-7 days of human-equivalent effort. Lifts the system from ~0% autonomous to ~75%.

---

## Specific code references for the fixes

- **Blocker 1**:
  - `src/applypilot/apply/prompt.py:888` — current single-line Gmail MCP instruction. Replace with full EMAIL VERIFICATION section.
  - `src/applypilot/apply/launcher.py:617` — `--disallowedTools` list. Confirm `mcp__gmail__search_emails` and `mcp__gmail__read_email` are NOT disallowed (they aren't today, good).
  - New: `src/applypilot/apply/gmail_auth.py` with `applypilot gmail login` and `applypilot gmail status` commands.
  - The verifier from the ghost-fix doc (`apply/verification.py`) — extend `VerificationRecord` with `verification_code_used: str | None` and check that email-gated forms set it.

- **Blocker 2**:
  - `src/applypilot/apply/prompt.py` — promote checkpoint protocol (already proposed in ghost-fix Tier 3c), make v3 detect-after-submit mandatory.
  - `src/applypilot/apply/apply_log_parser.py` — add `extract_checkpoints(text)`.
  - `src/applypilot/apply/launcher.py:run_job` — track consecutive snapshots without checkpoint advance; kill on 3.

- **Blocker 3**:
  - `src/applypilot/config/sites.yaml` — expand `manual_ats` + `contractor_marketplaces` lists.
  - `src/applypilot/apply/eligibility.py:classify_apply_target` — add `detect_geo_exclusion(description, user_country)` check.
  - Profile must expose `personal.country`. (Confirm it does in `~/.applypilot/profile.json`.)

- **Blocker 4 + 5**:
  - New: `src/applypilot/apply/liveness.py` — `check_apply_url_alive(url)` returning `(is_alive, reason)`.
  - `src/applypilot/apply/launcher.py:worker_loop` — call liveness check between `acquire_job` and `launch_chrome`. On dead, `mark_result(..., "failed", reason=..., permanent=True)` and continue.

---

## Verification plan per blocker

```bash
# Blocker 1 (email codes) — the headline test
# Pre: applypilot gmail login completes; applypilot gmail status returns 3 emails.
applypilot apply --url <stripe-greenhouse-url> --watch --keep-open 30
# Expect: agent fills form, clicks submit, calls mcp__gmail__search_emails,
#         extracts code, returns to form, types code, snapshots confirmation page,
#         emits RESULT_JSON status:"applied" with verification_code_used set.
# Expect (DB): apply_status='applied', not 'submitted_unverified'.

# Blocker 2 (multi-step + reCAPTCHA) — Airbnb retest
applypilot apply --url <airbnb-greenhouse-url> --watch
# Expect: CHECKPOINT lines in the worker log for each page transition.
# Expect: on reCAPTCHA v3 detection after submit, CAPTCHA SOLVE flow runs.
# Expect: if 3 consecutive snapshots show no checkpoint advance, the run kills
#         with a clear "failed:stuck_on_step_N" reason in the DB.

# Blocker 3 (filters) — Remote OK rejection
sqlite3 ~/.applypilot/applypilot.db "SELECT url, apply_status FROM jobs WHERE site LIKE '%Remote OK%' LIMIT 5;"
# Expect: Remote OK rows are 'manual' (aggregator), not 'failed'.
applypilot apply --url <a-known-india-excluded-job>
# Expect: pre-Chrome detection logs 'not_eligible_geo', no Chrome launch,
#         apply_status='manual', apply_error='geo_excluded:India-only'.

# Blocker 4 (liveness) — expired job
applypilot apply --url <known-expired-kraken-job>
# Expect: HTTP GET runs in <2s, detects expired phrase or 404,
#         apply_status='failed' apply_error='expired_text', no Chrome launch.

# Blocker 5 (SSO) — Fluxon via Remote OK
applypilot apply --url <fluxon-via-remoteok-url>
# Expect: pre-Chrome detection or Remote OK manual_ats list catches it,
#         apply_status='manual', apply_error='sso_required', no Chrome launch.
```

After all five tests pass, run the full corpus:

```bash
applypilot apply --limit 20 --workers 1
# Expect dashboard summary at end:
#   applied: 12-15 (of 20)
#   submitted_unverified: 0-2 (post-ghost-fix; mostly downgrades from failed verification)
#   manual: 2-3 (aggregators / SSO / geo-excluded)
#   failed: 0-2 (genuine ATS issues; each has a specific reason)
#   pause_for_human: 0-1 (novel MFA, identity verification)
```

Compare to the May 25 test (0 of N submitted). Each delta is concrete progress.

---

## NOT in scope

- **Replacing Anthropic Claude.** The agent works fine for form filling; the gap is around-the-agent infrastructure.
- **Building our own ATS for filing applications.** The user wants to submit through company portals, not bypass them.
- **Multi-account / persona management.** This is a single-user tool per AGENTS.md.
- **Twilio integration for phone OTPs.** Possible but out of scope; pause_for_human covers it.
- **Solving every CAPTCHA type.** CapSolver covers ~95%. The remaining 5% gets pause_for_human or RESULT:CAPTCHA.
- **Real-time desktop notifications.** Dashboard banner is enough; out of scope.
- **Auto-cleanup of `submitted_unverified` rows.** Tier 2 of the ghost-fix doc handles this; not in this doc's scope.

---

## What already exists (reuse, don't rebuild)

- `mcp__gmail__search_emails` and `mcp__gmail__read_email` are wired into the launcher's MCP config and are NOT in the disallowed list. The infrastructure is there; auth + prompt usage are the gaps.
- `pause_for_human` status (from ghost-fix Tier 3d) is already the right pattern for true-blocker cases. Email-code automation simply means it triggers less often, not differently.
- `classify_apply_target` (apply/eligibility.py) is the right hook for pre-Chrome geo / aggregator / manual routing. The function exists; add cases.
- `is_contractor_marketplace` and `is_manual_ats` exist and are config-driven via `sites.yaml`. Adding entries is YAML-only.
- `apply_log_parser.parse_apply_log` already extracts URL, fields, errors, fill_actions. Adding checkpoint extraction is mechanical.
- `_make_mcp_config` already wires Gmail MCP; no plumbing change needed.

---

## Failure modes after the fix

| Scenario | Today | After all 5 fixes |
|---|---|---|
| Greenhouse with email code | filled, paused for human | autonomous |
| Lever with email code | filled, paused for human | autonomous |
| Workday 5-step form | likely stuck at step 3-4 | checkpoint tracks each step; on stall, specific error |
| Remote OK aggregator | wasted Chrome+Claude, paused | manual, no Chrome launch |
| Lemon.io contractor | wasted Chrome+Claude, failed | manual, no Chrome launch |
| Expired Kraken job | Chrome launched, found expired | dead pre-Chrome, ~$0 wasted |
| Fluxon SSO required | wasted Chrome+Claude, failed | manual, no Chrome launch |
| US-only job for India user | Chrome launched, found ineligible | failed pre-Chrome with geo reason |
| Stripe with reCAPTCHA v3 | maybe stuck | mandatory v3 detect after submit; usually solved by CapSolver |
| Novel MFA (Yubikey, etc.) | pause_for_human | pause_for_human (unchanged) |
| Identity verification | RESULT:FAILED:unsafe_verification | unchanged (safety rule) |

---

## DEBUG REPORT

```
DEBUG REPORT
════════════════════════════════════════════════════════════
Symptom:         End-to-end test with real jobs: pipeline reaches
                 submission but produces 0 verified applies.
                 Stripe Greenhouse form filled completely, submit
                 clicked, blocked by 8-character email verification
                 code. Agent tried to open gmail.com in worker
                 Chrome (logged out), gave up, paused for human.

Root cause:      Five stacking issues. In priority order:
                 1. Email-code verification path is non-functional:
                    Gmail MCP exists but isn't authenticated; prompt
                    mentions it only in the LOGIN section (step 5f),
                    not for post-submit verification.
                 2. Multi-step / invisible reCAPTCHA detection isn't
                    enforced after submit; checkpoint protocol exists
                    in design but not in the prompt.
                 3. Aggregators (Remote OK, Wellfound) and contractor
                    marketplaces (Lemon.io) are NOT in sites.yaml
                    manual_ats/contractor_marketplaces lists; geo
                    exclusion isn't pre-checked from the user's
                    profile.country before Chrome launch.
                 4. No HTTP liveness check before launch_chrome;
                    expired jobs waste a Chrome+Claude cycle.
                 5. SSO routing has no pre-Chrome detection; the same
                    expensive cycle runs for un-applyable URLs.

Fix:             5 blockers in docs/apply-full-autonomy-may-2026.md.
                 Not applied. Ship order: 1 → 4 → 5 → 3 → 2.
                 - Blocker 1 (~3 hrs): Gmail MCP auth + dedicated
                   EMAIL VERIFICATION prompt section + verifier
                   field for verification_code_used.
                 - Blocker 4 (~1 hr): apply/liveness.py with HTTP
                   pre-check; skip Chrome on dead URLs.
                 - Blocker 5 (~1 hr): SSO URL pattern detection +
                   manual routing, piggy-backs on Blocker 4.
                 - Blocker 3 (~2 hrs): expand manual_ats and
                   contractor_marketplaces lists; add
                   detect_geo_exclusion in eligibility.
                 - Blocker 2 (~3 hrs): CHECKPOINT protocol in prompt
                   + parser + 3-snapshot-no-advance kill in launcher;
                   mandatory reCAPTCHA v3 detect after submit.
                 Total: ~10 hours CC time. Lifts autonomy from
                 ~0% (May 25 test) to ~75%.

Evidence:        - Stripe Greenhouse log shows submit click and
                   the agent's verbatim statement "Gmail isn't
                   logged in on this browser. Switching back to
                   the application tab and pausing for the human
                   to enter the verification code."
                 - launcher.py:617 confirms Gmail MCP tools are
                   not in disallowed list (they're allowed).
                 - prompt.py:888 has Gmail MCP mention only in
                   login flow, not post-submit.
                 - No ~/.gmail-mcp/ or Google credential file
                   found for gongrzhe MCP — auth never ran.
                 - sites.yaml manual_ats has only 2 entries
                   (ibegin, linkedin); contractor_marketplaces
                   has 7 entries, missing lemon.io.
                 - No HTTP liveness check anywhere in apply path.

Regression test: After Blocker 1 ships:
                 tests/test_email_code_extraction.py — extract
                 codes from 10 sample emails (Greenhouse, Lever,
                 Ashby, Workday, iCIMS). Each must return the
                 expected code string.
                 tests/test_apply_verifier_email_code.py — verifier
                 must require verification_code_used when the
                 form had a code step.
                 
                 After Blocker 4: tests/test_apply_liveness.py with
                 fixtures for 404, 410, expired_text patterns,
                 redirect to login.

Related:         - apply-ghost-fix-may-2026.md (the verification
                   record + pause_for_human pattern this doc
                   extends)
                 - apply-hang-fix-may-2026.md (Tier 1+2 shipped;
                   inactivity timeout protects the new email-code
                   wait too — verifier won't sit longer than the
                   configured inactivity_timeout)
                 - dashboard-redesign-requirements-may-2026.md
                   (manual queue surface needed for Blocker 3+5
                   routing to feel like UX, not punishment)
                 - discover-relevance-fix-may-2026.md (Tier 0
                   universal exclude_titles helps reduce the
                   denominator; this doc's fixes raise the
                   numerator)

Status:          DONE_WITH_CONCERNS — investigation complete, no
                 fix applied (per user request). The Stripe and
                 Airbnb logs from today's run are the regression
                 set. Test plan above gives the exit criteria.
════════════════════════════════════════════════════════════
```
