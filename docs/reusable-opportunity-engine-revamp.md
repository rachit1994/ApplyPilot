# Reusable Opportunity Engine Revamp

**Purpose:** explain how to reorganize ApplyPilot so the same code can be reused across many service-company projects, without copying fragile job-search-specific logic into every new product.

This is an instruction document only. It does not prescribe code changes line by line.

## The core idea

ApplyPilot should become one product built on top of a reusable local-first "opportunity automation" engine.

The reusable engine should not know that an opportunity is a job. It should know how to:

- discover opportunities from sources
- enrich raw listings into structured records
- dedupe and classify records
- score fit against a profile and rubric
- draft documents or messages
- prepare attachments
- submit through browser or API flows
- record outcomes, errors, costs, and deadlines
- expose status through CLI, API, dashboard, and logs

ApplyPilot should then become the job-search product pack:

- job sources
- candidate profile schema
- job-fit scoring rubric
- resume and cover-letter prompt packs
- application-form submission policy
- job-specific dashboard labels

The same engine can then power RFPPilot, GrantPilot, FreelancePilot, SalesPilot, TalentPilot, ScholarshipPilot, and research/intelligence products by swapping the product pack.

## Why this is worth doing

The existing code already has reusable service-business assets:

- `src/applypilot/discovery/`: source adapters, ATS APIs, feeds, agent browsing, SmartExtract
- `src/applypilot/enrichment/`: detail-page extraction and full-description scraping
- `src/applypilot/scoring/`: LLM scoring, pre-filtering, templates, validation, PDF/document generation
- `src/applypilot/apply/`: visible Chrome automation, form extraction, profile binding, browser workers, apply logs
- `src/applypilot/database.py`: local SQLite persistence and migration patterns
- `src/applypilot/orchestration/`: run records, run events, stage progress, SSE-friendly event stream
- `src/applypilot/server/` and `dashboard/web/`: API and dashboard shell
- `src/applypilot/inbox/` and `src/applypilot/outreach/`: adjacent workflow modules for messaging and referrals

The main blocker is vocabulary and coupling. Today the system says "jobs", "resume", "cover letter", "fit score", and "apply" everywhere. That is good for ApplyPilot, but bad for reuse.

The revamp should introduce neutral engine words underneath the product words.

## New shared vocabulary

Use these neutral terms inside the reusable package:

| Current ApplyPilot term | Reusable engine term | Examples in other products |
|---|---|---|
| Job | Opportunity | RFP, grant, freelance gig, scholarship, bounty, sales prospect |
| Candidate profile | Actor profile | applicant, vendor, student, agency client, sales ICP |
| Resume | Source document | resume, company capability statement, portfolio, research brief |
| Cover letter | Draft artifact | proposal response, grant narrative, pitch email, SOP, bid attachment |
| Apply | Submit | submit bid, send proposal, submit grant, send outreach |
| Application | Submission | bid, grant application, college application, vendor form |
| Fit score | Rubric score | eligibility, ICP fit, candidate match, scam risk, compensation signal |
| Job board/source | Source adapter | ATS, grants database, tender portal, GitHub bounty board, procurement feed |
| Searches config | Source plan | target roles, grant categories, agencies, industries, keywords |
| Run stage | Pipeline step | discover, enrich, score, draft, submit, verify, track |

Do not rename the ApplyPilot UI to these neutral terms. Users of ApplyPilot should still see "Jobs", "Applications", "Resume", and "Apply". The neutral vocabulary belongs in the reusable package boundary.

## Recommended package shape

Create a small family of packages, not one giant utility dump.

| Package | Responsibility | Existing ApplyPilot code to extract or wrap |
|---|---|---|
| `opportunitykit-core` | domain models, config loading, local paths, SQLite repository interfaces, run events, stage orchestration | `config.py`, `database.py`, `pipeline.py`, `orchestration/` |
| `opportunitykit-sources` | source adapters, HTTP helpers, feed runners, browser-assisted discovery | `discovery/`, parts of `enrichment/` |
| `opportunitykit-enrichment` | detail-page extraction, text normalization, structured-data parsing, URL resolution | `enrichment/detail.py`, SmartExtract helpers |
| `opportunitykit-rubrics` | pre-filters, scoring rubrics, LLM scoring wrappers, keyword extraction, validators | `scoring/scorer.py`, `pre_filter.py`, `embedding_filter.py`, `keyword_extractor.py`, `validator.py` |
| `opportunitykit-drafting` | prompt packs, templates, document rendering, PDF conversion | `scoring/tailor.py`, `templates.py`, `cover_letter.py`, `pdf.py` |
| `opportunitykit-browser` | Chrome worker lifecycle, form extraction, profile binding, direct driver, Claude rescue path | `apply/chrome.py`, `apply/direct/`, parts of `apply/launcher.py` |
| `opportunitykit-dashboard` | generic FastAPI routes, event streaming, dashboard primitives | `server/`, reusable parts of `dashboard/web/` |
| `applypilot-product` | job-specific product pack and CLI | current job-specific CLI, configs, prompts, dashboard labels |

If the team wants one installable package at first, keep the same internal folders but ship them under one namespace. The boundary still matters even if packaging is delayed.

## Product pack contract

Each reusable product should be mostly configuration plus prompts, not a fork.

A product pack should define:

| Product-pack piece | What it contains |
|---|---|
| Name and labels | Singular/plural words for UI and CLI, such as Job/Jobs or Grant/Grants |
| Opportunity schema | Required fields, optional fields, deadlines, money fields, organization fields |
| Actor profile schema | Candidate, company, student, vendor, agency client, or ICP profile |
| Source plan | Which source adapters run and with what keywords, regions, filters, and credentials |
| Dedupe policy | URL match, organization/title match, content hash, external ID, deadline-aware dedupe |
| Rubric | Score dimensions, thresholds, skip rules, explainable reasons |
| Draft artifacts | Resume, cover letter, RFP proposal, grant narrative, pitch email, SOP, checklist |
| Submission policy | Manual, browser-assisted, direct API, email draft, dry-run only, or auto-submit |
| Verification policy | What counts as submitted, what needs human review, what errors are terminal |
| Dashboard labels | Page labels, table columns, filters, KPIs, detail-panel fields |

No product pack should import another product pack. All packs import the engine.

## Monorepo layout

Use a monorepo while the service company is still learning which modules generalize.

Suggested layout:

```text
packages/
  opportunitykit-core/
  opportunitykit-sources/
  opportunitykit-enrichment/
  opportunitykit-rubrics/
  opportunitykit-drafting/
  opportunitykit-browser/
  opportunitykit-dashboard/

products/
  applypilot/
  rfppilot/
  grantpilot/
  freelancepilot/
  salespilot/
  talentpilot/
  scholarshippilot/
  researchpilot/

templates/
  product-pack/
  source-adapter/
  rubric-pack/
  draft-pack/

docs/
  reusable-opportunity-engine-revamp.md
```

At first, keep ApplyPilot as the only fully working product. New verticals should start as product packs that prove the package boundaries.

## Copy-paste vs package decision

Use this rule:

| Situation | Recommended reuse mode |
|---|---|
| One-off demo due this week | Copy a product template, but keep copied code minimal and tagged with source version |
| Second project uses the same module | Extract that module into a package |
| Third project uses the same module | Treat the package as the source of truth and delete forks |
| Client needs custom prompts/config only | Do not fork code; create a product pack |
| Client needs a new source site | Add a source adapter to the package if it is reusable; keep credentials/config in the product |
| Client needs private local data | Keep local SQLite and product data directories separate |

Copy-paste is acceptable only as a short-term delivery move. It should not become the service company's operating model.

## Migration plan

### Phase 0: classify the current code

Before moving files, tag every current module as one of:

- engine core
- reusable adapter
- product-specific ApplyPilot logic
- UI shell
- product-specific UI labels
- experimental or legacy

Do this in a short inventory document or issue list. Do not start with mass renames.

Current likely classification:

| Current path | Classification |
|---|---|
| `src/applypilot/config.py` | mostly engine core, with ApplyPilot path names |
| `src/applypilot/database.py` | engine core plus job-specific schema |
| `src/applypilot/pipeline.py` | engine orchestration plus job-specific stage order |
| `src/applypilot/discovery/` | reusable adapters plus job-source configs |
| `src/applypilot/enrichment/` | mostly reusable |
| `src/applypilot/scoring/` | reusable LLM/rubric/drafting patterns plus job prompts |
| `src/applypilot/apply/direct/` | reusable browser-form foundation |
| `src/applypilot/apply/launcher.py` | mixed: reusable worker orchestration plus ApplyPilot apply queue |
| `src/applypilot/server/` | mixed: reusable dashboard API plus job/application labels |
| `dashboard/web/` | mixed: reusable dashboard shell plus ApplyPilot pages |
| `src/applypilot/inbox/` | separate add-on workflow |
| `src/applypilot/outreach/` | separate add-on workflow |

### Phase 1: introduce neutral models without changing behavior

Create neutral internal concepts while keeping the current `jobs` table and ApplyPilot CLI working.

Required concepts:

- `Opportunity`
- `OpportunitySource`
- `ActorProfile`
- `RubricResult`
- `DraftArtifact`
- `SubmissionTarget`
- `SubmissionOutcome`
- `PipelineRun`
- `PipelineEvent`

ApplyPilot can adapt a database job row into an `Opportunity`. Do not force a database migration first.

### Phase 2: split product config from engine config

Move product-specific settings into an ApplyPilot product pack:

- job stage names
- job board/source defaults
- candidate profile labels
- resume and cover-letter prompts
- apply-status labels
- dashboard table labels
- job-specific filters such as junior-role filtering, visa hints, salary handling

Keep shared settings in engine config:

- data directory
- SQLite path
- LLM provider settings
- run IDs
- event stream settings
- source timeouts
- browser worker settings
- retry policy

### Phase 3: extract the pipeline engine

The engine should run a configurable list of steps.

ApplyPilot currently has:

`discover -> enrich -> score -> tailor -> pdf -> refer -> cover`

Other products may need:

- `discover -> enrich -> score -> draft -> submit -> track`
- `discover -> enrich -> classify -> report`
- `discover -> enrich -> score -> outreach`
- `discover -> extract -> benchmark`

The engine should not hardcode stage names. Product packs should provide stage order, stage labels, and stage runners.

### Phase 4: normalize storage

Do not wipe or replace the current ApplyPilot database.

For reusable products, move toward tables like:

| Neutral table | Purpose |
|---|---|
| `opportunities` | one row per discovered item |
| `opportunity_sources` | source-specific metadata and fetch stats |
| `opportunity_scores` | rubric scores and reasons |
| `draft_artifacts` | generated documents, messages, checklists, PDFs |
| `submission_targets` | URLs, email addresses, portals, or API endpoints |
| `submissions` | outcome ledger and verification state |
| `runs` | pipeline runs |
| `run_events` | progress, logs, SSE events |
| `llm_usage_events` | provider, model, operation, estimated cost |

ApplyPilot can continue using `jobs` until an explicit migration is worth it. Add adapters first, migrate later.

### Phase 5: extract source adapters

A source adapter should return raw opportunities and source metadata. It should not know about resumes, cover letters, or dashboard UI.

Reusable adapter families:

- HTTP feed adapters
- HTML listing adapters
- ATS/API adapters
- browser-assisted source adapters
- YAML-configured source registries
- deadline-aware source adapters for grants/RFPs/scholarships
- issue-board adapters for bounties
- procurement portal adapters

Each adapter should expose:

- source name
- required config
- auth requirements
- fetch limits
- rate limits
- raw records found
- records inserted or updated
- errors

### Phase 6: extract scoring as rubrics

The scoring engine should accept an opportunity, an actor profile, and a rubric.

Rubric examples:

- candidate-job fit
- grant eligibility
- RFP win probability
- freelance fit
- sales ICP fit
- scam risk
- visa sponsorship likelihood
- compensation signal confidence
- skill-demand strength
- candidate-role match

Keep LLM calls generic. Product packs own the prompt text and dimensions.

### Phase 7: extract drafting as artifact generation

Drafting should generate named artifacts from opportunity + profile + rubric result.

Examples:

- tailored resume
- cover letter
- RFP response outline
- compliance checklist
- grant narrative
- scholarship essay/SOP draft
- freelance proposal
- cold email
- agency pitch
- market research report
- candidate summary

Templates and prompts should live in product packs. The engine should only manage rendering, validation, paths, metadata, and retry behavior.

### Phase 8: extract browser submission

The browser module should become a generic form-submission toolkit.

Keep these reusable concepts:

- visible Chrome worker lifecycle
- persistent local browser profiles
- form extraction
- field binding
- deterministic fill
- dry-run mode
- confirmation pauses
- screenshot/log capture
- result parsing
- verification state
- escalation to an agent when deterministic logic fails

Product packs decide whether auto-submit is allowed. For some products, such as RFPs and grants, the default should be draft-and-review, not auto-submit.

### Phase 9: make the dashboard label-driven

Do not fork the dashboard for every product.

Make the dashboard shell reusable:

- run overview
- source progress
- live logs
- opportunity table
- detail panel
- draft artifacts
- submission ledger
- error summary
- LLM usage
- settings/status page

Product packs provide:

- nav labels
- table column labels
- filters
- score names
- status names
- empty states
- detail-panel sections
- KPI definitions

ApplyPilot should remain polished and job-specific on top of that shell.

### Phase 10: create a product starter template

The service company should be able to start a new vertical by filling in:

- product name
- actor profile schema
- opportunity schema
- source config
- rubric dimensions
- draft artifact types
- submission policy
- dashboard labels
- smoke-test fixtures

The starter should include an isolated local data directory and test fixtures. It should not point at `~/.applypilot`.

## Mapping the 30 use cases

| # | Use case | Product family | Reusable modules |
|---|---|---|---|
| 1 | RFP/tender discovery -> score fit -> draft proposal response -> submit bid | RFP/procurement | sources, enrichment, rubrics, drafting, browser/API submission, deadlines |
| 2 | Grant discovery -> score eligibility -> draft grant application -> track deadlines | Grants | deadline sources, eligibility rubrics, drafting, tracker |
| 3 | Freelance job discovery -> score fit -> tailor proposal -> auto-apply | Freelance | job-like sources, rubrics, proposal drafting, browser submission |
| 4 | B2B hiring-intent intelligence | Intelligence/sales | job sources, enrichment, aggregation, reporting |
| 5 | Competitor hiring radar | Intelligence | job sources, classification, trend reporting |
| 6 | Skill demand intelligence | Intelligence | keyword extraction, time-series aggregation, dashboard |
| 7 | Resume-market gap analyzer | Career | job sources, resume profile, skill gap rubric |
| 8 | Career positioning engine | Career | demand data, scoring, recommendation drafting |
| 9 | Recruiter-side candidate matching | Talent | opportunity scoring reversed against candidate pool |
| 10 | Candidate pitching engine | Talent/sales | candidate profiles, company opportunity data, pitch drafting |
| 11 | White-label career automation for coaches | Career | ApplyPilot product pack plus client profile switching |
| 12 | Niche job board backend | Job board | discovery, enrichment, dedupe, classification, API |
| 13 | Visa-sponsored job finder | Career | job discovery, sponsorship rubric, relocation labels |
| 14 | Scholarship/college application assistant | Education | program sources, eligibility rubric, essay/SOP drafting |
| 15 | ATS/application QA tester | QA/benchmark | browser module, form extraction, friction scoring |
| 16 | Job scam detector | Safety | source enrichment, company checks, scam-risk rubric |
| 17 | Sales prospecting engine | Sales | source discovery, ICP rubric, outreach drafting |
| 18 | Agency proposal generator | Sales/services | company signal discovery, pitch drafting |
| 19 | Local-first private job-search CRM | Career CRM | storage, dashboard, submissions, follow-ups |
| 20 | Compensation intelligence engine | Intelligence | salary extraction, aggregation, benchmarks |
| 21 | Workforce planning intelligence | Intelligence | market demand, competitor hiring, report drafting |
| 22 | Internal mobility engine | HR | internal role sources, employee profile matching, drafts |
| 23 | Vendor onboarding automation | Procurement ops | profile binding, browser forms, document checklists |
| 24 | University placement copilot | Education/career | job discovery, student profiles, tailoring, tracking |
| 25 | Market research report generator | Intelligence | source ingestion, classification, report drafting |
| 26 | Procurement opportunity radar | Procurement | tender sources, fit scoring, alerts, deadlines |
| 27 | Founder strategy intelligence | Intelligence | hiring radar, classification, narrative reports |
| 28 | AI agent browser-form benchmark | QA/benchmark | browser submission, form fixtures, outcome scoring |
| 29 | Compliance document assistant | Compliance | checklist generation, attachments, deadline tracking |
| 30 | Open-source bounty/project finder | Bounties | GitHub/issue sources, fit rubric, proposal drafting |

## First three products to prove reuse

Start with three verticals that reuse the most code but differ enough to test boundaries.

### 1. FreelancePilot

Why first: closest to ApplyPilot.

Reuse:

- discovery
- enrichment
- scoring
- proposal drafting
- browser submission
- applications/submissions dashboard

Changes:

- profile becomes freelancer/company profile
- resume becomes portfolio/capability statement
- cover letter becomes proposal
- apply policy may be dry-run first

### 2. GrantPilot

Why second: tests deadlines and eligibility.

Reuse:

- source adapters
- enrichment
- rubrics
- drafting
- tracking dashboard

Changes:

- no default auto-submit
- deadline-first schema
- grant-specific eligibility rubric
- application artifacts are narratives, budgets, checklists, attachments

### 3. SalesPilot

Why third: proves the engine is not only for applications.

Reuse:

- discovery
- enrichment
- scoring
- drafting
- outreach/inbox patterns
- dashboard

Changes:

- opportunity is a company/account
- score is ICP fit
- draft artifact is cold outreach or agency proposal
- submission is email/CRM task, not ATS form

## Things that must stay product-specific

Do not put these in the shared engine:

- ApplyPilot branding
- job-only table names in public APIs
- job-specific prompts
- resume-only validation rules
- cover-letter-only assumptions
- candidate-only profile fields
- job-board-only dashboard labels
- apply-status labels that only make sense for ATS workflows
- user-specific local paths such as `~/.applypilot`

The engine can provide the mechanism. The product pack provides meaning.

## Safety rules during the revamp

- Never wipe or replace the user's live ApplyPilot SQLite database.
- Use isolated local data directories for experiments and tests.
- Keep ApplyPilot working after every phase.
- Prefer adapters before migrations.
- Do not rename public CLI commands until product packaging is stable.
- Do not fork dashboard behavior just to change labels.
- Do not make the shared engine depend on an ApplyPilot product module.
- Keep browser auto-submit opt-in per product.
- Keep all generated documents and submissions auditable.
- Preserve visible Chrome workflows for application-like products.

## Verification checklist

Every extraction phase should prove:

- ApplyPilot still runs the original job pipeline.
- ApplyPilot dashboard still shows runs, logs, jobs, applications, and LLM usage.
- A product-pack fixture can run at least discover -> enrich -> score.
- A product-pack fixture can generate at least one draft artifact.
- SQLite tests run against an isolated temp directory.
- Browser-form tests do not mutate live user data.
- Package imports flow one way: product imports engine, engine does not import product.
- Product labels can change without changing engine code.

## What to do first

1. Create the neutral model names and adapters while leaving current behavior unchanged.
2. Move product-specific prompts and labels behind an ApplyPilot product pack.
3. Extract run orchestration and events into the core package.
4. Extract source adapters and enrichment.
5. Extract rubrics and drafting.
6. Extract browser submission.
7. Make dashboard labels product-pack driven.
8. Build FreelancePilot as the first reuse proof.
9. Build GrantPilot as the second reuse proof.
10. Build SalesPilot as the third reuse proof.

The win condition is simple: a new service-company project should be mostly a product pack, not a fork.

