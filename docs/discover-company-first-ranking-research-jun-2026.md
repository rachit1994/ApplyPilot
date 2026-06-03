# Company-First Discover Ranking Research (June 2026)

## One-line thesis

ApplyPilot discover should start by finding companies similar to the ones Rachit
has already succeeded in, then search those companies and their ATS/job-board
surfaces in priority order. Job boards are useful when they reveal promising
companies or links; they should not be treated as the final source of truth.

## Why the current framing is wrong

The old mental model is:

```text
search broad job boards -> collect many jobs -> filter junk -> score survivors
```

That wastes effort because the expensive part of the pipeline is not only LLM
scoring. It is the whole attention budget: crawl time, enrichment, tailoring,
apply attempts, and human trust.

The better model is:

```text
past-fit companies -> similar companies -> likely hiring surfaces -> likely job links
```

Discover should answer this first:

> Which companies are most likely to have roles where this specific candidate
> can create value and get through the apply flow?

Only after that should it decide which source, query, ATS, or agent crawl is
worth spending effort on.

## Seed profile from Rachit's history

Use `profile.json.resume_facts.preserved_companies` as the primary seed list,
with `resume.txt` as fallback:

```text
Happening Today
MIRA
Delta Exchange
BetterPlace
Liftoff Pvt Ltd
Daffodils Software
```

These seeds imply several company archetypes:

| Seed signal | Inferred company archetype | Why it matters for discover |
|---|---|---|
| Happening Today | AI platform, event discovery, RAG, agent workflows | Look for AI-native product companies using RAG, agents, retrieval, and real-time UX. |
| MIRA | Generative AI product at high user scale | Look for consumer or creator AI platforms with production LLM/RAG teams. |
| Delta Exchange | Fintech, trading, real-time systems | Look for fintech, crypto, trading, payments, market data, and risk platforms. |
| BetterPlace | SaaS, workforce, enterprise operations | Look for B2B SaaS platforms with workflow automation and data-heavy products. |
| Liftoff / Daffodils | Product engineering and services | Look for product studios, SaaS vendors, and engineering-led companies that value full-stack ownership. |

This is not about finding famous companies. It is about finding companies whose
problems resemble the problems already visible in the resume: senior full-stack
engineering, AI systems, RAG, agents, real-time products, distributed systems,
performance, and production ownership.

## What mature systems teach us

### LinkedIn-style talent matching

LinkedIn describes talent search as a multi-pass retrieval and ranking problem:
standardize entities, build an index, retrieve candidates, rank with ML features,
log interactions, and use the logs for later training. ApplyPilot should mirror
that shape for companies and jobs: standardize company identities, retrieve
candidate companies, rank them, log outcomes, then update the ranking model.

Source: [LinkedIn Talent Search and Recommendation Systems](https://engineering.linkedin.com/content/dam/me/engineering/li-en/research/SIGIR-2018.pdf)

### Learning to rank

Learning-to-rank research says the core problem is ordering results by relevance,
not merely classifying each item independently. ApplyPilot's discover stage
should therefore produce a ranked work plan: which company/source/query/link to
try next. A score is useful only if it changes ordering.

Source: [Learning to Rank for Information Retrieval](https://www.microsoft.com/en-us/research/wp-content/uploads/2016/02/LambdaMART_Final.pdf)

### Lead scoring

Lead scoring systems predict conversion probability from first-party history plus
external traits. ApplyPilot should treat companies like leads: use Rachit's own
work history, prior ApplyPilot outcomes, company metadata, source history, and
role-density signals to estimate "probability this company yields a fruitful
application."

Source: [B2B Lead Scoring Model Based on Machine Learning](https://pmc.ncbi.nlm.nih.gov/articles/PMC11925937/)

### Two-sided marketplace matching

Marketplace matching works best when preferences on both sides can be described.
For ApplyPilot, that means the company must want a senior full-stack/AI profile,
and Rachit must plausibly want the company's role, compensation, location, and
apply process. A company with many jobs but poor mutual fit should rank below a
company with fewer jobs and stronger match quality.

Source: [Optimal Matchmaking Strategy in Two-Sided Marketplaces](https://pubsonline.informs.org/doi/abs/10.1287/mnsc.2022.4444?journalCode=mnsc)

### Recommender bandits

Bandit systems balance exploitation and exploration: spend most effort on arms
that have historically produced reward, but keep trying uncertain arms so the
system can learn. ApplyPilot's arms are source-plan actions such as "crawl this
company's Greenhouse board," "search LinkedIn for this company plus AI engineer,"
or "try this job-board query."

Sources:
- [Multi-Armed Bandits in Recommendation Systems](https://www.sciencedirect.com/science/article/pii/S0957417422001543)
- [Warm-Start Contextual Bandits](https://link.springer.com/article/10.1007/s10115-023-01861-2)

### Google Ads quality score

Google Ads separates expected click probability, relevance, and landing-page
experience as diagnostic components. ApplyPilot can copy the pattern: score a
discover target by role probability, candidate-company relevance, and apply-page
quality instead of one vague "source quality" number.

Source: [Google Ads Quality Score](https://support.google.com/google-ads/answer/6167118/about-quality-score)

### Multi-touch attribution

Marketing attribution warns against giving all credit to the final click. If
LinkedIn reveals a strong Datadog role but the final application happens on a
Greenhouse URL, both surfaces contributed. ApplyPilot should credit the board for
discovery and the ATS/company page for applyability.

Source: [Multitouch Attribution in the Customer Purchase Journey](https://www.ama.org/multitouch-attribution-in-the-customer-purchase-journey/)

## Cross-domain pattern: get, maintain, update

Across talent platforms, ad systems, B2B lead scoring, and freelancer
marketplaces, the common pattern is not "find everything and filter later." The
common pattern is a managed opportunity graph:

```text
seed identity -> similar accounts -> ranked actions -> measured outcomes -> updated priorities
```

For ApplyPilot, the "accounts" are companies and hiring surfaces. The system
should manage them like a local, single-user CRM:

| Lifecycle step | What institutions do | ApplyPilot equivalent |
|---|---|---|
| Get | Use seed customers, lookalikes, intent signals, and source history to find high-probability accounts. | Generate companies similar to Rachit's past employers, then find their ATS/career/job-board surfaces. |
| Qualify | Score account fit before spending sales or marketplace effort. | Score company priority before crawling every listing. |
| Route | Send effort to the best next channel, not every possible channel. | Pick ATS API, career page, job-board query, or agent crawl based on expected reward. |
| Maintain | Keep productive accounts warm and refresh them periodically. | Revisit high-priority companies even when no job was found last run, with a sane cooldown. |
| Update | Feed every outcome back into the ranking model. | Raise/lower company, source, query, and ATS scores from valid links, scores, applies, failures, duplicates, and stale links. |
| Retire | Stop over-spending on accounts with repeated poor evidence. | Put noisy sources or companies into cooldown instead of deleting all history. |

This lifecycle matters because a source can be useful in one role and weak in
another. A job board might be bad as a final apply surface but excellent as a
company-discovery surface. A company might be a strong fit but temporarily have
no open senior roles. The ranking system should preserve those distinctions.

## The company-first algorithm

### Step 1: build the seed-company profile

Inputs:

- `profile.json.resume_facts.preserved_companies`
- `profile.json.skills_boundary`
- `profile.json.experience.current_job_title`
- `resume.txt` experience bullets and metrics
- existing `jobs` rows, especially companies with `fit_score >= 7`, tailored
  resumes, apply attempts, or real applications

Output:

```text
CandidateCompanyProfile:
  seed_companies
  target_industries
  target_products
  target_tech
  target_role_titles
  target_scale_signals
  avoid_signals
```

For Rachit, the first profile should weight:

- AI platforms, RAG, agentic workflows, LLMOps, semantic search
- fintech, trading, payments, risk, real-time data
- B2B SaaS, workflow automation, enterprise products
- senior full-stack roles using React, Node.js, Python, TypeScript, AWS
- companies with direct ATS links and India/remote-compatible roles

### Step 2: generate lookalike company candidates

Candidate companies can come from:

- current `config/career_targets.yaml`
- current `config/employers.yaml`
- ATS public boards already supported by ApplyPilot: Greenhouse, Lever, Ashby,
  Workday
- companies seen in existing job rows, even if their prior jobs were rejected
- portfolio/funding datasets, startup lists, and curated engineering-company
  sources
- job boards, but only as company-discovery surfaces

Each candidate company should be normalized to a stable identity:

```text
company_name
domain
known_ats_family
career_url
industries
products
tech_signals
regions
remote_policy
source_evidence
```

Important: if a job board reveals a strong company, the company enters the graph.
The board is not "bad" just because the final apply happens elsewhere.

### Step 3: score company probability

Rank companies by probability of fruitful jobs, not number of listings.

Suggested first scoring formula:

```text
company_priority =
  0.25 * seed_similarity
+ 0.20 * role_density
+ 0.15 * tech_stack_overlap
+ 0.15 * applyability
+ 0.10 * location_compensation_fit
+ 0.10 * source_history_reward
+ 0.05 * freshness_growth_signal
```

Feature meanings:

| Feature | Meaning |
|---|---|
| `seed_similarity` | How close the company is to Rachit's past-company archetypes. |
| `role_density` | Count and freshness of senior full-stack, AI engineer, platform engineer, backend/full-stack roles. |
| `tech_stack_overlap` | Evidence of React, Node, Python, TypeScript, AWS, RAG, agents, LLMOps, vector DBs, real-time systems. |
| `applyability` | Direct Greenhouse/Lever/Ashby/Workday or company website apply path, low CAPTCHA/login friction, not marketplace-only. |
| `location_compensation_fit` | India, remote, relocation, visa, and pay compatibility. Unknown is neutral, clearly bad is negative. |
| `source_history_reward` | Prior ApplyPilot outcomes for this company or sources that found it. |
| `freshness_growth_signal` | Recent hiring, funding, launches, active job changes, or recent discovered roles. |

Cold-start companies should not be punished too hard. Use Bayesian smoothing:

```text
smoothed_reward = (prior_successes + observed_successes) /
                  (prior_trials + observed_trials)
```

For seed-like companies with no observed ApplyPilot history, give them a warm
prior based on seed similarity, not a blank zero.

### Step 4: build a ranked discover plan

Each discover action should be attached to a company or company cluster:

```text
DiscoverAction:
  company_id
  action_type: ats_api | career_page | job_board_query | agent_crawl
  source
  query
  url
  expected_reward
  cost_estimate
  exploration_reason
```

Ordering rules:

1. Direct ATS APIs for high-priority companies first.
2. Company career pages second, especially when ATS family is known.
3. Job boards third, used to reveal company/link evidence.
4. Agent browser discovery only for explicitly marked agent-mode sites or high
   expected reward company targets.
5. Broad random source sweeps only inside the exploration budget.

Suggested action score:

```text
action_priority =
  company_priority
* role_query_match
* source_reliability
* apply_path_confidence
* freshness
* cost_penalty
```

Where `cost_penalty` reduces priority for slow, noisy, login-heavy, CAPTCHA-heavy,
or historically low-yield crawls.

## Source and link attribution

Use multi-touch credit instead of last-touch credit.

Example:

```text
LinkedIn search result -> company website -> Greenhouse apply URL -> applied
```

Credit should be split:

| Surface | Credit |
|---|---|
| LinkedIn | Found the company/job lead. |
| Company website | Confirmed canonical career path. |
| Greenhouse | Provided applyable direct form. |
| Company | Produced the actual fruitful opportunity. |

Suggested attribution weights for a successful application:

```text
company: 40%
first_discovery_source: 25%
canonical_career_source: 15%
final_ats_source: 15%
query_or_cluster: 5%
```

For failures, assign penalties to the right layer:

| Failure | Penalize |
|---|---|
| Job is irrelevant | Query, source, and company role-density signal. |
| Company is strong but board link is stale | Board/link source, not the company. |
| ATS blocks automation | ATS applyability, not discovery source relevance. |
| Job board reveals a great company | Reward the board even if final apply is elsewhere. |
| Duplicate listing appears on many boards | Do not punish all boards equally; reward earliest useful discovery and dedupe later surfaces. |

## Feedback loop

The system should keep track of what worked and what did not at each level:

```text
company -> source -> query -> link -> job -> apply outcome
```

Reward ladder:

| Event | Reward |
|---|---:|
| Valid job link found | +1 |
| Full description enriched | +2 |
| Fit score >= 7 | +5 |
| Tailored resume generated | +8 |
| Apply attempted | +10 |
| Application submitted or confirmed | +20 |
| Human-confirmed promising company | +20 |
| Duplicate, expired, or irrelevant link | -2 |
| Fit score <= 3 | -5 |
| Wrong location/compensation/seniority | -6 |
| Apply path impossible or marketplace-only | -8 |

This reward should update:

- company priority
- source reliability
- query value
- ATS applyability
- exploration budget allocation

Use separate short-term and long-term memory:

| Memory | Use |
|---|---|
| 7-day memory | Detect fresh openings, broken crawls, temporary source failures, and hot hiring bursts. |
| 30-day memory | Decide which companies and sources deserve regular budget. |
| 180-day memory | Preserve durable fit signals from companies, industries, ATS families, and job-board discovery paths. |

Apply decay, not amnesia. A company that worked three months ago should slowly
lose priority if it stops producing relevant roles, but it should not vanish.
Likewise, a board that produced one bad batch should recover if later runs reveal
good company leads.

The dashboard can later show this plainly:

```text
Why this company/source is being searched:
- Similar to MIRA and Happening Today: AI platform + RAG + agent workflow signals
- 6 senior full-stack/AI roles found in last 14 days
- Greenhouse direct apply path available
- Prior ApplyPilot jobs from this cluster averaged score 8.1
```

## Bandit policy for discover

Use a warm-started contextual bandit once enough telemetry exists.

Arms:

- `company + ATS family`
- `company + career page`
- `company + job board + query`
- `company cluster + source`
- `new source exploration`

Context:

- company similarity features
- source quality history
- role query
- location
- ATS family
- time since last crawl
- current queue gaps

Policy:

```text
80% exploit high expected reward actions
15% explore near-neighbor companies and uncertain sources
5% pure exploration for new company/source discovery
```

Use Thompson sampling or UCB-style optimism so promising but under-tested
companies get chances. Warm-start the priors from Rachit's seed companies and
existing ApplyPilot source telemetry.

## Implementation roadmap

This document is the only change for now. Future implementation should happen in
small steps.

### Phase 1: company graph, no behavior change

Add a local company candidate layer that extracts:

- past companies from `profile.json`
- companies from `jobs.site`, `jobs.sources`, and ATS URLs
- configured career targets and Workday employers
- known ATS board identities

No crawling changes yet. Just produce a ranked company report.

### Phase 2: ranked discover plan

Before `run_discover`, generate a ranked list of discover actions. Existing
source runners can stay unchanged; the runner only changes the order and budget.

Example output:

```text
1. Anthropic / Greenhouse / senior full-stack AI query
2. Datadog / custom Greenhouse / AI platform query
3. Stripe / Greenhouse / backend platform query
4. LinkedIn / discover companies similar to Delta Exchange
5. Wellfound / discover seed-like AI startups
```

### Phase 3: attribution ledger

Track every useful touchpoint:

```text
run_id
company_id
job_url
touch_type
source
query
url
timestamp
reward_delta
```

This prevents the false conclusion "LinkedIn did not work" when LinkedIn found
the company but the final apply happened on an ATS page.

### Phase 4: bandit update loop

Convert source/company outcomes into smoothed reward estimates. Keep the model
local, transparent, and single-user first. Do not require SaaS infrastructure.

### Phase 5: dashboard transparency

Show:

- why a company was selected
- what source found it
- what changed after the latest run
- which actions are exploit vs exploration
- which sources are noisy but still useful for company discovery

## Acceptance criteria for future code

A future implementation is working when:

- discover can explain the top companies it plans to search before crawling
- company similarity is computed before broad job-board search
- source budgets shift toward companies and links that produce high scores and
  successful applies
- job boards get credit for discovering good companies, even if the final apply
  URL belongs to the company or ATS
- broad random crawling is capped to an explicit exploration budget
- the user can see what worked, what failed, and why the next run changed

## Source list

- [LinkedIn Talent Search and Recommendation Systems](https://engineering.linkedin.com/content/dam/me/engineering/li-en/research/SIGIR-2018.pdf)
- [Learning to Rank for Information Retrieval](https://www.microsoft.com/en-us/research/wp-content/uploads/2016/02/LambdaMART_Final.pdf)
- [Multi-Armed Bandits in Recommendation Systems](https://www.sciencedirect.com/science/article/pii/S0957417422001543)
- [Warm-Start Contextual Bandits](https://link.springer.com/article/10.1007/s10115-023-01861-2)
- [B2B Lead Scoring Model Based on Machine Learning](https://pmc.ncbi.nlm.nih.gov/articles/PMC11925937/)
- [Optimal Matchmaking Strategy in Two-Sided Marketplaces](https://pubsonline.informs.org/doi/abs/10.1287/mnsc.2022.4444?journalCode=mnsc)
- [Google Ads Quality Score](https://support.google.com/google-ads/answer/6167118/about-quality-score)
- [Multitouch Attribution in the Customer Purchase Journey](https://www.ama.org/multitouch-attribution-in-the-customer-purchase-journey/)
