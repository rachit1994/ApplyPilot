# Claude Quota at Scale — Diagnosis & Plan (May 2026)

**Goal:** apply to a backlog of **2,000+ jobs** without exhausting Claude quota,
while keeping application quality high.

**Status today:** quota dies after ~7 applications. Prompt was already trimmed and
the default model switched to Haiku — usage is *still* too high.

---

## TL;DR

The prompt trim was correct but fixed the wrong layer. The static prompt is now
tiny (~165 fresh input tokens/apply). The quota killer is the **agentic browser
loop**: every turn re-reads the entire growing transcript of full-page DOM
snapshots. Measured cost is **~1.24 million cache-read tokens per single
application**.

> **No amount of prompt trimming or model swapping makes an LLM-drive-the-browser
> architecture scale to 2,000 applications.** The only thing that scales is
> removing Claude from the per-form hot loop and filling standard ATS forms
> deterministically, using an LLM (cheap: Gemini) only for the handful of
> freeform screening questions.

---

## The evidence (from your own `~/.applypilot/applypilot.db`)

`llm_usage_events`, grouped by provider/model:

| Provider | Model  | Applies | Fresh input | Output  | **Cache-read tokens** | Cost (API-equiv) |
|----------|--------|--------:|------------:|--------:|----------------------:|-----------------:|
| anthropic| haiku  | 16      | 2,646       | 74,443  | **25,684,709**        | $3.87            |
| anthropic| sonnet | 5       | 36          | 4,977   | 436,709               | $0.61            |
| gemini   | (all)  | 2,005   | 6,886,359   | 95,328  | —                     | **$0.29**        |

### What this proves

1. **Per application: ~1,240,000 cache-read tokens** (25.68M ÷ ~16 real applies).
   That is the dominant cost by ~3 orders of magnitude over everything else.
2. **The prompt trim worked.** Fresh input is ~165 tokens/apply. The static
   prompt is NOT your problem anymore. Stop optimizing it.
3. **Output is ~4,650 tokens/apply** — also not the problem.
4. **Gemini did 2,005 calls (scoring/tailoring/discovery) for $0.29 total.**
   Non-Claude models are effectively free at your volume.

### Why 1.24M cache-read tokens per apply?

The apply agent runs an **agentic loop** (`apply/launcher.py` → `claude` CLI):

- `prompt.py` *mandates* a fresh `browser_snapshot` after almost every action
  (navigate, every Apply/Next/Submit/Login click, every 5-field fill batch).
- Each `browser_snapshot` returns the **full accessibility tree** of the page.
  Complex ATS forms (Workday, Greenhouse multi-step) are 5,000–30,000 tokens each.
- Every turn re-sends the **entire conversation so far** (all prior snapshots +
  tool results) as cached input. Context grows ~quadratically: turn N re-reads
  turns 1…N-1.
- A 40-turn application therefore reads ≈ Σ(snapshots) ≈ **~1.24M tokens**.

**The Claude Code *subscription* quota counts cache-read tokens against your
5-hour session limit.** 7 applies × 1.24M ≈ 8.7M tokens → session exhausted.
That is exactly the "dies after 7" behavior.

### Why trimming the prompt didn't help

The prompt is sent **once** and cached. It contributes ~2,646 tokens total across
16 applies. Even cutting it to zero saves <0.02% of the 25.7M cache reads. The
cost is in the *loop*, not the *prompt*.

---

## Scale math

| Approach | Tokens / apply (Claude) | 2,000 applies | Feasible on subscription? |
|----------|------------------------:|--------------:|---------------------------|
| Today (LLM drives browser, Haiku) | ~1.24M | **~2.48 billion** | No — dies at ~7 |
| LLM loop + context editing + turn cap | ~150–250K | ~400M | Barely; ~$300+ on API |
| **Deterministic fill + Gemini for freeform** | **~0 Claude** | **~0 Claude; <$5 Gemini** | **Yes** |

Your own Gemini line proves the bottom row: 2,005 LLM calls already cost $0.29.

---

## Backlog shape (important nuance)

Of 3,663 unapplied jobs, **3,606 are stored as LinkedIn URLs**. The *real* ATS
destination (Greenhouse/Lever/Ashby/etc.) is only discovered at apply-time, when
the agent clicks "Apply on company website" (the `LINKEDIN SPECIAL RULE` in
`prompt.py`). So "deterministic ATS coverage" looks like 0% in the DB only
because the external URL isn't resolved yet.

**Implication:** the pipeline needs a cheap, LLM-free "resolve apply URL" step
that follows LinkedIn → company ATS and stores the real host. Then route by host.
`apply/apply_url_extract.py` / `coerce_application_url` already exist as a
starting point.

---

## The plan

### Tier 1 — Architecture change (the only thing that scales) ⭐

**Remove Claude from the per-form hot loop. Fill standard ATS forms with code.
Use Gemini only for freeform screening answers.**

1. **Resolve-URL pass (no LLM).** Headless Playwright follows LinkedIn →
   "Apply on company website" → final ATS URL. Store `application_url` + detected
   `ats_vendor`. Batch over the whole backlog once.

2. **Per-ATS deterministic adapters (Python + Playwright, zero LLM tokens).**
   The `ATS_URL_MARKERS` set in `eligibility.py` already enumerates the vendors.
   These have stable DOM + known field names/IDs:
   - **Greenhouse** (`boards.greenhouse.io`) — predictable field IDs; job board API.
   - **Lever** (`jobs.lever.co/.../apply`) — predictable form fields.
   - **Ashby** (`jobs.ashbyhq.com`) — GraphQL application API.
   - **Workable, SmartRecruiters, Recruitee, Teamtailor, Breezy, BambooHR** — patterned forms.
   Each adapter maps profile fields → form fields directly. No snapshot, no LLM.

3. **Freeform questions → Gemini Flash** (already wired in `llm.py`). "Why do you
   want this role", custom screening text → one cheap Gemini call each
   (~$0.0001). Cache answers per (question, role-family) to reuse across applies.

4. **Claude reserved for nothing by default.** Optional last-resort for truly
   unknown/broken forms, behind a hard per-run budget cap (see Tier 3).

5. **CAPTCHA** stays via CapSolver REST (already in `prompt.py`) — that path is
   LLM-light and can be called from the deterministic adapter.

**Expected result:** 2,000 applies consume ~0 Claude quota and <$5 of Gemini.

### Tier 2 — If you must keep an LLM driving the browser

Only relevant for the long-tail of non-adapter forms. Kill the quadratic blowup:

- **Switch from the `claude` CLI (subscription quota) to the Claude Agent SDK /
  API with context editing.** Clear old `tool_result` blocks each turn so context
  stops accumulating. Drops ~1.24M → ~150–250K tokens/apply and moves you off the
  session limit onto $-billing.
- **Hard `--max-turns` cap** (e.g. 12). Today `apply_timeout=600s` lets a confused
  agent burn an entire session on one stuck form.
- **Never dump the full accessibility tree.** Replace blanket `browser_snapshot`
  with scoped queries (the visible form region only). The `VERIFY PAGE STATE` JS
  already returns a compact field list — prefer it over raw snapshots.
- **Route the LLM loop to Gemini, not Claude.** Gemini is an OpenAI-compatible
  tool-use agent and is ~thousands× cheaper in your own data. Reserve Claude for
  cases where Gemini demonstrably fails.

### Tier 3 — Ops / safety rails

- **Per-run cost & quota budget with kill-switch.** Stop the run at e.g. $X or N
  tokens. You already record `llm_usage_events` — enforce a ceiling against it.
- **Cache resolved ATS URLs** so re-runs don't re-resolve.
- **Parallel workers** (`worker_id` already supported) — only useful *after*
  you're off the Claude session limit; otherwise more workers = faster quota death.
- **Quota backoff is already implemented** (`claude_quota_exhausted` →
  `apply_not_before`); keep it as a safety net, not the primary mechanism.

---

## Recommended sequencing

1. **Build the resolve-URL pass + Greenhouse + Lever + Ashby adapters.** These
   three vendors likely cover the majority of real destinations. Wire Gemini for
   freeform answers. This alone should take you from 7 → effectively unlimited
   applies/day at near-zero cost.
2. **Add Workable / SmartRecruiters / Recruitee / Teamtailor / Breezy adapters**
   to widen coverage.
3. **Add the Tier-2 Gemini/Agent-SDK fallback** for the long tail of unknown
   forms, behind a budget cap.
4. **Retire the per-job `claude` CLI subprocess** as the default path.

## What NOT to do (already tried / won't move the needle)

- ❌ Trimming the prompt further — it's already ~165 tokens/apply.
- ❌ Switching models (Haiku/Sonnet) — the cost is the loop, not the model tier.
- ❌ Disabling cache — cache-read is *cheaper* than re-reading uncached; the
  problem is the *volume* of context, not whether it's cached.
- ❌ Adding more parallel workers while still on Claude subscription — accelerates
  quota exhaustion.
