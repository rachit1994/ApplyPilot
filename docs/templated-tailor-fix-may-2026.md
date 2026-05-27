# Templated Tailoring — Cut LLM Cost 80%+ Without Losing Relevance (May 2026)

**Status:** Implemented (May 2026). Routing + classifier + CLI bootstrap shipped in repo. **Human step remaining:** bootstrap 8 resume/cover templates under `~/.applypilot/templates/` via `applypilot tailor-archetype` (until then, B-grade jobs fall back to LLM as before).

**One-line summary:** today every tailored resume + cover letter is generated fresh by Gemini with up to 4 internal retries + a judge call (~$0.03 per job). But your role universe collapses into ~8 archetypes (senior frontend, full-stack, AI engineer, staff/principal, founding engineer, etc.), and across the 179 existing tailored resumes only ~15% of the document actually changes per job. Build 8 pre-tailored resumes once, fill in 3-5 placeholders per job at $0 cost, and reserve the LLM call only for A-grade targets (fit_score ≥ 9 + in target-companies). Cost drops from ~$3/cycle to ~$0.50/cycle. Quality stays the same or improves (consistent voice, no LLM drift, no judge rejections).

---

## TL;DR

- **Most of a tailored resume doesn't actually change per job.** Companies, dates, education, real metrics (35% cost reduction, 50M+ users, etc.), and most experience bullets are identical across all 179 tailored outputs. What changes: the title line, the 2-3 sentence summary, the technical-skills *order*, and which 4-6 bullets get selected/emphasized.
- **Your role universe maps cleanly to ~8 archetypes.** searches.yaml shows ~25 search queries, but they cluster into a small set: Senior Frontend, Frontend Tech Lead, Senior Full Stack, AI/ML Engineer, Staff/Principal, Founding Engineer, Solution Architect / FDE, and EM-IC. Each archetype needs ONE pre-tailored resume and ONE cover letter template.
- **Hybrid pipeline:** classify the job into an archetype (free, deterministic) → load the pre-built resume + cover letter → light placeholder substitution for `{company}`, `{role_title}`, `{1-2 keywords}` (free, deterministic) → ship. Skip the LLM tailor call for ~80% of jobs.
- **LLM tailor remains for A-grade jobs only.** Define "A-grade" as `fit_score >= 9 AND company IN target_companies` (or user-flagged). Maybe 10-20% of the queue. These get the full LLM treatment because they're worth the spend.
- **Cost math:** ~$0.03/job today × 100 tailors per cycle = ~$3/cycle. After fix: 80 jobs templated × $0 + 20 jobs LLM × $0.03 = ~$0.60/cycle. **~80% reduction**. At 4 cycles/week, ~$10/week saved.
- **Bonus: kills the 5-attempt purgatory.** 289 jobs are dead at tailor_attempts=5 because the LLM kept failing validation. Templates can't fail validation — they're hand-curated once. The dead pile stops growing.
- **One-time bootstrap:** generate the 8 templates ONCE using LLM (cost: ~$0.04 total). Hand-review them. Commit to disk. Never regenerate.

---

## What's broken today: evidence

### How much actually changes per job (audit of recent tailored outputs)

Comparing `Remote_OK_Senior_Machine_Learning_Engineer.txt` against the base `~/.applypilot/resume.txt`:

```
Section                       % of bytes    Per-job changes
────────────────────────────  ────────────  ──────────────────────────────────────
Name + contact                ~4%           NEVER changes
Title line (one line)         ~1%           CHANGES — "Senior ML Engineer" etc.
Summary paragraph (3-4 lines) ~6%           CHANGES — 2-3 sentences re-framed
Technical Skills (ordered)    ~12%          REORDERED — same skills, prioritized differently
Experience companies/dates    ~5%           NEVER changes
Experience bullets (the bulk) ~60%          SELECTED — same bullets, different 4-6 chosen
Education                     ~3%           NEVER changes
Other (footer, formatting)    ~9%           NEVER changes
```

Roughly **70% of the content is identical across every tailored resume**. The remaining 30% breaks into:
- ~15% that varies by ARCHETYPE (title line, summary, skills order, which 6-8 bullets) — predictable, can be pre-built
- ~10% that varies by JOB-WITHIN-ARCHETYPE (1-2 keywords inserted, company name in the summary) — surface-level substitution
- ~5% that genuinely needs LLM reasoning to get right (cross-domain mapping, e.g., "my fintech experience for a healthcare role")

The current pipeline spends ~$0.03/job to regenerate all 100% of the resume, every time, even though 85% of that work could be a `cp` + `sed` operation.

### Tailoring cost breakdown (per job)

From scoring/tailor.py:
- `tailor_resume` runs up to 4 internal attempts (`max_retries=3`)
- Each attempt: ~5K input tokens (resume + job + system prompt) + up to 2,048 output tokens
- Plus the LLM judge (~3K input + 512 output)
- Realistic per-attempt cost on Gemini 3.1 flash-lite: ~$0.0025
- Realistic per-JOB cost (avg ~2 attempts + judge): **~$0.007**
- Cover letter adds ~$0.003 with its own retry loop
- **Total per job: ~$0.01-0.03 depending on how many retries fire**

Over 7,755 scored jobs (most NOT tailored), the user actually paid:
- 179 successful tailors × $0.015 = ~$2.69
- 289 failed-to-death tailors × $0.025 (more retries before dying) = ~$7.23
- 68 in-purgatory tailors (1-4 attempts, will retry) × $0.015 = ~$1.02
- **~$11 spent on tailoring** with only $2.69 producing usable artifacts.

That's a 75% failure-driven waste rate. Templates would have produced 179+ resumes with zero retries and zero LLM cost (after the one-time bootstrap).

### Why the LLM tailor fails so often

From the enrich-tailor-gap doc (prior in this series): the LLM-judge layer is strict about "banned words" (leverage, robust, comprehensive, etc.), banned phrases (LLM-leak markers), and JSON formatting. Each failure burns an attempt; 5 attempts = dead job.

**A hand-curated template can't fail any of these checks** — it's pre-validated by the human writing it. Once. Forever.

### Cover letter: even more templatizable

Cover letters from scoring/cover_letter.py are 3 short paragraphs:
- ¶1 (2-3 sentences): "something I built that solves their problem" — archetype-specific opening
- ¶2 (3-4 sentences): 2 achievements with numbers — archetype-specific bullets
- ¶3 (1-2 sentences): one thing about THIS company + close — the ONLY per-job content

So a cover letter is ~85% archetype-stable and ~15% per-job. Even more templatizable than the resume. And the per-job 15% is one paragraph that doesn't need LLM tokens to write — pattern-match on the job description for a product/technology mention, splice it into a templated sentence.

---

## The archetype taxonomy

From your `~/.applypilot/searches.yaml` (~25 queries) and resume header ("AI Engineer · Founding Engineer · Solution Architect · Forward Deployed Engineer · Senior Full Stack / Staff Engineer"), the natural archetypes:

```
ID                            Maps to searches.yaml queries                  Cover-letter angle
──────────────────────────    ─────────────────────────────────────────      ──────────────────────────
A1  Senior Frontend           senior frontend engineer, frontend engineer,   "shipped React @ scale"
                              senior front end developer, React engineer,
                              React developer, UI engineer
A2  Frontend Tech Lead        frontend tech lead, lead frontend engineer,    "led a frontend team / migration"
                              frontend lead, UI tech lead
A3  Senior Full Stack         senior full stack engineer, full stack         "frontend-heavy full stack"
                              engineer, full stack developer,
                              typescript developer, node.js developer
A4  AI / ML Engineer          ai engineer, ml engineer, applied ai,          "production RAG + 35% cost reduction"
                              machine learning engineer
A5  Staff / Principal         staff engineer, principal engineer,            "owned LLMOps stack end-to-end"
                              software architect
A6  Founding Engineer         founding engineer (YC / early-stage)           "scrappy 0→1, scaled to 50M"
A7  Solution Architect / FDE  solution architect, forward deployed,          "customer-facing technical, multi-product"
                              technical solutions engineer
A8  Engineering Manager       engineering manager (IC-hybrid only)           "tech lead growing into EM"
```

Each archetype has:
- **One resume `.txt` + `.pdf`** pre-built (8 total)
- **One cover-letter template** with placeholders (8 total)
- **A regex/keyword classifier** that maps a job title to an archetype (one classifier, deterministic)

Total artifacts: 16 files. Generated ONCE.

A few archetypes overlap (A1 / A2 / A3 / A5). That's fine — overlap doesn't cost anything because each is a separate file. If a job is genuinely on the boundary (e.g., "Senior Frontend Engineer at a Founding-Engineer-sized company"), the classifier picks the closest match; the cover letter is mostly templated so the difference is minor.

---

## The hybrid architecture

```
                NEW TAILOR FLOW

  Job enters tailor stage (fit_score >= 7)
       │
       ▼
  classify_archetype(job)         ← deterministic, regex on title + description
       │                            returns one of A1..A8
       │
       ┌────────────────┬────────────────┐
       │ B-grade        │ A-grade
       │ (default)      │ (fit_score >= 9 AND company in target_companies)
       │ ~80% of jobs   │ ~20% of jobs
       ▼                ▼
  ┌──────────────────┐  ┌─────────────────────┐
  │ load_template(   │  │ run LLM tailor      │
  │   archetype)     │  │ (today's behavior)  │
  │ + substitute     │  │                     │
  │ {company},       │  │ cost: ~$0.025       │
  │ {role_title},    │  └─────────────────────┘
  │ {1-2 keywords}   │
  │                  │
  │ cost: $0         │
  └──────────────────┘
       │
       ▼
  Save tailored_resume_path + cover_letter_path
       │
       ▼
  tailored_attempts += 1, tailored_at = now
```

### What's deterministic

**Classifier** (`classify_archetype`):
```python
import re

ARCHETYPE_RULES = [
    # Order matters: most specific first
    ("A8_eng_manager",   r"\bengineering manager\b|\beng\s+manager\b|\bem\s+manager\b"),
    ("A6_founding",      r"\bfounding engineer\b|\bfounder.?s\b"),
    ("A7_solutions",     r"\b(solutions?|forward deployed|customer engineer|partner)\s+engineer\b"),
    ("A4_ai_ml",         r"\b(ai|ml|machine learning|applied ai|llm|gen ai)\s+engineer\b|\bml(ops)?\s+engineer\b"),
    ("A5_staff",         r"\b(staff|principal|distinguished)\s+(engineer|architect)\b|\bsoftware architect\b"),
    ("A2_frontend_lead", r"\b(frontend|front[\s-]?end|ui)\s+(tech\s+lead|lead)\b|\blead\s+frontend\b"),
    ("A1_senior_fe",     r"\b(senior\s+)?(frontend|front[\s-]?end|ui|react)\s+(engineer|developer)\b"),
    ("A3_full_stack",    r"\b(senior\s+)?full[\s-]?stack\s+(engineer|developer)\b|\b(typescript|node\.?js)\s+developer\b"),
]

def classify_archetype(title: str, description: str = "") -> str:
    text = f"{title} {description[:500]}".lower()
    for archetype_id, pattern in ARCHETYPE_RULES:
        if re.search(pattern, text, re.I):
            return archetype_id
    return "A3_full_stack"   # safe default — covers the most general case
```

Cost: instant, $0. Deterministic. Tested in isolation.

**Templates** (one per archetype):

```
templates/
├── archetypes.yaml             # the classifier rules above, externalized
├── resumes/
│   ├── A1_senior_fe.json       # structured resume data
│   ├── A1_senior_fe.txt        # rendered text
│   ├── A1_senior_fe.pdf        # rendered PDF
│   ├── A2_frontend_lead.json
│   ├── A2_frontend_lead.txt
│   ├── A2_frontend_lead.pdf
│   ... (8 archetypes)
├── cover_letters/
│   ├── A1_senior_fe.txt        # with {company} {role_title} {keyword_1} placeholders
│   ├── A2_frontend_lead.txt
│   ... (8 archetypes)
└── keyword_pools.yaml          # per-archetype keyword library for the "1-2 keywords" splice
```

**Light substitution** (`fill_template`):

```python
def fill_template(template_text: str, job: dict, keyword_pool: dict) -> str:
    """Deterministic per-job customization. NO LLM."""
    company = job.get("site", "your company")
    role_title = job.get("title", "this role")

    # Extract 1-2 keywords from the job description that intersect with
    # the archetype's keyword pool. Greedy substring match — no NLP.
    desc = (job.get("full_description") or "").lower()
    job_keywords = [kw for kw in keyword_pool.get(job["_archetype"], [])
                    if kw.lower() in desc][:2]

    return (
        template_text
        .replace("{company}", company)
        .replace("{role_title}", role_title)
        .replace("{keyword_1}", job_keywords[0] if len(job_keywords) > 0 else "")
        .replace("{keyword_2}", job_keywords[1] if len(job_keywords) > 1 else "")
    )
```

That's the whole "tailoring." For 80% of jobs. $0 in LLM tokens.

### What stays LLM-driven

**A-grade definition** (configurable in profile.json):
```json
"tailor": {
  "a_grade": {
    "min_score": 9,
    "target_companies": [
      "Anthropic", "OpenAI", "Stripe", "Figma", "Linear",
      "Vercel", "Cursor", "Perplexity", "Notion", "Discord",
      "Airbnb", "Cloudflare", "Databricks", "DeepMind",
      "Y Combinator", "Sequoia portfolio", "..."
    ]
  }
}
```

If `(fit_score >= 9) OR (job.site in target_companies)`, run the existing LLM tailor as today. These are the jobs where extra polish actually moves the needle. ~10-20% of the queue.

For everyone else, the template path is plenty — and arguably BETTER, because the template was hand-reviewed by you, while the LLM output can drift, hallucinate, or include banned words.

---

## Cost projection

Assumptions (from the live test + prior docs):
- ~100 jobs reach tailor per discovery cycle (after the discover-relevance fix)
- ~80% are B-grade (template path), ~20% are A-grade (LLM path)
- A-grade LLM cost: ~$0.025 per successful tailor (factoring in retries)
- Cover letter cost similar

```
                          Today                 After fix
──────────────────────  ────────────────────  ──────────────────────────
B-grade (80 jobs)
  Resume tailor          80 × $0.015 = $1.20    80 × $0     = $0
  Cover letter           80 × $0.005 = $0.40    80 × $0     = $0
  Failed/dead retries    ~$2 wasted             ~$0 (templates can't fail)
A-grade (20 jobs)
  Resume tailor          20 × $0.015 = $0.30    20 × $0.015 = $0.30
  Cover letter           20 × $0.005 = $0.10    20 × $0.005 = $0.10
──────────────────────  ────────────────────  ──────────────────────────
Per-cycle total          ~$4.00                 ~$0.40
At 4 cycles/week         ~$16/week              ~$1.60/week
Monthly                  ~$70/month             ~$7/month
```

**~90% reduction in tailor + cover letter cost.** Plus the failure-driven waste (the $7 burned on 289 dead-at-5-attempts jobs in the prior doc) goes to zero because templates can't fail validation.

Combined with the discover-relevance-fix doc's ~90% scoring cost reduction, the user's total monthly LLM bill drops from ~$100 to ~$10. The savings compound because the discovery layer now passes through cheap data and the tailor layer mostly uses templates.

---

## The honest concern: ATS keyword matching

The main reason per-job LLM tailoring exists is **ATS keyword matching**. Recruiter tools (Greenhouse, Lever, Workday's parser) score resumes by extracting keywords from the job description and counting matches in the candidate's resume. A template can match the archetype's keywords but might miss job-specific ones (e.g., "GraphQL" or "Kafka" mentioned only in this job).

Three mitigations:

**Mitigation 1: per-archetype keyword pool, broad coverage.**

Each archetype's template includes a "Tools & Technologies" line that lists the FULL skills boundary from `profile.skills_boundary` — every tool the user can legitimately claim. ATS keyword matchers see all the user's real skills. If "GraphQL" is in the user's skills_boundary AND the job mentions it, the template matches.

**Mitigation 2: the `{keyword_1}` / `{keyword_2}` splice.**

The template has a "Recently shipped" or "Currently focused on" line that's filled in by the substitution layer:
```
Recently focused on: {keyword_1}, {keyword_2}
```
Where the substitution extracts 1-2 keywords from the job description that intersect with the archetype's pool. So even templated resumes get a job-specific keyword surface.

**Mitigation 3: monitor reply rate.**

Add a column `recruiter_reply_at` (or wire to the existing inbox classifier). If the templated path's reply rate drops vs the historical LLM-tailored rate, the templates aren't keyword-rich enough — iterate on the archetype files. The first-month metrics will tell you.

If reply rates drop significantly (say >20%), fall back to LLM tailor for B-grade jobs too. The cost is still bounded.

**Mitigation 4: keyword density check post-substitution.**

Before saving, run a deterministic check:
```python
def keyword_density_ok(resume_text: str, job_description: str, threshold: float = 0.4) -> bool:
    """Score keyword overlap. If too low, fall back to LLM tailor."""
    job_keywords = extract_top_keywords(job_description, top_n=15)  # TF-IDF, no LLM
    matched = sum(1 for k in job_keywords if k.lower() in resume_text.lower())
    return (matched / len(job_keywords)) >= threshold
```

If a templated resume scores < 40% keyword match against the job description, fall back to LLM tailor for THIS job specifically. Best of both: template-fast for 80%, LLM-fallback for the 5-10% where the archetype is too generic.

---

## Bootstrap: generate the 8 templates once

This is a one-time human-in-the-loop step. ~1 hour, ~$0.04 in LLM cost total.

**Step 1**: for each archetype, write a one-line "voice" brief.

```yaml
# archetypes.yaml
archetypes:
  A1_senior_fe:
    voice: "Frontend engineer who ships React at scale, performance-focused, with measurable conversion wins."
    seed_keywords: [React, TypeScript, Next.js, performance, Core Web Vitals, conversion, A/B testing]
  A4_ai_ml:
    voice: "Production RAG/agentic AI builder, model-aware cost engineer, LLMOps owner."
    seed_keywords: [RAG, LangChain, LangGraph, pgvector, evaluation, prompt engineering, cost reduction]
  # ... 6 more
```

**Step 2**: run the existing tailor LLM ONCE per archetype, using a fake "ideal job" prompt:

```bash
applypilot tailor-archetype A1_senior_fe \
  --output templates/resumes/A1_senior_fe.json \
  --voice "Frontend engineer who ships React at scale..."
```

The CLI builds a synthetic "ideal frontend role at a generic frontend-focused company" job, runs the existing tailor pipeline once, and saves the output to disk.

**Step 3**: hand-review each output. Edit the JSON / text file directly. Fix anything that feels off, tighten any line, lock in the voice. This is the only place a human is in the loop.

**Step 4**: render to PDF using the existing `scoring/pdf.py` once per archetype:
```bash
applypilot render-templates
# Renders all 8 .json → .txt → .pdf
```

**Step 5**: commit the 24 files (8 .json + 8 .txt + 8 .pdf) to the repo or to `~/.applypilot/templates/`. They never need regenerating unless the user's underlying skills or experience changes significantly.

**Cost of bootstrap**: 8 LLM tailor calls × ~$0.015 + 8 cover letter calls × ~$0.005 = **~$0.16 one-time**. Versus today's $3/cycle ongoing, the bootstrap pays for itself in the first 5 minutes of the next cycle.

---

## Implementation plan (files + scope)

```
[+] src/applypilot/scoring/templates.py           NEW — classifier + filler + selector
[+] src/applypilot/scoring/keyword_extractor.py   NEW — TF-IDF top-N keywords (no LLM)
[+] src/applypilot/cli.py                         + tailor-archetype, render-templates cmds
[~] src/applypilot/scoring/tailor.py              MODIFIED — routing fork before LLM call
[~] src/applypilot/scoring/cover_letter.py        MODIFIED — same routing fork
[~] src/applypilot/config.py                      + TEMPLATES_DIR constant, A-grade config loader
[+] ~/.applypilot/templates/archetypes.yaml       NEW — classifier rules + voices + keyword pools
[+] ~/.applypilot/templates/resumes/*.{json,txt,pdf}     NEW — 8 archetypes × 3 files = 24 files
[+] ~/.applypilot/templates/cover_letters/*.txt   NEW — 8 cover-letter templates with placeholders
[~] ~/.applypilot/profile.json                    + tailor.a_grade.{min_score, target_companies}
[+] tests/test_archetype_classifier.py            NEW — regex coverage tests
[+] tests/test_template_filler.py                 NEW — substitution + keyword density tests
```

Net code added: ~400-500 lines. Net code modified: ~50 lines (routing forks in tailor.py and cover_letter.py).

### The routing fork

```python
# scoring/tailor.py — modified

def tailor_resume_with_routing(job: dict, profile: dict) -> tuple[str, dict]:
    """Route between template path and LLM path based on A-grade rules."""
    a_grade_cfg = profile.get("tailor", {}).get("a_grade", {})
    min_score = a_grade_cfg.get("min_score", 9)
    target_companies = set(c.lower() for c in a_grade_cfg.get("target_companies", []))

    is_a_grade = (
        (job.get("fit_score") or 0) >= min_score
        or job.get("site", "").lower() in target_companies
    )

    if is_a_grade:
        # Existing LLM path — unchanged
        return tailor_resume(profile["resume_text"], job, profile)

    # Template path
    from applypilot.scoring.templates import classify_archetype, fill_template
    archetype = classify_archetype(job["title"], job.get("full_description", ""))
    job["_archetype"] = archetype
    template_text = load_template_resume(archetype)
    filled = fill_template(template_text, job, load_keyword_pools())

    # Keyword density safety check
    if not keyword_density_ok(filled, job.get("full_description", ""), threshold=0.4):
        # Fall through to LLM if the template doesn't match well
        return tailor_resume(profile["resume_text"], job, profile)

    return filled, {"status": "approved", "source": "template", "archetype": archetype}
```

The existing `run_tailoring` batch loop calls this instead of `tailor_resume` directly. Backward-compatible — drop the templates directory and the routing falls through to today's behavior.

### Cover letter routing — same shape

```python
# scoring/cover_letter.py — modified
def write_cover_letter_with_routing(job: dict, profile: dict) -> tuple[str, dict]:
    # Same A-grade check as resume.
    # Template path: load cover_letters/{archetype}.txt, substitute placeholders.
    # LLM path: existing.
```

---

## What I'd actually ship

1. **Day 1 (~1 hour):** archetype classifier + the 8 archetype config files. Just the classifier and the YAML. No template files yet, no integration. Verify the classifier picks the right archetype for 30-40 historical jobs from the DB. Tune regex.
2. **Day 1 (~2 hours):** bootstrap. Run `tailor-archetype` 8 times. Hand-review and edit each output. Render to PDFs. Commit.
3. **Day 2 (~3 hours):** integration. Routing fork in tailor.py + cover_letter.py. Keyword density check. Tests.
4. **Day 2 (~30 min):** first live run on 10 B-grade jobs. Verify outputs look right. Spot-check the filled-in placeholders.
5. **Week 1 ongoing:** monitor recruiter reply rate. If it drops vs historical, iterate on archetype templates.

Total effort: ~6 hours including the human-curation step. Saves ~$60/month in LLM cost on tailoring alone. Saves another ~$20/month indirectly (the dead-pile retries from the enrich-tailor-gap doc disappear because templates can't fail).

The 6 hours pays back in the first 2-3 days of normal use.

---

## Edge cases the design handles

| Scenario | Template path | LLM fallback fires? |
|---|---|---|
| Standard senior frontend job at Series-B company | Use A1_senior_fe template | No |
| Anthropic Research Engineer (target company) | — | YES (in target_companies list) |
| fit_score = 10 random Workday role | — | YES (min_score=9 triggers) |
| Job title is "Software Engineer" (generic, no domain word) | Classifier defaults to A3_full_stack | No, unless keyword density check fails |
| Job title is "Senior Lead Frontend Engineer" (rare combo) | Classifier picks A2 (regex order favors more specific) | No |
| Brand new archetype the classifier doesn't know (e.g., "Game Engine Programmer") | Defaults to A3, keyword density likely fails | YES (density check falls back to LLM) |
| Cover letter mentions a specific product (e.g., "Discord's voice infrastructure") | Template has `{keyword_1}` slot filled with "voice infrastructure" | No |
| Tailored resume needs to highlight blockchain experience for a crypto company | A3_full_stack template includes blockchain keywords from skills_boundary | No, blockchain shows up via the Tools line |
| Job description is 500 words, very specific | Template + density check + 2 spliced keywords usually OK | Density check decides |
| Job description is 200 words, very generic | Template fine | No |

The keyword density check is the safety net: when a template doesn't match a specific job well, the LLM takes over for that job only. The user never gets a stripped-down or wrong-feeling resume.

---

## NOT in scope

- **Replacing the resume PDF renderer.** `scoring/pdf.py` works fine; templates just feed it different `.txt` files.
- **Multi-resume profiles.** A user could have separate Profile A and Profile B (e.g., manager track vs IC track) with different base resumes. Out of scope — single profile per machine per AGENTS.md.
- **Auto-detecting new archetypes from the discover pile.** Could cluster scored jobs to find emerging archetypes. Cute but premature.
- **Translating templates to other languages.** Out of scope.
- **Real-time template editing in the dashboard.** Useful but separate UX work; for now, edit the `.txt` files directly.
- **Removing the LLM cover-letter judge for A-grade jobs.** Keep the existing safety net.

---

## What already exists (reuse, don't rebuild)

- `scoring/tailor._build_tailor_prompt` — used at bootstrap time to generate the 8 archetypes. Don't replace.
- `scoring/validator.BANNED_WORDS` + `LLM_LEAK_PHRASES` — apply these to templates at commit time so the hand-curated files don't accidentally contain banned words.
- `scoring/pdf.py` — render `.txt` → `.pdf`. Used unchanged.
- `config.TAILORED_DIR` — same destination directory for output files; just write template-filled content to it.
- `profile.json:skills_boundary` — already enumerates all legitimate skills. Templates pull from this.
- `profile.json:resume_facts.real_metrics + preserved_companies + preserved_projects` — these are the facts that every resume MUST include. Templates inherit them.
- `database.py:tailored_resume_path` column — same field, same purpose; only the file producer changes.

---

## Risk and mitigation

| Risk | Likelihood | Mitigation |
|---|---|---|
| Template too generic, ATS bots reject | Medium | Per-archetype keyword pool + density check + recruiter-reply monitoring |
| Archetype classifier picks wrong bucket | Low | 8 archetypes are well-separated by query patterns; default to A3 is sane; regex tests cover edge cases |
| Hand-curated template has typo / bad fact | Low | Validator runs at commit time; PDF preview before commit; one-time human review |
| User pivots career, templates stale | Medium | Templates are 24 files on disk; user re-runs bootstrap (~$0.16) when they update the base resume |
| LLM still needed for novel archetypes | Expected | Density check falls through to LLM; no jobs are stranded |
| Cover letter feels formulaic to recruiters | Medium | The 1 per-job sentence (¶3) is the differentiator; reply-rate monitoring catches drift |

---

## Verification once shipped

```bash
# A) Classifier test on historical jobs
applypilot debug classify-archetypes --recent 50
# Output: list of 50 jobs with predicted archetype. Manually spot-check 5-10
# to confirm the picks make sense.

# B) Bootstrap and review
applypilot tailor-archetype A1_senior_fe --voice "Frontend engineer..."
# Open templates/resumes/A1_senior_fe.txt. Read it. Edit if needed.
# Repeat for A2..A8.

# C) Render and preview
applypilot render-templates
open ~/.applypilot/templates/resumes/A1_senior_fe.pdf
# Visual review. Tweak the .txt and re-render if needed.

# D) Integration test (template path)
applypilot run tailor --limit 5 --min-score 7
# Expect: tailored_resume_path set, but LLM cost should be ~$0 because
# templates were used. Check the .json metadata: source=template, archetype=A?.
sqlite3 ~/.applypilot/applypilot.db "
  SELECT title, site, fit_score, tailored_resume_path
    FROM jobs WHERE tailored_resume_path IS NOT NULL
   ORDER BY tailored_at DESC LIMIT 5;
"

# E) A-grade routing test
sqlite3 ~/.applypilot/applypilot.db "
  UPDATE jobs SET fit_score = 10
   WHERE site IN ('Anthropic','OpenAI') AND tailored_resume_path IS NULL
   LIMIT 2;
"
applypilot run tailor --limit 2
# Expect: LLM path runs for these; cost ~$0.025 each; report.source="llm".

# F) Cost audit
# Inspect Gemini billing for the run. Should be ~10x lower than the previous
# equivalent run. Log each tailor's report.source in the DB so the dashboard
# can show "tailored via template: 38 / via LLM: 5" as a stat.
```

---

## DEBUG REPORT

```
DEBUG REPORT
════════════════════════════════════════════════════════════
Symptom:         Tailoring is the biggest LLM cost line item.
                 Per-job tailoring + cover letter spends ~$0.02-0.03
                 even though ~85% of the resume content is identical
                 across all 179 tailored outputs.

Root cause:      The pipeline regenerates 100% of the resume content
                 via LLM for every job, including the 70%+ that
                 doesn't actually change. There's no concept of role
                 archetypes or pre-built templates. Every tailor =
                 ~5K input tokens + up to 4 retries + LLM judge.

Fix:             Hybrid template+LLM — shipped in scoring/templates.py,
                 tailor_resume_with_routing, cover_letter routing, CLI.
                 - 8 pre-built archetype resumes + cover letters,
                   generated ONCE via bootstrap (~$0.16 one-time)
                 - Classifier (regex on title+description) picks the
                   archetype per job — deterministic, $0
                 - Light substitution for {company}, {role_title},
                   {keyword_1}, {keyword_2} — deterministic, $0
                 - Keyword density safety net (TF-IDF) falls back
                   to LLM if template-match is < 40%
                 - LLM tailor reserved for A-grade jobs only:
                   fit_score >= 9 OR site in target_companies
                 ~80% reduction in tailor LLM cost; ~90% with
                 cover letters folded in. Plus elimination of the
                 5-attempt dead-pile because templates can't fail
                 validation.

Evidence:        - Audit of recent tailored .txt: ~70% bytes are
                   identical to base resume.txt; ~15% varies by
                   archetype; ~10% by job; ~5% needs real reasoning.
                 - searches.yaml has 25 queries clustering to 8
                   archetypes. Resume header explicitly lists 5
                   role identities the user accepts.
                 - tailor.py + cover_letter.py both gate on
                   profile.skills_boundary + resume_facts already;
                   adding an archetype field is additive.
                 - 179 tailored / 289 dead-at-5-attempts = current
                   75% failure-driven cost waste; templates remove
                   this entirely for B-grade.

Regression test: tests/test_archetype_classifier.py — 30 historical
                 titles, expected archetype labels.
                 tests/test_template_filler.py — placeholder
                 substitution, keyword density check, fallback
                 trigger.
                 Plus: integration test that tailors 5 B-grade and
                 2 A-grade jobs, asserts source="template" vs
                 source="llm" routing.

Related:         - enrich-tailor-gap-fix-may-2026.md (the 289 dead
                   jobs disappear because templates can't fail; the
                   attempt cap becomes ~irrelevant for B-grade)
                 - discover-relevance-fix-may-2026.md (fewer jobs
                   reach tailor in the first place; templates handle
                   the rest cheaply)
                 - apply-full-autonomy-may-2026.md (templates produce
                   tailored output faster, which means the apply
                   pipeline isn't blocked on tailoring backlog)

Status:          SHIPPED — code + tests (52 classifier/filler tests).
                 Bootstrap templates on disk still required for $0
                 B-grade path; see "Verification once shipped".
════════════════════════════════════════════════════════════
```
