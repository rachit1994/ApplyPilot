# ApplyPilot Dashboard Redesign — Requirements (May 2026)

The current dashboard is functional but generic: a pipeline stepper, a stats row, a jobs table, a log console. It tells you *something happened*. It does not tell you *what is happening to me right now, why, and what I should do next.*

This doc is the brief for the v2 redesign. It exists so both the human and the design agents are calibrated on what "premium" and "ultra-helpful" mean for this specific product.

## Who is the user

One person, you, running ApplyPilot on their own machine to apply to 5-50 jobs per day. The dashboard is not a SaaS product. It is the cockpit for a single-pilot aircraft. The user is technical enough to read JSON but should not have to. They want to trust the autopilot enough to walk away, and intervene cleanly when it asks.

Three operating modes they slip between, often inside one session:

- **Walk-away mode.** "Run for 4 hours, apply to everything fit_score >= 7, ping me only if something needs me." Dashboard becomes a status surface they glance at on their phone.
- **Watch mode.** "I'm not sure I trust the agent on this site. Run with `--watch --pace 2`, show me the browser, let me see every fill." Dashboard becomes a side-by-side mission control.
- **Triage mode.** "Show me the 12 jobs that need my attention. Confirm, retry, or kill each one." Dashboard becomes a queue manager.

Premium for this user is **calm density**: a lot of truth on screen at once, in a typography and layout system that doesn't make them work to read it. Not a marketing landing page. Not a guided wizard with three icons in colored circles. Closer to Linear's app, Bloomberg's terminal, or Vercel's deploy dashboard — but tuned to a single-operator workflow.

## The phases the user has to understand

ApplyPilot has eight phases. Today the dashboard's pipeline stepper shows seven of them as equal pills with a checkmark/spinner. That is the wrong abstraction. The phases have different time scales, different failure modes, and different control surfaces. The redesign treats them differently.

| # | Phase | What it does | Failure mode the user fears | Time scale |
|---|-------|--------------|-----------------------------|-----------|
| 1 | **Discover** | JobSpy + Workday API + Smart extract pull new jobs | "Source X is silently broken, I'm missing roles" | Minutes to hours |
| 2 | **Enrich** | Fetch full job descriptions | "Scraping blocked, I'm scoring on titles only" | Seconds per job |
| 3 | **Score** | LLM rates fit 0-10 against your resume | "Scoring is being too harsh / too generous" | Seconds per job |
| 4 | **Tailor** | LLM rewrites resume for each job | "All tailored resumes look the same" | Seconds per job |
| 5 | **Cover** | LLM writes cover letter | Same as above | Seconds per job |
| 6 | **PDF** | Render resume + cover letter to PDF | "Wrong formatting, wrong name on file" | Sub-second |
| 7 | **Apply** | Chrome + Claude submit the application | "Marked applied but never submitted (the ghost bug)" | 30s-3min per job |
| 8 | **Refer** | Outreach to mutual connections via OpenOutreach | "Sent same message twice to one person" | Seconds per contact |

Plus a constant background: **Inbox** (recruiter replies), **Verification** (post-submit re-checks), and **Login warmers** (per-ATS cookie freshness). These are not phases per se but they need surface area.

## Core requirements, grouped by intent

### A. Make the user ultra-aware of what is happening

1. **A single "Now" panel that always answers: what is the system doing this second?**
   Not the high-level stage. The exact sub-step. "Worker 2: filling 'How did you hear about us?' field on Greenhouse application for Anthropic, attempt 1, 12 seconds in." If we have a screenshot or browser snapshot, show a thumbnail. If we're in the LLM call, show the model + token count so far.

2. **Quantitative progress, not "in progress."**
   `discover: 4/12 sources done, 387 new jobs, est 90s remaining`. `apply: 6/15 done in this batch, 3 verified, 2 needs-check, 1 failed`. Counts and percentages, always.

3. **Timeline ribbon, not pill stepper.**
   A horizontal ribbon at the top of the page showing the last 30 minutes of activity, color-coded per phase, with hoverable events. The user can rewind their attention to "wait, what happened 6 minutes ago when the apply count jumped?" without digging through logs.

4. **Show the ghosts.**
   The new `submitted_unverified` status from the ghost-fix doc gets a prominent counter on the home view, not buried in Applications. The user should not have to find out three days later.

5. **Workers are visible as cards, not abstractions.**
   When running with `--workers 3`, three "worker chips" sit in the Now panel. Each shows: current job title, ATS detected, sub-step, elapsed, cost-so-far. Clicking a chip opens a side panel with the worker's live log tail and last browser snapshot. This is the closest UI metaphor to "watching three Chromes at once" without actually opening three Chromes.

6. **Costs visible inline, never surprising.**
   Per-job LLM cost, per-run cost, per-day cost, per-month cost. Cap warning when projected month spend exceeds a configured ceiling.

### B. Give the user genuine control, without forcing them to the CLI

7. **Start, stop, pause from the dashboard.**
   The current dashboard can start the pipeline. It cannot pause apply mid-job, kill one worker but keep the others, or queue up "apply to this specific URL." Those should all be one click.

8. **Per-row actions on jobs and applications.**
   On any job row: "Apply now", "Skip permanently", "Mark manual", "Re-score", "Re-tailor", "View the prompt the agent will use". On any application row (especially unverified): "Confirm" (mark applied for real), "Retry" (re-queue), "Open in browser" (visit the apply URL to check), "View screenshot", "View log".

9. **A "Run plan" preview before any run starts.**
   When user clicks Start, show: "We will discover from 6 sources, enrich 200 jobs, score them, tailor the top 30, and auto-apply to ones scoring >= 7. Estimated time: 18 minutes. Estimated cost: $0.42." User can edit the plan inline (toggle stages, change min-score, change worker count, change pace) and re-preview before launching. No surprise spend.

10. **Stage toggles, not stage filters.**
    "I want to run discover only" and "I want to skip cover letter generation for this run" should be checkboxes on the Run plan, not buried in the CLI.

11. **Inline profile and search-config editing.**
    Today, you edit `~/.applypilot/profile.json` and `searches.yaml` by hand. The dashboard should let you edit them with a form, with validation, and reload without restarting the server.

12. **Login warmers as first-class controls.**
    A "Sites" or "Connections" tab shows: Greenhouse (logged in, cookies fresh, last verified 6h ago), Lever (cookies stale, click to refresh), Workday (never logged in, click to set up). One click triggers the warmer flow with a visible Chrome window.

13. **Human-in-the-loop pause.**
    The apply agent's `pause_for_human` status (from the ghost-fix doc) shows up as a big amber banner with the worker's last screenshot, the question, and an "I did it, resume" button. No CLI, no manual file edits.

14. **Spend ceiling and apply ceiling.**
    User sets "stop after $5 today" or "stop after 25 applies today" in a header control. Dashboard enforces both with a visible counter.

### C. Premium look — what that means for THIS dashboard

15. **Typography does the heavy lifting.**
    A real display typeface (not Inter) for headings and big numbers. A high-quality mono (JetBrains Mono / IBM Plex Mono / Berkeley Mono) for log lines, URLs, IDs, code-like data. Tabular numerals (`font-variant-numeric: tabular-nums`) on every counter, table cell, and currency value. Headings use `text-wrap: balance`. This alone will move the dashboard out of "generic dark theme React app" territory.

16. **One accent, used sparingly.**
    The current theme uses blue everywhere — buttons, badges, links, the ambient gradient. The redesign picks one accent (suggest electric violet or signal green, not the same blue every SaaS uses) and reserves it for actionable state: the currently-running phase, the primary CTA, the verified-applied count. Status colors (success/warning/danger) get their own desaturated palette. Everything else lives in a 5-step neutral ramp.

17. **Density without clutter.**
    Use 12px and 14px font sizes for table cells, log lines, and chip labels — but with generous line-height (1.6) and clear visual grouping. The Bloomberg trick: small text + air around it reads luxurious, small text + crammed margins reads like a phpMyAdmin clone.

18. **No decorative cards.**
    Every card must earn its existence. A card is justified when it represents a distinct interactive unit (a worker, a job, a connection). It is NOT justified as a way to put a 16px icon next to a 14px label next to a 12px body. Most "feature card" patterns in current SaaS are anti-patterns for an operator dashboard.

19. **Subtle motion that conveys state, not delight.**
    A pulse on the "Now" indicator when something changes. A slow shimmer on the active worker chip. A clean cubic-bezier slide for the log feed when new lines arrive. No bouncy spring animations, no animated gradients, no glow effects on hover. Premium motion is restrained motion.

20. **No AI-slop signatures.**
    No purple-to-blue gradient hero. No 3-column "feature grid" of icon-in-circle + bold title + 2-line description. No emoji as headings. No "Welcome to ApplyPilot" copy. No bubbly uniform border-radius. Border radii follow a hierarchy: 4px for small chips, 8px for buttons and inputs, 12px for cards, 0px for the page background.

21. **Numbers are the hero.**
    The dashboard's most prominent on-screen elements should be the counts that matter: jobs applied today, applies needing check, current spend, queue depth. Big tabular numerals in the display typeface. Everything else recedes.

### D. Layout and information architecture

22. **Three persistent regions.**
    - **Left:** thin nav rail with phase shortcuts, settings, log filter. 56px wide. Icon + tiny label.
    - **Center:** the active page (Pipeline / Applications / Sites / Profile / Inbox), full height.
    - **Right:** a contextual drawer for selected item details (worker → live tail, application → log + screenshot, job → resume preview). Collapsible.

23. **Pipeline page is the home.**
    Top: timeline ribbon (last 30 min). Below: Now panel (workers + current sub-step). Below: Queue panel (next 10 jobs to be processed, in order, with per-job preview). Below: log feed with proper auto-scroll and filter chips. Each region is sized to be readable at 1440x900 without scrolling on the page (the panels scroll, the page does not). On smaller screens, the queue moves under the log into a tab toggle.

24. **Applications page = ledger.**
    Big tabular view of every job the agent attempted to apply to. Default sort: newest first. Columns: status chip, title, company/site, score, applied at, duration, cost, verification, actions. Group header: "TODAY (12)", "YESTERDAY (8)", "MAY 21 (15)". Row click opens the right drawer with full detail (filled fields, screenshot, log excerpt, ATS detected, verification reasons).

25. **Sites/Connections page = the control panel.**
    Per-ATS cards (Greenhouse, Lever, Workday, Ashby, iCIMS, SmartRecruiters, BambooHR, WorkAtAStartup). Each card: status (logged in / stale / never), last verified, jobs applied via this ATS, success rate, action button (Log in / Refresh / Test).

26. **Profile and Searches editable from the dashboard.**
    Forms, validation, save with diff confirmation. No leaving the dashboard for these.

27. **Spend + Apply counters live in the header.**
    A persistent thin strip at the top, after the title and nav, that always shows: today's applies (3/25 cap), today's spend ($0.84/$5.00 cap), active workers (2/3), queue depth (47).

### E. Surface the things that today are invisible

28. **The exact prompt the agent will use.**
    For any job in the queue, the user can click "View prompt" and see the full Claude prompt that the apply agent will receive, with the resume text, profile, salary section, etc. — exactly as the agent will see it. If they don't trust the autopilot, this is the cheapest way to build trust.

29. **The form snapshot during apply.**
    Right side of the Now panel: when a worker is filling a form, show the live VERIFY PAGE STATE result — every field, every value the agent typed, every visible error. Updated in real-time. This is the "I want to see what it's typing" feature without needing to keep the Chrome window in view.

30. **Per-job audit trail.**
    On any applied or attempted job, surface the full audit: when discovered, from which source, score reasoning, tailored resume diff vs base, cover letter, the prompt sent, the agent's actions, the form snapshot at submit, the screenshot, the verification verdict and reasons.

31. **Verification status, prominently.**
    When the ghost-fix proposal ships, the dashboard must show: applied-verified count vs applied-unverified count, with a one-click bulk verifier ("re-verify the last 24h's applies by revisiting each URL").

32. **Inbox integration is not a separate world.**
    When a recruiter replies to an application, the corresponding application row gets a "🪶 reply" indicator. Click to see the email thread inline. No bouncing to Gmail. (This already exists as a separate Inbox tab; the redesign cross-links them.)

### F. Operational safety

33. **Big visible Stop, always reachable.**
    A red Stop button in the header, always visible, with a confirm modal. Distinct from Pause (which keeps the queue but stops new starts).

34. **Run history with diffs.**
    Past runs are listed with their plan, outcome, cost, duration. Clicking an old run shows what changed in the database (jobs discovered, applied, errors). For audit and "what was I doing yesterday."

35. **Soft warnings before destructive operations.**
    Reset failed, mark all manual, delete jobs by query — all need confirmation modals with the count of affected rows shown explicitly.

36. **Empty states with the next action.**
    "No jobs discovered yet. Run discover first" with a button to do exactly that. Never a blank panel.

37. **Errors are explained, not encoded.**
    `apply_error="not_eligible_salary"` → "We skipped this because the posted pay is below your $70K USD floor (configured in profile.json → compensation.salary_expectation)." With a link to edit the threshold inline.

## What "premium" rules out

To be explicit about the antipatterns, since AI-generated dashboards converge on them:

- No `linear-gradient(to right, #6366f1, #a855f7)` blue-to-purple hero.
- No glassmorphism / heavy backdrop-filter on every panel.
- No emoji in headings or as status icons. Lucide / Phosphor / custom SVG only.
- No 3-column feature grid section on the home page. (There is no marketing copy on this product anyway.)
- No "welcome back, John" hero banner.
- No animated counting numbers on every refresh.
- No "powered by Claude" badges or AI mystique branding.
- No carousels.
- No light-blue "info" banners with an ⓘ icon.

## Required pages, in priority order

1. **Pipeline** (home) — Now panel, queue, log feed, timeline ribbon.
2. **Applications** — ledger of submitted/attempted applies, with verification controls.
3. **Sites / Connections** — login warmers per ATS, success-rate per ATS.
4. **Jobs** — the full discovered queue, filterable, with per-row actions.
5. **Inbox** — recruiter replies, classified.
6. **Profile** — personal info, work auth, compensation, target roles.
7. **Searches** — boards, queries, company list, location filters.
8. **Run history** — past runs with diffs.
9. **Settings** — caps, pacing, model selection, telemetry, paths.

The first three are the redesign's main focus and must be designed in detail. The remaining six should be present in the IA (left nav) and sketched in layout, even if the v2 HTML doesn't fully render all of them.

## Component inventory the redesign needs

For both variant agents to produce a consistent system, they will design the following components:

- **Status chip** (5 variants: ready, running, verified, needs-check, failed)
- **Worker chip** (live, with sub-step, elapsed, cost)
- **Job row** (in queue / in jobs table)
- **Application row** (with verification status + reasons)
- **Phase node** (a single node in the timeline ribbon)
- **Counter card** (the big-number tiles)
- **Connection card** (per-ATS in Sites page)
- **Log line** (with level, worker, action type, copy-button)
- **Form snapshot panel** (mini live preview of the agent's view)
- **Run plan modal** (the pre-launch preview)
- **Right drawer** (contextual detail panel)
- **Header strip** (caps, spend, active workers, queue depth, Stop)

## Output format for both variant agents

Each agent produces a single self-contained `.html` file with inline `<style>` (no external CSS, no JS frameworks; vanilla HTML + CSS only). The file should render in a browser as a static design mockup of the **Pipeline page** with realistic placeholder data, plus a snippet of the **Applications page** and **Sites page** below it (scroll down to see). Use real-feeling data that reflects the failure modes: include `submitted_unverified` rows, a paused worker, a stale Lever warmer.

Total HTML budget: ~1000-1500 lines including CSS. The mockup must be print-quality at 1440px viewport.

## Voice and tone in copy

- Direct: "3 needs check" not "3 items require attention"
- Action verbs: "Apply now", "Re-verify", "Skip"
- Specific: "Stale (6 days)" not "May need refresh"
- No idle reassurance: cut "Everything is running smoothly" type copy

## Calibration references

Aspirational anchors, in roughly descending order of relevance:

- **Linear** — for typography, neutral palette, card economy, drawer pattern
- **Vercel** — for header strip, counter cards, calm density
- **Bloomberg Terminal** — for sub-step transparency, mono-font event feeds
- **GitHub Actions run view** — for timeline ribbon + log feed pattern
- **Stripe Dashboard** — for spend/cap visibility patterns
- **Sentry** — for event grouping ("TODAY (12)") and right-drawer detail

Not:
- Notion (too word-processor-y for an ops tool)
- Figma (too canvas-centric)
- Generic shadcn/ui starter templates (the AI-slop signature)
