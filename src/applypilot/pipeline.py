"""ApplyPilot Pipeline Orchestrator.

Runs pipeline stages in sequence or concurrently (streaming mode).

Usage (via CLI):
    applypilot run                        # all stages, sequential
    applypilot run --stream               # all stages, concurrent
    applypilot run discover enrich        # specific stages
    applypilot run score tailor cover     # LLM-only stages
    applypilot run --dry-run              # preview without executing
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from applypilot.config import load_env, ensure_dirs
from applypilot.database import init_db, get_connection, get_stats
from applypilot.orchestration.events import emit_run_event

log = logging.getLogger(__name__)
console = Console()


# ---------------------------------------------------------------------------
# Stage definitions
# ---------------------------------------------------------------------------

STAGE_ORDER = ("discover", "enrich", "score", "tailor", "pdf", "refer", "cover")

STAGE_META: dict[str, dict] = {
    "discover": {"desc": "Job discovery (JobSpy + Workday + smart extract)"},
    "enrich":   {"desc": "Detail enrichment (full descriptions + apply URLs)"},
    "score":    {"desc": "LLM scoring (fit 1-10)"},
    "refer":    {"desc": "LinkedIn referral outreach (Gemini draft + tailored resume, OpenOutreach)"},
    "tailor":   {"desc": "Resume tailoring (LLM + validation)"},
    "cover":    {"desc": "Cover letter generation"},
    "pdf":      {"desc": "PDF conversion (tailored resumes + cover letters)"},
}

# Upstream dependency: a stage only finishes when its upstream is done AND
# it has no remaining pending work.
_UPSTREAM: dict[str, str | None] = {
    "discover": None,
    "enrich":   "discover",
    "score":    "enrich",
    "tailor":   "score",
    "pdf":      "tailor",
    "refer":    "tailor",
    "cover":    "tailor",
}


# ---------------------------------------------------------------------------
# Individual stage runners
# ---------------------------------------------------------------------------

def _run_discover(workers: int = 1) -> dict:
    """Stage: Job discovery — JobSpy, Workday, and smart-extract scrapers."""
    stats: dict = {"jobspy": None, "workday": None, "smartextract": None}

    # JobSpy
    console.print("  [cyan]JobSpy full crawl...[/cyan]")
    try:
        from applypilot.discovery.jobspy import run_discovery
        run_discovery()
        stats["jobspy"] = "ok"
    except Exception as e:
        log.error("JobSpy crawl failed: %s", e)
        console.print(f"  [red]JobSpy error:[/red] {e}")
        if "jobspy" in str(e).lower():
            from applypilot.discovery.jobspy_install import install_hint

            console.print(f"  [yellow]{install_hint()}[/yellow]")
        stats["jobspy"] = f"error: {e}"

    # Workday corporate scraper
    console.print("  [cyan]Workday corporate scraper...[/cyan]")
    try:
        from applypilot.discovery.workday import run_workday_discovery
        run_workday_discovery(workers=workers)
        stats["workday"] = "ok"
    except Exception as e:
        log.error("Workday scraper failed: %s", e)
        console.print(f"  [red]Workday error:[/red] {e}")
        stats["workday"] = f"error: {e}"

    # Smart extract
    console.print("  [cyan]Smart extract (AI-powered scraping)...[/cyan]")
    try:
        from applypilot.discovery.smartextract import run_smart_extract
        run_smart_extract(workers=workers)
        stats["smartextract"] = "ok"
    except Exception as e:
        log.error("Smart extract failed: %s", e)
        console.print(f"  [red]Smart extract error:[/red] {e}")
        stats["smartextract"] = f"error: {e}"

    return stats


def _run_enrich(workers: int = 1) -> dict:
    """Stage: Detail enrichment — scrape full descriptions and apply URLs."""
    try:
        from applypilot.enrichment.detail import run_enrichment
        run_enrichment(workers=workers)
        return {"status": "ok"}
    except Exception as e:
        log.error("Enrichment failed: %s", e)
        return {"status": f"error: {e}"}


def _run_score() -> dict:
    """Stage: LLM scoring — assign fit scores 1-10."""
    try:
        from applypilot.scoring.scorer import run_scoring
        run_scoring()
        return {"status": "ok"}
    except Exception as e:
        log.error("Scoring failed: %s", e)
        return {"status": f"error: {e}"}


def _run_tailor(min_score: int = 7, validation_mode: str = "normal") -> dict:
    """Stage: Resume tailoring — generate tailored resumes for high-fit jobs."""
    try:
        from applypilot.scoring.tailor import run_tailoring
        run_tailoring(min_score=min_score, validation_mode=validation_mode)
        return {"status": "ok"}
    except Exception as e:
        log.error("Tailoring failed: %s", e)
        return {"status": f"error: {e}"}


def _run_cover(min_score: int = 7, validation_mode: str = "normal") -> dict:
    """Stage: Cover letter generation."""
    try:
        from applypilot.scoring.cover_letter import run_cover_letters
        run_cover_letters(min_score=min_score, validation_mode=validation_mode)
        return {"status": "ok"}
    except Exception as e:
        log.error("Cover letter generation failed: %s", e)
        return {"status": f"error: {e}"}


def _run_pdf() -> dict:
    """Stage: PDF conversion — convert tailored resumes and cover letters to PDF."""
    try:
        from applypilot.scoring.pdf import batch_convert
        batch_convert()
        return {"status": "ok"}
    except Exception as e:
        log.error("PDF conversion failed: %s", e)
        return {"status": f"error: {e}"}


def _run_refer() -> dict:
    """Stage: LinkedIn referral outreach via OpenOutreach."""
    from applypilot.outreach.config import load_outreach_config, outreach_is_configured
    from applypilot.outreach.pipeline import run_referral_pipeline

    settings = load_outreach_config()
    if not settings.enabled:
        console.print("  [yellow]Referral outreach disabled (outreach.yaml)[/yellow]")
        return {"status": "skipped"}
    if not outreach_is_configured(settings):
        console.print("  [yellow]OpenOutreach not configured — skipping refer stage[/yellow]")
        return {"status": "skipped"}
    try:
        summary = run_referral_pipeline()
        if summary.get("error"):
            return {"status": f"error: {summary['error']}"}
        connect = summary.get("connect") or {}
        message = summary.get("message") or {}
        if connect.get("skipped") == "openoutreach_unreachable" or message.get(
            "skipped"
        ) == "openoutreach_unreachable":
            detail = connect.get("detail") or message.get("detail") or "OpenOutreach unreachable"
            log.warning("Referral connect/message skipped: %s", detail)
            return {"status": "skipped", "reason": detail, **summary}
        for stage_name in ("connect", "message"):
            stage = summary.get(stage_name) or {}
            if stage.get("error"):
                log.warning("Referral %s stage error: %s", stage_name, stage["error"])
                return {"status": f"error: {stage_name}: {stage['error']}", **summary}
        return {"status": "ok", **summary}
    except Exception as e:
        log.error("Referral outreach failed: %s", e)
        return {"status": f"error: {e}"}


# Map stage names to their runner functions
_STAGE_RUNNERS: dict[str, callable] = {
    "discover": _run_discover,
    "enrich":   _run_enrich,
    "score":    _run_score,
    "refer":    _run_refer,
    "tailor":   _run_tailor,
    "cover":    _run_cover,
    "pdf":      _run_pdf,
}


# ---------------------------------------------------------------------------
# Stage resolution
# ---------------------------------------------------------------------------

def _resolve_stages(stage_names: list[str]) -> list[str]:
    """Resolve 'all' and validate/order stage names."""
    if "all" in stage_names:
        return list(STAGE_ORDER)

    resolved = []
    for name in stage_names:
        if name not in STAGE_META:
            console.print(
                f"[red]Unknown stage:[/red] '{name}'. "
                f"Available: {', '.join(STAGE_ORDER)}, all"
            )
            raise SystemExit(1)
        if name not in resolved:
            resolved.append(name)

    # Maintain canonical order
    return [s for s in STAGE_ORDER if s in resolved]


# ---------------------------------------------------------------------------
# Streaming pipeline helpers
# ---------------------------------------------------------------------------

class _StageTracker:
    """Thread-safe tracker for which stages have finished producing work."""

    def __init__(self):
        self._events: dict[str, threading.Event] = {
            stage: threading.Event() for stage in STAGE_ORDER
        }
        self._results: dict[str, dict] = {}
        self._lock = threading.Lock()

    def mark_done(self, stage: str, result: dict | None = None) -> None:
        with self._lock:
            self._results[stage] = result or {"status": "ok"}
        self._events[stage].set()

    def is_done(self, stage: str) -> bool:
        return self._events[stage].is_set()

    def wait(self, stage: str, timeout: float | None = None) -> bool:
        return self._events[stage].wait(timeout=timeout)

    def get_results(self) -> dict[str, dict]:
        with self._lock:
            return dict(self._results)


# SQL to count pending work for each stage
_PENDING_SQL: dict[str, str] = {
    "enrich": "SELECT COUNT(*) FROM jobs WHERE detail_scraped_at IS NULL",
    "score":  "SELECT COUNT(*) FROM jobs WHERE full_description IS NOT NULL AND fit_score IS NULL",
    "tailor": (
        "SELECT COUNT(*) FROM jobs WHERE fit_score >= ? "
        "AND full_description IS NOT NULL "
        "AND tailored_resume_path IS NULL "
        "AND COALESCE(tailor_attempts, 0) < 5"
    ),
    "cover": (
        "SELECT COUNT(*) FROM jobs WHERE tailored_resume_path IS NOT NULL "
        "AND (cover_letter_path IS NULL OR cover_letter_path = '') "
        "AND COALESCE(cover_attempts, 0) < 5"
    ),
    "pdf": (
        "SELECT COUNT(*) FROM jobs WHERE tailored_resume_path IS NOT NULL "
        "AND tailored_resume_path LIKE '%.txt'"
    ),
    "refer": (
        "SELECT COUNT(*) FROM jobs WHERE fit_score >= ? "
        "AND discovered_at >= datetime('now', '-72 hours') "
        "AND ("
        "  (recruiter_public_id IS NULL OR recruiter_public_id = '') "
        "  OR (referral_message IS NULL OR referral_message = '') "
        "  OR referral_status IN ('pending_connect', 'connect_sent')"
        ") AND ("
        "  LOWER(COALESCE(site, '')) LIKE '%linkedin%' "
        "  OR LOWER(COALESCE(url, '')) LIKE '%linkedin.com/jobs%'"
        "  OR LOWER(COALESCE(application_url, '')) LIKE '%linkedin.com/jobs%'"
        ")"
    ),
}

# How long to sleep between polling loops in streaming mode (seconds)
_STREAM_POLL_INTERVAL = 10


def _count_pending(stage: str, min_score: int = 7) -> int:
    """Count pending work items for a stage."""
    if stage == "pdf":
        from applypilot.scoring.pdf import pending_pdf_conversions

        return pending_pdf_conversions()

    sql = _PENDING_SQL.get(stage)
    if sql is None:
        return 0
    conn = get_connection()
    if "?" in sql:
        return conn.execute(sql, (min_score,)).fetchone()[0]
    return conn.execute(sql).fetchone()[0]


def _progress_percent(done: int, denom: int) -> int | None:
    if denom <= 0:
        return None
    return min(100, max(0, int(round(100 * done / denom))))


def _stage_progress_snapshot(stage: str, min_score: int = 7) -> dict[str, Any]:
    """Job counts for dashboard stage_progress events."""
    stats = get_stats()
    total = int(stats.get("total") or 0)

    if stage == "discover":
        return {
            "stage": stage,
            "total": total,
            "detail": "JobSpy, Workday, and smart extract",
        }

    if stage == "enrich":
        done = int(stats.get("with_description") or 0)
        pending = int(stats.get("pending_detail") or 0)
        denom = total if total > 0 else done + pending
        return {
            "stage": stage,
            "done": done,
            "pending": pending,
            "total": denom,
            "percent": _progress_percent(done, denom),
            "detail": f"{done}/{denom} with descriptions · {pending} left",
        }

    if stage == "score":
        done = int(stats.get("scored") or 0)
        pending = int(stats.get("unscored") or 0)
        denom = done + pending
        return {
            "stage": stage,
            "done": done,
            "pending": pending,
            "total": denom,
            "percent": _progress_percent(done, denom),
            "detail": f"{done} scored · {pending} waiting",
        }

    if stage == "tailor":
        done = int(stats.get("tailored") or 0)
        pending = _count_pending("tailor", min_score)
        denom = done + pending
        return {
            "stage": stage,
            "done": done,
            "pending": pending,
            "total": denom,
            "percent": _progress_percent(done, denom),
            "detail": f"{done} tailored · {pending} left (score ≥ {min_score})",
        }

    if stage == "cover":
        done = int(stats.get("with_cover_letter") or 0)
        pending = _count_pending("cover", min_score)
        denom = done + pending
        return {
            "stage": stage,
            "done": done,
            "pending": pending,
            "total": denom,
            "percent": _progress_percent(done, denom),
            "detail": f"{done} cover letters · {pending} left",
        }

    if stage == "pdf":
        pending = _count_pending("pdf", min_score)
        tailored = int(stats.get("tailored") or 0)
        done = max(0, tailored - pending)
        denom = tailored
        return {
            "stage": stage,
            "done": done,
            "pending": pending,
            "total": denom,
            "percent": _progress_percent(done, denom),
            "detail": f"{done} PDFs ready · {pending} pending",
        }

    if stage == "refer":
        done = int(stats.get("referral_message_sent") or 0)
        pending = _count_pending("refer", min_score)
        denom = done + pending
        return {
            "stage": stage,
            "done": done,
            "pending": pending,
            "total": denom,
            "percent": _progress_percent(done, denom) if denom else None,
            "detail": f"{done} messages sent · {pending} in outreach queue",
        }

    pending = _count_pending(stage, min_score)
    return {
        "stage": stage,
        "pending": pending,
        "detail": f"{pending} pending",
    }


def _emit_stage_progress(
    stage: str,
    min_score: int = 7,
    *,
    waiting_upstream: bool = False,
) -> dict[str, Any] | None:
    try:
        snap = _stage_progress_snapshot(stage, min_score)
        if waiting_upstream:
            snap["waiting_upstream"] = True
            snap["detail"] = f"{snap.get('detail', '')} · waiting on upstream"
        detail = str(snap.get("detail") or "")
        return emit_run_event(
            "stage_progress", stage=stage, message=detail, payload=snap
        )
    except Exception:
        return None


def _progress_reporter_loop(stage: str, min_score: int, stop: threading.Event) -> None:
    while True:
        _emit_stage_progress(stage, min_score)
        if stop.wait(_STREAM_POLL_INTERVAL):
            break


def _run_with_progress_reporter(stage: str, min_score: int, fn):
    """Run blocking stage work while emitting stage_progress every poll interval."""
    stop = threading.Event()
    reporter = threading.Thread(
        target=_progress_reporter_loop,
        args=(stage, min_score, stop),
        name=f"progress-{stage}",
        daemon=True,
    )
    reporter.start()
    try:
        return fn()
    finally:
        stop.set()
        reporter.join(timeout=2.0)


def _run_stage_streaming(
    stage: str,
    tracker: _StageTracker,
    stop_event: threading.Event,
    min_score: int = 7,
    workers: int = 1,
    validation_mode: str = "normal",
) -> None:
    """Run a single stage in streaming mode: loop until upstream done + no work.

    For discover: runs once, then marks done.
    For all others: polls DB for pending work, runs the batch processor,
    and repeats until upstream is done and no pending work remains.
    """
    runner = _STAGE_RUNNERS[stage]
    kwargs: dict = {}
    if stage in ("tailor", "cover"):
        kwargs["min_score"] = min_score
        kwargs["validation_mode"] = validation_mode
    if stage in ("discover", "enrich"):
        kwargs["workers"] = workers

    upstream = _UPSTREAM[stage]

    if stage == "discover":
        emit_run_event("stage_start", stage=stage)
        _emit_stage_progress(stage, min_score)
        try:
            result = _run_with_progress_reporter(
                stage,
                min_score,
                lambda: runner(**kwargs),
            )
            tracker.mark_done(stage, result)
            _emit_stage_progress(stage, min_score)
            emit_run_event("stage_end", stage=stage, payload=result if isinstance(result, dict) else {})
        except Exception as e:
            log.exception("Stage '%s' crashed", stage)
            emit_run_event("stage_error", stage=stage, level="error", message=str(e))
            tracker.mark_done(stage, {"status": f"error: {e}"})
        return

    emit_run_event("stage_start", stage=stage)
    _emit_stage_progress(stage, min_score)
    # For downstream stages: loop until upstream done + no pending work
    passes = 0
    while not stop_event.is_set():
        # Wait for upstream to start producing work (first pass only)
        if passes == 0 and upstream and not tracker.is_done(upstream):
            # Wait a bit for upstream to produce some work before first run
            tracker.wait(upstream, timeout=_STREAM_POLL_INTERVAL)

        pending = _count_pending(stage, min_score)
        waiting_upstream = (
            pending == 0
            and upstream is not None
            and not tracker.is_done(upstream)
        )
        _emit_stage_progress(stage, min_score, waiting_upstream=waiting_upstream)

        if pending > 0:
            try:
                _run_with_progress_reporter(
                    stage,
                    min_score,
                    lambda: runner(**kwargs),
                )
                passes += 1
            except Exception as e:
                log.error("Stage '%s' error (pass %d): %s", stage, passes, e)
                passes += 1
        else:
            # No work right now
            upstream_done = upstream is None or tracker.is_done(upstream)
            if upstream_done:
                # No work and upstream is done — this stage is finished
                break
            # Upstream still running, wait and retry
            if stop_event.wait(timeout=_STREAM_POLL_INTERVAL):
                break  # Stop requested

    _emit_stage_progress(stage, min_score)
    tracker.mark_done(stage, {"status": "ok", "passes": passes})
    emit_run_event(
        "stage_end",
        stage=stage,
        payload={"status": "ok", "passes": passes},
    )
    try:
        emit_run_event("stats_tick", payload=get_stats())
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Pipeline orchestrators
# ---------------------------------------------------------------------------

def _emit_stats_tick() -> None:
    try:
        emit_run_event("stats_tick", payload=get_stats())
    except Exception:
        pass


def _run_sequential(ordered: list[str], min_score: int, workers: int = 1,
                    validation_mode: str = "normal") -> dict:
    """Execute stages one at a time (original behavior)."""
    results: list[dict] = []
    errors: dict[str, str] = {}
    pipeline_start = time.time()

    for name in ordered:
        meta = STAGE_META[name]
        console.print(f"\n{'=' * 70}")
        console.print(f"  [bold]STAGE: {name}[/bold] — {meta['desc']}")
        console.print(f"  Started: {datetime.now().strftime('%H:%M:%S')}")
        console.print(f"{'=' * 70}")

        t0 = time.time()
        runner = _STAGE_RUNNERS[name]
        emit_run_event("stage_start", stage=name)
        _emit_stage_progress(name, min_score)

        try:
            kwargs: dict = {}
            if name in ("tailor", "cover"):
                kwargs["min_score"] = min_score
                kwargs["validation_mode"] = validation_mode
            if name in ("discover", "enrich"):
                kwargs["workers"] = workers
            result = _run_with_progress_reporter(
                name,
                min_score,
                lambda: runner(**kwargs),
            )
            elapsed = time.time() - t0

            status = "ok"
            stage_payload: dict = {}
            if isinstance(result, dict):
                status = result.get("status", "ok")
                stage_payload = dict(result)
                if name == "discover":
                    sub_errors = [
                        f"{k}: {v}" for k, v in result.items()
                        if isinstance(v, str) and v.startswith("error")
                    ]
                    if sub_errors:
                        status = "partial"

            emit_run_event(
                "stage_end",
                stage=name,
                payload={"status": status, "elapsed": elapsed, **stage_payload},
            )
            _emit_stats_tick()

        except Exception as e:
            elapsed = time.time() - t0
            status = f"error: {e}"
            log.exception("Stage '%s' crashed", name)
            console.print(f"\n  [red]STAGE FAILED:[/red] {e}")
            emit_run_event("stage_error", stage=name, level="error", message=str(e))

        results.append({"stage": name, "status": status, "elapsed": elapsed})
        if status not in ("ok", "partial"):
            errors[name] = status

        console.print(f"\n  Stage '{name}' completed in {elapsed:.1f}s — {status}")

    total_elapsed = time.time() - pipeline_start
    return {"stages": results, "errors": errors, "elapsed": total_elapsed}


def _run_streaming(ordered: list[str], min_score: int, workers: int = 1,
                   validation_mode: str = "normal") -> dict:
    """Execute stages concurrently with DB as conveyor belt."""
    tracker = _StageTracker()
    stop_event = threading.Event()
    pipeline_start = time.time()

    console.print(f"\n  [bold cyan]STREAMING MODE[/bold cyan] — stages run concurrently")
    console.print(f"  Poll interval: {_STREAM_POLL_INTERVAL}s\n")

    # Mark stages NOT in `ordered` as done so downstream doesn't wait for them
    for stage in STAGE_ORDER:
        if stage not in ordered:
            tracker.mark_done(stage, {"status": "skipped"})

    # Launch each stage in its own thread
    threads: dict[str, threading.Thread] = {}
    start_times: dict[str, float] = {}

    for name in ordered:
        start_times[name] = time.time()
        t = threading.Thread(
            target=_run_stage_streaming,
            args=(name, tracker, stop_event, min_score, workers, validation_mode),
            name=f"stage-{name}",
            daemon=True,
        )
        threads[name] = t
        t.start()
        console.print(f"  [dim]Started thread:[/dim] {name}")

    # Wait for all threads to finish
    try:
        for name in ordered:
            threads[name].join()
            elapsed = time.time() - start_times[name]
            console.print(
                f"  [green]Completed:[/green] {name} ({elapsed:.1f}s)"
            )
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted — stopping stages...[/yellow]")
        stop_event.set()
        for t in threads.values():
            t.join(timeout=10)

    total_elapsed = time.time() - pipeline_start

    # Build results from tracker
    all_results = tracker.get_results()
    results: list[dict] = []
    errors: dict[str, str] = {}

    for name in ordered:
        r = all_results.get(name, {"status": "unknown"})
        elapsed = time.time() - start_times.get(name, pipeline_start)
        status = r.get("status", "ok")

        results.append({"stage": name, "status": status, "elapsed": elapsed})
        if status not in ("ok", "partial", "skipped"):
            errors[name] = status

    return {"stages": results, "errors": errors, "elapsed": total_elapsed}


def run_pipeline(
    stages: list[str] | None = None,
    min_score: int = 7,
    dry_run: bool = False,
    stream: bool = False,
    workers: int = 1,
    validation_mode: str = "normal",
) -> dict:
    """Run pipeline stages.

    Args:
        stages: List of stage names, or None / ["all"] for full pipeline.
        min_score: Minimum fit score for tailor/cover stages.
        dry_run: If True, preview stages without executing.
        stream: If True, run stages concurrently (streaming mode).
        workers: Number of parallel threads for discovery/enrichment stages.

    Returns:
        Dict with keys: stages (list of result dicts), errors (dict), elapsed (float).
    """
    # Bootstrap
    load_env()
    ensure_dirs()
    init_db()

    # Resolve stages
    if stages is None:
        stages = ["all"]
    ordered = _resolve_stages(stages)

    # Banner
    mode = "streaming" if stream else "sequential"
    console.print()
    console.print(Panel.fit(
        f"[bold]ApplyPilot Pipeline[/bold] ({mode})",
        border_style="blue",
    ))
    console.print(f"  Min score:  {min_score}")
    console.print(f"  Workers:    {workers}")
    console.print(f"  Validation: {validation_mode}")
    console.print(f"  Stages:     {' -> '.join(ordered)}")

    # Pre-run stats
    pre_stats = get_stats()
    console.print(f"  DB:        {pre_stats['total']} jobs, {pre_stats['pending_detail']} pending enrichment")

    if dry_run:
        console.print(f"\n  [yellow]DRY RUN[/yellow] — would execute ({mode}):")
        for name in ordered:
            meta = STAGE_META[name]
            console.print(f"    {name:<12s}  {meta['desc']}")
        console.print(f"\n  No changes made.")
        emit_run_event(
            "run_finished",
            message="dry_run",
            payload={"stages": ordered, "dry_run": True},
        )
        return {"stages": [], "errors": {}, "elapsed": 0.0}

    emit_run_event(
        "run_started",
        message=f"pipeline ({mode})",
        payload={"stages": ordered, "stream": stream, "min_score": min_score},
    )

    # Execute
    if stream:
        result = _run_streaming(ordered, min_score, workers=workers,
                                validation_mode=validation_mode)
    else:
        result = _run_sequential(ordered, min_score, workers=workers,
                                 validation_mode=validation_mode)

    # Summary table
    console.print(f"\n{'=' * 70}")
    summary = Table(title="Pipeline Summary", show_header=True, header_style="bold")
    summary.add_column("Stage", style="bold")
    summary.add_column("Status")
    summary.add_column("Time", justify="right")

    for r in result["stages"]:
        elapsed_str = f"{r['elapsed']:.1f}s"
        status_display = r["status"][:30]
        if r["status"] == "ok":
            style = "green"
        elif r["status"] in ("partial", "skipped"):
            style = "yellow"
        else:
            style = "red"
        summary.add_row(r["stage"], f"[{style}]{status_display}[/{style}]", elapsed_str)

    summary.add_row("", "", "")
    summary.add_row("[bold]Total[/bold]", "", f"[bold]{result['elapsed']:.1f}s[/bold]")
    console.print(summary)

    # Final DB stats
    final = get_stats()
    console.print(f"\n  [bold]DB Final State:[/bold]")
    console.print(f"    Total jobs:     {final['total']}")
    console.print(f"    With desc:      {final['with_description']}")
    console.print(f"    Scored:         {final['scored']}")
    console.print(f"    Tailored:       {final['tailored']}")
    console.print(f"    Cover letters:  {final['with_cover_letter']}")
    console.print(f"    Ready to apply: {final['ready_to_apply']}")
    console.print(f"    Applied:        {final['applied']}")
    if final.get("referral_recruiter_scraped") is not None:
        console.print(f"    Referrals sent: {final.get('referral_message_sent', 0)}")
    console.print(f"{'=' * 70}\n")

    emit_run_event(
        "run_finished",
        message="completed" if not result.get("errors") else "completed_with_errors",
        payload={
            "elapsed": result.get("elapsed"),
            "errors": result.get("errors"),
            "stats": final,
        },
    )

    return result
