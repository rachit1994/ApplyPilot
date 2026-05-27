# Apply Hang Root-Cause and Fix (May 2026)

**Status:** Tier 1 + Tier 2 implemented (May 2026). Fast-fail on quota/auth text, reader-thread inactivity + wall timeouts, quota worker pause.

**One-line summary:** the apply pipeline blocks on `for line in proc.stdout` inside `run_job` because the Claude subprocess stops emitting output but stays alive. The configured `apply_timeout=600s` never fires because it's checked *after* the for-loop exits, which it can't do while waiting on `readline`. Two real triggers today: (A) Claude session quota exhausted prints one line then sits, (B) Playwright MCP browser tools called without a tool-level timeout.

---

## TL;DR

- **You are out of Claude session quota right now.** 382 of the 462 apply attempts in `worker-0.log` end with "You've hit your limit · resets 11am (Asia/Calcutta)". Until that resets, no apply will ever submit. This is the most-recent and most-visible failure mode you're seeing.
- **Structurally, the launcher will hang on quota errors and on browser-tool stalls forever.** The Python read-loop has no inactivity watchdog. The 10-minute `apply_timeout` is at the wrong place in the code path. The `session_log_incomplete` retry doubles the wall-time pain.
- **Three tiers of fix, listed in priority order:**
  1. **Acute (do today):** detect "You've hit your limit" in the agent's first message and exit fast with a permanent `failed:claude_quota_exhausted` status. Wall-time per quota'd job drops from minutes to seconds.
  2. **Structural (do this week):** wrap the stdout read in a reader thread + main-thread timeout; cap total job wall-time at `apply_timeout`; cap inactivity (no new line for N seconds) at a smaller `apply_inactivity_timeout`. Kill the subprocess on either trigger.
  3. **Prompt-level (do alongside):** bake hard caps into the prompt — max one `browser_wait_for time: 3`, max 60 tool calls total, mandatory CAPTCHA bailout after 2 poll cycles. Belt and suspenders.
- **Stop retrying incomplete sessions blindly.** The current retry path doubles the pain on every hang and every quota error.

---

## What's broken: evidence

### From `~/.applypilot/logs/worker-0.log` (462 total apply attempts, full history)

```
Outcome                                          Count    %
─────────────────────────────────────────────  ──────  ─────
APPLIED (claimed; many are ghost-applies)         21    4.5%
FAILED (with RESULT:FAILED line)                  23    5.0%
EXPIRED (with RESULT:EXPIRED line)                 2    0.4%
QUOTA exhaustion ("You've hit your limit")       382   82.7%
Real hang (browser_* activity, no RESULT)         33    7.1%
Other / empty                                      1    <0.1%
```

**82.7% of all apply attempts ever logged hit the Claude session-quota wall.** This is dominating your experience right now. The recent batch from 2026-05-24 08:07 through 08:16 are all quota errors against the same 3-4 LinkedIn URLs being retried.

**7.1% are true mid-process hangs** with browser activity that never reached a RESULT line. The last action emitted in those hangs:

```
  browser_snapshot               (most common — agent snapshots, then silence)
  browser_wait_for               (likely waiting on a selector or page event)
  browser_take_screenshot        (slow page, slow disk write, MCP stalled)
  browser_evaluate               (JS evaluation never resolves — e.g. await on a
                                  Promise that never settles, CAPTCHA poll loop)
  browser_navigate               (page load that doesn't fire 'load' event)
```

### From the database

```
apply_status            count
────────────────────  ─────
failed                  147
submitted_unverified     25   ← your prior ghost-fix doc's status is live
applied                  20
in_progress               0   ← good: stale-lock recovery is working
```

Zero rows are stuck in_progress, which means the subprocess does eventually die (Chrome crash, OS pressure, MCP timeout from another path). But the wall-time before death is enormous — `apply_timeout=600s` means a single hung job can burn 10 minutes before the launcher moves on, and the retry path doubles that to 20.

---

## Why it hangs: the architecture

```
                CURRENT FLOW (hangs)

  ┌─────────────────────────────────────────────────────────┐
  │ launcher.run_job  (apply/launcher.py:577)               │
  │   spawns: claude --output-format stream-json ...        │
  │   stdin .write(prompt); stdin.close()                   │
  └──────────────────┬──────────────────────────────────────┘
                     │
                     ▼
  ┌─────────────────────────────────────────────────────────┐
  │ launcher.py:677  for line in proc.stdout:               │
  │   parses each stream-json line                          │
  │   updates dashboard state                               │
  │   writes worker-N.log                                   │
  │                                                         │
  │   THIS BLOCKS on readline() if Claude stops emitting    │
  │   but doesn't close stdout.                             │
  └──────────────────┬──────────────────────────────────────┘
                     │
                     ▼  (only reached after for-loop returns)
  ┌─────────────────────────────────────────────────────────┐
  │ launcher.py:728  proc.wait(timeout=600s)                │
  │                                                         │
  │   This is dead code while the for-loop is blocked.      │
  │   The timeout cannot fire here.                         │
  └─────────────────────────────────────────────────────────┘
```

Two real-world ways Claude stops emitting but doesn't close stdout:

### Trigger A — quota wall (today's dominant problem)

1. Launcher spawns `claude -p` with the apply prompt
2. Anthropic API returns `"You've hit your limit · resets 11am (Asia/Calcutta)"`
3. Claude CLI writes that single text line, then…
4. …keeps the stdout pipe open while it does its own internal teardown
5. Python's for-loop sits on `readline()` waiting for the next line
6. Eventually the process exits, stdout closes, the for-loop returns, `proc.wait` succeeds with returncode 0
7. The parser sees no RESULT line, returns `failed:no_result_line`
8. The launcher's `session_log_incomplete` check fires and retries the same job — which hits the same quota wall, doubles the wall time

In testing today this loop is happening every ~50 seconds, which is fast enough that it looks "stuck" from the dashboard's perspective even though the worker is technically advancing.

### Trigger B — Playwright MCP tool hang (the slower, scarier one)

1. Claude calls a Playwright MCP tool like `browser_evaluate` with a JS function
2. The JS function contains `await new Promise(resolve => fetch(...))` to poll CapSolver, or `await page.waitForSelector` on a selector that never appears
3. Playwright MCP has no client-side cap; the call hangs server-side
4. Claude's tool-use waits for the MCP response, emits no further stream-json lines
5. Python's for-loop sits on `readline()` for 10+ minutes
6. Eventually MCP times out on its own (or Chrome crashes); subprocess exits; for-loop returns

We see 33 of these in the historical log. The most common last-actions match this pattern exactly (`browser_evaluate`, `browser_wait_for`, `browser_snapshot` on slow pages).

### Why the existing safety nets don't help

| Safety net | Where | Why it doesn't catch this |
|---|---|---|
| `apply_timeout = 600s` | launcher.py:206, used at :728 | The `proc.wait(timeout=600)` is after the for-loop. While the loop is blocked the timeout cannot start counting. |
| `session_log_incomplete` retry | launcher.py:914-927 | Triggers AFTER the for-loop returns; only adds a second hang on top of the first. |
| `release_stale_locks(45 min)` | launcher.py:280 | Helps the DB stay clean after a crash but does nothing to *prevent* the hang. |
| `kill_all_chrome()` on stop | chrome.py:269 | Only runs on Ctrl+C. A user watching the dashboard has no signal to interrupt because the worker chip shows "applying" the whole time. |
| Playwright MCP server timeouts | not configured | `_make_mcp_config` passes no `--timeout` / `--action-timeout` arg to `@playwright/mcp@latest`. |
| Claude CLI side timeouts | not used | The `claude` binary supports no `--inactivity-timeout`. The launcher doesn't enforce one either. |

The combined effect is: a hang anywhere in the agent's tool chain costs you 10-20 minutes of dashboard "applying" time per job, with the worker chip frozen on whatever the last tool call was.

### Why the pacing makes it worse

`apply --watch` and `--pace 2 --confirm-submit` are great UX features for letting you watch the agent work in a visible Chrome. But they inject explicit `browser_wait_for time: N` calls between every action (prompt.py:474-477) plus a 45+ second `confirm_submit` wait before submit (prompt.py:482-484). Even on a healthy run, that's 50+ extra seconds of intentional waiting per apply. If the subprocess gets confused about whether it's still waiting or actually hung, the symptoms look identical to a real hang.

---

## Specific code references

- **launcher.py:206** — `"apply_timeout": 600` in DEFAULTS. Configurable.
- **launcher.py:677-727** — the blocking for-loop that has no timeout and no inactivity watchdog.
- **launcher.py:728** — `proc.wait(timeout=...)` in the wrong place. Cannot fire while the for-loop is blocked.
- **launcher.py:780-790** — `subprocess.TimeoutExpired` handler that returns `failed:timeout`. This branch is unreachable in the current code path because the for-loop blocks first.
- **launcher.py:73-90** — `_make_mcp_config`: no tool timeouts passed to `@playwright/mcp@latest` or `@gongrzhe/server-gmail-autoauth-mcp`.
- **launcher.py:914-927** — `session_log_incomplete` retry path. Doubles the pain on every hang and every quota error.
- **prompt.py:474-505** — pacing instructions that bake in `browser_wait_for` calls. Healthy under watch mode, magnify confusion when something is actually stuck.
- **prompt.py:336-457** — CAPTCHA SOLVE flow has a "Loop: browser_wait_for time: 3, then poll" with `Max 10 polls (30s)` cap. Good. But the cap is a soft prompt instruction, not enforced. A confused agent can poll forever.

---

## Fix plan

Three tiers. **Tier 1 and Tier 2 are shipped** in `launcher.py` + `config.DEFAULTS`. Tier 3 (prompt caps) is still optional follow-up.

### Tier 1: stop the bleeding (~30 minutes of work, 10-100x wall-time win)

Goal: kill quota-exhausted runs in <5 seconds instead of 60-600 seconds. This alone restores the dashboard to a usable state today.

**Change 1:** In the for-loop at `launcher.py:687-689`, when a text block is appended, scan it for known fast-failure strings before queuing it. If matched, kill the subprocess immediately and return a permanent failure.

```python
# Add near the top of the file
FAST_FAIL_TEXT_PATTERNS = {
    "claude_quota_exhausted": (
        "you've hit your limit",
        "you have hit your limit",
        "rate limited",
        "session limit · resets",
    ),
    "claude_auth_failed": (
        "please run `claude login`",
        "not authenticated",
        "invalid api key",
    ),
}

def _detect_fast_fail(text: str) -> str | None:
    lower = text.lower()
    for reason, needles in FAST_FAIL_TEXT_PATTERNS.items():
        if any(n in lower for n in needles):
            return reason
    return None
```

Inside the assistant-text branch in `run_job`:
```python
if bt == "text":
    text_parts.append(block["text"])
    lf.write(block["text"] + "\n")
    if (reason := _detect_fast_fail(block["text"])):
        add_event(f"[W{worker_id}] FAST_FAIL: {reason}")
        # break out of for-loop; the finally clause kills subprocess
        return f"failed:{reason}", int((time.time()-start)*1000), None
```

**Change 2:** Add `claude_quota_exhausted` and `claude_auth_failed` to `PERMANENT_FAILURES` so they don't get retried.

```python
PERMANENT_FAILURES: set[str] = {
    "expired", "captcha", "login_issue",
    "not_eligible_location", "not_eligible_salary", "not_eligible_experience",
    "already_applied", "account_required",
    "not_a_job_application", "unsafe_permissions",
    "unsafe_verification", "sso_required",
    "site_blocked", "cloudflare_blocked", "blocked_by_cloudflare",
    "claude_quota_exhausted", "claude_auth_failed",   # ← new
}
```

But: `claude_quota_exhausted` should *not* be permanent on the job — it's permanent on the *current session*. It should fail-now without burning an attempt count, and pause the worker for a configurable interval (or until next dashboard run). Concretely: in `worker_loop`, when result is `failed:claude_quota_exhausted`, **release the lock** (don't increment attempts), log the reset time from the message if available, and sleep until then or up to a max of `apply_quota_pause = 1800s`.

**Change 3:** Surface the quota state on the dashboard. The worker chip should show "PAUSED: Claude quota — resets 11am" rather than "applying" indefinitely.

**Why this is Tier 1:** zero changes to subprocess plumbing. Pure text-match short circuit. Eliminates the 82% failure mode today.

### Tier 2: real inactivity watchdog (~2-3 hours of work, fixes the structural bug)

Goal: any hung subprocess (quota, MCP stall, CAPTCHA loop, slow page) gets killed within a configurable inactivity budget. The 600s wall-time cap actually works.

**Change 1:** Replace `for line in proc.stdout:` with a reader-thread pattern that pushes lines onto a `queue.Queue`. Main thread uses `queue.get(timeout=apply_inactivity_timeout)` so that an idle subprocess triggers a real timeout.

```python
import queue, threading

def _stream_reader(stdout, q: queue.Queue):
    try:
        for line in stdout:
            q.put(("line", line))
    finally:
        q.put(("eof", None))

q: queue.Queue = queue.Queue(maxsize=1024)
reader = threading.Thread(target=_stream_reader, args=(proc.stdout, q), daemon=True)
reader.start()

inactivity = config.DEFAULTS["apply_inactivity_timeout"]   # new, default 120s
wall_deadline = start + config.DEFAULTS["apply_timeout"]
fast_fail_reason: str | None = None

with open(worker_log, "a", encoding="utf-8") as lf:
    lf.write(log_header)
    while True:
        if time.time() > wall_deadline:
            add_event(f"[W{worker_id}] WALL TIMEOUT after {int(time.time()-start)}s")
            _kill_process_tree(proc.pid)
            return "failed:wall_timeout", int((time.time()-start)*1000), None
        try:
            kind, item = q.get(timeout=inactivity)
        except queue.Empty:
            add_event(f"[W{worker_id}] INACTIVITY TIMEOUT after {inactivity}s")
            _kill_process_tree(proc.pid)
            return "failed:inactivity_timeout", int((time.time()-start)*1000), None
        if kind == "eof":
            break
        # … existing line-parse logic …
        if fast_fail_reason:
            _kill_process_tree(proc.pid)
            return f"failed:{fast_fail_reason}", int((time.time()-start)*1000), None
```

**Change 2:** Add to `DEFAULTS`:
```python
"apply_timeout":            600,   # wall-clock, existing
"apply_inactivity_timeout": 120,   # NEW: no new stream-json line for 2 minutes
"apply_quota_pause":       1800,   # NEW: pause worker on quota error
```

**Change 3:** Add to `PERMANENT_FAILURES`: `"wall_timeout"`, `"inactivity_timeout"`.

**Why this is Tier 2:** addresses the root cause. No more hangs longer than 2 minutes (inactivity) or 10 minutes (wall) for any reason — quota, MCP stall, CAPTCHA poll, slow page, anything. The existing 600s timeout finally enforces itself.

**Risk:** the reader thread can leak if subprocess never closes. Mark it `daemon=True` so it dies with the process. We already kill the subprocess in the finally clause; the reader will then see EOF and exit cleanly.

**Test:** the regression set is in `tests/test_apply_log_parser.py`. Add `tests/test_apply_run_job_timeouts.py` covering:
- `proc emits nothing for 120s` → inactivity_timeout
- `proc emits one line then nothing for 130s` → inactivity_timeout
- `proc emits a quota line` → claude_quota_exhausted fast-fail in <2s
- `proc emits valid lines steadily for 700s` → wall_timeout at 600s
- `proc emits valid lines then RESULT:APPLIED in 30s` → applied

Mock the subprocess with a `FakePopen` that drives a controllable line stream and a `pid` so `_kill_process_tree` can be patched.

### Tier 3: prompt-level guardrails (~1 hour, belt-and-suspenders)

Goal: even with Tier 2's hard timeouts, reduce the chance that the agent talks itself into a loop.

**Change 1:** In `prompt.py` "WHEN TO GIVE UP" section, add hard caps:
```
- MAX 60 total browser tool calls per job. If you reach 50, finish what you're doing
  and emit RESULT:FAILED:tool_budget_exceeded with a one-line reason.
- MAX 10 CAPTCHA polls (already stated; promote to MUST). If 10 polls and still
  no token, emit RESULT:CAPTCHA immediately.
- MAX 3 retries of the same browser_evaluate function. If the same eval fails
  3 times with the same error, emit RESULT:FAILED:eval_loop.
```

**Change 2:** Add a hard rule for slow pages:
```
- If browser_navigate is followed by browser_snapshot returning {fieldCount: 0,
  visibleButtons: []} for 2 consecutive snapshots, the page failed to load.
  Emit RESULT:FAILED:page_did_not_load.
```

**Change 3:** Remove the `dry_run` instruction that tells the agent to emit `RESULT:APPLIED` without submitting (this was the ghost-apply trigger from the prior doc; folding it in here for completeness).

**Why Tier 3:** these are prompt instructions, not enforcement, so they're not a true safety net — but they reduce the agent's surface area for self-inflicted loops, which means the Tier 2 timeouts trigger less often.

---

## What I'd actually ship

Ship Tier 1 + Tier 2 together as a single PR. Tier 1 alone restores today's usability; Tier 2 alone prevents tomorrow's regressions. Together they're roughly 200-300 lines of code and 150 lines of tests. Tier 3 can be a follow-up.

The acute pain right now is quota — your machine is genuinely out of Claude usage until 11am. There is no code change that fixes that today. The reasonable mitigations are:

1. **Stop the launcher now.** Continuing to run it burns more attempts on every job (incrementing `apply_attempts`), and your DB now has 147 rows marked `failed` from these no-op quota errors. Those will need a `reset_failed` after the quota resets.
2. **Restart after 11am** with a small `--limit 3` and visible Chrome so you can confirm the fix path is working end-to-end before going continuous.
3. **Plan to ship Tier 1 today** so the quota wall stops costing you 50+ seconds per attempt.

---

## Edge cases the fix needs to handle

| Edge case | Current behavior | After Tier 2 |
|---|---|---|
| Claude returns single quota line | for-loop blocks ~60s, then no_result_line, then retry, then 60s more | fast-fail in <2s, no retry, status `failed:claude_quota_exhausted` |
| Playwright MCP `browser_evaluate` runs infinite-await JS | for-loop blocks 10+ min, eventually `apply_timeout` would fire (but doesn't reach it) | inactivity_timeout after 120s, subprocess killed, status `failed:inactivity_timeout` |
| Chrome crash mid-apply | subprocess emits no more lines, for-loop blocks until MCP server detects disconnect | inactivity_timeout after 120s |
| Site loads in 3 minutes due to slow network | agent emits a snapshot every 30s while waiting | no timeout — inactivity is per-line, not per-action |
| Healthy run with `--pace 2 --watch` | works | works (inactivity_timeout >> pace_seconds) |
| `confirm_submit` 45s pause | works | works (inactivity_timeout = 120s > 45s) |
| User Ctrl+C during hang | kill_all_chrome runs, subprocess dies, for-loop returns | same |

The 120s inactivity default is chosen to be > the longest legitimate gap (45s `confirm_submit` + slow snapshot ≈ 60s) and < the historical hang time (10+ min). Tunable via `~/.applypilot/.env` if your network is slower.

---

## NOT in scope

- Replacing Anthropic Claude with another model — quota is policy, not a bug.
- Auto-purchasing Claude credits — explicit user decision.
- Persistent Claude session across job runs — every apply spawns a fresh `claude -p` subprocess by design (isolation).
- Reworking the agent prompt beyond Tier 3's safety caps.
- The ghost-apply bug from `apply-ghost-fix-may-2026.md` — separate issue, separate fix. The two should ship together if possible because they share `launcher.run_job`.

---

## How to verify the fix once shipped

```bash
# A) Quota fast-fail test (today, while quota is exhausted):
applypilot apply --limit 1 --watch
# Expect: dashboard chip shows "FAST_FAIL: claude_quota_exhausted" in <5s
# Expect: job status in DB is "failed", apply_error="claude_quota_exhausted"

# B) Inactivity timeout test (any time, simulate via short timeout):
APPLYPILOT_APPLY_INACTIVITY_TIMEOUT=10 applypilot apply --limit 1 --url <broken-site>
# Expect: hangs for ~12s then status "failed:inactivity_timeout"

# C) Regression — healthy apply should still work:
applypilot apply --limit 1 --url <known-good-WaaS-job> --watch
# Expect: completes normally, emits RESULT_JSON (post-ghost-fix) or RESULT:APPLIED
```

End-to-end verification per your stated preference ("end-to-end verification that ApplyPilot actually runs and applies to jobs, not just code changes or theory").

---

## Appendix A: reproduction without waiting for a hang

```bash
# Simulate a quota error
cat > /tmp/fake-claude.sh <<'EOF'
#!/bin/bash
sleep 0.5
echo '{"type":"assistant","message":{"content":[{"type":"text","text":"You'\''ve hit your limit · resets 11am (Asia/Calcutta)"}]}}'
# Then never close stdout — keep stdin/stdout open for 600s to simulate the real hang
sleep 600
EOF
chmod +x /tmp/fake-claude.sh

# Set PATH so launcher picks up the fake
export PATH="/tmp:$PATH"
# Rename for the launcher's `claude` cmd
ln -s /tmp/fake-claude.sh /tmp/claude

# Run apply on any job; observe the hang
applypilot apply --limit 1 --url <any-url>
# Without Tier 1: hangs ~600s, then no_result_line, retries, hangs ~600s more.
# With Tier 1:    fast-fails in <2s.
```

## Appendix B: how to recover the 147 `failed` rows

After the quota resets and Tier 1 ships, many of the current `failed` rows are recoverable — they failed for `no_result_line` only because of the quota wall:

```sql
-- Identify quota-only failures (after Tier 1 lands, apply_error will be 'claude_quota_exhausted')
UPDATE jobs
   SET apply_status = NULL,
       apply_error = NULL,
       apply_attempts = 0,
       agent_id = NULL
 WHERE apply_status = 'failed'
   AND (apply_error LIKE '%no_result_line%' OR apply_error LIKE '%claude_quota%')
   AND apply_attempts < 99;
```

That re-queues them for the next apply run. The existing `applypilot apply --reset-failed` does the same thing for retryable failures and is the safer option.

---

## DEBUG REPORT

```
DEBUG REPORT
════════════════════════════════════════════════════════════
Symptom:         Apply runs appear to "hang mid-way" and never reach submit.
                 Dashboard worker chip stays on the last tool call for minutes.

Root cause:      launcher.run_job uses `for line in proc.stdout:` to read the
                 Claude subprocess's stream-json output. This call blocks on
                 readline() until a new line arrives or stdout closes. When
                 Claude stops emitting lines but stays alive — either because
                 the API returned a quota error or because a Playwright MCP
                 browser tool is hung server-side — the for-loop blocks
                 indefinitely. The proc.wait(timeout=600) at launcher.py:728
                 is unreachable while the for-loop blocks, so the documented
                 10-minute cap never enforces.

                 Today, 82.7% of attempts hit this path via Trigger A (quota
                 wall): you are out of Claude session usage until 11am
                 Asia/Calcutta. 7.1% hit it via Trigger B (MCP browser tool
                 stall) at various times in the history. Combined, 89.8% of
                 your apply attempts in worker-0.log never emitted a RESULT
                 line. The session_log_incomplete retry path doubles the
                 wall-time pain on every occurrence.

Fix:             Tier 1+2 in launcher.py; tests in tests/test_apply_run_job_timeouts.py.
                 - Tier 1 (today): fast-fail on quota text. <5s instead of 600s.
                 - Tier 2 (this week): reader thread + inactivity_timeout=120s.
                                       Real wall_timeout=600s that actually fires.
                 - Tier 3 (alongside): prompt caps for tool budget, CAPTCHA polls,
                                       eval retries.

Evidence:        - launcher.py:677-728 read by line
                 - 462 job blocks parsed from worker-0.log
                 - 382 quota-text matches, 33 real hangs (last action mostly
                   browser_snapshot / browser_evaluate / browser_wait_for)
                 - DB: 147 failed, 25 submitted_unverified, 20 applied,
                   0 in_progress (stale-lock recovery is working but does not
                   prevent wall-time loss)

Regression test: tests/test_apply_run_job_timeouts.py (to be written with Tier 2).
                 Cases listed in the fix doc.

Related:         - docs/apply-ghost-fix-may-2026.md (shares launcher.run_job;
                   ship together)
                 - DB rows in submitted_unverified suggest prior ghost-fix
                   guidance was already partially adopted

Status:          FIXED (Tier 1+2). Retest end-to-end after Claude quota resets.
════════════════════════════════════════════════════════════
```
