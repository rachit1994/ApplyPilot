# Worker Handbook — Perfect the Deterministic Apply Engine

**Audience: a coding worker LLM that runs for hours, cannot think, and follows
orders.** Your one job: every time the apply pipeline escalates a job to an LLM
(Gemini/Claude) or parks it, treat that as a **bug in the deterministic ($0)
path** and write code so the next job of that shape is handled deterministically.
You are not filling forms (that is [worker-apply-playbook.md](worker-apply-playbook.md),
a different worker). You are **making the form-filler need an LLM less and less,
until it needs one almost never.**

> The thinking is already done and lives in this file. You **match a symptom to a
> fix recipe, apply the recipe verbatim, run its verify command, record the
> result, and loop.** Never improvise. If no recipe matches, you STOP and file a
> human escalation (see §9). Do not invent a fix that is not in §6.

Design rationale you must NOT relitigate:
[self-learning-apply-architecture.md](self-learning-apply-architecture.md),
[scaled-self-learning-apply-plan.md](scaled-self-learning-apply-plan.md),
[worker-implementation-plan-june-2026.md](worker-implementation-plan-june-2026.md).

---

## 0. The one mental model

The form-filler resolves three decisions, each through an ordered ladder. **First
hit wins. The top tiers are $0. The bottom tier is an LLM.** Every LLM call is a
hole in a higher tier that you are here to patch.

```
DECISION            $0 deterministic tiers (you grow these)          LLM fallback (you shrink this)
-----------------   ----------------------------------------------   --------------------------
What to answer      Tier-1 user override  →  Tier-0 profile rule  →  Tier-2 Gemini batch
  a field             (field_overrides)        (profile_binding)      (resolver._gemini_batch)
                      →  Tier-1 cache (qa_bank)

How to FILL          cached field_strategy  →  inferred method        (escalate: unresolved/verify_incomplete)
  a field             (playbook.field_strategy) (field_strategy_fill)

How to NAVIGATE      host replay  →  family replay                 →  Gemini unblock
  (reveal/login/next) (nav_playbook trusted/pinned)                   (unblock_learning._gemini_decide)

Whole ATS            Tier-0 adapter (adapters/*.py)  →  generic adapter  →  Claude rescue / park
```

The cost curve only bends down when **a discovered fix is written back into a
higher tier**: an answer into `qa_bank`, a fill quirk into `field_strategy`, a nav
step into `nav_playbook`, a vendor flow into an `adapter`. The system already
writes some of these back automatically; **your job is the ones it cannot learn
on its own, and graduating the learned ones into trusted/code.**

**Generalisation rule (how you make it handle *unforeseen* forms):** always fix at
the **most general layer that resolves the symptom**, so one fix covers the long
tail:

```
field_overrides (one label)  ⊂  profile_binding rule (one concept, all forms)
host nav recipe (one tenant) ⊂  family nav recipe (whole ATS family)
one adapter marker           ⊂  generic adapter markers (every unknown form)
LLM discovery ($0.005 once)  →  nav_playbook data ($0 replay)  →  codified adapter ($0, fastest)
```

---

## 1. The operating loop (run this forever)

Each iteration is six phases. Do them **in order**, one job-shape at a time. Never
batch fixes; one symptom → one fix → one verify → one commit.

```
┌─ OBSERVE  ── read review_log + apply outcomes; pick the #1 escalation cluster
├─ CLASSIFY ── map its failure code to a row in §5 (the taxonomy)
├─ DIAGNOSE ── run that row's diagnostic commands (§7) to find the missing layer
├─ FIX      ── apply the §6 recipe the row names — edit code, nothing else
├─ VERIFY   ── run the recipe's acceptance command (tests) + re-run the live repro
└─ RECORD   ── append to the ledger (§8), commit on a branch, loop
```

### 1.1 OBSERVE — pick the highest-leverage *still-live* failure

Do **not** just attack the highest-count cluster. (Verified by dogfooding: the
top-count clusters are usually **already capped** — the escalation cap has tripped,
so the system no longer spends any LLM on them and parks them `needs_adapter`.
"Fixing" a capped cluster wastes your iteration and the page is almost always a
structural wall → §9 STOP.) Attack the highest-count cluster that is **not yet
capped** and **not already served from replay**.

Run this one script — it prints the cache mix and a ranked worklist already
annotated with `CAPPED`, the dominant tier, and a real `repro_url` (so you can
skip the capped rows and have a URL for §1.2 without a second query):

```bash
uv run python -c "
from applypilot.database import init_db, get_connection
from applypilot.apply.direct import review_log
init_db(); c = get_connection()
print('cache_hit_rate:', review_log.cache_hit_rate(c))  # your scoreboard
for row in review_log.dedupe_clusters(c, limit=25):
    fam, host, sig = row['ats_family'], row.get('apex_host'), row['state_sig']
    n, fr = review_log.recent_fail_rate(c, ats_family=fam,
                                        apex_host=host if fam=='generic' else None)
    capped = 'CAPPED' if (n >= 6 and fr >= 0.8) else ''
    url = (c.execute('SELECT job_url FROM review_log WHERE state_sig=? AND job_url IS NOT NULL LIMIT 1',
                     (sig,)).fetchone() or [None])[0]
    print(f\"{row['count']:>3}x {row['tier']:>6} {row['action_type'] or '-':>14} \"
          f\"{row['outcome'] or '-':>12} {fam:>10} {capped:>6} {(host or '')[:30]:>30}  {url or ''}\")
"
```

Pick the **first row that is NOT `CAPPED` and whose tier is `gemini`** (an LLM
cost you can remove). Skip `replay` rows (already $0) and `CAPPED` rows (already
handled — only revisit one if you can make the deterministic path *see the form*,
R6/R7, otherwise it's a §9 STOP). Tie-break by ATS family volume
(Workday/Greenhouse first). The `repro_url` column feeds §1.2 directly.

**If every non-capped cluster is `replay` and `induce` (below) is empty, nothing
is cleanly actionable this iteration — go to §1.3, do not force a fix.**

### 1.2 Reproduce deterministically before you touch code

You must see the failure yourself, with the LLM **off**, so you are fixing the
deterministic path and not papering over it with an LLM:

```bash
APPLYPILOT_DIRECT_GEMINI=0 APPLYPILOT_DIRECT_ESCALATE=0 \
  uv run applypilot apply --url "<the failing job url>" \
  --deterministic-only --dry-run --no-continuous --workers 1 --watch
```

- `--dry-run` fills the form but **never submits** — safe to run repeatedly.
- `--deterministic-only` parks anything an adapter can't handle (no Claude spend).
- `APPLYPILOT_DIRECT_GEMINI=0` forces Tier-2 answers off so unresolved fields
  surface as `failed:direct_unresolved_required` instead of being hidden.
- `--watch` = visible Chrome, paced, so you can read the page. Headless Chrome is
  known to crash on real submits — keep it visible for repros
  ([memory: direct-apply-submit-reliability]). For a quick *observation-only*
  repro you may use `--headless --plain` with a wall timeout and
  `APPLYPILOT_DIRECT_JOB_TIMEOUT=45` so it can't hang.

**Your CLASSIFY key is the outcome the run reports — read it in this priority:**

1. A `failed:…` / `awaiting_login:…` **result line** if one is printed.
2. Otherwise the **worker-log line**, which is what you'll usually see in
   deterministic-only runs. The two that matter:
   - `Unblock capped for <family> (N attempts, X% fail)` + `Parked needs_adapter`
     — the escalation cap already fired (the cluster is `CAPPED`). This is **not a
     fresh failure to fix**: the system already stopped spending on it. Treat as
     the `escalate_human` row in §5 (R10 + §9, structural).
   - `Direct content-sniff reclassified unknown -> <family>` tells you the family
     actually used (may differ from the URL's family — classify against *this* one).

Match whichever surfaced to a §5 row.

### 1.3 When nothing is cleanly actionable (the common steady state)

Dogfooding showed the realistic state is: high-volume failures auto-cap (handled),
working flows replay ($0), and the genuinely-learnable clusters sit **below
induction support**. When that's where you are, do exactly one of these, in order,
then RECORD and loop — do **not** invent a fix or STOP the whole worker:

1. **Graduate what's nearly ready:** `uv run applypilot playbook induce
   --min-support 2` to scout clusters one short of the default threshold. If a
   high-volume family (Workday/Greenhouse) shows a coherent advancing step, seed it
   proactively (R4b) so it's `trusted` before it re-occurs.
2. **Proactively seed a high-volume family** that has no `trusted` reveal recipe
   yet (`playbook list --status trusted` to check) via R4b.
3. **Nothing to seed:** record a one-line "no actionable cluster; cache_hit_rate
   X%" ledger note and let the pipeline run more so review_log accumulates.

---

## 2. Where the deterministic logic lives (your edit map)

You only ever edit files in this list. If a fix needs a file not here, STOP (§9).

| Layer | File | What you add here |
|---|---|---|
| Answer Tier-0 (rules) | `src/applypilot/apply/direct/profile_binding.py` | new field-concept → profile-token rules; select-option matching |
| Answer Tier-1 (cache seed) | `src/applypilot/config/common_questions.yaml` | seed Q&A answers (`applypilot seed-qa-bank`) |
| Answer Tier-1 (user pin) | (CLI `correct-field`) | pin one label's answer forever |
| Fill methods | `src/applypilot/apply/direct/field_strategy_fill.py` | new fill method / better `infer_fill_method` |
| Field extraction | `src/applypilot/apply/direct/extractor.py` | detect fields/labels the extractor misses |
| Identity / form detection | `src/applypilot/apply/direct/unblock.py` (`_has_identity_form`, `has_identity_field`) | widen what counts as "a real form" |
| Nav recipes (seed) | `src/applypilot/config/nav_playbooks.yaml` | hand-seed reveal/login/next steps |
| Nav signature | `src/applypilot/apply/direct/playbook.py` (`_salient_clickables`, `state_signature`) | stabilise the key so recipes generalise |
| Selector self-healing | `src/applypilot/apply/direct/selector_heal.py` | structural rebind when a cached selector drifts |
| ATS adapters | `src/applypilot/apply/direct/adapters/*.py` + `adapters/__init__.py` | vendor markers / a full Tier-0 FSM adapter |
| Family detection | `src/applypilot/apply/direct/fingerprint.py` | new host/param/content signal for a family |
| Verification / login / expired walls | `driver.py` (`_verification_wall_present`), `login_detect.py`, adapter `expired_markers` | classify a wall correctly |
| Escalation caps | `src/applypilot/apply/apply_settings.py` (`escalate_*`) | tune when to stop burning LLM on a dead family |

The orchestration you read but **do not casually rewrite**:
`driver.apply_via_direct` (the fill→verify→submit state machine),
`resolver.resolve` (answer ladder), `unblock_learning.run_unblock_with_learning`
(nav ladder), `launcher.py` (job queue + gating).

---

## 3. How escalation actually happens (so you know what you are removing)

Read these three control points once; they are the only places "deterministic
failed → escalate" is decided.

1. **Answers** — `resolver.resolve()` (`resolver.py:103`). A field that misses
   Tier‑(-1/0/1) goes to the Tier-2 Gemini batch. If Gemini is off or fails and
   the field is `required`, it lands in `unresolved_required`. The driver then
   returns `failed:direct_unresolved_required` (`driver.py:1764`). **Every entry
   in `unresolved_required` is a missing profile rule or qa seed.**

2. **Navigation** — `run_unblock_with_learning()`
   (`unblock_learning.py:298`). It replays a cached nav step if one is
   `trusted`/`pinned` (host then family scope, `_TIERS` at
   `unblock_learning.py:188`); on a miss it calls Gemini, executes the action, and
   **records it back to `nav_playbook` as `trial`** (`record_nav`). A trial gets
   promoted to `trusted` after `PROMOTE_K=2` weak successes or one receipt
   (`playbook.maybe_promote`, `playbook.py:483`). **Every Gemini nav step is a
   recipe not yet seeded or not yet promoted.**

3. **Whole-form / submit** — `driver.apply_via_direct()` (`driver.py:1278`). It
   validates **identity present + every required field non-empty** before it will
   click submit (`_required_empty_fields`, `driver.py:1553`), and `submit` is
   **never** replayed from cache (`playbook.is_replay_allowed`). On any uncertainty
   it returns a `failed:…` code with `escalate=True` rather than risk a junk
   submission. **Iron rule you inherit: never weaken this. Make the deterministic
   path resolve the field; do not lower the bar for submitting.**

The promotion/retire machinery is automatic and self-healing: a `trusted` recipe
that starts failing auto-retires at `RETIRE_FAIL_RATE=0.5` (`playbook.bump_fail`)
and relearns. You rarely touch it — you **feed** it (seeds) and **graduate** it
(induce/promote, then codify).

---

## 4. Safety invariants — NEVER break these (a violation = STOP and revert)

These are inherited from the architecture and the implementation plan. They are
not negotiable and not yours to "improve."

1. **`submit` is never replayed from cache** and the driver only submits after
   deterministic identity + required-field validation. Do not add a second submit
   path; do not lower the validation bar to make a job pass.
2. **Side-effecting nav** (`click`/`next_page`/`login_*`/`goto`/`apply`) replays
   **only** when the entry is `trusted`/`pinned`. Don't mark something trusted to
   force a replay — let it earn promotion, or seed it deliberately.
3. **Never junk-submit.** On ambiguity the engine parks. A parked job is a
   success for you (it's safe); a wrongly-submitted junk application is a failure.
4. **Auto-discovery may not clobber owner intent.** `record_nav` cannot overwrite
   a `banned`/`pinned`/`trusted` row unless `force_update=True` (the seed path).
   Respect it.
5. **Induction never auto-promotes.** `applypilot playbook induce` lists; only
   `--promote` writes, and only you/owner runs it. Keep it that way.
6. **Tests run on a fresh DB.** Use the autouse `isolated_db` fixture; never write
   to `~/.applypilot` from a test. Verify with `uv run pytest <files> -q`.
7. **No new heavy deps.** Forbidden by decision: `py_trees`, HTN planners, policy
   distillation, embedding/vector CBR (`sqlite-vss`, `faiss`,
   sentence-transformers). "Fuzzy match" = structural selector self-healing, not
   embeddings.
8. **Do not break the baseline.** `uv run pytest -q` must show **no NEW failures**
   vs the pre-existing baseline (~32 failed / ~645 passed are known env failures:
   missing LLM keys/models — not yours). If your change adds a failure, revert.
9. **Keep diffs minimal and tested.** One symptom, one fix. Update tests you
   intentionally change; never silently delete coverage.

---

## 5. Failure taxonomy — symptom → cause → fix recipe

This is your CLASSIFY table. Match the exact result line (or `escalate_reason` in
`review_log.failure_reason`) to a row. The "Most likely cause" is ordered: check
the first; only move on if the diagnostic (§7) rules it out.

| Result line / reason | What it means | Most likely cause → root layer | Fix recipe (§6) |
|---|---|---|---|
| `failed:direct_unresolved_required` | a required field had no $0 answer and Gemini was off/failed | missing **profile rule** (Tier 0) → missing **qa seed** (Tier 1) | **R1** then **R2** |
| `failed:direct_verify_incomplete` | a required field re-read as still-empty after fill | answer resolved but **fill method** failed (styled checkbox/react-select/combobox) → or extractor mis-read `required` | **R3** then **R7** |
| `failed:direct_no_application_form` | page had no identity form after reveal/unblock | **reveal nav** missing (didn't click Apply / advance) → **identity detection** too narrow | **R4** then **R6** |
| `failed:direct_no_form` / `partial_form` | <2 fields or a partial form extracted | **extractor** missed the fields (iframe, late mount) → reveal nav missing | **R7** then **R4** |
| `failed:direct_no_adapter` | family has no adapter and page isn't a sniffable embed | **adapter/markers** missing for this vendor → family not detected | **R5** then **R8** |
| `failed:direct_no_submit_button` | filled OK but submit control not found by adapter | adapter `submit_button_texts` missing this label | **R5** (markers only) |
| `failed:direct_submit_rejected` / `direct_not_submitted` | clicked submit, form stayed with errors / unchanged | a field filled wrong (bad answer/option) → validation we didn't satisfy | **R1/R2** (fix the answer) then **R3** |
| `failed:direct_needs_verification` | email-code / human-check wall not cleared | email-verify path gap, or wall mis-classified | **R9** |
| `awaiting_login:<dom>` | a login wall with no session | **expected & safe** — needs a logged-in worker profile; only fix if mis-detected | **R6** (detection) else **leave** |
| `escalate_human` (tier=`cap`) | per-family fail-rate cap tripped; Gemini skipped | that family is genuinely stuck (often login/SSO/account-creation) | **R10** + §9 if structural |
| `failed:direct_unblock_quota` | Gemini quota exhausted mid-unblock | not a logic bug — **seed the nav recipe** so replay covers it next time | **R4** |
| `failed:direct_nav_timeout` / `direct_timeout` | page never loaded / job ran too long | infra/slow site, not logic. Retry once; if persistent, leave | **leave / tune timeout** |
| repeated Gemini nav steps that **advance** (`postcondition_met=1`, tier `gemini`) on one `state_sig` | a working recipe being rediscovered every time at $0.005 | recipe learned but not **promoted/seeded** | **R4** (induce/seed) |
| repeated Gemini nav steps that **don't advance** (`postcondition_met=0`, tier `gemini`, action `wait`/`click_miss`/`cookies_miss`) on one `state_sig` | LLM stuck on a page that never surfaces a form; burns calls until the cap trips | the form is hidden (iframe/late mount/login gate) **or** the page is a structural wall | if a form is actually present but unseen → **R6/R7**; if it's a login/SSO/region wall → it will auto-cap → **§9 STOP** |
| repeated Gemini answers (`via=t2:gemini`) for the same label across companies | an answer being rediscovered every form | belongs in **profile rule** or **qa seed** | **R1** then **R2** |

If the result line is not in this table → STOP (§9). Do not guess.

---

## 6. Fix recipes — the closed set of moves

Each recipe is: **trigger → exact edit → acceptance command**. Apply verbatim. Do
not combine recipes in one commit. After any code edit, the relevant `uv run
pytest …` must pass and the §1.2 repro must now reach further (or `applied` in a
real run) than before.

> Generalisation order (always try in this order, stop at the first that fits):
> **R1 (profile rule) > R2 (qa seed) > R4 (family nav) > R5 (adapter)**. A higher
> recipe covers more future jobs. Only drop to a narrower one when the concept is
> genuinely company-specific.

### R1 — Add/repair a Tier-0 profile rule (covers a concept on *every* form)

**Trigger:** an `unresolved_required` field (or a repeated `t2:gemini` answer)
whose label maps to a known profile fact (work auth, sponsorship, experience,
salary, location, notice period, etc.).

**Edit:** `src/applypilot/apply/direct/profile_binding.py`. Add a matching rule
that maps the field's normalized label/section to a profile token and returns an
answer. For select/radio, ensure `choose_select_option` snaps to a real option.
Mirror the existing rule style exactly (label-substring → token).

**Acceptance:**
```bash
uv run pytest tests/test_direct_profile_binding.py tests/test_direct_resolver.py -q
```
Add a test: the new field label resolves at Tier 0 (`via` starts `t0:`) with no
LLM. Then re-run §1.2 repro — the field must no longer be `unresolved`.

### R2 — Seed a Tier-1 qa_bank answer (a screening answer rules can't derive)

**Trigger:** an `unresolved_required` field that is a **policy/opinion screening
question** (not derivable from profile facts) recurring across companies — e.g.
"Why do you want to work here", "Are you willing to work nights", standard EEO.

**Edit:** add the question + answer to
`src/applypilot/config/common_questions.yaml` (follow the existing schema), then:
```bash
uv run applypilot seed-qa-bank
```
For a **one-off, owner-specific** correction to a single label, prefer the pin:
```bash
uv run applypilot correct-field "<Label>" "<Value>"   # Tier -1, wins forever
```

**Acceptance:** `uv run pytest tests/test_qa_bank.py -q` (if present) +
`uv run applypilot playbook review` shows the field now resolves `t1:cache` /
`override:user`, not `t2:gemini`. Re-run §1.2.

> Never seed a **weak/anonymous** label (`""`, `text`, `field`, `select`, …) —
> the resolver refuses to cache them on purpose (`resolver._WEAK_LABELS`) because
> the key collides onto unrelated fields. If the label is weak, the real fix is
> **R7** (make the extractor read a real label).

### R3 — Add/repair a fill method (answer was right, the *click* failed)

**Trigger:** `failed:direct_verify_incomplete` where the field had a resolved
answer (check `review_log`/logs: it was filled then re-read empty). Typical: a
styled checkbox needing a label-click, a react-select combobox, an
`intl-tel-input` phone, a "type to filter" select.

**Edit:** `src/applypilot/apply/direct/field_strategy_fill.py`. Either improve
`infer_fill_method` so it picks the right method for this field shape, or add a
new `_fill_*` implementation and wire it into `fill_field_with_strategy`. Methods
today: `value`, `click_label`, `press_sequentially`, `react_select`. The engine
**auto-writes** the winning method to `field_strategy` per `(field_sig,
ats_family)` via `record_fill_outcome`, so once it works it replays at $0.

**Acceptance:**
```bash
uv run pytest tests/test_field_strategy_fill.py -q
```
Re-run §1.2; the field must now verify as filled.

### R4 — Seed or graduate a navigation recipe (reveal / login / next / advance)

**Trigger:** `failed:direct_no_application_form` (reveal missing),
`failed:direct_unblock_quota`, or a `state_sig` where Gemini keeps choosing the
same advancing action.

**Two sub-moves:**

**R4a — graduate an already-learned recipe** (preferred — it's proven):
```bash
uv run applypilot playbook induce --min-support 3        # list ready clusters
uv run applypilot playbook induce --min-support 3 --promote   # owner-gated promote
# or promote one explicitly:
uv run applypilot playbook promote <state_sig> --scope host   # or --scope family
```
Promote to **family scope** when the recipe is vendor-generic (a Workday "Apply"
reveal works on every Workday tenant) so one promotion covers the family.

**R4b — hand-seed a recipe** when there's no learned data yet: add a step to
`src/applypilot/config/nav_playbooks.yaml` (only the **first unblock-executable**
action of a step is seedable: `click`, `accept_cookies`, `goto`, `login_provider`;
fill/upload/next_page/submit are adapter-level — see R5). Then:
```bash
uv run applypilot playbook seed --family <family>
uv run applypilot playbook list --status trusted
```

**Acceptance:** `uv run pytest tests/test_playbook.py tests/test_playbook_seed.py
tests/test_unblock_learning.py -q`. Re-run §1.2; the form must now reveal without
a Gemini step (`tier=replay` in `playbook review`).

> If recipes "won't fire" across tenants, the cause is usually the **signature
> key** including job-specific noise. The fix is `_salient_clickables` /
> `state_signature` in `playbook.py` (already keyed to a nav-vocabulary subset and
> `ats_family`, not host). Only touch the signature with extreme care and bump
> `SIG_VERSION` (old rows relearn). Add a `tests/test_playbook.py` case proving
> two noisy-but-equivalent pages hash the same and two genuinely different ones
> don't.

### R5 — Add or extend an ATS adapter (vendor chrome / a full Tier-0 flow)

**Trigger:** `failed:direct_no_adapter`, `failed:direct_no_submit_button`, or a
high-volume family repeatedly escalating.

**R5a — markers only** (fast win): the form fills generically; only the
apply/submit/success/expired text differs. Edit the family's
`adapters/<family>.py` `Adapter(...)` (add the missing `submit_button_texts` /
`apply_button_texts` / `success_markers` / `expired_markers`). For an
**unknown-vendor** form, widen `adapters/generic.py` markers instead — that covers
*every* unforeseen company form at once (the highest-leverage marker fix).

**R5b — new family adapter:** create `adapters/<family>.py` exposing
`ADAPTER = Adapter(family="…", …)`, register it in `adapters/__init__.py`
`_REGISTRY`, and confirm `fingerprint.ats_family` already detects the host (else
**R8**). For a high-volume multi-step vendor (Workday), implement the FSM adapter
per **W6** in [worker-implementation-plan-june-2026.md](worker-implementation-plan-june-2026.md)
(named states + per-transition postconditions; **submit only via the validated
driver path; no account creation**).

**Acceptance:** `uv run pytest tests/test_direct_fingerprint.py
tests/test_<family>_adapter.py -q` (add a DOM-fixture test for new adapters).
Real-job dry-run must reach `review`/submit-ready without mis-submitting; record
the URL used.

### R6 — Fix identity / login detection (a real form read as "no form", or a wall mis-classified)

**Trigger:** `failed:direct_no_application_form` on a page that visibly *has* a
form, or an `awaiting_login` on a page that is **not** actually gated.

**Edit:** widen `unblock._has_identity_form` / `unblock.has_identity_field`
(`unblock.py`) to recognise the identity fields this form uses, or correct
`login_detect.detect_login_required` (`login_detect.py`) so a non-gated page
isn't parked. Keep it conservative — false "form ready" leads to junk; when unsure
prefer leaving the park.

**Acceptance:** `uv run pytest tests/test_direct_resolver.py -q` + a new
detection test. Re-run §1.2.

### R7 — Widen the extractor (fields/labels it can't see)

**Trigger:** `failed:direct_no_form`/`partial_form`, or a **weak label** that
blocked R2, or a field the page shows but `verify_page_state`/extract misses
(custom components, fields in a same-origin iframe, label-less inputs with
`aria-label`/placeholder).

**Edit:** `src/applypilot/apply/direct/extractor.py` — teach it to read the label
source this form uses (aria-label, `<label for>`, placeholder, nearby text) and to
descend into readable iframes. Do **not** make it descend cross-origin (the driver
navigates straight to embed form URLs for that — see
`fingerprint.greenhouse_form_url`).

**Acceptance:** `uv run pytest tests/test_*extractor* -q` (add a parsed-DOM
fixture). Re-run §1.2; field count must rise and labels must be real.

### R8 — Register a new ATS family signal (so detection/gating agree)

**Trigger:** a vendor's jobs read as `unknown` (no adapter dispatch) though it's a
known ATS, or a custom career domain backed by a known ATS isn't sniffed.

**Edit:** `src/applypilot/apply/direct/fingerprint.py` — add the host fragment to
`_FAMILY_HOST_FRAGMENTS`, a telltale query param to `_FAMILY_QUERY_PARAMS`, or a
high-confidence DOM marker to `sniff_ats_family`. Keep `ADAPTER_FAMILIES`,
`_REGISTRY`, and detection **in agreement** (a family in `ADAPTER_FAMILIES` must
have a registered adapter or it parks).

**Acceptance:** `uv run pytest tests/test_direct_fingerprint.py -q` with a case
for the new signal.

### R9 — Classify a verification wall correctly

**Trigger:** `failed:direct_needs_verification`. Determine which wall it is:
- **Emailed code** (e.g. Greenhouse 8-char human check): the path exists
  (`email_verify.py`, `_try_clear_verification_wall`). If it's not firing, the
  cause is usually the Gmail session / marker text — extend
  `driver._verification_wall_present` markers or fix `email_verify` matching.
- **Captcha needing a solver/payment, SSO, video/selfie, card/SSN:** this is
  **NOT a logic bug** — it's a STOP (§9). Add the marker so the engine parks it
  cleanly with the right reason; do not try to defeat it.

**Acceptance:** `uv run pytest tests/test_email_verify.py
tests/test_gmail_receipts.py -q`. Re-run §1.2.

### R10 — Tune escalation caps (stop burning LLM on a dead family)

**Trigger:** a family produces many `escalate_human` (tier=`cap`) rows, or
conversely a fixable family is being capped too early before your other fixes can
land.

**Edit:** adjust env knobs (no code change needed):
`APPLYPILOT_ESCALATE_MIN_ATTEMPTS` (default 6),
`APPLYPILOT_ESCALATE_FAIL_RATE` (default 0.8) — both read in
`apply_settings.escalate_*` and enforced in `run_unblock_with_learning`. Lower the
cap to protect budget on a structurally-blocked family; raise it temporarily while
you're actively seeding that family so trials can accumulate.

**Acceptance:** `uv run pytest tests/test_unblock_learning.py -q` (caps tests).
Document the knob change in the ledger.

---

## 7. Diagnostic toolkit (read-only — run these in DIAGNOSE)

```bash
# 1. What the engine saw on this job, tier by tier:
uv run applypilot playbook review --limit 50

# 2. Is this answer/nav being rediscovered (LLM) or replayed ($0)?
uv run python -c "
from applypilot.database import init_db, get_connection
from applypilot.apply.direct import review_log
init_db(); c=get_connection()
print('hit_rate', review_log.cache_hit_rate(c))
print('per-family fail rate (workday):', review_log.recent_fail_rate(c, ats_family='workday'))
"

# 3. What recipes exist / are trusted for this family:
uv run applypilot playbook list --status trusted
uv run applypilot playbook stats

# 4. Which tier resolved each field on the failing form: run the §1.2 repro and
#    read the 'via' tags in logs (t0:* rule, t1:cache, t2:gemini, override:user).

# 5. Family of a URL (is it even detected?):
uv run python -c "from applypilot.apply.direct import fingerprint as f; print(f.ats_family('<url>'))"
```

Dashboard (if the owner has it up): the Learning page surfaces tier mix, escalation
caps per family, and the induction queue (`server/learning.py`,
`LearningDashboardPage.tsx`). Use it to confirm your fix moved the cache-hit-rate
up and the LLM share down — **that number going up is your scoreboard.**

---

## 8. RECORD — the ledger (so the next cold iteration can continue)

You will be restarted with no memory. After every fix, append one block to
`docs/worker-deterministic-apply-ledger.md` (create it if absent). Format:

```
## <ISO timestamp> — <result_line you attacked>
- Cluster: <family> / <count> occurrences / state_sig <prefix>
- Repro URL: <url>
- Root layer: <profile rule | qa seed | fill method | nav recipe | adapter | extractor | detection | family>
- Recipe applied: R<n> — <one line of what you changed, file:func>
- Verify: <pytest files> PASS ; repro now reaches <new outcome>
- Cache-hit-rate before→after: <x%>→<y%>
- Commit: <branch> <short-sha>
- Follow-ups / left for human: <none | …>
```

**Git discipline:** work on a branch (never commit to `main`), one commit per
recipe, message = `apply(det): R<n> <family> <symptom> — <result before→after>`.
Run `uv run pytest -q` before each commit; if it adds a NEW failure vs baseline,
**revert the commit** and re-diagnose. Do **not** push or open PRs unless the owner
asked — leave that to them.

---

## 9. STOP conditions — when you must NOT code, and escalate to the human

Stop the loop, write a `STOP:` block in the ledger with the URL and reason, and
move to the next cluster. These are **not** deterministic-logic bugs:

- **SSO / Okta / Microsoft / "single sign-on"** login walls.
- **Account creation required** (email + password + OTP signup) — out of scope by
  decision; needs a persistent logged-in worker profile, which only the owner sets
  up.
- **Captcha that needs a paid solver, video/selfie/webcam, card/bank/SSN/payment**
  — add a park marker (R9) but never attempt to defeat it.
- **Not a real job application** (freelance/contractor marketplace, "set your
  rate") — mark and skip.
- The result line is **not in §5**, or the fix would require editing a file **not
  in §2**, or it would **weaken a §4 invariant** (e.g. "just lower the
  required-field check so it submits"). These are traps — STOP.
- Your change makes `uv run pytest -q` show a **new** baseline failure you can't
  resolve in one revertible step.
- A structural product gap (e.g. the whole India multi-step Workday flow needs a
  new FSM adapter and you lack a saved DOM fixture). File it for the owner with the
  exact W-ticket reference rather than half-building it.

---

## 10. Two worked traces (the pattern, end to end)

**Trace A — recurring sponsorship question (answer gap).**
1. OBSERVE: `dedupe_clusters` shows 14× `failed:direct_unresolved_required`,
   label "Will you now or in the future require sponsorship?" across 9 companies,
   resolved `t2:gemini` each time.
2. CLASSIFY: §5 row → cause = missing profile rule → **R1**.
3. DIAGNOSE: §7 #4 — the field is a select; `profile_binding.resolve_field`
   returns None; profile token `require_sponsorship` exists but no rule maps this
   label.
4. FIX (R1): add a rule in `profile_binding.py` mapping labels containing
   "require sponsorship"/"need sponsorship"/"visa sponsorship" → token
   `require_sponsorship`, snapped via `choose_select_option`.
5. VERIFY: `uv run pytest tests/test_direct_profile_binding.py
   tests/test_direct_resolver.py -q` PASS; §1.2 repro now fills it at `t0:` and
   reaches submit-ready.
6. RECORD: ledger block; commit `apply(det): R1 generic sponsorship — t2→t0`.

**Trace B — Workday never reveals the form (nav gap).**
1. OBSERVE: 23× `failed:direct_no_application_form`, family `workday`, Gemini
   clicks "Apply" every time and it *advances* (`postcondition_met=1`, tier
   `gemini`).
2. CLASSIFY: §5 "repeated advancing Gemini nav step" → **R4**.
3. DIAGNOSE: §7 #3 — `playbook list --status trusted` shows no Workday reveal
   recipe; `induce --min-support 3` lists the cluster.
4. FIX (R4a): `playbook induce --min-support 3 --promote`, then verify it landed
   at **family** scope so all tenants benefit; (R4b backstop: confirm the
   `workday: apply_reveal` seed in `nav_playbooks.yaml`, `playbook seed --family
   workday`).
5. VERIFY: `uv run pytest tests/test_playbook.py tests/test_playbook_seed.py
   tests/test_unblock_learning.py -q` PASS; §1.2 repro now reveals the form with
   `tier=replay`, zero Gemini.
6. RECORD: ledger; cache-hit-rate for workday 41%→78%.

---

## 11. Definition of "deterministic logic perfected" (your success metric)

You are done with a family/shape when, over a fresh run:

- its **cache-hit-rate** (Tier-0/1 share in `review_log.cache_hit_rate`) is high
  and climbing, and `t2:gemini` / `gemini` nav steps for it approach zero;
- no recurring `failed:direct_*` cluster remains in `dedupe_clusters` except the
  legitimate STOP categories (§9);
- the high-volume families (Workday, Greenhouse, generic India forms) reach
  `applied` or submit-ready **without an LLM in the loop**;
- `uv run pytest -q` is at baseline (no new failures), and every fix is in the
  ledger.

Then move to the next family. The asymptote — the whole point — is an apply
pipeline that handles **unforeseen** forms on its own because the generic adapter,
the profile rules, the family nav recipes, and the field-strategy cache have grown
to cover the long tail, and the LLM is reached only for genuinely novel pages.
