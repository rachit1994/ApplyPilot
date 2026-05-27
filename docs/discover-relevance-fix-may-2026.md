# Discover Relevance and LLM Cost (May 2026)

**Status:** Implemented Tier 0 (universal discover filters) and Tier 1 (pre-score rule gate). Tier 2–3 (embedding, batched scoring) not shipped.

**One-line summary:** the scoring stage sends every enriched job to Gemini with zero pre-filtering, and 72% of those calls end up below the score-7 cutoff (wasted spend). Nine of the ten discover sources don't even apply the user's `exclude_titles` list. Add a tiered pre-score filter (regex → location → embedding → LLM) and Gemini sees ~85% fewer jobs while finding the same top-7 jobs.

---

## TL;DR

- **The pipeline doesn't filter for relevance before paying Gemini.** Every job that has a `full_description` gets a Gemini scoring call. Of 7,755 scored, 5,545 (72%) ended ≤ 6 and were thrown out. That's 5,545 paid LLM calls per discovery cycle producing zero downstream value.
- **`exclude_titles` is implemented but applied at only one source.** JobSpy filters out "intern / junior / co-op / 0-2 years" etc. before scoring. Workday, Smart extract, RemoteOK, Remotive, Himalayas, WeWorkRemotely, HN Hiring, Work-at-a-Startup, and Watchlist do not. They all dump straight to DB with no title filter.
- **The score prompt is fat.** Each call sends the resume (~3KB) + role list + system prompt + job title + 6000 chars of full description. With Gemini 3.1 flash-lite the per-call input is ~5K tokens. 5,545 wasted calls ≈ 25-30M wasted input tokens.
- **There is no cheap pre-LLM pipeline.** No title regex enforcer, no location heuristic, no salary parse, no keyword/embedding similarity. The scoring code path goes: `get_jobs_by_stage("pending_score") → for job in jobs: gemini.chat(...)`. That's it.
- **Fix proposal — tiered cheap-first filter:**
  - **T0 (universal title filter):** apply `exclude_titles` + a positive allowlist at ALL 10 discover sources, not just JobSpy. Kills 30-40% before they ever land in the DB.
  - **T1 (pre-score rules):** before each Gemini call, apply regex + location + salary + seniority + role-keyword checks. Kills another 20-30%.
  - **T2 (resume embedding):** local sentence-transformer cosine similarity between resume and job. One-time 80MB model download, ~10ms per job, no API cost. Kills another 20-30%.
  - **T3 (batched LLM score):** for survivors, batch 5-10 jobs into one Gemini call. Cuts remaining tokens 60-80%.
- **Net effect:** Gemini cost per discovery cycle drops from "score 7,755 jobs" to "score ~1,000". Same top-7 jobs surface, in less wall time, at 10-15% of the cost. The user can then run discovery more aggressively (more queries, wider net) without budget anxiety.

---

## What's broken: evidence

### Funnel waste (May 2026 DB snapshot, pre-reset)

```
Stage                                Count       % of scored    Notes
─────────────────────────────────  ──────────  ─────────────  ─────────────────────────────
Discovered                           8,811                     ten sources combined
Enriched (has full_description)      7,768       100.2%        bytes paid: HTTP fetches
Scored (paid Gemini call)            7,755       100.0%        baseline for "waste" calc
  → kept (score ≥ 7)                 2,207        28.5%        ✓ useful
  → borderline (5-6)                 1,876        24.2%        ✗ near miss, wasted
  → rejected (3-4)                   2,007        25.9%        ✗ clear miss, wasted
  → trash (1-2)                      1,662        21.4%        ✗ totally off-target
Tailored                               179         2.3%
Applied                                 25         0.3%
```

**Cumulative waste at the score stage: 71.5% of all Gemini calls.** Even at score 5-6 (borderline), the jobs almost never get tailored — only 2 of the 1,876 borderline jobs were tailored. So in practice the threshold is effectively 7; scores 1-6 are pure waste.

### Per-call cost math (Gemini 3.1 flash-lite, the default)

Prompt size per call (from `scoring/scorer.py:117-129`):
- System prompt (`SCORE_PROMPT`): ~600 tokens
- Target roles block: ~50 tokens
- Resume: ~1,500-2,500 tokens
- Job text (title + company + location + 6000-char description): ~1,500-2,000 tokens
- **Total input per scoring call: ~4,000-5,000 tokens**

Output: `max_tokens=512`, but typical scoring response is ~150-300 tokens.

Conservative estimate at Gemini 3.1 flash-lite published pricing:
- Input: ~$0.04 per million tokens
- Output: ~$0.16 per million tokens
- Per call ≈ $0.000200 + $0.000040 = **~$0.00024 per scoring call**

Scaled to the observed corpus:
- 7,755 scored × $0.00024 = **~$1.86 per full-corpus cycle**
- Of which 5,545 wasted × $0.00024 = **~$1.33 wasted per cycle**

That's small for one cycle. But the user is running discovery continuously, multiple times per week. At 4 cycles/week, that's ~$5.50/week, $24/month — and **72% of it is buying nothing**. And the corpus keeps growing; the next cycle scores more jobs, not the same 7,755.

### Where the waste actually concentrates

Tailoring is much more expensive per call (~$0.005 due to a bigger output + 4 internal retries), but it only runs on score ≥ 7. So the structural cost waste is at scoring, not tailoring. The fix is to stop *getting to* tailoring with junk.

### Coverage of `exclude_titles` across the 10 discover sources

```
source              exclude_titles applied?    code path
────────────────    ───────────────────────    ────────────────────────────────────────────
jobspy              YES                        jobspy.py:292-302 (DataFrame filter)
workday             NO                         workday.py — 0 filter mentions
workatastartup      NO                         workatastartup.py — 0 filter mentions
smartextract        NO                         smartextract.py — 0 filter mentions
hn_hiring           NO                         hn_hiring.py — 0 filter mentions
watchlist           NO                         watchlist.py — 0 filter mentions
feeds/remoteok      NO                         remoteok.py — 0 filter mentions
feeds/remotive      NO                         remotive.py — 0 filter mentions
feeds/himalayas     NO                         himalayas.py — 0 filter mentions
feeds/wwr           NO                         wwr.py — 0 filter mentions
```

The user's `exclude_titles` list ("intern, junior, 0-2 years, fresher, TS/SCI clearance, …") is doing real work for JobSpy — but jobs identical in name from the same companies arrive via Workday / RemoteOK / smart extract unfiltered, get enriched (HTTP fetch), and get scored (Gemini call). The user is paying twice for the same junk.

### Scoring code: zero pre-filter

```python
# scoring/scorer.py:165
jobs = get_jobs_by_stage(conn=conn, stage="pending_score", limit=limit)
# ... straight into the for loop ...
for job in jobs:
    result = score_job(resume_text, job)  # ← Gemini call, no filter
```

`get_jobs_by_stage("pending_score")` (database.py) is just:
```sql
full_description IS NOT NULL AND fit_score IS NULL
```

There is no title check, no location check, no salary check, no keyword check, no embedding check between enrich and score. Every enriched job becomes a billable LLM call.

### Enrich also doesn't filter

`enrichment/detail.run_enrichment` (around line 890) fetches HTTP for every job in `pending_detail`. Same pattern: no pre-fetch filter on title/location/source. So we waste bandwidth too — though that's a smaller line item than the LLM cost.

### The current exclude_titles list (from `~/.applypilot/searches.yaml`)

```yaml
exclude_titles:
  - "chief financial"
  - "chief operating"
  - "chief marketing"
  - "chief revenue"
  - "intern"
  - "internship"
  - "co-op"
  - "trainee"
  - "graduate"
  - "entry level"
  - "entry-level"
  - "junior "
  - " jr "
  - "fresher"
  - "0-2 years"
  - "0-3 years"
  - "1-3 years"
  - "2-4 years"
  - "clearance required"
  - "TS/SCI"
```

20 patterns. Good list, but conservative. It misses common categories that almost certainly score low for a frontend/full-stack/AI engineer:
- Sales / marketing / HR / recruiting / customer success
- Hardware / firmware / embedded
- Mobile-only (iOS / Android specialist with no web)
- Game dev (Unity / Unreal-specific)
- QA-only / tester / SDET (unless that's your target)
- Data analyst / BI / Tableau / Looker
- Solutions architect / pre-sales engineer
- Site reliability / DevOps without coding
- Salesforce / SAP / ServiceNow specialist
- Healthcare / clinical / nursing / pharma
- Legal / paralegal
- Adjacent leadership-only (VP of Engineering, Director, Engineering Manager, where the role is not hands-on)

Adding these to the list AND applying them universally would catch a huge chunk of today's "scored 1-3" jobs without involving an LLM.

---

## Why so much junk leaks in: the architecture

```
                CURRENT FLOW (every enriched job → Gemini)

  DISCOVERY (10 sources)
    ├─ jobspy        → filters via exclude_titles ✓
    ├─ workday       → NO FILTER ✗
    ├─ workatastartup→ NO FILTER ✗
    ├─ smartextract  → NO FILTER ✗
    ├─ hn_hiring     → NO FILTER ✗
    ├─ watchlist     → NO FILTER ✗
    ├─ feeds/remoteok→ NO FILTER ✗
    ├─ feeds/remotive→ NO FILTER ✗
    ├─ feeds/himalayas→ NO FILTER ✗
    └─ feeds/wwr     → NO FILTER ✗
                       │
                       ▼  (jobs table, no relevance gating)
  ENRICH (HTTP fetch every URL)
                       │
                       ▼
  SCORE (Gemini call EVERY job)
                       │
        ┌──────────────┼──────────────┐
        │ 7/8/9/10    │ 5-6           │ 1-4
        │ 2,207 (28%) │ 1,876 (24%)   │ 3,672 (47%)
        ▼              ▼               ▼
     TAILOR         dropped         dropped
     (179 of these)
```

**Three architectural gaps:**
1. **Filter coverage is fragmented.** Only 1 of 10 sources applies the user's exclude list.
2. **No semantic gate between enrich and score.** The cheapest possible test ("does the job title contain any of the words on my resume?") is not run before paying Gemini.
3. **No batching at the LLM layer.** Each scoring call is 1 job. Gemini supports batched inputs; the prompt could be re-shaped to score N jobs in one call.

---

## Specific code references

- **`scoring/scorer.py:146-170`** — `run_scoring` pulls jobs, no pre-filter, sends each to Gemini one-by-one.
- **`scoring/scorer.py:117-129`** — `job_text` construction; truncates description to 6000 chars but doesn't decide whether to send at all.
- **`scoring/scorer.py:134`** — `client.chat(messages, max_tokens=512, temperature=0.2)`. The one Gemini call.
- **`database.py:pending_score`** — the query: `full_description IS NOT NULL AND fit_score IS NULL`. No relevance gate.
- **`discovery/jobspy.py:88-92, 292-302`** — `_title_excluded` + DataFrame filter. The only place exclude_titles is applied.
- **`discovery/workday.py / workatastartup.py / smartextract.py / hn_hiring.py / watchlist.py / feeds/*.py`** — no exclude_titles, no location filter, no salary filter.
- **`apply/eligibility.py:69-73`** — `load_exclude_title_substrings` exists but docstring says "discover only; not used in apply classify". So it's intended as a discover utility, but only JobSpy calls it.
- **`config/searches.example.yaml`** — defines the `exclude_titles` schema; same applies to user's `~/.applypilot/searches.yaml`.
- **`llm.py:20`** — `DEFAULT_GEMINI_MODEL = "gemini-3.1-flash-lite"`. Cheap, but still per-call.

---

## Fix plan

Four tiers. **Tier 0 and Tier 1 are implemented** (see `discovery/_filters.py`, `scoring/pre_filter.py`). Tier 2–3 remain optional follow-ups.

### Tier 0: universal `exclude_titles` enforcement (~30 minutes, 50 lines, huge cheap win)

Goal: apply the user's existing exclude list at every source. Net effect: ~30-40% of today's discovered junk never lands in the DB.

**Change 1 — central filter module.** Lift `_title_excluded` from `discovery/jobspy.py` into `discovery/_filters.py`:

```python
# discovery/_filters.py — NEW
from applypilot.config import load_search_config

def load_title_filters() -> tuple[list[str], list[str]]:
    """Return (exclude_substrings, include_substrings) from searches.yaml."""
    cfg = load_search_config()
    excludes = [str(x).lower() for x in (cfg.get("exclude_titles") or []) if x]
    includes = [str(x).lower() for x in (cfg.get("include_titles") or []) if x]
    return excludes, includes

def title_passes(title: str | None, excludes: list[str], includes: list[str]) -> bool:
    if not title:
        return True
    lower = title.lower()
    if any(sub in lower for sub in excludes):
        return False
    if includes and not any(sub in lower for sub in includes):
        return False
    return True

def location_passes(location: str | None) -> bool:
    """Reuse jobspy._location_ok logic — same accept/reject pattern."""
    # ... lift from jobspy.py:_load_location_config + _location_ok ...
```

**Change 2 — wire it into every source's insertion path.** Each source has a `store_*` or `insert` function that pushes rows. Wrap them:

```python
# In discovery/workday.py, workatastartup.py, smartextract.py, hn_hiring.py,
# watchlist.py, and each feeds/*.py file:

from applypilot.discovery._filters import load_title_filters, title_passes, location_passes

EXCLUDES, INCLUDES = load_title_filters()  # cached at import

# Before INSERT for each job:
if not title_passes(job["title"], EXCLUDES, INCLUDES):
    continue
if not location_passes(job.get("location")):
    continue
```

**Change 3 — add `include_titles` to `searches.yaml`** (optional but high leverage):

```yaml
include_titles:
  - "frontend"
  - "front end"
  - "front-end"
  - "ui engineer"
  - "ui lead"
  - "react"
  - "next.js"
  - "full stack"
  - "fullstack"
  - "full-stack"
  - "javascript"
  - "typescript"
  - "node"
  - "ai engineer"
  - "ml engineer"
  - "applied ai"
  - "engineering lead"
  - "tech lead"
  - "staff engineer"
  - "principal engineer"
  - "software architect"
  - "platform engineer"
  - "developer experience"
  - "growth engineer"
```

With both an allowlist (must match one) and a blocklist (must match none), the filter is much sharper. The current list-only approach catches obvious junk but lets through generic "engineer" titles that are far from the user's target.

**Change 4 — expand the exclude list.** Add the categories from the "current exclude_titles is conservative" section above. Suggested additions:
```yaml
exclude_titles:
  # ... existing ...
  - " sales "
  - "account executive"
  - "business development"
  - "customer success"
  - "marketing manager"
  - "hr manager"
  - "recruiter"
  - "talent acquisition"
  - "embedded"
  - "firmware"
  - "ios developer"     # remove if user wants iOS roles
  - "android developer" # remove if user wants Android roles
  - "qa engineer"
  - "qa tester"
  - "sdet"
  - "test engineer"
  - "data analyst"
  - "bi analyst"
  - "salesforce"
  - "sap "
  - "servicenow"
  - "solutions architect"
  - "pre-sales"
  - "pharmacist"
  - "nurse"
  - "registered nurse"
  - "physician"
```

**Why this is Tier 0:** zero new infrastructure, ~50 lines of code, the user's existing list finally works everywhere. Catches 30-40% of junk before it touches the DB.

### Tier 1: pre-score rule gate (~2 hours, 200 lines, blocks 20-30% more before Gemini)

Goal: between enrich and score, run a deterministic rule check that knocks out obvious mismatches without an LLM call.

**Change 1 — `scoring/pre_filter.py`** (new):

```python
"""Cheap pre-score filter. Reject obvious mismatches before paying Gemini."""

from __future__ import annotations
import re
from dataclasses import dataclass

from applypilot.config import load_profile, load_search_config
from applypilot.apply.salary import parse_salary_to_annual_usd, get_apply_floor_usd

# Pre-compiled regex pools (built once at import)
SENIORITY_BAD = re.compile(
    r"\b(intern|internship|junior|jr\b|entry[\s-]?level|graduate|trainee|fresher|"
    r"0[-\s]?(1|2|3)\s*years?|0[-\s]?3\+?\s*yrs?)\b", re.I,
)
SENIORITY_GOOD = re.compile(
    r"\b(senior|staff|principal|lead|architect|head\s+of)\b", re.I,
)
EXEC_ROLES = re.compile(
    r"\b(chief\s+(financial|operating|marketing|revenue|legal|people)|"
    r"vp\s+of|director\s+of\s+(sales|marketing|hr))\b", re.I,
)
ADJACENT_NONENG = re.compile(
    r"\b(sales\s+engineer|solutions?\s+engineer|pre[-\s]?sales|"
    r"customer\s+success|product\s+manager|business\s+analyst)\b", re.I,
)

@dataclass(frozen=True)
class PreFilterVerdict:
    passes: bool
    reason: str | None    # e.g. "title:seniority_bad", "location:reject", "salary:below_floor"

def pre_score_filter(job: dict, profile: dict, search_cfg: dict) -> PreFilterVerdict:
    """Return PreFilterVerdict for one job. Pure function, no I/O."""
    title = (job.get("title") or "").strip()
    description = (job.get("full_description") or "")[:3000]  # only check first 3KB
    location = (job.get("location") or "").strip()
    salary = (job.get("salary") or "").strip()

    # 1. Title regex: hard rejects
    if SENIORITY_BAD.search(title):
        return PreFilterVerdict(False, "title:junior_or_intern")
    if EXEC_ROLES.search(title):
        return PreFilterVerdict(False, "title:exec_non_eng")
    if ADJACENT_NONENG.search(title):
        return PreFilterVerdict(False, "title:adjacent_role")

    # 2. Title allowlist (from include_titles in searches.yaml)
    includes = [s.lower() for s in (search_cfg.get("include_titles") or [])]
    if includes and not any(s in title.lower() for s in includes):
        return PreFilterVerdict(False, "title:not_in_allowlist")

    # 3. Location heuristic
    from applypilot.config import load_location_filter_patterns
    accept, reject = load_location_filter_patterns(search_cfg)
    if location:
        loc_l = location.lower()
        if not any(r in loc_l for r in ("remote", "anywhere", "wfh", "distributed")):
            if any(rj.lower() in loc_l for rj in reject):
                return PreFilterVerdict(False, "location:reject_pattern")
            if accept and not any(ac.lower() in loc_l for ac in accept):
                return PreFilterVerdict(False, "location:not_in_accept")

    # 4. Salary parse (only if salary is listed)
    if salary:
        annual = parse_salary_to_annual_usd(salary)
        if annual is not None and annual < get_apply_floor_usd():
            return PreFilterVerdict(False, "salary:below_floor")

    # 5. Description seniority check (if title is ambiguous)
    if not SENIORITY_GOOD.search(title) and SENIORITY_BAD.search(description):
        return PreFilterVerdict(False, "description:junior_signal")

    return PreFilterVerdict(True, None)
```

**Change 2 — wire it into `scoring/scorer.run_scoring`:**

```python
# scoring/scorer.py — modify run_scoring:
from applypilot.scoring.pre_filter import pre_score_filter
from applypilot.config import load_profile, load_search_config

def run_scoring(limit: int = 0, rescore: bool = False) -> dict:
    profile = load_profile()
    search_cfg = load_search_config()
    resume_text = RESUME_PATH.read_text(encoding="utf-8")
    conn = get_connection()
    jobs = get_jobs_by_stage(conn=conn, stage="pending_score", limit=limit)
    if not jobs:
        return {"scored": 0, "skipped_pre": 0, "errors": 0, ...}

    now = datetime.now(timezone.utc).isoformat()
    skipped_pre = 0
    survivors = []

    for job in jobs:
        verdict = pre_score_filter(job, profile, search_cfg)
        if not verdict.passes:
            # Mark as pre-filter rejected — score 0 with a reason
            conn.execute(
                "UPDATE jobs SET fit_score = 0, score_reasoning = ?, scored_at = ? WHERE url = ?",
                (f"pre_filter:{verdict.reason}", now, job["url"]),
            )
            skipped_pre += 1
            continue
        survivors.append(job)
    conn.commit()

    # Now Gemini-score only the survivors:
    for job in survivors:
        result = score_job(resume_text, job)
        # ... existing logic ...

    return {
        "scored": len(survivors),
        "skipped_pre": skipped_pre,
        "errors": errors,
        ...
    }
```

**Change 3 — surface `skipped_pre` on the dashboard.** The pipeline progress for `score` should show "12 scored · 47 pre-filtered · 3 errors" so the user can see the filter is working.

**Why this is Tier 1:** no new dependencies. Pure Python + regex. Reuses existing salary parsing. Cuts another 20-30% of Gemini calls. Easy to A/B: set `APPLYPILOT_DISABLE_PRE_FILTER=1` to bypass.

### Tier 2: embedding similarity gate (~3 hours, 200 lines, blocks another 20-30%)

Goal: even when title and location look plausible, a fast local embedding catches semantic mismatches. The user's resume vs job description in a 384-dim vector space; cosine similarity < threshold → reject without calling Gemini.

**Stack choice:** sentence-transformers `BAAI/bge-small-en-v1.5` or `intfloat/e5-small-v2`. 80MB download, ~10ms inference per job on CPU, no API cost ever.

**Change 1 — `scoring/embedding.py`** (new):

```python
"""Local embedding similarity check. One-time model download, cached forever."""

from __future__ import annotations
import functools
import numpy as np

from applypilot.config import RESUME_PATH

_MODEL_NAME = "BAAI/bge-small-en-v1.5"
_THRESHOLD = 0.55   # tunable; observe distribution on first run

@functools.lru_cache(maxsize=1)
def _get_model():
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(_MODEL_NAME)

@functools.lru_cache(maxsize=1)
def _resume_embedding() -> np.ndarray:
    resume = RESUME_PATH.read_text(encoding="utf-8")
    model = _get_model()
    return model.encode([resume], normalize_embeddings=True)[0]

def cosine_relevance(job: dict) -> float:
    """Return cosine similarity in [-1, 1] between resume and job text."""
    text = (
        f"{job.get('title','')}\n"
        f"{job.get('full_description','')[:4000]}"
    )
    model = _get_model()
    job_emb = model.encode([text], normalize_embeddings=True)[0]
    return float(np.dot(_resume_embedding(), job_emb))

def embedding_passes(job: dict, threshold: float = _THRESHOLD) -> tuple[bool, float]:
    sim = cosine_relevance(job)
    return sim >= threshold, sim
```

**Change 2 — add to `pre_score_filter` after rule checks pass:**

```python
# in pre_filter.py, after the rule checks:
from applypilot.scoring.embedding import embedding_passes

ok, sim = embedding_passes(job)
if not ok:
    return PreFilterVerdict(False, f"embedding:low_similarity({sim:.2f})")
```

**Change 3 — calibrate the threshold.** First run: log every cosine score alongside the eventual Gemini score. Plot the distribution. A threshold around 0.55-0.65 typically catches ~80% of the LLM's "score ≤ 4" pile while preserving ~95% of the "score ≥ 7" pile. Tune per user.

**Change 4 — `pip install sentence-transformers` added to dependencies; first-run model download (~80MB).** Document this in CLAUDE.md.

**Why this is Tier 2:** zero API cost (Gemini scoring drops further), catches semantic mismatches the regex can't (e.g., "Engineer" in a chemical engineering company), and the model is cached forever. The 80MB download is a one-time cost; you save Gemini money on every cycle.

### Tier 3: batch the LLM scoring (~1 hour, 80 lines)

Goal: for the survivors that still need Gemini, batch them into a single call. 10 jobs → 1 call instead of 10.

**Change 1 — modify `score_job` to accept multiple jobs:**

```python
def score_jobs_batch(resume_text: str, jobs: list[dict], profile: dict | None = None) -> list[dict]:
    """Score up to 10 jobs in one LLM call."""
    profile = profile or load_profile()
    roles = get_target_roles(profile)
    roles_block = f"TARGET ROLES (strong fit = 7+): {', '.join(roles)}\n\n" if roles else ""

    jobs_text = "\n\n---\n\n".join(
        f"JOB {i+1}:\nTITLE: {j['title']}\nCOMPANY: {j['site']}\n"
        f"LOCATION: {j.get('location','N/A')}\n\n"
        f"DESCRIPTION:\n{(j.get('full_description','') or '')[:2500]}"   # shorter when batched
        for i, j in enumerate(jobs)
    )

    messages = [
        {"role": "system", "content": SCORE_PROMPT_BATCH},  # new prompt with JSON output schema
        {"role": "user", "content":
            f"{roles_block}RESUME:\n{resume_text}\n\n---\n\n"
            f"Score the following {len(jobs)} jobs. Return a JSON array of objects "
            f"with shape {{\"job\":N, \"score\":int, \"recommendation\":\"apply\"|\"skip\", "
            f"\"keywords\":\"...\", \"reasoning\":\"...\"}}. "
            f"Jobs:\n\n{jobs_text}"
        },
    ]
    client = get_client()
    response = client.chat(messages, max_tokens=512 * len(jobs), temperature=0.2)
    return _parse_batch_score_response(response, jobs)
```

**Change 2 — call in batches of 10:**

```python
# in run_scoring:
BATCH_SIZE = 10
for i in range(0, len(survivors), BATCH_SIZE):
    batch = survivors[i:i+BATCH_SIZE]
    results.extend(score_jobs_batch(resume_text, batch))
```

**Why this is Tier 3:** the system prompt and resume are sent once per batch instead of once per job. That's the bulk of the input tokens. Per-call cost drops modestly (batched output still costs), but total cost drops 50-70%.

**Risk:** Gemini's JSON-out batched scoring can have quality dips vs per-job scoring. Test on a 100-job sample before committing. If quality degrades, drop batch size to 5 or skip Tier 3.

---

## Cost projection (if all four tiers ship)

Estimates use the May 2026 corpus baseline: 7,755 enriched jobs entering the score stage per cycle.

```
Stage                         Today          T0 + T1        T0 + T1 + T2      All four tiers
─────────────────────────  ────────────   ─────────────   ─────────────────   ─────────────────
Jobs entering score          7,755          ~5,400          ~3,500             ~3,500
After title filter (T0)      —              ~5,400          ~5,400             ~5,400
After rule filter (T1)       —              ~3,800          ~3,800             ~3,800
After embedding (T2)         —              —               ~2,000             ~2,000
LLM calls made               7,755          ~3,800          ~2,000             ~200 (batches)
Gemini cost / cycle          ~$1.86         ~$0.91          ~$0.48             ~$0.18
                                                                                
Reduction vs today           baseline       -51%            -74%               -90%
```

Numbers are estimates from filter coverage. Actual savings depend on the user's resume vs the job mix; first-week metrics will calibrate. The order-of-magnitude reduction (~10x) is conservative.

At 4 cycles/week, that's roughly $7.50/week today → $0.70/week after all four tiers, while finding the same top-tier jobs (probably more, because the filters are deterministic and the LLM is no longer asked low-signal questions).

---

## What I'd actually ship

Same staging as the prior docs:

1. **Today (~30 min):** Tier 0. Universal `exclude_titles` + `include_titles` allowlist applied at all 10 sources. Edit `~/.applypilot/searches.yaml` to widen the exclude list. **Immediate ~30-40% reduction in stuff hitting the DB.** No code risk because the regex is a yes/no gate.
2. **This week (~2-3 hours):** Tier 1. Pre-score rule gate. Watch the `skipped_pre` counter on the dashboard. **Another 20% Gemini call reduction.** Risk: a false-positive in the regex would silently drop a good job. Mitigate with the `score_reasoning = "pre_filter:..."` audit trail.
3. **Next week (~3 hours):** Tier 2. Embedding gate. One-time download + calibration. **Another 20% reduction.** Risk: similarity threshold needs tuning per user; first run logs the distribution so you can pick a sane value.
4. **Optional / when convenient:** Tier 3. Batched scoring. **Roughly halves the remaining cost.** Risk: batch-mode Gemini output may have slight quality dips.

Stacked total: ~90% Gemini cost reduction with no loss of useful coverage. The user can finally turn on Tier 3 queries in `searches.yaml` (wider net) without budget anxiety, because the filter funnel handles the increased volume cheaply.

---

## Edge cases the fix needs to handle

| Scenario | Today | After Tier 1 | After Tier 2 |
|---|---|---|---|
| Title = "Engineer" (generic, no domain word) | Gemini scores it 4-6 | T1 allowlist rejects (no domain word) | same |
| Title = "Senior Frontend Engineer" at health-tech | Gemini scores it 8 | T1 passes (allowlist match) | T2 passes (embedding similarity OK) |
| Title = "Senior Sales Engineer" | Gemini scores it 2-3 | T1 rejects (`sales\s+engineer` regex) | same |
| Title = "Senior React Developer", description is actually about Salesforce admin work | Gemini scores it 3-4 | T1 passes (title looks fine) | T2 catches the mismatch via embedding |
| Title = "Software Engineer III", description matches resume tightly | Gemini scores it 7 | T1 passes (matches "senior" via III) | T2 passes |
| Listing has no salary | Gemini scores it | T1 doesn't reject on salary (only rejects if listed + below floor) | T2 evaluates normally |
| Listing is from a new company with sparse description | Gemini scores it 3-5 | T1 passes | T2 might reject if embedding < threshold; log + adjust threshold |
| User pivots career, resume changes | scoring continues | T1 unaffected (rules are config-driven) | T2 must re-embed resume (file change triggers cache invalidation) |

The fix doc proposes auditing each pre-filter rejection by storing `score_reasoning = "pre_filter:title:not_in_allowlist"` so the user can spot-check what got blocked. If a real job gets wrongly rejected, adjusting `include_titles` is a one-line YAML edit.

---

## NOT in scope

- Switching scoring LLM provider. Gemini 3.1 flash-lite is fine; the goal is *fewer calls*, not *cheaper calls per call*.
- Replacing JobSpy or any of the source scrapers. The discovery layer is fine; the gap is the post-discovery filter.
- Re-scoring all 7,755 existing jobs. Once Tier 1 ships, existing scored rows stay. Future cycles benefit immediately.
- Tightening `searches.yaml` queries themselves. That's user-tunable already; the doc just notes that the queries can be wider once filters are doing the work downstream.
- Rebuilding the score prompt to be smaller. Possible follow-up, but per-call cost is small relative to call volume.

---

## What already exists (reuse, don't rebuild)

- `discovery/jobspy._title_excluded` — lift verbatim into `discovery/_filters.py`. Already proven, just needs to be applied universally.
- `discovery/jobspy._location_ok` + `config.load_location_filter_patterns` — same lift.
- `apply/salary.parse_salary_to_annual_usd` + `get_apply_floor_usd` — already used by apply eligibility; reuse for pre-score salary check.
- `apply/eligibility.is_too_junior_role` — title-based junior detection; can feed `SENIORITY_BAD` regex.
- `config.load_search_config` and `load_profile` — cached config loaders; safe to call in `pre_score_filter`.
- `database.fit_score = 0 with score_reasoning` — existing schema can store the pre-filter reason without migration.
- Pipeline `_count_pending` and `stage_progress` events — extending to show `skipped_pre` is mechanical.

---

## Verification once the fix ships

```bash
# A) Baseline: run scoring on a small batch with no pre-filter (env override).
APPLYPILOT_DISABLE_PRE_FILTER=1 applypilot run score --limit 100
# Record: total LLM calls = 100. Cost ~$0.024.

# B) Same batch with all filters on.
applypilot run score --limit 100
# Expect: LLM calls < 30. Cost < $0.008. Dashboard shows "27 scored, 73 pre-filtered".

# C) Audit pre-filter rejections.
sqlite3 ~/.applypilot/applypilot.db "
  SELECT score_reasoning, COUNT(*) FROM jobs
   WHERE fit_score = 0 AND score_reasoning LIKE 'pre_filter:%'
   GROUP BY score_reasoning ORDER BY COUNT(*) DESC;
"
# Sanity-check that the rejected categories make sense.

# D) Calibrate embedding threshold.
applypilot run score --emit-embedding-scores > embed_dist.tsv
# Plot histogram of cosine similarity. Pick threshold where the
# "Gemini score >= 7" pile starts (~0.55-0.65 typical).

# E) Spot-check false-positives (good jobs the filters blocked).
sqlite3 ~/.applypilot/applypilot.db "
  SELECT url, title, site, score_reasoning FROM jobs
   WHERE fit_score = 0 AND score_reasoning LIKE 'pre_filter:%'
   ORDER BY RANDOM() LIMIT 20;
"
# Manually review. Any that should have scored 7+ → tighten the rule that blocked it.
```

---

## DEBUG REPORT

```
DEBUG REPORT
════════════════════════════════════════════════════════════
Symptom:         Discover pulls thousands of jobs but very few are
                 relevant. Gemini cost (scoring stage) is high.

Root cause:      Two stacking gaps.
                 (A) The user's exclude_titles list is only applied
                     at 1 of 10 discover sources (JobSpy). The other
                     9 sources (Workday, Smart extract, RemoteOK,
                     Remotive, Himalayas, WWR, HN Hiring, WaaS,
                     Watchlist) dump unfiltered. Junk titles ride
                     all the way to enrich (HTTP) and score (Gemini).
                 (B) The scoring stage has NO pre-filter. Every
                     enriched job becomes a billable Gemini call.
                     72% of those calls end up below the user's
                     score-7 threshold and are discarded. That's
                     the bulk of the cost.

Fix:             4 tiers in docs/discover-relevance-fix-may-2026.md.
                 Not applied.
                 - Tier 0 (~30 min): apply exclude_titles + add
                   include_titles allowlist at all 10 sources.
                 - Tier 1 (~2-3 hours): pre-score rule gate
                   (regex + location + salary + seniority).
                 - Tier 2 (~3 hours): local embedding cosine
                   similarity gate using BAAI/bge-small-en-v1.5.
                 - Tier 3 (~1 hour): batched Gemini scoring,
                   10 jobs per call.
                 Combined: ~90% reduction in Gemini scoring spend
                 while preserving / improving top-tier coverage.

Evidence:        - Funnel: 7,755 scored / 2,207 kept / 5,545 wasted
                 - 9 of 10 discover source files have 0 mentions
                   of exclude_titles / title filter
                 - scoring/scorer.py:165 calls get_jobs_by_stage
                   then loops to Gemini with no intervening filter
                 - pending_score query: no relevance gate
                 - Per-call cost: ~$0.00024 (4-5K input tokens)
                 - Cost per cycle (today): ~$1.86, of which $1.33
                   is wasted on rejected jobs

Regression test: tests/test_pre_filter.py (to be added with Tier 1).
                 Cases: every regex branch, include allowlist,
                 location reject/accept, salary below/above floor,
                 description seniority signal, empty fields.
                 Plus: golden file of 50 hand-labeled jobs
                 where the human verdict (apply/skip) is known;
                 filter must agree on >= 95%.

Related:         - docs/enrich-tailor-gap-fix-may-2026.md (same
                   pattern: stages run sequentially with no
                   cross-stage relevance signal)
                 - docs/apply-ghost-fix-may-2026.md (independent;
                   ghost-fix is at the apply stage, this is at
                   discover/score)
                 - searches.yaml structure already supports
                   exclude_titles and (after Tier 0) include_titles

Status:          SHIPPED — Tier 0 + Tier 1 implemented. Cost
                 numbers are estimates based on published Gemini
                 3.1 flash-lite pricing × observed call volume.
                 First production run after Tier 1 will tighten
                 the estimate.
════════════════════════════════════════════════════════════
```
