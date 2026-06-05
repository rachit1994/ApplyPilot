# Recommended algorithms for tiered web apply (May 2026)

Research-backed algorithm choices for long-tail browser automation — behavior trees, fallback ladders, cache-first agents, and self-improving apply. Synthesized from [parallel deep research](research/behavior-tree-web-automation-may-2026.json) (run `trun_0ec0321fbf464a6786e8168336bebcd5`, May 2026).

ApplyPilot context: see [self-learning-apply-architecture.md](self-learning-apply-architecture.md) (Cache-the-Fix / CtF-Apply tiers) and [scaled-self-learning-apply-plan.md](scaled-self-learning-apply-plan.md).

---

## Executive summary

| Priority | Algorithm / technique | Role in apply automation | Fit for ApplyPilot today |
|----------|----------------------|--------------------------|--------------------------|
| **1** | Behavior Tree **Selector/Fallback** | Native “cheap → cache → LLM” escalation | Partial — linear fallback exists; full `py_trees` planned |
| **2** | **Exact-match action cache** (Stagehand-style) | Zero-token replay on repeated DOM/instruction | Strong — `nav_playbook` + `field_strategy` |
| **3** | **Case-Based Reasoning (CBR)** | Fuzzy match: similar DOM → adapt past recipe | Strong — signature-keyed playbooks are CBR-lite |
| **4** | **Agent Workflow Memory (AWM)** | Induce reusable sub-routines from traces | Planned — nightly workflow induction |
| **5** | **HTN + BT hybrid** | HTN plans steps; each step is a BT with fallbacks | Future — Workday/Greenhouse semi-standard flows |
| **6** | **On-policy distillation (OPD)** | Promote LLM trajectories into smaller/faster policy | Future — after enough verified receipts |
| **7** | **WebCoach-style cross-session memory** | Reflection + continual learning without retrain | Partial — `review_log`, promote/ban gates |
| **8** | **Escalation calibration** (“Act or Escalate?”) | Tune when to hit human vs keep trying | Required before scaling autonomous apply |

Estimated token savings on repetitive form workflows when Selector ladders hit cache/rules first: **~60–80%** (research estimate; validate per ATS family).

---

## 1. Behavior Trees (control layer)

**What:** Tree of nodes returning `SUCCESS` | `FAILURE` | `RUNNING`. Composites:

- **Selector (Fallback):** try children left-to-right; first success wins — *is* a tiered escalation ladder.
- **Sequence:** run children in order; first failure aborts — multi-step apply sub-flow.
- **Parallel:** concurrent children with success threshold — e.g. cookie dismiss + form detect.

**Implementation:** [py_trees](https://py-trees.readthedocs.io/) (Python 2.2.x+): Blackboards for `cache_hit`, `state_sig`, decorators (retry, timeout, invert, ForEach over form fields).

**Why for apply:** Replaces brittle if/else chains with auditable trees; each tier is an independent subtree; tick status shows which tier fired (dashboard/debug).

**ApplyPilot mapping:**

```
Selector: ResolveNavigationBlocker
  ├─ Sequence: Tier-0 rules (profile_binding, fingerprint)
  ├─ Sequence: Tier-1 nav_playbook replay (CtF cache)
  ├─ Sequence: Tier-2 Gemini unblock (record on success)
  ├─ Sequence: Tier-3 Claude rescue (record on success)
  └─ Sequence: Escalate human (login gate / dashboard)
```

**References:** py_trees docs; [Orchestrating LLM Agents with Behavior Trees](https://medium.com/@Micheal-Lanham/orchestrating-llm-agents-with-behavior-trees-a-practical-guide-6762540e6ab3).

---

## 2. Fallback ladders and tiered escalation

**What:** Explicit ordering: deterministic rules → exact cache → fuzzy cache → small model → frontier LLM → human.

**BT encoding:** One Selector per decision point (per field, per nav state, per page). Blackboard write on LLM success feeds lower tiers next tick.

**Calibration:** [Act or Escalate? (arXiv 2604.08588)](https://arxiv.org/abs/2604.08588) — models differ in when they escalate; thresholds must be **per ATS family / step**, not global. ApplyPilot should log escalation outcomes in `review_log` and tune promote/ban gates empirically.

**Self-improving loop:** expensive tier success → write to Tier-1 (`stamp_verified`, promote) → optional distill to Tier-0 rules.

---

## 3. Exact-match action caching (Stagehand pattern)

**What:** Cache keys from **instruction + accessibility tree + options** (not raw pixel). Two modes:

| Mode | Where | When to use |
|------|-------|-------------|
| Server cache | Hosted browser infra | Managed replay, auto-invalidation on DOM change |
| Local cache | Filesystem `cacheDir` | Deterministic CI replay, commit cache with fixtures |

**Design detail:** Key on variable **names**, not values — one cache entry serves any email/resume path (critical for multi-account apply tests).

**ApplyPilot mapping:** `nav_playbook` + `field_strategy` rows keyed by `state_sig` / field signature; replay via closed action vocabulary in architecture doc.

**References:** [Stagehand caching docs](https://docs.stagehand.dev/v3/best-practices/caching).

---

## 4. Case-Based Reasoning (CBR)

**What:** Retrieve → reuse → revise → retain.

| CBR step | Apply automation |
|----------|------------------|
| Case | `(DOM/state_sig, action_sequence)` |
| Retrieve | Similarity on accessibility tree / ATS family + flags |
| Reuse | Replay playbook steps |
| Revise | Adapt selectors/values for variant layout |
| Retain | Insert/update `nav_playbook` after verified apply |

**Tier position:** Between exact cache and LLM — fuzzy match at ~1/100 token cost of full inference.

**ApplyPilot:** CtF-Apply signatures (`ats_family`, `apex_host`, `step_name`, `state_flags`) are intentional narrow CBR keys; avoid over-broad keys that cause wrong-case reuse.

**References:** [MDPI CBR review](https://www.mdpi.com/2076-3417/14/16/7130).

---

## 5. Agent Workflow Memory (AWM)

**What:** Induce reusable **workflows** (sub-routines) from traces; inject into agent context for later tasks.

| Mode | Data | Self-improving |
|------|------|----------------|
| Offline | Labeled training traces | Bootstrap ATS families |
| Online | Agent’s own successful runs | Yes — grows with production apply |

**Reported gains:** +51.1% relative on WebArena, +24.6% on Mind2Web; online AWM +8.9–14.0 absolute points as train/test gap widens.

**BT integration:** Workflow = **Sequence** subtree; parent **Selector** falls back to raw LLM if layout changed.

**ApplyPilot:** Nightly induction from `review_log` + successful applications → candidate workflows → human/auto promote to `nav_playbook` bundles.

**References:** [arXiv 2409.07429](https://arxiv.org/abs/2409.07429); [agent-workflow-memory](https://github.com/zorazrw/agent-workflow-memory).

---

## 6. HTN vs BT (use both)

| Dimension | Behavior Trees | HTN |
|-----------|----------------|-----|
| Model | Reactive tick | Plan then execute |
| Volatile sites | Strong (LLM fallback per step) | Weak without re-plan |
| Predictable multi-page flows | Good with Sequences | Strong decomposition |
| Long-tail novel UI | Native Selector escape | Needs new methods |

**Recommendation for job apply:** **Hybrid**

1. **HTN layer:** `apply_to_job` → `personal_info` → `work_history` → `education` → `submit`.
2. **BT layer:** Each HTN primitive = Selector ladder (rules → cache → CBR → LLM).
3. **Re-plan:** HTN replans when BT subtree fails N times; Blackboard reports subtask status.

**ApplyPilot:** Tier-0 Workday/Greenhouse adapters as HTN-like fixed pipelines; generic long-tail stays BT-driven.

**References:** [IEEE BT vs HTN comparison](https://ieeexplore.ieee.org/document/10371841).

---

## 7. Policy distillation (LLM → cheap policy)

**What:** **On-policy distillation (OPD)** — student rolls out its own trajectories; teacher/reward scores them — fixes compounding error vs naive KD.

**Tier role:**

- Stagehand cache = **exact** state match
- Distilled policy = **fuzzy** generalization
- Full LLM = final fallback

**When:** After thousands of verified receipts per ATS family; periodic offline jobs, not inline on every apply.

**References:** [OPD survey (AlphaXiv)](https://www.alphaxiv.org/abs/2604.00626v1); [Hybrid Policy Distillation (arXiv 2604.20244)](https://arxiv.org/abs/2604.20244).

---

## 8. Learning from demonstration and cross-session memory

| Method | Approach | Fine-tune? | Self-improving | Apply use |
|--------|----------|------------|----------------|-----------|
| **AdaptAgent** | Few-shot from human demos | No | Static | Bootstrap new ATS from 3–5 watched applies |
| **ScribeAgent** | Train small LM on browser traces | Yes | Offline | Optional local action model tier |
| **WebCoach** | Cross-session memory + reflection | No | Yes | Extend `review_log` + reflection prompts |
| **AWM** | Workflow induction | No | Yes | See §5 |
| **Stagehand cache** | Deterministic replay | No | Grows on hit | See §3 |

**References:** [AdaptAgent ACL 2025](https://aclanthology.org/2025.acl-long.1008.pdf); [WebCoach arXiv 2511.12997](https://arxiv.org/html/2511.12997).

---

## 9. Integrated stack (recommended production architecture)

```
┌─────────────────────────────────────────────────────────────┐
│  HTN Planner: decompose apply job into ordered subtasks        │
└────────────────────────────┬────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────┐
│  BT per subtask: Selector (Fallback Ladder)                  │
│    1. User override (Tier -1)                                │
│    2. Deterministic rules (Tier 0)                           │
│    3. Exact cache — nav_playbook / field_strategy (Tier 1)     │
│    4. CBR fuzzy case retrieve + adapt                        │
│    5. AWM workflow Sequence (with timeout decorator)         │
│    6. Distilled policy (future)                              │
│    7. Gemini / Claude (Tier 2–3, record on success)          │
│    8. Human escalate (login gate, calibrated threshold)      │
└────────────────────────────┬────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────┐
│  Memory layer (write-back on verified success)               │
│    nav_playbook, field_strategy, qa_bank, review_log, AWM    │
└────────────────────────────┬────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────┐
│  Distillation layer (offline)                                │
│    OPD → smaller policy; selector extraction → Tier 0 rules  │
└─────────────────────────────────────────────────────────────┘
```

---

## 10. Implementation checklist for ApplyPilot

**Now (high ROI, aligns with CtF-Apply)**

- [ ] Wrap launcher/unblock paths in explicit **Selector** semantics (even before `py_trees`).
- [ ] Narrow **CBR keys** — document ban reasons when retrieve-adapt fails.
- [ ] **Stagehand-style** cache discipline: `networkidle` before capture; stable viewport; key on field names not values.
- [ ] Log **which tier fired** per step for escalation calibration.
- [ ] **Promote/ban** gates tied to `stamp_verified` receipt weight (already started).

**Next**

- [ ] **`py_trees`** Fallback tree for `apply/direct` with Blackboard (`state_sig`, `cache_hit`, `job_id`).
- [ ] **AWM offline** induction per `ats_family` from successful application exports.
- [ ] **HTN sketch** for Greenhouse/Workday happy paths as Sequence subtrees.

**Later**

- [ ] CBR retrieve with DOM/a11y similarity (sqlite-vss or embedding).
- [ ] **OPD** batch job from verified trajectories.
- [ ] **AdaptAgent**-style few-shot demo import for new portals.

---

## 11. Failure modes (design for)

| Tier | Typical failure | Mitigation |
|------|-----------------|------------|
| CSS/rule | Site redesign | Fall through Selector; retire rule on repeated failure |
| Exact cache | Stale DOM | Auto-invalidate on state_sig mismatch; ban cluster |
| CBR | Superficial similarity | Order specific-before-abstract; require receipt threshold |
| AWM workflow | Layout drift | Timeout decorator; fallback to LLM |
| Distilled policy | Hallucinated action | Keep LLM + human rightmost in Selector |
| LLM | CAPTCHA, auth wall | `login_gate`, escalate node |

Every Selector should end with **escalate-to-human**, threshold tuned per family using logged outcomes.

---

## Source artifacts

| File | Contents |
|------|----------|
| `docs/research/behavior-tree-web-automation-may-2026.json` | Full deep-research report, citations, executive summary |
| `docs/self-learning-apply-architecture.md` | ApplyPilot CtF-Apply tier model and action vocabulary |
| `docs/scaled-self-learning-apply-plan.md` | Engineering rollout (py_trees, AWM, receipts) |

---

*Generated May 2026 from Parallel deep research (`pro-fast`). Re-run research with `parallel-cli research run "..."` to refresh as papers ship.*
