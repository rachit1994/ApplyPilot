# Self-Learning Apply Architecture — cache the fix, LLM as fallback

## Principle

Every time an LLM (Gemini) solves a blocker, **record the solution as a
structured, replayable recipe** keyed by a signature of the problem. The next
time the same signature appears, **replay the recipe deterministically at $0** —
never ask an LLM again. The LLM is the fallback for *novel* problems only. Over
time, common sites/steps are fully covered and LLM calls asymptote to
"genuinely new situation."

This is the exact pattern `apply/direct/qa_bank.py` already uses for field
**answers** (Tier-1). We generalize it to two more decision classes:

| Decision class        | Today                         | Add                          |
|-----------------------|-------------------------------|------------------------------|
| What to answer a field| `qa_bank` (Tier-1) ✅          | keep                         |
| **How to fill a field** (checkbox/combobox quirk) | hard-coded in `driver._fill_field` | `field_strategy` cache |
| **How to navigate** (reveal form, login, advance) | Gemini every time (`unblock.py`) | `nav_playbook` cache |

## Tiered resolution (one model for all three decision classes)

```
Tier -1  user correction      field_overrides / correct-field      $0, wins always
Tier  0  deterministic rules   profile_binding, fingerprint         $0
Tier  1  LEARNED CACHE         qa_bank + nav_playbook + field_strategy   $0  ← the self-learning layer
Tier  2  Gemini                novel field/state                    ~$0.005, RECORDS to Tier 1 on success
Tier  3  Claude                Gemini failed / quota                rare,   RECORDS to Tier 1 on success
```

First hit wins. Tiers 2–3 always **write back** to Tier 1, so the system gets
cheaper with every application it files.

## The action vocabulary — the "functions" we create

A recipe is an ordered list of steps drawn from a **closed set of primitives**
(so a recorded step is replayable without an LLM). These are the functions that
get used over and over; most already exist in `driver.py`/`unblock.py` and just
need to be exposed behind one dispatch table:

```
# Navigation primitives
click(text)                 # button/link by visible text  (unblock._click_text)
accept_cookies()            # OneTrust + consent banners    (unblock._dismiss_cookies)
login_provider(name)        # "google" | "linkedin" | ...   (unblock login_google)
goto(url)
scroll()
wait_for_form(timeout)      # driver._wait_for_form_ready
next_page()                 # advance multi-step            (driver._find_advance_button + click)

# Fill primitives  (keyed by field signature, value from profile/qa_bank)
fill(field_sig, value)
select(field_sig, value)    # native <select> / react-select / radio
check(field_sig)            # checkbox; "click_label" variant for styled inputs
set_phone(field_sig, e164)  # intl-tel-input quirk
upload(field_sig, doc)      # doc ∈ {resume, cover}

# Terminal / detectors  (decide which recipe branch applies)
submit()
is_form_ready()             # ≥2 fields incl. identity      (unblock._has_identity_form)
detect_login()              # login_detect.detect_login_required
detect_verification_wall()  # driver._verification_wall_present
```

A `nav_playbook` step = `{tool: <one of the above>, args: {...}}`.
A `field_strategy` row = the *method* that worked for a field type on an ATS
(e.g. `{check: "click_label"}` for Greenhouse "I acknowledge").

## Signatures — how we recognise "the same problem"

The whole correctness story is in the **key** (same lesson as `qa_bank`). Three
signature levels, coarse→fine:

1. **Field signature** (exists): `sha1(norm(label)|section|name_attr|type)` —
   `qa_bank.question_key`. Reused for `field_strategy`.

2. **Navigation-state signature** (new):
   ```
   state_sig = sha1(
       ats_family |                       # workday, greenhouse, generic …  (NOT host)
       sorted(normalized clickable texts) |
       has_application_form |             # bool
       has_password_field |              # bool
       has_cookie_banner                 # bool
   )
   ```
   Keying on **`ats_family`, not host**, is the big win: a recipe learned on one
   Workday tenant replays on *every* Workday tenant. Tenant-specific noise
   (company name, job id) is excluded from the hash.

3. **Step signature** (new, for known multi-step ATS):
   `(ats_family, step_name)` e.g. `("workday", "my_information")`,
   `("workday", "voluntary_disclosures")`. Detected from page headings. Lets us
   seed/curate recipes per ATS step by hand (see "Seeding").

## Storage (SQLite, mirrors `qa_bank`)

```sql
-- Learned navigation recipes (one row per state → action that worked)
CREATE TABLE nav_playbook (
  state_sig      TEXT PRIMARY KEY,
  ats_family     TEXT,
  step_name      TEXT,          -- nullable; for known multi-step ATS
  action_type    TEXT,          -- one of the navigation primitives
  action_args    TEXT,          -- JSON
  status         TEXT,          -- 'trial' | 'trusted' | 'retired'
  success_count  INTEGER DEFAULT 0,
  fail_count     INTEGER DEFAULT 0,
  source         TEXT,          -- 'gemini' | 'claude' | 'seed' | 'human'
  created_at     TEXT,
  last_used_at   TEXT,
  last_verified_at TEXT         -- last time it led to an end-to-end apply
);

-- Learned per-field fill quirks (how, not what)
CREATE TABLE field_strategy (
  field_sig      TEXT,
  ats_family     TEXT,
  fill_method    TEXT,          -- 'value' | 'click_label' | 'react_select' | 'press_sequentially' …
  match_rule     TEXT,          -- JSON: option-matching rule for selects
  status         TEXT,
  success_count  INTEGER DEFAULT 0,
  fail_count     INTEGER DEFAULT 0,
  PRIMARY KEY (field_sig, ats_family)
);

-- qa_bank (field answers) and field_overrides (user corrections) already exist.
```

## The self-learning loop (no LLM after learning)

This is model-free, tabular reinforcement: cache the action that worked for each
state, with a confidence gate so a wrong action is never trusted.

```
def resolve_state(page):
    sig = state_signature(page)
    entry = nav_playbook.get(sig)                      # Tier 1
    if entry and entry.status == 'trusted':
        return entry.action                            #  $0 replay
    if entry and entry.status == 'trial':
        return entry.action                            #  $0 replay, provisional
    action = gemini_decide(page)                       # Tier 2 fallback
    nav_playbook.record(sig, action, status='trial')   #  write-back
    return action

# After executing the action:
def feedback(sig, advanced: bool):
    if advanced:                                       # state moved toward the form/submit
        nav_playbook.bump_success(sig)
        if success_count(sig) >= PROMOTE_K and recent_fail_rate(sig) < 0.2:
            nav_playbook.promote(sig, 'trusted')
    else:
        nav_playbook.bump_fail(sig)
        if recent_fail_rate(sig) > RETIRE_T:           # site changed → relearn
            nav_playbook.retire(sig)                   # next time falls back to Gemini
```

- **"advanced" signal** = the post-action `state_sig` is closer to a ready form
  (form appeared, login cleared, page index increased). Cheap to compute, no LLM.
- **Promotion gate** (`PROMOTE_K`, ~2) stops a one-off fluke from being trusted.
- **End-to-end confirmation**: when a job reaches `applied`, stamp
  `last_verified_at` on every recipe step used in that run — the strongest signal.
- **Decay/retire**: if a trusted recipe starts failing (the site redesigned), it
  auto-retires and Gemini relearns. Self-healing.

Same loop for `field_strategy`: first time the Greenhouse acknowledge checkbox
needs `click_label`, Gemini/Claude (or a one-line rule) discovers it, we record
`(field_sig, greenhouse) → click_label`, and every Greenhouse "I acknowledge"
after that is $0.

## Generalisation + graduation (cost goes to zero, then to code)

```
LLM discovery  ──►  nav_playbook (data, per ats_family)  ──►  codified adapter (code)
  $0.005/once          $0 replay, self-healing                $0, hand-verified, fastest
```

- Learning at the **ats_family** level means one Workday lesson covers thousands
  of Workday tenants — most of the long tail collapses fast.
- When a family's playbook is **trusted + high-volume**, graduate it into a real
  adapter (like `adapters/greenhouse.py`). The playbook literally tells you the
  step sequence to codify. This is the path to a first-class **Workday adapter**
  — the single highest-value gap (4 of the current 13 India jobs funnel to it).

## Seeding (don't cold-start the big ATS)

`config/common_questions.yaml` already seeds `qa_bank` (`seed-qa-bank`). Add
`config/nav_playbooks.yaml` to hand-seed recipes for the top ATS by step:

```yaml
workday:
  steps:
    - name: account_or_signin
      actions: [{tool: login_provider, args: {name: existing_session}}, {tool: next_page}]
    - name: my_information
      actions: [{tool: fill_all_known}, {tool: upload, args: {doc: resume}}, {tool: next_page}]
    - name: voluntary_disclosures
      actions: [{tool: fill_all_known}, {tool: next_page}]
    - name: review
      actions: [{tool: submit}]
```

Seeds start as `status='trusted', source='seed'` and decay like any other entry
if they stop working.

## Where this plugs into today's code

- `unblock.gemini_unblock()` → wrap each step: check `nav_playbook` first, call
  Gemini only on miss, record on success. (Smallest first build.)
- `resolver.resolve()` Tier-2 already records answers to `qa_bank`; add
  `field_strategy` write-back from `_fill_field` outcomes.
- `apply_outcomes` ledger already exists → feed `last_verified_at`.
- `correct-field` CLI → already Tier -1; extend to let a human pin a nav recipe.

## Build order

1. `nav_playbook` table + `playbook.py` (signature, record, replay, confidence).
2. Wire into `unblock.py`: Tier-1 replay before Gemini; write-back after.
3. `field_strategy` table + write-back from `_fill_field`.
4. `config/nav_playbooks.yaml` seeds for Workday/Greenhouse/Ashby.
5. Telemetry: % steps served from cache vs LLM (the cost curve), per ats_family.
6. Graduate the first trusted family (Workday) into a codified adapter.
```
