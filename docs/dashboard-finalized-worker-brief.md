# ApplyPilot Dashboard Finalized UI Implementation Spec

This doc is written for a worker LLM that needs exact instructions.
Follow it literally.

Reference HTML:

`/Users/rachitsrivastava/.gstack/projects/ApplyPilot/designs/dashboard-20260527/finalized.html`

React dashboard:

`/Users/rachitsrivastava/viralEquation/ideas/ApplyPilot/dashboard/web`

Do not edit any database.
Do not wipe any data.
Do not make a new product direction.
Only update the dashboard UI to match the finalized HTML pattern.

## Outcome

The running dashboard must look like `finalized.html` on all pages:

- Home / Overview
- Jobs
- Apply Queue
- Applications

The current app already has the basic shell and much of the CSS in `dashboard/web/src/index.css`.
Do not create a new visual system. Use the finalized HTML class system.

## Files To Work In

Required files:

- `dashboard/web/src/index.css`
- `dashboard/web/src/components/HomePage.tsx`
- `dashboard/web/src/components/JobsExplorerPage.tsx`
- `dashboard/web/src/components/ApplyPage.tsx`
- `dashboard/web/src/components/AppliedApplicationsPage.tsx`
- `dashboard/web/src/components/layout/DashboardLayout.tsx`
- `dashboard/web/src/components/layout/HeaderStrip.tsx`
- `dashboard/web/src/components/layout/NavRail.tsx`
- `dashboard/web/src/dashboardNav.ts`

Optional small helper files:

- `dashboard/web/src/components/ApplicationDetailPanel.tsx`
- `dashboard/web/src/components/LogConsole.tsx`
- `dashboard/web/src/components/VirtualScroll.tsx`
- New shared presentational components only if they reduce repeated markup.

Do not touch backend unless the UI cannot build because of a type mismatch.

## Non-Negotiable Design System

Copy these rules from `finalized.html`.

### Tokens

Use these exact CSS variables in `:root`:

```css
--bg: #000000;
--surface: #1c1c1e;
--surface-2: #2c2c2e;
--surface-3: #3a3a3c;
--hair: rgba(255,255,255,0.06);
--hair-2: rgba(255,255,255,0.10);
--hair-3: rgba(255,255,255,0.16);
--ink: #f5f5f7;
--ink-2: #d1d1d6;
--ink-3: #8e8e93;
--ink-4: #636366;
--ink-5: #48484a;
--acc: #0a84ff;
--acc-2: #409cff;
--acc-dim: rgba(10,132,255,0.16);
--acc-line: rgba(10,132,255,0.32);
--acc-glow: rgba(10,132,255,0.40);
--display: "Inter Display", "Inter", -apple-system, BlinkMacSystemFont, "SF Pro Display", system-ui, sans-serif;
--body: "Inter", -apple-system, BlinkMacSystemFont, "SF Pro Text", system-ui, sans-serif;
--mono: "JetBrains Mono", ui-monospace, "SF Mono", Menlo, monospace;
```

Do not add a second palette.
Do not use beige, purple, slate-blue, brown, or colorful gradients.
Do not use light-mode backgrounds.

### Typography

Use:

- Body: `13.5px`, `line-height: 1.5`, `var(--body)`
- Display headings: `var(--display)`
- Metrics and code-like counters: `var(--mono)` only when the reference uses mono
- Compact panel headings: `15px`
- Header page title: `17px`
- Run title: `22px`
- KPI value: reference-sized large metric text

Do not use oversized marketing headings.
Do not use viewport-scaled font sizes.
Letter spacing should be `0` or the exact reference values only.

### App Shell

Every page must render inside this structure:

```tsx
<div className="app">
  <NavRail />
  <HeaderStrip />
  <main className="main">
    <div className="canvas">
      {pageContent}
    </div>
  </main>
  <RightDrawer />
</div>
```

Required shell CSS:

- `.app`: grid, `grid-template-columns: 64px 1fr`, `height: 100vh`, `overflow: hidden`
- `.rail`: 64px left rail, border-right, icon-only buttons
- `.head`: 68px header, border-bottom
- `.main`: the only page scroll region, `overflow-y: auto`
- `.canvas`: 12-column grid, `gap: 16px`, `padding: 22px 28px 36px`, `max-width: 1640px`

Do not add page-level wrappers that create another body scroll.
Do not add `h-screen overflow-y-auto` wrappers inside page components.
Logs can scroll internally; pages should scroll through `<main class="main">`.

### Core Classes To Use

Use these finalized classes everywhere:

Panels:

- `panel`
- `panel__head`
- `panel__title`
- `panel__sub`
- `panel__meta`
- `panel__actions`
- `panel__body`
- `panel__body--tight`

Buttons:

- `btn`
- `btn--accent`
- `btn--ghost`
- `icon-btn`

Filters:

- `chip`
- `chip--on`
- `chip__count`

Tables:

- `dt`
- `jobtitle`
- `jobtitle__t`
- `jobtitle__s`
- `src-tag`
- `score`
- `score--acc`
- `status`
- `status--ready`
- `status--review`
- `status__dot`
- `row-actions`

Home visualizations:

- `runband`
- `stepper`
- `step`
- `kpis`
- `kpi`
- `funnel`
- `fnl`
- `scoredist`
- `histogram`
- `sources`
- `feed`
- `event`
- `cost`
- `worker`

If any of these classes are missing in `index.css`, copy their CSS from `finalized.html`.

## Current Mismatch To Fix

Current files already partly match:

- `DashboardLayout.tsx`: has the shell.
- `NavRail.tsx`: mostly matches the reference.
- `HeaderStrip.tsx`: mostly matches the reference.
- `HomePage.tsx`: partly uses the reference classes.
- `index.css`: already contains many copied reference classes.

Current files that must be hardened:

- `JobsExplorerPage.tsx`: still uses generic Tailwind card/table layout.
- `ApplyPage.tsx`: still uses generic form/card layout.
- `AppliedApplicationsPage.tsx`: still uses generic two-column Tailwind layout.
- Some home sections may be missing exact labels or exact fields from `finalized.html`.

Your job is to convert these pages to the finalized design system, not to make the current Tailwind pages a little darker.

## Global Navigation

Use exact rail entries:

1. `Overview`
2. `Jobs`
3. `Apply Queue`
4. `Applications`
5. `Inbox`
6. `Analytics`
7. `Settings`

The route type currently only supports:

- `home`
- `jobs`
- `apply`
- `applications`

Keep Inbox, Analytics, and Settings visually present. They may be inert if no page exists.

Header must show:

- Breadcrumb: `ApplyPilot` then `›` then current page title then `Local`
- Command search: `Search jobs, companies, runs…` and `⌘K`
- Live status: `Live · {workers} workers`
- Verification status: `{count} to verify` when nonzero
- Bell icon with dot when verification count is nonzero
- Avatar: `RS`

Page titles:

- `home` -> `Overview`, not `Home`
- `jobs` -> `Jobs`
- `apply` -> `Apply Queue`
- `applications` -> `Applications`

Update `dashboardNav.ts` if needed.

## Home Page Exact Layout

Home must be the closest page to `finalized.html`.
Use exactly these sections in exactly this order.

### Home Section 1: Active Run

Component: `HomePage.tsx`

Outer markup:

```tsx
<section className="runband" aria-label="Active run">
```

Must include:

- `runband__status`
- `runband__pulse`
- `runband__label`
- `runband__title`
- `runband__sub`
- `stepper`
- `runband__controls`
- `runband__metrics`

Fields:

- Label: `Running` if active, else `Idle`
- Title: live run title or `Discover & score pipeline`
- Subtitle: live subtitle, including run id / elapsed / ETA if available
- Stage names in this exact order:
  1. `Discover`
  2. `Filter`
  3. `Enrich`
  4. `Score`
  5. `Tailor`
  6. `Cover`
  7. `Apply`
- Controls:
  - `Pause`
  - `Stop`
  - `New run`
- Metrics:
  - `Throughput`
  - `Score pass rate`
  - `Run cost`
  - `ETA to apply`
  - `Errors`

Progress rule:

- Done stage: `step step--done`
- Current stage: `step step--active`
- Pending stage: `step step--pending`
- Bar fill width must use real percent when available.
- Count text must show real counts when available, for example `287/463`.
- Do not only show "running" without counts.

### Home Section 2: KPI Row

Outer markup:

```tsx
<section className="kpis" aria-label="Top-line metrics">
```

Must include exactly six KPI cards:

1. `Applied · 30 days`
2. `Needs verify`
3. `Ready to apply`
4. `Pipeline total`
5. `Spend · today`
6. `Callback · 14 days`

Rules:

- Use `kpi`.
- Use `kpi kpi--attn` for `Needs verify` when value is above zero.
- Keep the sparkline SVGs from the reference where already present.
- If callback data is missing, show `—%`.

### Home Section 3: Funnel

Outer markup:

```tsx
<section className="panel funnel" aria-label="Pipeline funnel">
```

Panel title:

`Funnel`

Subtitle format:

`7-day rolling · {pipeline_total} in · {applied_30d} out`

Meta format:

`end-to-end {percent}%`

Rows in exact order:

1. `Discovered`
2. `Passed filter`
3. `Scored ≥ 7`
4. `Tailored`
5. `Cover written`
6. `Applied`
7. `Callback`

Each row must use:

- `fnl`
- `fnl__name`
- `fnl__bar`
- `fnl__bar-fill`
- `fnl__count`
- `fnl__rate`

### Home Section 4: Score Distribution

Outer markup:

```tsx
<section className="panel scoredist" aria-label="Score distribution">
```

Panel title:

`Score distribution`

Subtitle format:

`30 days · μ {mean} · σ {stddev}`

Meta format:

`{count} scored`

Buckets:

- Show labels `1` through `10`.
- Scores `7`, `8`, `9`, and `10` get `bar bar--apply`.
- Scores under `7` get `bar`.

Legend:

- `Apply (≥7)`
- `Skip`

### Home Section 5: Top Opportunities

Outer markup:

```tsx
<section className="panel opp" aria-label="Top opportunities">
```

Panel title:

`Top opportunities`

Subtitle:

`{ready_count} ready · sorted by fit score`

Filter bar chips:

1. `Ready`
2. `Tailored`
3. `Needs check`
4. `Applied`
5. `Score ≥ 8`
6. `Funded`
7. `Remote`
8. `SF / NYC`

Table must use class `dt`.

Table columns:

1. `Role · Company`
2. `Source`
3. `Location`
4. `Salary`
5. `Score`
6. `Status`
7. empty actions column

Row rules:

- Role/company cell uses `jobtitle`, `jobtitle__t`, `jobtitle__s`.
- Source uses `src-tag`.
- Score uses `score`; use `score score--acc` for high scores, normally `>= 9`.
- Status uses `status`, plus:
  - Ready: `status status--ready`
  - Needs check/review: `status status--review`
  - Other: `status`
- Actions use `row-actions` and `icon-btn`.

Use real jobs from the API. Do not hardcode the sample companies from the HTML.

### Home Section 6: Sources

Outer markup:

```tsx
<section className="panel sources" aria-label="Source quality">
```

Panel title:

`Sources`

Subtitle:

`Score ≥ 7 / discovered · last 7 days`

Rows use:

- `src-row`
- `src__name`
- `src__meter`
- `src__meter-fill`
- `src__eff`

Each row shows:

- Source name
- `{count} jobs`
- Efficiency percent or `—`

### Home Section 7: Activity

Outer markup:

```tsx
<section className="panel feed" aria-label="Activity">
```

Panel title:

`Activity`

Subtitle:

`Live · {event_count} events`

Filter chips:

- `All`
- `Errors`

Each event uses:

- `event`
- `event--accent` only for important success/start events
- `event__time`
- `event__msg`
- `event__stage`

### Home Section 8: Caps & Spend

Outer markup:

```tsx
<section className="panel cost" aria-label="Cost & throttles">
```

Panel title:

`Caps & spend`

Subtitle:

`Today · resets at midnight local`

Rows in exact order:

1. `LLM spend`
2. `Auto-apply`
3. `Resume tailoring`

Each row uses:

- `cost__row`
- `cost__label`
- `cost__value`
- `cost__bar`
- `cost__bar-fill`
- `cost__cap`

### Home Section 9: Workers

Outer markup:

```tsx
<section className="panel inbox" aria-label="Workers">
```

Panel title:

`Workers`

Subtitle:

`{active_count} active · all healthy`

Each worker uses:

- `worker`
- `worker__ring`
- `worker__ring-bg`
- `worker__ring-fg`
- `worker__name`
- `worker__stat`

Show worker name, sub-step, percent/status, and elapsed/health if available.

### Home Footer

Use:

```tsx
<footer className="footer">
```

Text format:

`ApplyPilot · v{version} · run {run_id} · {elapsed} elapsed`

Use `—` for missing values.

## Jobs Page Exact Changes

File:

`dashboard/web/src/components/JobsExplorerPage.tsx`

Replace the generic Tailwind page wrapper with direct children of `.canvas`.

Do not use:

- `space-y-4`
- `rounded-card`
- `bg-panel`
- `border-panel-border`
- utility-first table styling as the main visual language

Use this layout:

1. `section.panel.jobs-toolbar`
2. `section.panel.opp.jobs-list`

### Jobs Toolbar

Outer:

```tsx
<section className="panel jobs-toolbar" aria-label="Job filters">
```

Head:

- `panel__head`
- `panel__title`: `Jobs`
- `panel__sub`: `{total} roles · newest first unless sorted`
- `panel__actions`: page range, refresh state, Prev, Next using `btn btn--ghost`

Body:

- `panel__body`
- First row: stage chips using `chip`
- Second row: compact controls for:
  - Stage
  - Min score
  - Site
  - Sort
  - Page size
  - Search

Control styling:

Add or reuse:

- `control-grid`
- `control`
- `control__label`
- `control__input`
- `control__select`

These controls must use graphite backgrounds and `var(--hair-2)` borders.

### Jobs List

Outer:

```tsx
<section className="panel opp jobs-list" aria-label="Jobs">
```

Use a `dt` table.

Columns:

1. `Role · Company`
2. `Source`
3. `Location`
4. `Salary`
5. `Score`
6. `Stage`
7. `Date`
8. `Apply`
9. empty actions column

Rows:

- Role/company: `jobtitle`, `jobtitle__t`, `jobtitle__s`
- Source: `src-tag`
- Score: `score`
- Stage: `status`
- Date: visible in every row
- Apply: status text or `—`
- Actions:
  - open/select icon button

Keep existing filters, URL params, pagination, and job selection behavior.
Keep newest-first visible by default.

If using virtualization:

- Do not break table appearance.
- Fixed row height is okay.
- Header must remain visually aligned with body.

## Apply Queue Page Exact Changes

File:

`dashboard/web/src/components/ApplyPage.tsx`

This page should look like a command center for `applypilot apply`.
It must not look like a plain settings form.

Use this layout:

1. `section.runband.apply-runband`
2. `section.kpis.apply-kpis`
3. `section.panel.apply-controls`
4. `section.panel inbox.apply-workers`
5. `section.panel feed.apply-logs`

### Apply Runband

Use `runband` classes.

Fields:

- Label: `Apply Queue`
- Title: `Visible Chrome apply run`
- Subtitle: active run id/status or CLI preview
- Controls:
  - `Run apply` as `btn btn--accent`
  - `Stop` as `btn btn--ghost`
  - `Review applications` as `btn btn--ghost` if `onOpenApplications` exists

Metrics in `runband__metrics`:

1. `Ready`
2. `Applied`
3. `Unverified`
4. `Errors`
5. `Workers`

### Apply KPI Row

Use `kpis` with compact cards:

- `Ready to apply`
- `Applied today`
- `Needs verify`
- `Failed`
- `Worker count`
- `Mode`

### Apply Controls Panel

Panel title:

`Run controls`

Subtitle:

`Visible Chrome by default · use watch + pace`

Required controls:

- CLI preview command
- Limit
- Min score
- Workers
- Watch
- Pace
- Headless
- Continuous
- Dry run

Use:

- `chip chip--on` for enabled boolean options
- `chip` for disabled boolean options
- `control`, `control__input`, `control__select` for numeric fields
- `btn btn--accent` for starting
- `btn btn--ghost` for stopping/canceling

The visible browser preference must be obvious:

Text must include:

`Visible Chrome by default`

### Apply Workers Panel

Panel class:

```tsx
<section className="panel inbox apply-workers" aria-label="Apply workers">
```

Use worker rows:

- Worker ID
- Current sub-step
- Status
- Elapsed or `—`

Use `worker` classes. Do not leave the old generic list card.

### Apply Logs Panel

Panel class:

```tsx
<section className="panel feed apply-logs" aria-label="Apply logs">
```

Use `LogConsole` only if it visually matches. Otherwise wrap events in `event` rows.

Rules:

- Logs panel can scroll internally.
- Logs panel must not auto-scroll the whole page.
- Log rows should use `event`, `event__time`, `event__msg`, `event__stage`.
- Error rows should not turn all INFO lines red.

## Applications Page Exact Changes

File:

`dashboard/web/src/components/AppliedApplicationsPage.tsx`

This page must be an audit ledger for jobs actually submitted via apply.

Use this layout:

1. `section.kpis.applications-kpis`
2. `section.panel.applications-toolbar`
3. `section.panel.applications-ledger`
4. `section.panel.applications-detail`

At desktop widths, ledger and detail may be side by side.
At mobile widths, stack them.

### Applications KPI Row

Use `kpis`.

Cards:

1. `Applied`
2. `Needs verification`
3. `Failed`
4. `Manual`
5. `With field snapshot`
6. `Needs action`

### Applications Toolbar

Panel title:

`Applications`

Subtitle:

`Every apply attempt · fields filled, failure reasons, and submit proof`

Use chips for status filters:

- `All outcomes`
- `Needs action`
- `Applied`
- `Needs verification`
- `Failed`
- `Manual`
- `Has apply log`

Search uses `control__input`.

### Applications Ledger

Panel title:

`Application ledger`

Use `dt` table if space allows. If using a list, it must still use finalized visual classes.

Columns:

1. `Status`
2. `Role · Company`
3. `Score`
4. `Applied`
5. `Fields`
6. `Error`
7. empty actions column

Row data:

- Status: `status` classes
- Role/company: `jobtitle`
- Site/source: `src-tag`
- Score: `score`
- Applied date/time must be visible
- Field count must be visible
- Error or failure reason must be visible when present
- Selecting a row updates the detail panel

### Applications Detail

Panel title:

`Apply details`

Must show:

- Application status
- Role title
- Company/site
- URL
- Fit score
- Applied time
- Form field count
- Fields filled on the form
- Submit proof / screenshot / log path when available
- Apply log path
- Error message / failure reason
- Human action needed flag

Use the same graphite panel styling.
Do not leave this as a generic light bordered card.

If `ApplicationDetailPanel.tsx` already shows these fields, restyle it to use:

- `panel`
- `panel__head`
- `panel__title`
- `panel__sub`
- `panel__body`
- `src-tag`
- `status`
- `chip`

## CSS Additions Allowed

Only add classes that extend the finalized design system.
Recommended additions:

```css
.control-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; }
.control { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.control__label { font-size: 10.5px; font-weight: 500; text-transform: uppercase; letter-spacing: 0.06em; color: var(--ink-4); }
.control__input,
.control__select {
  width: 100%;
  min-height: 34px;
  border-radius: 8px;
  border: 1px solid var(--hair-2);
  background: var(--surface-2);
  color: var(--ink);
  padding: 7px 10px;
  outline: none;
}
.control__input:focus,
.control__select:focus { border-color: var(--acc-line); box-shadow: 0 0 0 3px var(--acc-dim); }
.page-span-12 { grid-column: span 12; }
.page-grid-2 { grid-column: span 12; display: grid; grid-template-columns: minmax(0, 1.3fr) minmax(320px, 0.7fr); gap: 16px; }
```

You may add page-specific layout classes:

- `jobs-toolbar`
- `jobs-list`
- `apply-runband`
- `apply-kpis`
- `apply-controls`
- `apply-workers`
- `apply-logs`
- `applications-kpis`
- `applications-toolbar`
- `applications-ledger`
- `applications-detail`

Page-specific classes should only set grid span, height, or small layout details.
Do not use them to create a different palette.

## Data Mapping

Use existing APIs:

- `fetchOverview`
- `fetchStats`
- `fetchJobs`
- `fetchApplications`
- `fetchActiveRun`

Do not hardcode sample rows from the HTML.
Do not invent fake counts.

Fallbacks:

- Missing text: `—`
- Missing number: `—`
- Missing percent: `—`
- Missing callback data: `—%`
- Missing list: finalized empty state inside `panel`

If a field is unavailable, still render the field label so the layout matches.

## What Not To Do

Do not:

- Build a marketing landing page.
- Replace the app with the static HTML.
- Remove live React data.
- Leave Jobs/Apply/Applications in Tailwind card style.
- Add large hero sections.
- Add nested cards inside cards.
- Add decorative orbs or colorful gradients.
- Add a second sidebar.
- Add a top nav.
- Use white backgrounds.
- Hide dates in Jobs rows.
- Hide apply errors in Applications.
- Let logs auto-scroll the entire page.
- Use destructive database commands.

## Step-By-Step Execution Plan

1. Open `finalized.html`.
2. Open `dashboard/web/src/index.css`.
3. Confirm all finalized classes exist in `index.css`.
4. Copy missing finalized class CSS from the HTML into `index.css`.
5. Add only the small allowed CSS additions listed above.
6. Update `dashboardNav.ts` page title for home to `Overview` and apply to `Apply Queue`.
7. Verify `DashboardLayout`, `NavRail`, and `HeaderStrip` still match the shell spec.
8. Update `HomePage.tsx` to include every Home section and field listed above.
9. Rewrite `JobsExplorerPage.tsx` into toolbar panel plus finalized table panel.
10. Rewrite `ApplyPage.tsx` into runband, KPI row, controls panel, workers panel, logs panel.
11. Rewrite `AppliedApplicationsPage.tsx` into KPI row, toolbar, ledger, detail panel.
12. Run TypeScript build.
13. Run the dashboard and inspect all four pages.

## Verification Commands

Build:

```bash
cd /Users/rachitsrivastava/viralEquation/ideas/ApplyPilot/dashboard/web
npm run build
```

Serve:

```bash
cd /Users/rachitsrivastava/viralEquation/ideas/ApplyPilot
uv run applypilot serve
```

Open:

`http://127.0.0.1:9477`

Check:

- `/`
- `/?tab=jobs`
- `/?tab=apply`
- `/?tab=applications`

## Acceptance Checklist

The job is not done until all items are true:

- Home visually matches `finalized.html` closely.
- Home has all nine sections plus footer.
- Home uses the exact listed field labels.
- Jobs page uses finalized panels, chips, table, status, source tags, scores, and icon buttons.
- Jobs rows show dates.
- Jobs default sort remains newest-first unless an existing route chooses apply priority.
- Apply page uses runband, KPI row, controls panel, worker rows, and feed/log panel.
- Apply page clearly shows visible Chrome/watch/pace controls.
- Applications page uses finalized KPI row, toolbar, ledger, and detail panel.
- Applications detail shows filled form fields and apply errors.
- Header and rail match the finalized HTML.
- `<main class="main">` is the main scroll region.
- Logs do not scroll the whole page.
- No page looks like a plain Tailwind admin page.
- No static mock companies from the HTML are used as live rows.
- `npm run build` passes.

## Final Report Format

When finished, report exactly:

- Files changed
- Pages updated
- Build result
- Any fields still showing `—` because backend data is missing
- Any browser inspection issues found
