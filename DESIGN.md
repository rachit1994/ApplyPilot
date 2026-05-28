# ApplyPilot Design System

Generated from `/design-html` · 2026-05-27 · scope: full app (six pages)

## Philosophy

Apple-inspired, end-user focused. The job seeker doesn't open ApplyPilot to admire metrics. They open it to know **what changed, what to do next, am I winning**. Every page is designed around that question.

- Two colors total: neutral graphite ladder + iOS blue (#0A84FF)
- Numbers as plain English: "12 new jobs match you" not "Total jobs: 12"
- One primary action per page
- Power-user complexity (pipeline math, source stats, throughput, caps) lives in a dedicated Pipeline tab, off the main flow
- Status differentiation through shape (filled dot, hollow ring, opacity) not extra color
- Sidebar icons always have labels (Today, Jobs, Apps, Inbox, Pipeline, Settings)

## Page model

| Page | Purpose | Layout |
|---|---|---|
| **Today** | Morning brief — what changed, what to do next | 3 summary cards, next-action callout, current run, yesterday recap |
| **Jobs** | Triage inbox — apply / save / skip | Two-pane: list + detail (Mail-style) |
| **Apps** | What's been sent — callbacks at the top | Pinned callbacks band + grouped list |
| **Inbox** | Recruiter replies + suggested replies | Two-pane: list + message view |
| **Pipeline** | Pro view — agent internals | Run band + funnel + sources + caps |
| **Settings** | Tune the agent | iOS-Settings-style grouped row cards |

## Color tokens

```
--bg:        #000000
--surface:   #1c1c1e
--surface-2: #2c2c2e
--surface-3: #3a3a3c

--hair:      rgba(255,255,255,0.06)
--hair-2:    rgba(255,255,255,0.10)
--hair-3:    rgba(255,255,255,0.16)

--ink:       #f5f5f7
--ink-2:     #d1d1d6
--ink-3:     #8e8e93
--ink-4:     #636366
--ink-5:     #48484a

--acc:       #0a84ff
--acc-2:     #409cff
--acc-dim:   rgba(10,132,255,0.16)
--acc-line:  rgba(10,132,255,0.32)
--acc-glow:  rgba(10,132,255,0.40)
```

Accent is reserved for: primary buttons, the "live" pulse, active state, score on the top-tier job, callbacks pinned band, suggested-reply box. Everything else is the neutral ladder.

## Typography

```
--display: 'Inter Display', 'SF Pro Display', system-ui   500 / 600 / 700
--body:    'Inter', 'SF Pro Text', system-ui              400 / 500 / 600
--mono:    'JetBrains Mono', 'SF Mono'                    400 / 500
```

- Body 14px, line-height 1.5, letter-spacing -0.005em
- Display headers -0.015 to -0.025em tracking (bigger = tighter)
- Numerals always `font-variant-numeric: tabular-nums`
- Big summary numbers: 40px display weight, -0.035em
- Page greeting: 22px display, -0.025em

## Spacing & radius

```
sidebar width:   84px
panel radius:    14px
runband radius:  16px
button radius:   10px
chip radius:     999px (pill)
canvas padding:  32px 32px 64px (max-width 1200px, or 1480px for wide pages)
panel head pad:  18px 22px
panel body pad:  18px 22px
grid gap:        14–22px
```

## Components

- **Sidebar button** — 8px padding, 22px icon on top, 10.5px label underneath. Active = surface background + hairline-2 border. Notification badge top-right.
- **Header** — 18px padding, blurred backdrop. Greeting + sub-line on left. Search + bell + avatar on right.
- **Summary card (Today)** — 22×24 padding, icon chip top-left, 40px count, 15px label, 13px sub, CTA row at bottom. Hover lifts 1px.
- **Next-action callout** — gradient blue background, 48px icon chip, title + sub, accent button on right.
- **Job row** — 44px logo + title + meta + score + age, 3px accent strip when selected.
- **Job detail pane** — logo + title + facts grid + "Why ApplyPilot picked this" paragraph + action row (Skip / Save / Apply).
- **Application row** — 36px logo + title/company + date + status + chevron. Callbacks band uses gradient blue background.
- **Inbox message row** — from + time + subject + 1-line preview. Unread = leading blue dot + blue tint.
- **Settings group** — bordered card containing rows. Each row = title + sub on left, value or toggle or chevron on right. iOS-style.
- **Toggle** — 40×22 pill, 18px thumb, accent fill when on.
- **Segment** — pill-grouped button bar, active button gets surface fill + shadow.
- **Chip** — pill, 6×13 padding, neutral by default, accent fill when selected.

## Layout breakpoints

- ≥1280px: full multi-pane layouts (jobs list+detail, inbox list+detail, pipeline 3-col)
- 1024–1280px: pipeline collapses to 2-col, jobs hides detail pane (use selection drawer instead)
- ≤1024px: all panes stack, runband stacks vertical, stepper wraps
- ≤768px: rail compresses to 72px, header wraps, today hero stacks 1-col

## Don'ts

- No additional accent colors (green/amber/red are off-limits)
- No phosphor / neon glow on the accent
- No dot-grid or hatched backgrounds
- No color-coded score pills with multiple tiers — accent for the top, neutral bold for the rest
- No metric dashboards on the default page — that's the Pipeline tab's job
- No uppercase mono labels with wide letter-spacing as the dominant label style — use sentence case
- No bare numbers as page content without a verb or noun attached
