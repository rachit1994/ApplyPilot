# India source map — portals & ATS (WP-0)

Evidence-backed inventory for **India-first, reply-first** apply strategy. Informs which portals and ATS families deserve deterministic adapters vs manual/assisted flows only.

**North star (from `WORKER_BRIEF_INDIA_FIRST.md`):** interview replies from Indian employers — not raw apply volume.

**Evidence confidence:** Most entries are **medium** (vendor help pages, ToS, industry blogs, third-party aggregators). Few have candidate-facing official APIs. Where confidence is **low**, treat automation feasibility as “needs URL sampling on live Indian jobs” before WP-3.

**Last reviewed:** 2026-06-04.

---

## How to read this doc

| Field | Meaning |
|--------|---------|
| **Login / auth** | How a candidate authenticates |
| **Bot / ban risk** | Likelihood that aggressive automation harms the user’s real account |
| **Automation path** | Best realistic path for ApplyPilot (see legend below) |
| **Reply tier** | High / Med / Low for **getting a human reply** in India (not “ease of apply”) |
| **ToS / safety** | Account-safety flags for the user’s real job hunt |

### Reply-rate tiers (Section 2 of worker brief)

| Tier | Meaning in India |
|------|------------------|
| **High** | Recruiter-initiated contact, direct recruiter chat, or referrals — profile visibility and inbound dominate |
| **Med** | Curated platforms + selective one-click / easy-apply; replies possible but not guaranteed |
| **Low** | Cold career-page / ATS form spray; necessary for coverage but poor reply-per-apply |

### Automation path legend

| Path | Description |
|------|-------------|
| **Official API** | Documented, OAuth/API access intended for integrations (usually **employer-side**, not job-seeker bulk apply) |
| **Easy apply** | Platform-native quick apply (logged-in session); rate-limited |
| **Form adapter** | Per-company career URL with stable form → Playwright deterministic adapter (ApplyPilot `apply/direct/` pattern) |
| **Manual / assisted only** | Human-in-the-loop or transparent browser assist; **no** headless spray — ToS or ban risk |

---

## Indian job portals

### Naukri (InfoEdge / naukri.com)

| Dimension | Assessment |
|-----------|------------|
| **Login / auth** | Email/mobile OTP; persistent session on web/app. Employer integrations use separate recruiter APIs (e.g. Greenhouse, Workable, Teamtailor) — **paid recruiter accounts**, not job-seeker APIs. |
| **Bot / ban risk** | **High** for scraping, credential sharing, or scripted apply. InfoEdge actively monetizes recruiter search (Resdex). Third-party “auto apply” tools exist publicly but are **ToS-hostile**. |
| **Automation path** | **Manual / assisted only** for apply and profile actions on the user account. Job **discovery** via unofficial scrapers = same risk — flag as assisted research only. Optional future: employer-posted jobs that deep-link to **external ATS** (then form adapter on destination). |
| **Reply tier** | **High** for **profile visibility** (recruiters search Resdex; Naukri states a large share of hiring is recruiter-database driven). **Med/Low** for cold “Apply” on listings without recruiter pull-through. |
| **ToS / safety** | Treat Naukri as **account-critical**. A ban blocks India’s largest recruiter-search graph. Do **not** bulk auto-apply or scrape logged-in session. Prefer: profile freshness, keyword alignment, **reply instrumentation** when recruiters message via Naukri/email. |

**Sources:** Naukri recruiter/ATS integration pages; InfoEdge business model; public third-party auto-apply repos (risk signal only).

---

### LinkedIn (India)

| Dimension | Assessment |
|-----------|------------|
| **Login / auth** | Microsoft/LinkedIn OAuth; session cookies; 2FA common. |
| **Bot / ban risk** | **High**. User Agreement prohibits unauthorized automation/scraping. Community reports of **Easy Apply caps** (~50/day scale, varies). Aggressive connection/InMail automation triggers restrictions. |
| **Automation path** | **Easy apply** only in **assisted / watched** mode with strict throttles — not unattended headless spray. **Manual / assisted** for profile, messaging, recruiter search. No official job-seeker apply API for third-party bulk tools. |
| **Reply tier** | **High** for inbound recruiter InMail/search and warm network. **Med** for Easy Apply (volume capped, mixed response). **Low** for indiscriminate Easy Apply spray. |
| **ToS / safety** | LinkedIn restriction = career damage for senior India roles. Align with existing ApplyPilot posture: inbox on **Other** tab, no auto-reply unless invited (`AGENTS.md`). |

**Sources:** LinkedIn Professional Community Policies / User Agreement; practitioner reports on Easy Apply limits.

---

### Instahyre (instahyre.com)

| Dimension | Assessment |
|-----------|------------|
| **Login / auth** | Email / Google SSO; candidate profile required for InstaMatch. |
| **Bot / ban risk** | **Med–High**. Public GitHub “auto apply” projects target Instahyre — strong signal of **ToS violation risk**, not endorsement. |
| **Automation path** | **Easy apply** + **InstaMatch** opportunities → feasible as **assisted** one-click apply with human-visible browser. **Manual / assisted** for messaging. Employer ATS integrations (API keys) are **employer-side** only. |
| **Reply tier** | **High** for recruiter-initiated InstaMatch / outreach on curated tech roles. **Med** for candidate-initiated apply on matched jobs. |
| **ToS / safety** | Do not run unattended bots against Instahyre login. Curated catalog favors **quality over volume** — matches reply-first strategy. |

**Sources:** Instahyre product pages (InstaMatch); public auto-apply repos (risk signal).

---

### Hirist (hirist.tech / InfoEdge family)

| Dimension | Assessment |
|-----------|------------|
| **Login / auth** | Email/social login; profile-backed applications. |
| **Bot / ban risk** | **Med** (smaller surface than Naukri/LinkedIn; same parent ecosystem incentives). |
| **Automation path** | **Easy apply** from profile → **assisted** only unless WP-3 validates stable DOM and ToS. Tech-only catalog. |
| **Reply tier** | **Med** — good for tech niche, smaller recruiter pool than Naukri/Instahyre. **Low** for generic spray. |
| **ToS / safety** | Same InfoEdge family caution; avoid scraping logged-in feeds. |

**Sources:** Hirist product positioning (tech jobs); InfoEdge relationship.

---

### Cutshort (cutshort.io)

| Dimension | Assessment |
|-----------|------------|
| **Login / auth** | Email/social; employer and candidate accounts. |
| **Bot / ban risk** | **High** for automation — ToS explicitly restricts automated access and systematic data collection. |
| **Automation path** | **Manual / assisted only**. Platform emphasizes shortlists and recruiter workflows; built-in recruiter automations are **in-product**, not third-party. |
| **Reply tier** | **Med–High** for shortlist/recruiter-driven flows when profile matches. **Low** for blind bulk apply. |
| **ToS / safety** | **Do not scrape or bot Cutshort.** Terms prohibit automated access — treat as manual/assisted channel only. |

**Sources:** [Cutshort Terms](https://cutshort.io/terms) (automated access restrictions).

---

### Foundit / Monster India (foundit.in, ex-Monster India)

| Dimension | Assessment |
|-----------|------------|
| **Login / auth** | Email/phone OTP; profile and resume upload. |
| **Bot / ban risk** | **Med–High** for scrapers and scripted apply (legacy Monster India scraper ecosystem). |
| **Automation path** | **Manual / assisted** apply (Quick Apply where offered). Recruiter search products are **employer-paid** (similar to Naukri Resdex). |
| **Reply tier** | **Med** via recruiter search visibility; **Low** for cold Quick Apply volume. |
| **ToS / safety** | Avoid logged-in automation; account used across mid-market India hiring. |

**Sources:** Foundit employer/candidate marketing; historical Monster India aggregator patterns.

---

### Wellfound — India (wellfound.com; AngelList Talent)

| Dimension | Assessment |
|-----------|------------|
| **Login / auth** | OAuth/email; often requires login to view/apply. |
| **Bot / ban risk** | **Med–High** when logged in; anti-bot on hiring flows. |
| **Automation path** | ApplyPilot already has **`workatastartup`** adapter for YC/startup board — **not India-specific**. India startup jobs on Wellfound: **manual / assisted** or extend Western adapter only where URL family matches. No stable public candidate API (legacy AngelList API deprecated). |
| **Reply tier** | **Med** for funded startups with direct founder/recruiter contact; **Low** for spray. Niche vs Naukri mass market. |
| **ToS / safety** | Don’t confuse global Wellfound adapter coverage with India volume. |

**Sources:** Wellfound help center; ApplyPilot `workatastartup` adapter scope.

---

### IIMJobs & Hirist premium (iimjobs.com) / Hirect (hirect.in)

| Dimension | Assessment |
|-----------|------------|
| **Login / auth** | **IIMJobs:** email, premium tiers for visibility. **Hirect:** mobile-first OTP, recruiter chat. |
| **Bot / ban risk** | **Med** (Hirect chat automation would be visibly abusive). |
| **Automation path** | **Manual / assisted only** — especially Hirect **direct chat** with recruiters. IIMJobs: assisted apply on premium/manager+ roles. |
| **Reply tier** | **High** for Hirect **recruiter-initiated chat** and IIMJobs premium visibility (manager+). **Low** for spammy bulk apply. |
| **ToS / safety** | Hirect value is conversation, not form fill. Wrong to optimize as ATS adapter. |

**Sources:** Product positioning (manager+ / direct chat); category fit for senior India roles in user profile.

---

## ATS & career-page systems (Indian employers)

These power **company career sites** discovered via enrich/discover. Reply tier for cold apply is generally **Low**, but deterministic adapters reduce Claude cost and improve **verified apply** signal.

### Keka Hire (keka.com)

| Dimension | Assessment |
|-----------|------------|
| **Login / auth** | **Per-company** career portal; candidate applies without a global Keka account. Partner **OAuth API** at `developers.keka.com` is for **HRIS/employer integrations**, not candidate bulk apply. |
| **Bot / ban risk** | **Low–Med** on public career pages (standard form POST); per-tenant rate limits unknown without sampling. |
| **Automation path** | **Form adapter** — career site + job board syndication (including Naukri). Fingerprint `*.keka.com` / customer career hosts after sampling. |
| **Reply tier** | **Low** for cold apply; **Med** if job syndicated from active recruiter requisition. Common in India SMB/mid-market. |
| **ToS / safety** | Prefer public career forms only; do not abuse employer APIs without contract. |

**Sources:** Keka Hire marketing; Keka developer portal (employer OAuth).

---

### Darwinbox (darwinbox.in)

| Dimension | Assessment |
|-----------|------------|
| **Login / auth** | Per-tenant `{company}.darwinbox.in` candidate portal; registration/login on apply. |
| **Bot / ban risk** | **Med** — enterprise tenants may use CAPTCHA/SSO variants. |
| **Automation path** | **Form adapter** per tenant pattern (e.g. `/ms/candidatev2/main/careers/jobDetails/{id}` reported in market). No unified public candidate API found. |
| **Reply tier** | **Low** cold apply; enterprise India (large employers). |
| **ToS / safety** | Sample top Indian employers before generalizing fingerprint; avoid credential stuffing across tenants. |

**Sources:** Public career URL patterns (aggregators, job posts); Darwinbox India enterprise adoption.

---

### Zoho Recruit (zoho.com/recruit)

| Dimension | Assessment |
|-----------|------------|
| **Login / auth** | Hosted `{company}.zohorecruit.com` or `{company}.zohorecruit.in` (+ custom CNAME). Candidate applies on tenant site; OAuth API is **org-scoped** (own tenant only). |
| **Bot / ban risk** | **Low–Med** on public career pages. |
| **Automation path** | **Form adapter** — stable `/jobs` / `/jobs/careers` patterns; embeddable widgets. Third-party indexers scrape career pages (no cross-tenant official API). |
| **Reply tier** | **Low** cold apply; strong **India SMB** penetration. |
| **ToS / safety** | Scrape public postings only; don’t impersonate org OAuth. |

**Sources:** Zoho Recruit career site docs; JobsPipe/Zoho Recruit notes on tenant URLs.

---

### Freshteam (freshworks.com/freshteam)

| Dimension | Assessment |
|-----------|------------|
| **Login / auth** | `{company}.freshteam.com` career sites; optional candidate account. |
| **Bot / ban risk** | **Low–Med** on public career pages. |
| **Automation path** | **Form adapter** — Freshworks widely used in India; job embeds and career site templates. |
| **Reply tier** | **Low** cold apply. |
| **ToS / safety** | Standard public-form only. |

**Sources:** Freshteam career site product docs.

---

### greytHR Recruit (greythr.com)

| Dimension | Assessment |
|-----------|------------|
| **Login / auth** | Per-organization career page (no single global host); Apply → form. |
| **Bot / ban risk** | **Low–Med**; hostnames vary by customer deployment. |
| **Automation path** | **Form adapter** after fingerprinting Indian customer URLs (harder than single-domain ATS). |
| **Reply tier** | **Low** cold apply; common in India HRMS-installed base. |
| **ToS / safety** | Requires empirical URL collection from Indian jobs in DB. |

**Sources:** greytHR admin/help documentation (career page setup).

---

### SmartRecruiters (smartrecruiters.com)

| Dimension | Assessment |
|-----------|------------|
| **Login / auth** | Public postings; apply via `jobs.smartrecruiters.com/{Company}` or `applyUrl` from API. |
| **Bot / ban risk** | **Low** for read-only Posting API; **Med** for aggressive apply automation. |
| **Automation path** | **Official API** (read): `GET /v1/companies/{slug}/postings` → **form adapter** on `applyUrl`. ApplyPilot already lists `smartrecruiters` in settings/eligibility markers but **no adapter** in `apply/direct/adapters/` (only greenhouse, lever, ashby, workatastartup). |
| **Reply tier** | **Low** cold apply; **Med** for India MNCs using SR for structured hiring. |
| **ToS / safety** | Respect Posting API terms; apply automation on public forms only. |

**Sources:** SmartRecruiters Posting API documentation; ApplyPilot `config.py` / `eligibility.py` markers.

---

### Workday & SAP SuccessFactors (enterprise)

| Dimension | Assessment |
|-----------|------------|
| **Login / auth** | **Workday:** `{tenant}.{wdN}.myworkdayjobs.com` — often account creation mid-apply. **SuccessFactors:** per-employer RC portals (varied hosts). |
| **Bot / ban risk** | **Med–High** — multi-step forms, SSO, CAPTCHA on some tenants; Workday warns of recruitment scams (official apply on tenant domain only). |
| **Automation path** | **Form adapter** (hard) — Workday: tenant-specific but repeating patterns; ApplyPilot discover already recognizes Workday URLs. SuccessFactors: **manual / assisted** until fingerprint proven. No candidate API. |
| **Reply tier** | **Low** cold apply for India enterprise requisitions; necessary for large tech/services employers. |
| **ToS / safety** | Do not use third-party scrapers with user credentials; prefer official tenant `applyUrl` from discovery. |

**Sources:** Workday careers fraud notice; Workday URL structure documentation (aggregators); ApplyPilot Workday discovery notes.

---

## ApplyPilot stack gap (context only)

| Area | Today | India gap |
|------|--------|-----------|
| Direct adapters | Greenhouse, Lever, Ashby, workatastartup | No Indian ATS or portal adapters |
| `ATS_URL_MARKERS` / eligibility | US-centric visa/residency blocking | Must invert for India-only (`WP-4`) |
| Default outcome | Indian jobs → Claude path | Structural cost + unreliability |

New work should extend `src/applypilot/apply/direct/` — **not** a parallel framework (`WORKER_BRIEF` §2b).

---

## Recommended next 3–4 builds (WP-3)

Ordered for **deterministic coverage of Indian employer career pages** first (fixes Claude-default path), while **reply strategy** continues to weight Naukri/LinkedIn/Instahyre as **manual/assisted visibility** channels.

| Priority | Target | Automation path | One-line justification |
|----------|--------|-----------------|-------------------------|
| **1** | **SmartRecruiters** | Posting API + form adapter on `applyUrl` | Public read API and stable apply URLs; marker already in eligibility; many India MNCs; fastest extension of proven Western adapter pattern. |
| **2** | **Keka Hire** | Form adapter on career portals | Very common India mid-market ATS; syndicates to boards; repeatable hosted career forms without candidate portal login. |
| **3** | **Zoho Recruit** | Form adapter on `{tenant}.zohorecruit.in` / `.com` | Dense India SMB footprint; consistent `/jobs` career hosts; good second fingerprint after Keka sampling. |
| **4** | **Darwinbox** | Per-tenant form adapter | Large India enterprise share; predictable `darwinbox.in` career paths once fingerprinted from real job URLs in DB. |

**Not recommended as unattended adapters (reply-first + ToS):** Naukri, LinkedIn, Cutshort — use **profile assist, watched Easy Apply, and reply instrumentation (WP-1)** instead. **Instahyre / Hirist:** assisted easy-apply only after explicit throttle + ToS review.

**Defer but track:** greytHR (variable hosts), SuccessFactors (heterogeneous RC URLs), Foundit/IIMJobs/Hirect (portal-specific chat/premium, not form adapters).

---

## Blockers & open validation (before WP-3 coding)

1. **URL sampling on live DB** — Run fingerprint pass on Indian jobs already in `~/.applypilot/applypilot.db` (read-only) to confirm Keka/Darwinbox/Zoho host distributions; greytHR may need new markers.
2. **Form heterogeneity** — Same ATS family may use custom fields, CAPTCHA, or SSO; adapter v1 should **park** `needs_adapter` rather than false-positive submit.
3. **No candidate APIs on portals** — Naukri/Instahyre/LinkedIn wins are **visibility + replies**, not silent bulk apply; WP-1 must prove channel mix.
4. **Evidence refresh** — Portal ToS and Easy Apply limits change; re-check quarterly.

---

## Source list (used in synthesis)

| Source | Use |
|--------|-----|
| `WORKER_BRIEF_INDIA_FIRST.md` | North star, reply-rate logic, WP-0 acceptance |
| Naukri / InfoEdge recruiter integration pages | Employer API vs job seeker |
| LinkedIn User Agreement / Easy Apply limit reports | Ban risk, assisted apply |
| Cutshort Terms (`cutshort.io/terms`) | Automated access prohibition |
| Zoho Recruit career site documentation | `{tenant}.zohorecruit.com` patterns |
| SmartRecruiters Posting API docs | `applyUrl`, company slug |
| Keka developers.keka.com | Employer OAuth scope |
| Workday careers fraud notice | Official apply domains |
| JobsPipe / Apify Workday scraper docs | `myworkdayjobs.com` URL shape (discovery only) |
| ApplyPilot `src/applypilot/apply/eligibility.py`, `apply/direct/adapters/` | Current adapter gap |
