# ApplyPilot Dashboard Redesign (Mission Control)

Date: 2026-05-27

## Goal

Redesign the ApplyPilot dashboard UI to match the visual language and composition of `~/.gstack/projects/ApplyPilot/designs/dashboard-20260527/finalized.html`, while **preserving the existing dashboard’s routes, data sources, and behaviors**.

Primary outcomes:

- A professional “Mission Control” dashboard shell (rail + header) and a Home page layout that matches the finalized design.
- A coherent, centralized set of **design tokens** (CSS variables) that drive Tailwind v4 theme utilities across the app.
- Incremental adoption: other pages continue to work; Home becomes the canonical new style baseline.

Non-goals (this pass):

- Re-architecting backend APIs or adding new endpoints solely to satisfy visuals.
- Removing Tailwind or replacing the component system wholesale.

## Scope decision (approved)

- **Full shell + layout redesign** to match `finalized.html` composition (rail/header + Home page panels).
- **Theme**: primary accent **cyan** + secondary **violet**, exactly as `finalized.html`.
- **Missing data**: panels that don’t have current API support will ship with **real empty states / placeholders** (no fake numbers).

## Approach (recommended + approved)

### Approach A: Token-first Tailwind v4 (recommended)

Keep the existing Tailwind v4 + React structure, but map all styling primitives to a new token set aligned with `finalized.html`.

Why:

- Minimal churn across existing components.
- Theme consistency via existing utilities (`bg-canvas`, `text-ink`, `border-panel-border`, etc.).
- Enables incremental rollout per-page/per-component.

## Information architecture

### Global app shell

The dashboard remains a two-region shell:

- **Nav rail** (left, fixed width): primary navigation.
- **Main region** (right): header strip + scrollable `<main>` content + right drawer.

### Home page (“Mission Control”)

Home becomes a 12-column canvas grid containing (in priority order):

1. **Run band hero** (full-width): active run status + pipeline stepper + primary controls + run metrics.
2. **KPI row** (full-width): 6 KPI tiles.
3. **Funnel** (span 7): rolling pipeline funnel.
4. **Score distribution** (span 5): histogram/summary (placeholder if no data).
5. **Top opportunities** (span 8): jobs table + filter chips (wired to existing jobs list where available).
6. **Source quality** (span 4): source performance list (wired where available; placeholder otherwise).
7. **Activity feed** (span 4–6 depending on breakpoint): live events/logs (reuse existing log feed).
8. **Cost & throttles** (span 4–6 depending on breakpoint): caps/spend summary (wired where available; placeholder otherwise).
9. **Workers** (full-width at smaller breakpoints): worker status list (reuse existing worker components where available).

## Design system & tokens

### Token principles

- **Single source of truth**: tokens live in `dashboard/web/src/index.css`.
- **CSS variables first**: all semantic colors are CSS variables, referenced by Tailwind theme variables.
- **Layered surfaces**: explicit surface tokens for background elevation, rather than arbitrary hex usage in components.
- **Ink ladder**: use `--ink` → `--ink-5` consistently for text hierarchy.
- **Accents**:
  - Cyan is the only “action accent” (primary buttons, active indicators).
  - Violet is used for secondary differentiation (non-semantic), never for error/success/warn.

### Canonical token set (aligned to `finalized.html`)

Surfaces:

- `--canvas`, `--canvas-2`
- `--panel`, `--panel-2`, `--panel-3`

Borders:

- `--hairline`, `--hairline-2`, `--hairline-3`

Ink ladder:

- `--ink`, `--ink-2`, `--ink-3`, `--ink-4`, `--ink-5`

Accents:

- `--acc`, `--acc-dim`, `--acc-bg`, `--acc-line`
- `--vio`, `--vio-dim`

Semantic:

- `--ok`, `--ok-dim`
- `--warn`, `--warn-dim`
- `--bad`, `--bad-dim`

Typography:

- `--f-display` (Inter Tight preferred), `--f-body` (Inter), `--f-mono` (JetBrains Mono)

Spacing/radius:

- Radius tokens: `--rad-chip`, `--rad-btn`, `--rad-card` (and any necessary additions)
- Prefer Tailwind spacing utilities; introduce a spacing scale only if needed for 1:1 match.

### Tailwind v4 mapping

Continue using the `@theme` section to map:

- `--color-canvas` → `var(--canvas)`
- `--color-panel` → `var(--panel)`
- `--color-ink-*` → ink ladder
- `--color-accent` → `var(--acc)` and add secondary mapping for violet where needed
- `--color-success|warning|danger` → ok/warn/bad
- `--radius-*` → radius tokens

This preserves existing utility usage while changing the underlying aesthetic.

## Component design (high level)

### Layout primitives

- **Canvas grid**: 12-column responsive grid container for the Home page.
- **Panel primitive**: a consistent panel shell (header + body) used across funnel, distribution, tables, etc.
- **Chips**: small toggle-able filters with selected state.
- **Icon buttons**: compact icon-only actions with hover surfaces.
- **Buttons**: primary (accent), secondary (neutral), danger.

### App shell components mapping

- `NavRail` → match rail sizing, hover, active indicator, and icon styling from the finalized design.
- `HeaderStrip` → evolve into a header with:
  - crumb (“ApplyPilot / Mission Control”)
  - command search affordance (initially visual-only)
  - right-side live indicators + avatar

### Home composition mapping

- `HomeRunBar` / `RunBanner` / `PhaseStepper` / `StageControlBar` (existing) will be visually composed into the **Run band hero**. Behavior remains: stop run, show current stage, show run id, etc.
- `StatsRow` becomes the **KPI row** (6 cards).
- `JobsTable` becomes the “Top opportunities” table (restyled).
- Log/feed components become the activity panel (restyled; preserve “autoscroll near bottom only” behavior).
- Worker components become the workers panel (restyled).

## Behaviors & UX requirements (preserve)

- **Single scroll region**: main content scrolls in `<main>`; avoid nested scroll containers that trap scroll.
- **Live logs autoscroll**: auto-scroll new lines only if user is already near the bottom.
- **Jobs table**: defaults to newest-first with dates visible per row (existing expectation).
- **Drawer**: right drawer remains functional and accessible.

## Secondary pages (Mission Control / Apple parity) — scope added 2026-05-27

Home is the reference implementation: classes and tokens ported from `finalized.html` in `dashboard/web/src/index.css`, plus shell components (`NavRail`, `HeaderStrip`, `DashboardLayout`). **All routed dashboard pages must match the same principles** — not necessarily duplicate every Home-only block (runband, KPI row), but share the **same typography, surfaces, spacing rhythm, panels, chips, buttons, tables, and focus/focus-visible treatment**.

### In scope (primary routes from `App.tsx`)

1. **`JobsExplorerPage`**
   - Wrap the page body in the same canvas/panel vocabulary as Home (e.g. `.panel`, `.panel__head`, `.panel__title`, table region with hairline borders and consistent padding).
   - Filters: chip styling aligned with `Chip` / finalized chip classes; toolbars use ink ladder (`--ink-2` / `--ink-3` labels, `--mono` for counts).
   - Preserve virtualization, URL-synced filters, and row interactions; avoid new nested scroll areas inside `<main>`.

2. **`ApplyPage`**
   - Status/worker/log blocks become panel shells with the same heads and subtitles as finalized table sections.
   - Primary actions remain obvious (accent `--acc`); destructive/secondary actions use neutral surfaces, not one-off hex colors.

3. **`AppliedApplicationsPage`**
   - Applications table + filters: same panel + chip patterns as Jobs; audit/status badges map to semantic tokens (`--ok`, `--warn`, `--bad`) with text labels, not color-only.

4. **Shared overlays**
   - **`RightDrawer`**: surfaces, widths, shadows, borders, and header typography consistent with finalized panels (not a legacy gray card).
   - **Modals** (e.g. `RunPlanModal`): backdrop + modal card use the same `--surface*` stack and radius tokens.

### Out of scope (unless product adds routes)

- **`StagePipelinePage`**, **`InboxPage`**: not mounted in `App.tsx` today — defer restyling until they are part of IA; optionally delete or consolidate later to avoid drift.

### Consistency checklist (per page, before marking done)

- [ ] No stray legacy Tailwind grays that fight `--bg` / `--surface` ladder.
- [ ] Section titles use display/body ladder per finalized patterns.
- [ ] Interactive hit targets and focus rings match shell behavior.
- [ ] Empty and loading states match Home placeholder policy (stable layout, honest copy).

## Placeholder / empty state policy (approved)

If a panel has no backing data:

- Show a professional empty state (no demo numbers).
- Prefer one-liners like “No data yet” + a hint at what enables it (“Run a pipeline to populate this panel.”).
- Keep layout stable so wiring later doesn’t require redesign.

## Accessibility

- Maintain semantic landmarks: `nav`, `header`, `main`.
- Interactive elements have visible focus states consistent with accent tokens.
- Do not rely on color alone for status; include labels/icons where feasible.

## Testing strategy (UI-focused)

- Visual regression is out of scope unless already present, but we should validate:
  - Layout does not introduce nested scrolling regressions.
  - Navigation still works across **home, jobs, apply, applications**.
  - Existing pages render with the new tokens without unreadable text.
  - Drawer and modals retain keyboard focus trap and legible contrast on all pages.

## Rollout plan

1. Introduce tokens and Tailwind mappings (no layout changes).
2. Update app shell (rail/header) to Mission Control styling.
3. Redesign Home page into the finalized composition (done — keep as reference).
4. **Apply secondary-page parity** (`JobsExplorerPage`, `ApplyPage`, `AppliedApplicationsPage`, `RightDrawer`, modals): reuse Home’s class system and tokens; no behavioral regressions.
5. Backend/API wiring for Home panels (`/api/overview`, activity stream, workers) proceeds per engineering plan; secondary pages continue to use existing endpoints unless a panel explicitly needs aggregation.

