# Worker Implementation Plan — Leaner Self-Learning Apply (June 2026)

**Audience: coding worker LLMs.** Each ticket below is self-contained — file paths,
the exact contract, an acceptance test, and guardrails. You do NOT have the design
conversation; everything you need is in the ticket. Do the ticket, run its
acceptance command, stop. Do not expand scope.

Design rationale (already decided, do not relitigate): see
`docs/self-learning-apply-architecture.md`, `docs/scaled-self-learning-apply-plan.md`,
and the leaner review in `docs/behavior-tree-apply-recommended-algorithms-may-2026.md`.

---

## Ground rules for every ticket

- **Run on a fresh DB.** Tests use the autouse `isolated_db` fixture in
  `tests/conftest.py` (tmp SQLite per test). Never write to `~/.applypilot`.
- **Verify command:** `uv run pytest <files> -q`. Add tests in `tests/`.
- **No new heavy deps.** Specifically forbidden (decided): `py_trees`, an HTN
  planner, policy distillation (OPD), and embedding/vector CBR (`sqlite-vss`,
  `faiss`, sentence-transformers). The escalation ladder stays an ordered Python
  list; "fuzzy match" is structural selector self-healing, not embeddings.
- **Safety invariants you must never break:**
  - `submit` is never replayed from cache (`playbook.is_replay_allowed` returns
    False for submit).
  - Side-effecting nav (`click`/`next_page`/`login_*`/`goto`/`apply`) replays only
    when the entry is `trusted`/`pinned`.
  - The driver only submits after deterministic identity + required-field
    validation (`driver.apply_via_direct`). Do not weaken this.
- **Keep diffs minimal and tested.** Update tests you intentionally change; do not
  silently delete coverage.

## Already built — DO NOT rebuild

`apply/direct/playbook.py` (nav_playbook + field_strategy, record/lookup/promote/
retire/stamp_verified, submit carve-out, banned/pinned/trusted guard,
family-scope fallback), `unblock_learning.py` (replay-before-Gemini loop,
postcondition-gated `used_state_sigs`, `llm_suggestion` logging), `field_strategy_fill.py`,
`review_log.py` (log + `dedupe_clusters` + `cache_hit_rate`), `playbook_seed.py`
(executable-nav-only seeding), `server/learning.py` + dashboard `LearningDashboardPage.tsx`,
driver multi-step loop + identity guard. Extend these; don't duplicate them.

---

## Lanes & sequencing

```
Lane A (foundation):  W1 → W4            signature key + explicit ladder
Lane B (robustness):  W2 → W3            selector self-healing + escalation caps
Lane C (scale):       W5                 single-writer review_log
Lane D (80/20):       W7 → W6            launcher gating + Workday adapter (isolated)
Lane E (learning):    W8 → W9            induction + dashboard surfacing
```

Launch A, B, C, D in parallel (different files). W6/W9 depend on their lane head.
W1 changes the signature, which touches seeds/tests — land it before W8.

---

## W1 — Stable-subset navigation signature  (P1, Lane A, the #1 lever)

**Why:** `playbook.state_signature` currently hashes the FULL sorted clickable set,
so a job-specific button ("Refer and Earn", company name, role title) changes the
key and breaks cache hits across tenants/jobs. This is why seeds and cross-page
replay barely fire. Key on a *salient* subset instead.

**File:** `src/applypilot/apply/direct/playbook.py`

**Contract:**
1. Add a nav-vocabulary canonicalizer:
   ```python
   _NAV_VOCAB = ("apply", "next", "continue", "submit", "save", "sign in",
                 "log in", "login", "accept", "agree", "review", "back",
                 "upload", "create account", "register", "google")
   def _salient_clickables(clickables: list[str] | None) -> list[str]:
       # keep only labels containing a nav-vocab token; canonicalize
       # ("apply for this job" / "apply now" -> "apply"); dedupe; sort.
   ```
2. In `state_signature`, replace `",".join(_normalize_clickables(...))` with
   `",".join(_salient_clickables(page_snapshot.get("clickables")))`.
3. Bump `SIG_VERSION` to `2` (old entries become unreachable and relearn — fine).
   Keep `sig_version` written into the row.

**Acceptance** (`tests/test_playbook.py`, add):
- Two snapshots, same `ats_family`/step/flags, salient buttons identical but with
  DIFFERENT noise buttons → **same** `state_signature`.
- Two snapshots whose salient buttons differ ("apply" vs "next") → **different** sig.
- `uv run pytest tests/test_playbook.py tests/test_playbook_seed.py tests/test_unblock_learning.py -q`
  (update seed/unblock tests whose fixtures assumed full-clickable hashing).

**Guardrails:** do not add embeddings. Do not change the field signature
(`field_sig` / `qa_bank.question_key`). Keep flags (`has_application_form`,
`has_password_field`, `has_cookie_banner`) in the hash.

---

## W2 — Structural selector self-healing  (P1, Lane B)

**Why:** replay/fill break when a cached selector (often visible text) changes.
A structural rebind (role + accessible name + nearby label + tag) recovers it at
$0 — the right "revise" step, instead of embedding similarity.

**New file:** `src/applypilot/apply/direct/selector_heal.py`

**Contract:**
```python
def heal_locator(page, descriptor: dict):
    """descriptor keys (any subset): role, name, label, nearby_text, css, tag,
    text. Try in order: exact css/text → role+name → text → xpath normalize-space
    → nearby-label proximity. Return a Playwright Locator or None."""
```
- Reuse the robust click logic already in `unblock._click_text` (scroll + force +
  xpath) — factor the element-finding half into `selector_heal` and have
  `unblock._click_text` call it. Do not fork a third copy.
- Wire into `field_strategy_fill._locator`: when `data-ap-key`/`data-ap-id` both
  miss, call `heal_locator` with the field's `{label, name_attr, type}` before
  giving up.

**Acceptance** (`tests/test_selector_heal.py`, new):
- A fake DOM (use the existing Playwright test harness pattern, or a unit test
  over a parsed structure) where the primary text changed but role+name match →
  `heal_locator` returns the element.
- `uv run pytest tests/test_selector_heal.py tests/test_field_strategy_fill.py -q`

**Guardrails:** read-only element finding; never click/submit inside this module.

---

## W3 — Per-(family, step) escalation caps  (P1, Lane B)

**Why:** at 300/day you must stop burning 8 Gemini steps + a Claude rescue on a
dead login wall. Cap attempts per `(ats_family, step)` from recent `review_log`
outcomes and short-circuit to park/human.

**Files:** `src/applypilot/apply/direct/review_log.py` (+ read helper),
`src/applypilot/apply/direct/unblock_learning.py`

**Contract:**
1. `review_log.recent_fail_rate(conn, *, ats_family, since_hours=24) -> tuple[int,float]`
   returns `(attempts, fail_fraction)` where fail = outcome not in {'advanced'}.
2. New env knobs (default in `apply_settings` style):
   `APPLYPILOT_ESCALATE_MIN_ATTEMPTS` (default 6),
   `APPLYPILOT_ESCALATE_FAIL_RATE` (default 0.8).
3. In `run_unblock_with_learning`, before the step loop: if
   `attempts >= MIN and fail_fraction >= RATE`, log one `review_log` row with
   `outcome='escalate_human'` and return `False` immediately (park; the driver
   already parks on unblock failure). Do NOT call Gemini.

**Acceptance** (`tests/test_escalation_caps.py`, new):
- Seed `review_log` with 6 `no_change` rows for `ats_family='workday'`;
  `recent_fail_rate` → `(6, 1.0)`; `run_unblock_with_learning` returns False with
  zero Gemini calls (assert via a mocked `_gemini_decide`).
- Below threshold → normal loop runs.

**Guardrails:** caps are per-family (not global). Never cap below MIN attempts.

---

## W4 — Make the escalation ladder an explicit ordered list  (P2, Lane A)

**Why:** the tier order is currently implicit inside `resolve_unblock_action`.
Make it an auditable ordered list so tiers are pluggable and `review_log.tier` is
exact. No `py_trees` — a list of callables.

**File:** `src/applypilot/apply/direct/unblock_learning.py`

**Contract:**
```python
# ordered: each returns (action|None, tier_label); first non-None wins
_TIERS = [_tier_host_replay, _tier_family_replay, _tier_gemini]
def resolve_unblock_action(...): # iterate _TIERS, return first hit
```
Behavior must be **identical** to today (host replay → family replay → gemini).
This is a refactor, not a behavior change.

**Acceptance:** existing `tests/test_unblock_learning.py` passes unchanged plus a
new test asserting tier order (host hit preferred over family; family over gemini).
`uv run pytest tests/test_unblock_learning.py -q`

---

## W5 — Single-writer review_log (SQLite contention)  (P1, Lane C)

**Why:** 3 worker threads calling `review_log.log_event` with per-row
`conn.commit()` will hit `database is locked` under sustained load.

**File:** `src/applypilot/apply/direct/review_log.py`

**Contract:**
- Add a module-level single-writer queue: `log_event` enqueues a dict onto a
  `queue.Queue`; one daemon writer thread drains it and batches commits (e.g.
  flush every 50 rows or 1s). Provide `flush()` and `stop_writer()` for tests and
  shutdown. Keep the synchronous `log_event(conn, ...)` signature working (when no
  writer running, fall back to direct insert so unit tests stay simple).
- Wire `flush()`/`stop_writer()` into the launcher shutdown path
  (`apply/launcher.py` cleanup).

**Acceptance** (`tests/test_review_log_writer.py`, new):
- 3 threads × 100 `log_event` calls → after `flush()`, `list_recent` shows 300
  rows, no exception. `uv run pytest tests/test_review_log_writer.py -q`

**Guardrails:** do not lose rows on shutdown (flush before exit). Do not block the
fill loop waiting on writes.

---

## W7 — Launcher gating: let adapter-less families reach the driver  (P1, Lane D, prereq for W6)

**Why:** `launcher.py` parks non-adapter, non-`unknown` families (Workday) BEFORE
`apply_via_direct` runs (~`launcher.py:1865`), so no Workday recipe/adapter can
ever execute. Let generic+unblock attempt them in deterministic-only mode.

**File:** `src/applypilot/apply/launcher.py`

**Contract:** in `_try_direct_apply`, when `get_adapter(family) is None and family
!= UNKNOWN_FAMILY`, additionally allow the driver to run when
`apply_settings.deterministic_only_enabled()` is true (generic adapter handles it).
Preserve current behavior when not deterministic-only. Keep the park path for
genuinely unrunnable families behind a new check `job_runnable_in_deterministic_only`.

**Acceptance** (`tests/test_launcher_gating.py`, new):
- A Workday-URL job in deterministic-only mode reaches `apply_via_direct` (mock the
  driver, assert it was called); without deterministic-only, it parks as today.
- `uv run pytest tests/test_launcher_gating.py -q`

---

## W6 — Tier-0 Workday adapter (FSM)  (P1, Lane D, isolated)

**Why:** ~4 of every 10 target jobs funnel to Workday. A deterministic FSM adapter
is the 80/20 $0 lever; it dominates any learned/LLM path for this high-volume ATS.

**Files:** `src/applypilot/apply/direct/adapters/workday.py` (new),
`adapters/__init__.py` (register), align `fingerprint.py` (Workday already in
`ADAPTER_FAMILIES` but not registered — make detection + registry + gating agree).

**Contract:**
- Implement an `Adapter`-shaped descriptor + an FSM with named states keyed by
  page postconditions: `account_or_signin → my_information → my_experience →
  voluntary_disclosures → review → submit`. Each state: detect (DOM markers),
  fill via the existing resolver/`field_strategy_fill`, then advance via
  `next_page`. The final `submit` only fires after required-field validation
  (reuse the driver's validation; do NOT add a second submit path).
- Each transition declares a **postcondition** the executor verifies; a transition
  that did not advance is a failure (escalate, don't loop).
- Account creation (email/password/OTP) is OUT OF SCOPE — rely on a persistent
  logged-in worker profile; if `account_or_signin` shows a login wall with no
  session, return `awaiting_login` (the existing login-gate path).

**Acceptance:**
- Unit test the state detection + transition table against a saved Workday DOM
  fixture (`tests/fixtures/workday_*.html`) — assert the FSM picks the right state
  and next action per fixture. `uv run pytest tests/test_workday_adapter.py -q`
- Manual: a real Workday job dry-run reaches `review` without mis-submitting
  (document the URL used).

**Guardrails:** no account creation. Submit only via the validated path. Keep the
adapter self-contained under `adapters/`.

---

## W8 — Lightweight workflow induction (graduate clusters)  (P2, Lane E)

**Why:** turn repeated LLM-discovered sequences into owner-promotable recipes/
adapters. This is the useful 5% of AWM — a `GROUP BY`, not a framework.

**Files:** `src/applypilot/apply/direct/induction.py` (new), `cli.py` (subcommand)

**Contract:**
- `induce_candidates(conn, *, min_support=3) -> list[dict]`: group `review_log` by
  `(ats_family, state_sig)` where the same `action_type` succeeded
  (`postcondition_met=1`) at least `min_support` times and is not already
  `trusted` in `nav_playbook`; return candidates `{ats_family, state_sig,
  action_type, support}`.
- CLI `applypilot playbook induce [--promote]`: list candidates; with `--promote`,
  call `playbook.promote(state_sig, scope='host')` for each (owner-gated, so keep
  `--promote` explicit).

**Acceptance** (`tests/test_induction.py`, new):
- Seed `review_log` with 3 successful `click` rows on one `state_sig` →
  `induce_candidates` returns that cluster; a 2-row cluster is excluded.
- `uv run pytest tests/test_induction.py -q`

**Guardrails:** induction never auto-promotes without `--promote`. Offline only —
do not call this inside the apply hot path.

---

## W9 — Dashboard: tier mix, escalation caps, induction queue  (P2, Lane E)

**Why:** the owner needs to see which tier is firing, which families are hitting
escalation caps, and the induction candidates to promote.

**Files:** `src/applypilot/server/learning.py` (+ routes),
`dashboard/web/src/components/LearningDashboardPage.tsx`, `dashboard/web/src/api.ts`

**Contract:**
- New read endpoints: `/learning/tier-mix` (counts per `review_log.tier` over a
  window via existing `cache_hit_rate` shape), `/learning/escalations`
  (per-family `recent_fail_rate` from W3), `/learning/induction` (W8 candidates).
- Dashboard: add three read-only panels + a "Promote" button on induction rows
  (POSTs to the existing `/learning/promote`).

**Acceptance** (`tests/test_learning_api.py`, extend):
- Each new endpoint returns the expected JSON shape on seeded data.
- `uv run pytest tests/test_learning_api.py -q`

**Guardrails:** read-only except the existing promote/ban POSTs. No new auth.

---

## Explicitly OUT OF SCOPE (do not build)

- **HTN planner** — apply flows are linear; the multi-step driver loop + Workday
  FSM cover it.
- **`py_trees`** — the ladder is an ordered list (W4); the framework's reactive
  ticking/parallel/RUNNING semantics are not needed.
- **Policy distillation / OPD** — a deterministic adapter beats a distilled policy
  for the top ATS, and the long tail lacks the receipt volume.
- **Embedding / vector CBR** (`sqlite-vss`, faiss, sentence-transformers) — use W2
  structural self-healing for "revise" instead.
- **Account creation automation** (email/password/OTP) — persistent logged-in
  profiles + login-gate only.

## Verify before citing

The `2604.*` / `2511.*` arXiv IDs in
`docs/behavior-tree-apply-recommended-algorithms-may-2026.md` are future-dated and
unverified. AWM (`2409.07429`) and the Stagehand/py_trees links are real. Do not
base implementation choices on the unverified citations.

---

## Definition of done (whole plan)

- W1–W3, W5, W7 landed and green (the leaner core + scale-readiness + Workday gate).
- W6 Workday adapter reaches `review` on a real job without mis-submitting.
- `uv run pytest -q` shows no NEW failures vs the pre-plan baseline (32 failed /
  645 passed are pre-existing env failures — missing LLM keys/models, not yours).
- Dashboard shows tier mix + escalation + induction (W9).
- No forbidden deps added; safety invariants intact.
