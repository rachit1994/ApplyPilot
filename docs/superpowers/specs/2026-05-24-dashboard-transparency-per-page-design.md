# Dashboard transparency & control — per-page design

**Status:** Approved for implementation (May 2026)  
**Audience:** Single local operator running ApplyPilot  
**Aligns with:** [dashboard-redesign-requirements-may-2026.md](../../dashboard-redesign-requirements-may-2026.md)

## Principles

Every page answers without the CLI:

1. What is running right now?
2. What will happen if I click Run?
3. What changed in my database?
4. What needs my attention?

Three modes: walk-away (big numbers + caps), watch (sub-steps + logs), triage (row actions).

## Information architecture

| Page | Purpose |
|------|---------|
| Home | Mission control, health numbers, needs-you banners, stage shortcuts |
| Discover … PDF | One cockpit per pipeline stage; run only that stage |
| Apply | Ledger, ghosts, apply run control, worker visibility |
| Inbox | LinkedIn Other-tab ranked queue + scan/send actions |

Persistent chrome: header caps (applies, spend, unverified, workers), global Stop, right drawer for job/application audit.

## Shared chrome

- **Caps strip:** applied today, needs verification (`submitted_unverified`), ready queue, LLM spend today, active workers.
- **Global Stop:** confirms, calls `POST /api/runs/{id}/stop`.
- **Right drawer:** job fields + application log snapshot + confirm/retry when applicable.

## Home

- Hero metrics with links to Apply (unverified filter) and stages.
- Needs-you stack: unverified count, failed run, other stage running.
- Stage cards: pending count, running badge, last run hint.
- Active run snippet with latest `stage_progress` detail.

## Per-stage pages

Layout: Timeline → Run plan → Now → Progress → Queue toggle + Jobs | Logs.

- **Run plan:** preview counts and CLI equivalent before confirm.
- **Now:** latest `stage_progress` detail; discover shows per-source grid from `source_progress` events.
- **Progress:** percent bar from SSE payloads.
- **Jobs:** filter to stage by default; drawer on click.

## Apply page

- Run controls: limit, min score, workers, watch/pace/headless/continuous/dry-run.
- Status counters from stats pipeline.
- Applications ledger: newest first, confirm/retry for `submitted_unverified`, expandable detail with form snapshot.
- Worker chips from `worker_heartbeat` events parsed from apply logs (phase 3).

## Inbox page

- `GET /api/inbox/queue` — ranked threads.
- `POST /api/inbox/run` — scan | classify | send | pipeline (subprocess).
- Connection status via existing OpenOutreach health pattern where relevant.

## Backend contracts

- `POST /api/runs` with `run_type: "apply"` spawns `applypilot apply` subprocess (same as pipeline).
- `source_progress` events during discover from unified runner.
- `worker_heartbeat` events from apply log line parsing in run controller.

## Phased delivery

1. **Phase 1:** Apply nav/page, Home hero, stage progress UI, header caps, applications ledger.
2. **Phase 2:** Run plan modal, discover source panel, rich drawer, global stop wiring.
3. **Phase 3:** Apply run from dashboard, inbox API/UI, worker chips.

## Out of scope

- Referrals page, Sites/warmers, Profile/searches forms, dedicated run history page.
