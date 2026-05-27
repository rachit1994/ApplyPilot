# Target Recently Funded Series A/B Companies

Status: recommendation
Date: 2026-05-24

## Short Answer

This is partly config-only, but not fully.

ApplyPilot can already target specific companies if you provide their career pages or ATS board IDs in YAML. That is enough for a curated list of recently funded Series A/B companies.

ApplyPilot cannot yet discover recently funded companies automatically. There is no funding-round source, no company-to-careers resolver, and no persisted company funding metadata in the current pipeline. That part needs a larger discover-source change.

There are no XML config files in this repo. The relevant files are YAML:

- `~/.applypilot/career_targets.yaml`
- `~/.applypilot/watchlist.yaml`
- `~/.applypilot/searches.yaml`
- `~/.applypilot/discover.yaml`
- package examples under `src/applypilot/config/`

## Config-Only Path

Use this when you have a list of companies from TechCrunch, Crunchbase, YC, Wellfound, SignalFire, investor portfolios, or a manual spreadsheet.

### 1. Add company career pages

Create or edit `~/.applypilot/career_targets.yaml`:

```yaml
targets:
  - name: CodeRabbit
    careers_url: https://www.coderabbit.ai/careers
    ats: custom
    mode: smartextract
    funding_stage: series_b
    funding_note: "Raised Series B; developer-tooling company"

  - name: Emergent
    careers_url: https://emergent.sh/careers
    ats: custom
    mode: smartextract
    funding_stage: series_b
    funding_note: "Raised Series B; AI coding company"

  - name: Vega
    careers_url: https://careers.redpoint.com/companies/vega-ventures-2
    ats: custom
    mode: smartextract
    funding_stage: series_b
    funding_note: "Raised Series B; cybersecurity company"
```

Use `mode: smartextract` first. Use `mode: agent` only for career sites that need browser interaction, because agent discovery is slower and more brittle.

### 2. Add Greenhouse or Lever board IDs when known

Create or edit `~/.applypilot/watchlist.yaml`:

```yaml
companies:
  - name: CodeRabbit
    greenhouse_board: coderabbit

  - name: Example Lever Company
    lever_site: example-company
```

This is the best path when the company uses Greenhouse or Lever because ApplyPilot can call those public APIs directly.

### 3. Tighten developer searches

Edit `~/.applypilot/searches.yaml`:

```yaml
queries:
  - query: "software engineer"
    tier: 1
  - query: "backend engineer"
    tier: 1
  - query: "full stack engineer"
    tier: 1
  - query: "frontend engineer"
    tier: 2
  - query: "platform engineer"
    tier: 2
  - query: "infrastructure engineer"
    tier: 2
  - query: "AI engineer"
    tier: 2

include_titles:
  - "software"
  - "backend"
  - "frontend"
  - "full stack"
  - "platform"
  - "infrastructure"
  - "developer"
  - "AI engineer"
  - "machine learning"

exclude_titles:
  - "intern"
  - "internship"
  - "co-op"
  - "founding account executive"
  - "sales"
  - "marketing"
  - "recruiter"
  - "customer success"
```

### 4. Keep the right discover sources on

Edit `~/.applypilot/discover.yaml`:

```yaml
sources:
  career_targets: true
  greenhouse: true
  lever: true
  smartextract: true
  jobspy: true
  workday: false
  workatastartup: true
  hn_hiring: true
  remoteok: true
  himalayas: true
  remotive: true
  weworkremotely: true

agent_discover:
  enabled: true
  max_pages: 3
  headless: false
```

For the funded-startup search, `career_targets`, `greenhouse`, `lever`, and `smartextract` matter most.

## What This Gets You

Config-only targeting will:

- Pull jobs from selected funded companies.
- Apply existing title and location filters.
- Feed matching developer jobs into the existing enrich, score, tailor, cover, pdf, and apply stages.
- Keep the system local-first and single-user.

Config-only targeting will not:

- Find newly funded companies automatically.
- Know whether a company raised Series A or Series B unless you manually add that note.
- Rank jobs higher because of funding stage.
- Refresh the company list every day or week.

## Larger Product Change

To make this automatic, add a new discover source called something like `funded_startups`.

### Proposed User Config

```yaml
funded_startups:
  enabled: true
  stages: ["series_a", "series_b"]
  min_amount_usd: 15000000
  max_round_age_days: 120
  sectors:
    - developer tools
    - ai
    - cybersecurity
    - infrastructure
    - data
  countries:
    - United States
    - Canada
    - India
  require_open_engineering_roles: true
```

### Data Model

Add a local table for company funding metadata:

```sql
CREATE TABLE IF NOT EXISTS company_targets (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  domain TEXT,
  careers_url TEXT,
  ats TEXT,
  greenhouse_board TEXT,
  lever_site TEXT,
  funding_stage TEXT,
  funding_amount_usd INTEGER,
  funding_announced_at TEXT,
  funding_source_url TEXT,
  discovered_at TEXT DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(name, funding_announced_at)
);
```

Jobs could keep using the existing `jobs` table, with optional future columns for `company_funding_stage` and `company_funding_announced_at`.

### Source Pipeline

1. Fetch recent funding announcements from configured sources.
2. Extract company name, round stage, amount, announcement date, source URL, and domain.
3. Resolve a careers URL.
4. Detect ATS:
   - Greenhouse board
   - Lever site
   - Workday where possible
   - fallback to smart extract
5. Pull engineering jobs.
6. Store jobs with a site label like `FundedStartups:CompanyName`.
7. Optionally boost scoring for recent Series A/B companies.

### Suggested Implementation Files

- `src/applypilot/discovery/funded_startups.py`
- `src/applypilot/discovery/runner.py`
- `src/applypilot/discovery/discover_config.py`
- `src/applypilot/config/discover.example.yaml`
- `src/applypilot/database.py`
- `tests/test_funded_startups.py`

### Effort

Small if manually curated: YAML-only.

Medium to large if automatic:

- Need at least one reliable funding source.
- Need deduping and normalization.
- Need careers URL resolution.
- Need tests that avoid mutating the live DB.
- Need good logging, because funding-source failures should not break normal discover.

## Recommendation

Start with the config-only path for 20-50 known funded startups. It is quick, local-first, and uses the existing discover pipeline.

Only build `funded_startups` after the manual list proves useful. The automatic source is worthwhile, but it is not a one-file or XML-style change.
