# ApplyPilot redundancy report

Generated: 2026-06-08 (updated same day — second pass)  
Method: Four parallel codebase audits (initial), then **three parallel re-audits** after Postgres migration and a stuck-pipeline incident (Python/schema/server, live dashboard runtime, tests/docs/onboarding).

This report covers **unused files**, **partially dead files** (redundant code inside live modules), and **duplicate logic** across modules. Percentages are estimates based on import graphs, grep, and line counts — not formal dead-code analysis.

**Canonical worker docs:** [`worker-deterministic-apply-handbook.md`](worker-deterministic-apply-handbook.md) and files it references (see §11).

---

## Executive summary

| Area | Total LOC (approx.) | Fully dead / unreachable | Partial redundancy inside live files | Duplicate logic across modules |
|------|---------------------|--------------------------|--------------------------------------|--------------------------------|
| `src/applypilot/` (Python) | ~53,000 | ~0.5% (~200 LOC) | ~1–2% (~400–700 LOC) | ~2–3% (~800–1,200 LOC recoverable) |
| `dashboard/web/src/` | ~18,500 | **~30% (~5,600 LOC)** | ~2% (~350–550 LOC) | ~180–220 LOC (run hooks alone) |
| `tests/` | ~17,500 | ~0.8% (142 LOC) | ~1.2% fixture boilerplate | ~0.7% overlapping role-resume tests |
| `scripts/` | ~855 | ~35% strong delete candidates | — | ~40–90% overlap with CLI per script |
| `docs/` | ~13,800 | — | — | **~4–5k LOC** overlapping clusters |

**Bottom line:** The largest win is still the **unmounted dashboard subtree** (~5,600 LOC, ~33% of frontend). **New critical debt:** **21 pytest files fail collection** after Postgres migration (§13.1). Python production code is relatively lean; redundancy is mostly **parallel implementations** (unblock vs actions, view vs server, stage pipeline vs overview dashboard, TS vs Python stage predicates, dual jobs column registries).

---

## How redundancy was classified

| Status | Meaning |
|--------|---------|
| **Fully dead** | No path from entry points (`cli.py`, `server/app.py`, `main.tsx` → `App.tsx`, pytest for production modules). ~100% of file is redundant. |
| **Legacy wired** | Reachable only via deprecated CLI/manual script; superseded by newer surface. ~65–100% redundant in product terms. |
| **Partially redundant** | File is active but contains dead exports, unreachable branches, or duplicated blocks. % = estimated redundant lines within file. |
| **Duplicate logic** | Same behavior implemented in 2+ places; consolidation would remove N lines without losing features. |

---

## 1. Python backend (`src/applypilot/`)

### 1.1 Fully dead files (100% redundant)

| File | LOC | Why | Replacement |
|------|-----|-----|-------------|
| `apply/direct/actions.py` | 194 | Self-learning dispatch table from `docs/scaled-self-learning-apply-plan.md` (T1). Never wired; only `tests/test_actions.py` imports it. Production uses `unblock._execute` + `unblock_learning`. | Wire into unblock stack **or** delete with test file. |
| `tests/test_actions.py` | 142 | Sole consumer of dead `actions.py`. | Delete with `actions.py`. |

**Subtotal:** ~336 LOC, **100% dead**.

### 1.2 Legacy wired (superseded but still callable)

| File | LOC | Redundant % | Why | Replacement |
|------|-----|-------------|-----|-------------|
| `view.py` | 406 | ~65–75% | Static `~/.applypilot/dashboard.html`. Duplicates KPI SQL from `server/stats.py`. | `applypilot serve` + React dashboard. Still: `cli.py` → `applypilot dashboard`. |
| ~~`db/migrate_sqlite.py`~~ | — | **Removed** | File deleted after Postgres cutover; report row was stale. | Use `applypilot db migrate-sqlite` / `db init` if still needed; drop references. |

### 1.3 Partially redundant within active files

| File | LOC | Redundant % | What’s redundant | Consolidation target |
|------|-----|-------------|------------------|----------------------|
| `apply/direct/unblock.py` | ~450 | ~18% (~80 LOC) | `_execute` mirrors dead `actions.execute()` | Single `actions.execute` dispatcher |
| `apply/direct/unblock_learning.py` | ~500 | ~7% (~35 LOC) | `_state_advanced` ≈ `actions.detect_advanced` | Same |
| `apply/direct/playbook.py` | ~500 | ~3% | `SIDE_EFFECTING_ACTIONS` overlaps `actions` vocab | Import from one module |
| `apply/direct/adapters/__init__.py` | ~45 | ~5% | Empty `_STAGED = {}`; stale comment (Lever/Ashby “not dispatched” but they are in `_REGISTRY`) | Fix comment; remove dead dict |
| `apply/launcher.py` | 3,467 | ~1% (~35 LOC) | `mark_result` / `mark_prepare_review` duplicate log-read → `form_filled` block | `_extract_log_artifacts(log_path)` |
| `server/stats.py` | ~200 | ~15% conceptual | KPI queries overlap `view.py` | Already superseded by server APIs |
| `server/referrals.py` | ~300 | ~35% structural | Same orchestrator wiring as `outreach/pipeline.py` | Shared referral helper module (~80–100 LOC) |
| `scoring/filter_stage.py` | 134 | ~25–30% | Thin wrapper around `pre_score_filter` | Acceptable stage boundary; optional inline |
| `role_resumes.py` | 3,900 | ~2% (~75 LOC) | `_remoteok_jobs`, `_remotive_jobs`, `_jobicy_jobs` duplicate `discovery/feeds/*` fetchers | Import from discovery feeds |

**Estimated recoverable in active Python:** ~400–700 LOC (~1–2% of backend).

### 1.4 Cross-module duplicate logic (Python)

| Cluster | Files involved | ~Dup LOC | Recommended consolidation |
|---------|----------------|----------|---------------------------|
| **Unblock dispatch** | `actions.py`, `unblock._execute`, `unblock_learning`, `playbook` | 90–120 | `actions.execute` as sole browser primitive; unblock maps outcomes for Gemini loop |
| **Apply URL resolution** | `launcher._resolve_job_apply_url`, `enrichment/detail.py`, `jobspy.py`, `apply_url_extract.py` | 40–72 | `apply/apply_url_resolve.py` with `resolve_apply_url(job, persist=)` |
| **URL naming confusion** | `visit_ledger.canonical_apply_url` vs `driver._canonical_apply_url` | — | Rename driver helper to `navigation_apply_url` |
| **Pipeline stage predicates** | `pipeline._PENDING_SQL`, `role_resumes` tailor SQL, `cover_letter.py`, `database.get_jobs_by_stage`, `server/job_pipeline_stage.py` | 80–100 | `pipeline/stage_predicates.py` single registry |
| **CLI argv assembly** | `run_controller.start_apply_run`, `start_pipeline_run` vs dashboard TS builders | 55–70 | `orchestration/cli_argv.py`; optional `/api/runs/cli-preview`. **Partial fix (2026-06-08):** `_resolve_cli()` now uses `[sys.executable, "-m", "applypilot"]` (was Homebrew `applypilot` without `psycopg`). TS argv builders still duplicate Python. |
| **Referral surfaces** | `server/referrals.py`, `outreach/pipeline.py`, `cli refer` | 80–100 | Shared eligibility + orchestrator wiring |
| **Application list rows** | `server/applications.py` duplicate `form_filled` / resume path blocks | ~25 | `_normalize_application_row(row)` |

**Not audited at function level:** `launcher.py`, `driver.py`, `cli.py` (2,073 LOC), `smartextract.py` — likely contain additional dead branches.

---

## 2. Dashboard frontend (`dashboard/web/src/`)

**Live graph:** `main.tsx` → `App.tsx` → 7 pages + layout shell.

### 2.1 Fully dead files (~5,633 LOC, ~30% of `src/`)

#### Unmounted pages

| File | LOC | Why | Replacement |
|------|-----|-----|-------------|
| `ApplicationsPage.tsx` | ~90 | Not routed | `AppliedApplicationsPage.tsx` |
| `ApplyPage.tsx` | 262 | Not routed | `AppliedApplicationsPage` + `PipelineDashboardPage` |
| `InboxPage.tsx` | 165 | ~95% duplicate of outreach | `OutreachDashboardPage.tsx` |
| `StagePipelinePage.tsx` | ~280 | Per-stage pipeline replaced | `PipelineDashboardPage.tsx` |
| `HomeRunBar.tsx` | ~260 | Old home run strip | Inline run band in `HomePage.tsx` |

#### Orphan component tree (only used by dead pages)

| File | LOC | Only used by |
|------|-----|--------------|
| `ControlBar.tsx` | ~80 | *(none)* |
| `StatsRow.tsx` | ~90 | *(none)* |
| `PriorityBoardsBanner.tsx` | ~40 | `StatsRow` |
| `JobsTable.tsx` | 251 | `StagePipelinePage` |
| `RunBanner.tsx` | ~50 | `StagePipelinePage` |
| `StageControlBar.tsx` | ~80 | `StagePipelinePage` |
| `PhaseStepper.tsx` | ~195 | `StagePipelinePage` |
| `ApplicationRow.tsx` | ~120 | `ApplicationsPage` |
| `LogConsole.tsx` | ~180 | dead apply/home/stage pages |
| `LogLine.tsx` | ~130 | `LogConsole` |
| `pipeline/TimelineRibbon.tsx` | ~390 | `StagePipelinePage` |
| `pipeline/NowPanel.tsx` | ~80 | `StagePipelinePage` |
| `pipeline/DiscoverSourcePanel.tsx` | ~60 | `StagePipelinePage` |
| `pipeline/QueuePanel.tsx` | ~200 | *(never wired)* |
| `pipeline/WorkerChip.tsx` | ~50 | *(never wired)* |
| `pipeline/statusChip.tsx` | ~40 | `WorkerChip` |

**Pipeline subtree subtotal:** ~1,160 LOC.

#### Dead hooks, utils, CSS, UI primitives

| File | LOC | Why |
|------|-----|-----|
| `hooks/useStageRun.ts` | ~180 | Only `StagePipelinePage` |
| `utils/stageProgress.ts` | ~120 | Stage pipeline only |
| `utils/stageCounts.ts` | ~50 | Stage pipeline only (`stagePendingLabel` unused) |
| `utils/jobsTableColumns.ts` | 221 | Zero importers |
| `finalized-parity.css` | 1,022 | Never imported; tokens in `index.css` |
| `ui/chip.tsx`, `ui/icon-button.tsx` | ~60 | Zero importers |
| `ui/badge.tsx`, `ui/button.tsx`, `ui/card.tsx`, `ui/input.tsx`, `ui/select.tsx` | ~200 | Only dead components import them |

### 2.2 Partially redundant live files

| File | LOC | Redundant % | What’s redundant |
|------|-----|-------------|------------------|
| `HomePage.tsx` | ~520 | ~25% | Devlog UI duplicates dead `LogConsole` (~85% same behavior) |
| `PipelineDashboardPage.tsx` | ~280 | ~20% | Runband/stepper overlaps `HomePage` run-card |
| `JobsExplorerPage.tsx` | ~400 | ~5% | Dual job detail: `JobDetailPane` + `RightDrawer` via `onJobSelect` |
| `JobDetailPane.tsx` | 130 | ~30% | Overlaps `RightDrawer` job section |
| `RightDrawer.tsx` | ~150 | ~50% | Application branch never opened (`App.tsx` never sets `selectedApplication`) |
| `App.tsx` | ~320 | ~5% | Dead application drawer path |
| `VirtualScroll.tsx` | ~100 | ~45% | `VirtualGrid` only used by dead `JobsTable` |
| `index.css` | 2,598 | ~35% | Legacy selectors for dead components + duplicated parity tokens |
| `api.ts` | ~800 | ~10% (~120 LOC) | 8 unused fetchers/types (see below) |
| `dashboardNav.ts` | ~120 | ~15% | `jobMatchesStage`, `filterEventsForStage` only for dead stage page |
| `format.ts` | ~80 | ~65% | `formatDuration`, `runDuration`, `formatTime` unused in live graph |
| `logLevel.ts` | ~40 | ~20% | `isLogError` only via dead `LogConsole` |
| `applicationAudit.ts` | ~200 | ~7% | `statusChipClass` unused |
| `jobPipeline.ts` | ~80 | ~17% | `stageBadgeClass` unused |
| `sitePriority.ts` | ~60 | ~25% | `APPLY_QUEUE_ORDER_LABEL`, `PRIORITY_BOARD_NAMES` unused |

#### Unused `api.ts` exports (live graph)

| Export | Status |
|--------|--------|
| `fetchApplyErrorSummary`, `fetchAttentionApplications` | No UI consumer |
| `fetchReferrals`, `postReferralAction` | Outreach uses inbox API, not referral REST |
| `fetchRecentJobs`, `fetchSourceStats` | Dead pages only |
| `fetchPendingLogins`, `postResumeLogin` | Dead `ApplyPage` only |
| Types: `PipelineStageFilter`, `PendingLogin`, `Referral*`, `ApplyErrorGroup` | Dead-only |

### 2.3 Duplicate patterns (live vs dead)

| Pattern | Active | Dead duplicate | Overlap |
|---------|--------|----------------|---------|
| Dev log panel | `HomePage` + `devlog.ts` (~130 LOC UI) | `LogConsole` + `LogLine` (~309 LOC) | ~85% |
| Applications list | `AppliedApplicationsPage` (891 LOC) | `ApplicationsPage` + `ApplicationRow` (293 LOC) | 100% dead side |
| Job table model | `JobsExplorerPage` inline rows | `JobsTable` + `jobsTableColumns.ts` (~472 LOC) | ~470 LOC parallel column/stage model |
| Run status UI | Home run-card + Pipeline runband | `PhaseStepper`, `RunBanner`, `HomeRunBar` | ~150 LOC |
| Inbox/outreach | `OutreachDashboardPage` | `InboxPage` | ~95% |
| Run plan modals | `RunPlanModal` ← `ApplyRunPlanModal` / `PipelineRunPlanModal` | Same modals imported by dead pages | **Shell is correct** — keep |

### 2.4 Cross-hook duplication (highest-impact frontend refactor)

| Hook | Overlapping concern | ~Dup LOC |
|------|-------------------|----------|
| `useStageRun.ts` | SSE append, 10s poll, events cap, refresh | ~95 |
| `useHomeRuns.ts` | Same + history merge | ~110 |
| `useApplyRun.ts` | Same + apply settings + throttled invalidation | ~100 |
| `useRunLiveRefresh.ts` | Second SSE subscription for same run | ~35 |

**Consolidation target:** `useRunSession.ts` (parameterized by run type) → thin wrappers. **~180–220 LOC recoverable.**

### 2.5 UI helper duplication in live components

| Helper | Duplicated in | Fix |
|--------|---------------|-----|
| `formatWhen` | `ApplicationRow`, `RightDrawer`, `applyRunState.ts` | Use `applicationAudit.formatWhen` |
| Requeue / status chips | `ApplicationRow` (dead) bypasses audit utils | Live pages already use `ApplicationRowActions` |
| `resolvedFormFields` | Dead `ApplicationRow` reads raw `log_detail` | Live path uses `formFilled.ts` |

---

## 3. Tests (`tests/`)

| Item | LOC | Redundant % | Why |
|------|-----|-------------|-----|
| `test_actions.py` | 142 | **100%** | Tests unwired `actions.py` |
| `temp_db` fixtures (11 files) | ~220 | **100% maintenance dup** | Duplicate `conftest.py` `isolated_db` pattern |
| `test_role_resumes.py` + `test_role_aware_scoring.py` | 2,159 | ~0.7% overlap | Both test role-resume resolution; trim scoring file to scoring-only paths |
| Playbook doc-contract tests (6 files) | — | ~0.5% | Repeated `worker-apply-playbook.md` RESULT line checks |
| `test_role_resumes.py` size | 1,600 | Oversized, not dead | Optional split by concern |

**Fixtures (keep):** `apply_ghost/*.txt`, `workday_*.html` — active, right-sized.

---

## 4. Scripts (`scripts/`)

| Script | LOC | Redundant vs CLI | Recommendation |
|--------|-----|------------------|----------------|
| `dashboard_serve_daemon.sh` | 6 | **~95%** | Use `applypilot serve-daemon` |
| `probe_page.py` | 38 | **~100%** undocumented | Merge into `direct_dryrun` or CLI debug subcommand |
| `driver_smoke.py` | 51 | **~70%** vs `direct_dryrun.py` | Delete; use `direct_dryrun` or `apply --dry-run` |
| `direct_dryrun.py` | 105 | **~40%** vs `applypilot apply --dry-run` | Keep for visible Chrome + role-resume path |
| `run_inbox_job_replies.py` | 36 | **~90%** | Use `applypilot inbox run` |
| `test_inbox_send_one.py` | 100 | **~85%** | Dev scratch only |
| `overnight_pipeline_apply.sh` | 74 | **~60%** | Document CLI daemon pattern |
| `apply_overnight_daemon.sh` | 42 | **~50%** | Restart loop only; optional keep |
| `run_workatastartup.py` | 239 | **~30%** | Manual WaaS runner; OK |
| `linkedin_harvest.py` | 52 | **~25%** | Discover config can run same source |
| `login_resume.py`, `clean_db.py`, `pipeline_stage_snapshot.py` | 112 | **Keep** | Documented runbooks, no CLI equivalent |

**Strong delete/consolidate candidates:** ~370 LOC (~35% of scripts/).

---

## 5. Documentation (`docs/`)

Documentation redundancy is **narrative overlap**, not dead code. Estimated **~4–5k LOC** across clusters:

| Cluster | Approx. LOC | Overlap | Keep |
|---------|-------------|---------|------|
| Worker deterministic trilogy | ~1,500 | ~40% | Handbook + ledger + playbook; archive implementation plan |
| Self-learning architecture stack | ~920 | ~45% | Handbook for ops; architecture as rationale only |
| Dashboard redesign stack | ~2,700 | ~50–60% if shipped | `DESIGN.md` + finalized brief; archive superpowers specs |
| Apply incident trilogy (May 2026) | ~1,715 | ~30% | Keep hang fix; merge ghost/autonomy into playbook |
| Pipeline runbooks | ~403 | ~25% | `pipeline-stages.md` + verification checklist |

### Docs referencing unbuilt code

| Planned module | Referenced in | Actual |
|----------------|---------------|--------|
| `discovery/linkedin_resolve.py` | `maxed-apply-pipeline-jun-2026.md` | Does not exist |
| `apply/direct/humanize.py` | maxed pipeline, direct-apply-architecture | Does not exist — use `throttle.py` |
| Wired `actions.py` | scaled-self-learning-apply-plan | Built but unwired |
| `docs/STATUS-BOARD.md` | IMPLEMENTATION-PLAYBOOK | File missing |
| QueuePanel / WorkerChip | EM-INTEGRATION | Never wired in React |

### Design artifacts

| Path | Status |
|------|--------|
| `docs/dashboard-mockups/variant-A-mission-control.html` | Static mockup only |
| `docs/dashboard-mockups/variant-B-calm-operator.html` | Static mockup only |

---

## 6. Config and root files

| Path | Redundant? | Why |
|------|------------|-----|
| `config/watchlist.generated.yaml` | **~100% unused** | Code loads `~/.applypilot/watchlist.yaml` or `src/applypilot/config/watchlist.example.yaml` |
| `config/inbox.example.yaml` | **Misplaced** | Loader expects `src/applypilot/config/inbox.example.yaml` (missing); repo-root copy never read |
| `role_resumes/` | **Active** (not dead) | Default `ROLE_RESUME_DIR`; PDFs often missing in repo (stale manifest risk, not unused) |
| `WORKER_BRIEF_INDIA_FIRST.md` | ~35% vs `docs/india-source-map.md` | Strategy overlap; keep one entry point |
| `job-search-effectiveness-2026.md` | **~100% orphan** | Zero in-repo references |
| `technical-job-discovery-improvements-2026.json` | **~100% orphan** | ~7.5k LOC; zero imports (§13.7) |
| `linkedin-other-inbox-automation-gaps.json` | **~100% orphan** | ~3k LOC; zero imports |
| `job-workflow-may-2026.json` | **~100% orphan** | Markdown twin deleted; JSON at repo root unused |
| `high-paying-react-node-python-jobs-jun-2026.json` | **~100% orphan** | Zero imports |

---

## 7. Priority consolidation matrix

| Priority | Action | LOC impact | Risk |
|----------|--------|------------|------|
| **P0** | Fix **21 pytest collection errors** (Postgres migration leftovers; §13.1) | **0 LOC deleted — unblock CI** | Low — mechanical fixture rewrites |
| **P0** | Delete dead dashboard subtree (§2.1) | **~5,600** | Low after visual QA on live pages |
| **P0** | Extract `useRunSession.ts` from 3 run hooks | **~180–220** | Medium — test all run flows |
| **P1** | Delete `actions.py` + `test_actions.py` OR wire actions | **~336** | Low if not shipping self-learning T1 |
| **P1** | Unify `actions.execute` / `unblock._execute` | **~90–120** | Medium — apply unblock path |
| **P1** | `stage_predicates.py` + contract test TS ↔ Python | **~80–100+** | Medium — jobs API filters |
| **P1** | Unify `JOBS_EXTRA_COLUMNS` + `_ALL_COLUMNS` (§13.2) | **~0 user-facing — prevents schema drift** | Medium |
| **P1** | Dedupe overview/stats SQL + client polling (§13.4–13.5) | **~60–120 BE + fewer HTTP calls** | Medium |
| **P1** | Single active-run poll + SSE (`useRunSession` / React Query) | **~180–220 FE** | Medium |
| **P1** | `cli_argv.py` + fix pipeline `--validation` drift | **~55–70** | Low |
| **P2** | Retire `view.py` + `applypilot dashboard` CLI | **~406** | Low after doc update |
| **P2** | Trim `api.ts` dead exports | **~120** | Low |
| **P2** | Consolidate scripts (§4) | **~370** | Medium — verify personal ops |
| **P2** | `apply_url_resolve.py`, launcher log artifacts | **~75–110** | Low |
| **P3** | Archive overlapping doc clusters | **~4–5k docs** | Low |
| **P3** | Consolidate `temp_db` pytest fixtures | **~220 maintenance** | Low |
| **P3** | Fix `inbox.example.yaml` path | 0 (bug fix) | Low |

---

## 8. Estimated total recoverable

| Category | LOC |
|----------|-----|
| Dead dashboard files + parity CSS + dead UI primitives | **~5,600–6,200** |
| Dead Python + tests (`actions` cluster) | **~336** |
| Legacy `view.py` (optional) | **~406** |
| Partial redundancy inside live files (FE + BE) | **~750–1,250** |
| Cross-module duplicate logic (if fully consolidated) | **~800–1,200** |
| Scripts | **~370** |
| **Code subtotal (conservative)** | **~7,500–9,500** |
| Documentation archive (optional) | **~4,000–5,000** |

As a share of **production code** (Python + dashboard TS/CSS, ~72k LOC): **~10–13%** is dead or strongly consolidatable without changing product behavior.

---

## 9. What is NOT redundant (do not delete)

Recent/active paths verified during audit:

- `job_log.py`, `server/artifacts.py`, `server/runtime.py`, `server/daemon.py`
- `db/schema.py` → `sync_serial_sequences()` (live; fixes BIGSERIAL drift after SQLite→Postgres import — not redundant)
- `scoring/tailored_cleanup.py`, `utils/devlog.ts`, `artifacts.ts`, `pipelineRunPlan.ts`
- `PipelineRunControls.tsx`, `FormValuesModal.tsx`, `ToggleSwitch.tsx`, `StopSquareIcon.tsx`
- `RunPlanModal` / `ApplyRunPlanModal` / `PipelineRunPlanModal` (layered, not duplicates)
- `role_resumes/` runtime tree (regenerate PDFs, don’t delete)
- `db/` package (active via `database.py`, `inbox/db.py`)
- `launcher.py`, `driver.py`, `pipeline.py`, discovery/scoring modules on hot paths
- Test fixtures: `workday_*.html`, `apply_ghost/*.txt`
- Scripts: `login_resume.py`, `clean_db.py`, `pipeline_stage_snapshot.py`, `direct_dryrun.py`

---

## 10. Suggested execution phases

**Phase A — Safe deletes (~6k LOC):** Dead dashboard pages + subtree, `finalized-parity.css`, dead `ui/*`, `jobsTableColumns.ts`, unused `api.ts` exports, prune dead CSS selectors.

**Phase B — Hook consolidation (~200 LOC + behavior fix):** `useRunSession.ts`; unify SSE subscriptions; single devlog component.

**Phase C — Python apply cleanup (~500 LOC):** Resolve `actions.py` fate; `cli_argv.py`; launcher log artifact helper; optional `view.py` retirement.

**Phase D — Contract hardening:** Pipeline stage predicates single source; OpenAPI/codegen for `api.ts` ↔ `schemas.py`; test TS vs SQL stage labels.

**Phase E — Docs/scripts hygiene:** Archive doc clusters; remove redundant scripts; fix inbox example path.

---

## Appendix: audit agents

This report merges findings from parallel audits of:

1. Python backend modules (`apply/`, `server/`, `discovery/`, `scoring/`, `orchestration/`, `cli.py`)
2. Dashboard frontend (every component, hook, util, CSS file)
3. Tests, scripts, docs, config, root markdown
4. Cross-cutting duplicate logic (URLs, run hooks, audit utils, CLI argv, unblock stack, stage SQL, API types)

**Second pass (2026-06-08):** three agents re-scanned after Postgres migration — schema/registry split, live dashboard polling overlap, broken pytest fixtures, stale onboarding docs, root JSON orphans.

Re-run after major refactors using import-graph checks (`rg` from `main.tsx`, `App.tsx`, `cli.py`, `server/app.py` entry points).

---

## 11. Shell-confirmed line counts (2026-06-08)

Verified with `wc -l` on the working tree:

| Cluster | Lines |
|---------|------:|
| `apply/direct/actions.py` | 194 |
| `view.py` (legacy static dashboard) | 406 |
| `tests/test_actions.py` | 142 |
| **Dead Python cluster subtotal** | **742** |
| `components/pipeline/*.tsx` (orphan subtree) | 1,160 |
| Dashboard `*.ts` / `*.tsx` files (file count) | 86 |

The orphan pipeline folder (`DiscoverSourcePanel`, `NowPanel`, `QueuePanel`, `statusChip`, `TimelineRibbon`, `WorkerChip`) accounts for **1,160 LOC** — about **21%** of the unmounted dashboard dead-code estimate when combined with unmounted pages (~5,600 LOC total).

---

## 12. Documentation retention (2026-06-08)

**Policy:** Keep only the deterministic worker handbook cluster plus this redundancy audit. All other files under `docs/` were removed in the same cleanup pass.

### Kept (9 files)

| File | Role |
|------|------|
| [`worker-deterministic-apply-handbook.md`](worker-deterministic-apply-handbook.md) | Primary worker orders — fix recipes, verify commands, escalation |
| [`worker-apply-playbook.md`](worker-apply-playbook.md) | Form-filler worker (separate from deterministic engine worker) |
| [`self-learning-apply-architecture.md`](self-learning-apply-architecture.md) | Tier model / design rationale (handbook § intro) |
| [`scaled-self-learning-apply-plan.md`](scaled-self-learning-apply-plan.md) | Engineering rollout plan (handbook § intro) |
| [`worker-implementation-plan-june-2026.md`](worker-implementation-plan-june-2026.md) | June 2026 implementation plan (handbook § intro) |
| [`behavior-tree-apply-recommended-algorithms-may-2026.md`](behavior-tree-apply-recommended-algorithms-may-2026.md) | Referenced by implementation plan |
| [`research/behavior-tree-web-automation-may-2026.json`](research/behavior-tree-web-automation-may-2026.json) | Research appendix for behavior-tree doc |
| [`worker-deterministic-apply-ledger.md`](worker-deterministic-apply-ledger.md) | Append-only iteration log (handbook §8) |
| [`redundancy-report.md`](redundancy-report.md) | This file — codebase redundancy audit |

### Removed (~35 files)

Archived clusters deleted: May/June 2026 fix runbooks (`apply-*-may-2026.md`, `enrich-tailor-gap-fix`, `discover-relevance-fix`, etc.), India targeting docs, dashboard redesign specs and HTML mockups, `IMPLEMENTATION-PLAYBOOK.md`, `superpowers/specs/*`, and one-off inventories (`deprecated-files-inventory.md`).

**Note:** Some Python modules still cite deleted docs in comments (e.g. `maxed-apply-pipeline-jun-2026.md`, `direct-apply-architecture.md`). Treat the handbook cluster as the live doc set; update code comments when touching those modules.

---

## 13. Second-pass findings (2026-06-08, post-Postgres migration)

Three parallel re-audits after the SQLite→Postgres cutover and a stuck-pipeline incident. Items below are **new** relative to §1–§12 unless marked as a correction.

### 13.1 Critical: broken test collection (maintenance debt, not dead code)

| Item | Detail |
|------|--------|
| **Symptom** | `pytest --collect-only` → **21 collection errors**, 674 tests otherwise collectable |
| **Cause** | Migration left IndentationError / undefined `db_path` / file-path fixtures passing `*.db` into `get_connection()` |
| **Affected files** | `test_apply_visit_ledger.py`, `test_embedding_filter.py`, `test_learning_api.py`, `test_playbook_seed.py`, `test_job_triage.py`, `test_gmail_receipts.py`, `test_run_controller_active_run.py`, `test_filter_stage.py`, `test_llm_usage.py`, `test_direct_qa_bank.py`, `test_direct_resolver.py`, `test_tailored_cleanup.py`, `test_apply_prepare_staged.py`, `test_apply_queue_preflight.py`, `test_apply_quota_e2e.py`, `test_role_resumes.py`, `test_role_aware_scoring.py`, `test_worker_playbook_benchmark.py`, … |
| **Fix** | Standardize on autouse `isolated_db` from `tests/conftest.py`; remove per-file `temp_db` / `apply_db` SQLite paths |
| **Severity** | **Critical** — blocks CI and contradicts kept worker docs that say “run pytest” |

### 13.2 Postgres schema: dual column registries (High)

| Registry | Location | Role |
|----------|----------|------|
| `JOBS_EXTRA_COLUMNS` | `db/schema.py` | `ensure_jobs_columns()` — 9 late columns (`pdf_*`, `triage_*`, `role_*`, `referral_attempts`) |
| `_ALL_COLUMNS` | `database.py` | `ensure_columns()` — full base/migration set (~47 keys) |

Both run from `init_db()` (`init_schema` then `ensure_columns`). Keys are **complementary**, not identical — but two registries mean new columns can be added to one list and missed by the other.

| Also duplicated | Files | Recommendation |
|-----------------|-------|----------------|
| BIGSERIAL table list | `schema.TABLES_WITH_SERIAL_ID` vs `connection._maybe_add_returning.serial_tables` | Single exported constant |
| Lazy `init_run_schema()` | Called on every `emit_run_event` though `init_db()` already created runs | No-op after startup or once-per-process |
| Dead wrappers | `ensure_dashboard_activity_table()` (`database.py`), `ensure_inbox_columns_legacy()` (`inbox/db.py`) | Delete (~14 LOC) |
| Unused imports | `inbox/db.py` — `table_columns`, `INBOX_OPPORTUNITY_COLUMNS`, `INBOX_REPLY_COLUMNS` | Remove |

**Partial fix landed:** `sync_serial_sequences()` in `init_schema()` — aligns BIGSERIAL after bulk import (fixed `run_events_pkey` duplicate-key failures when dashboard restarted pipeline).

### 13.3 Operational split-brain (incident, not redundant code)

Observed when a long-running dashboard daemon predated the Postgres-only server:

| Symptom | Cause |
|---------|--------|
| UI showed “agent running” with no log progress | Subprocess died; Postgres `runs.status` stayed `running` |
| Failed restart via API | Homebrew `/opt/homebrew/bin/applypilot` lacked `psycopg` |
| Empty `~/.applypilot/applypilot.db` (4096 B, 0 jobs) vs Postgres (3427 jobs) | Stale daemon + old code path wrote runs to SQLite stub |
| `duplicate key … run_events_pkey Key (id)=(1)` | BIGSERIAL sequence not advanced after migration |

**Mitigations applied:** `serve-daemon restart`, `_resolve_cli()` → venv interpreter, `sync_serial_sequences()`. **Remaining hardening:** reconcile orphans on shorter idle window; document “restart serve after DB migration”; optional guard if `APPLYPILOT_DATABASE_URL` unset.

### 13.4 Backend duplicate work (live server)

| File | Issue | ~Impact |
|------|-------|---------|
| `server/overview.py` `build_overview()` | Calls `fetch_stats()` (which runs `init_db()` + `get_stats()`) **and** `get_stats()` again | Double stats query + double init per overview request |
| Same module | `_jobs_discovered_today`, `_count_score_ge`, etc. overlap fields already in `get_stats()` | ~60–80 LOC SQL overlap |
| `server/stats.py` `fetch_stats()` | Redundant `init_db()` when caller already initialized | Low |

### 13.5 Live dashboard runtime overlap (beyond §2.4 dead hooks)

| Location | Issue | Severity |
|----------|-------|----------|
| `PipelineDashboardPage.tsx` | Mounts **both** `useHomeRuns()` and `useApplyRun()` — dual 10s polls + dual SSE | Medium |
| `App.tsx` + both hooks | Up to **three** `fetchActiveRun` pollers on `/pipeline` | Medium |
| `HomePage.tsx` + `PipelineDashboardPage.tsx` | Both poll `fetchOverview` **and** `fetchStats` every 5s; overview already embeds stats server-side | Medium |
| `useHomeRuns.ts` | Still exports full apply settings/start/stop but **no live page uses them** (apply pages use `useApplyRun`) | Medium (~80–120 LOC) |
| `App.tsx` vs `AppliedApplicationsPage.tsx` | Two stop paths (header fire-and-forget vs hook invalidation) | Medium |
| `ApplyRunControls.tsx` + `PipelineRunControls.tsx` | Duplicate local `SetRow` helper (~18 LOC each) | Low |
| `AppliedApplicationsPage.tsx` | Raw `RunPlanModal` for prepare/staged vs `ApplyRunPlanModal` for submit | Low — add wrapper modals |
| `applyRunState.ts` | Private `formatWhen()` duplicates `applicationAudit.formatWhen` | Low |

### 13.6 Stale onboarding / kept docs (Postgres drift)

| Path | Issue | Severity |
|------|-------|----------|
| `README.md` | No Postgres / `applypilot db init`; promotes legacy `applypilot dashboard` over `applypilot serve` | High |
| `CONTRIBUTING.md` | Wrong package tree; `applypilot discover` examples (actual: `applypilot run discover`); no Postgres in dev setup | Medium |
| `AGENTS.md` | “Dashboard can start `applypilot run` only” — API also starts apply/inbox runs | Medium |
| `docs/worker-implementation-plan-june-2026.md` | Still says tests use tmp SQLite; W5 “SQLite contention” | High / Medium |
| `docs/self-learning-apply-architecture.md` | “Storage (SQLite, mirrors qa_bank)” | High |
| `docs/scaled-self-learning-apply-plan.md` | WAL / “database is locked” as production assumptions | Medium |
| `DESIGN.md` | Orphan vs §12 kept set; route drift (Learning live, Inbox → Outreach) | Medium |
| `WORKER_BRIEF_INDIA_FIRST.md` | Still references deleted `docs/india-source-map.md` | Medium |

### 13.7 Root JSON orphans (not in §6)

| File | ~LOC | Imports |
|------|------|---------|
| `technical-job-discovery-improvements-2026.json` | 7,516 | 0 |
| `linkedin-other-inbox-automation-gaps.json` | 3,007 | 0 |
| `job-workflow-may-2026.json` | 1,657 | 0 |
| `high-paying-react-node-python-jobs-jun-2026.json` | 181 | 0 |

**Recommendation:** Move to `docs/research/` or delete. (`docs/research/behavior-tree-web-automation-may-2026.json` is **kept** — referenced by handbook cluster.)

### 13.8 CLI / API surface overlap (new)

| Surface | Overlap |
|---------|---------|
| `applypilot playbook *` (CLI) | Same operator actions as `/api/learning/*` (`server/learning.py`) — stats, review, clusters, promote, ban, induce |
| `applypilot doctor` | Does not check Postgres connectivity; `init` wizard does not run `db init` |

Pick canonical path: dashboard → REST; thin or deprecate duplicate CLI group.

### 13.9 Legacy naming (SQLite-era params, no sqlite in `src/`)

| Symbol | Location | Note |
|--------|----------|------|
| `init_db(db_path=…)` | `database.py` | Accepts Postgres URL only — rename to `database_url=` |
| `list_run_events(..., db_path=…)` | `orchestration/events.py` | Same |
| `_writer_db_path` / `_db_path_from_conn()` | `apply/direct/review_log.py` | Always resolves `DATABASE_URL` |
| `substr(created_at, 1, 10) = ?` | `overview.py`, `llm_usage_api.py` | SQLite-style dates beside Postgres `::timestamptz` casts |

### 13.10 Stale code comments (deleted docs)

Modules still linking to removed architecture docs: `database.py`, `apply/direct/__init__.py`, `throttle.py`, `profile_binding.py`, `adapters/__init__.py`, `extractor.py`, `config/common_questions.yaml`, `apply/direct/qa_bank.py`, `server/overview.py`. Repoint to handbook cluster on next touch.

---

## 14. Corrections to earlier sections

| § | Correction |
|---|------------|
| §1.2 | `db/migrate_sqlite.py` **removed** from repo — row struck through |
| §1.4 | `_resolve_cli()` **fixed** to use venv `sys.executable`; TS argv builders still duplicate |
| §9 | `sync_serial_sequences()` is **active infrastructure**, not redundancy |
| §12 | Extend retention policy to classify root onboarding files (`README.md`, `CONTRIBUTING.md`, `DESIGN.md`, `WORKER_BRIEF_INDIA_FIRST.md`) and root JSON research artifacts |
