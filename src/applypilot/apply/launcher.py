"""Apply orchestration: acquire jobs, spawn Claude Code sessions, track results.

This is the main entry point for the apply pipeline. It pulls jobs from
the database, launches Chrome + Claude Code for each one, parses the
result, and updates the database. Supports parallel workers via --workers.
"""

import atexit
import json
import logging
import os
import platform
import queue
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

from rich.console import Console
from rich.live import Live

from applypilot import config
from applypilot.config import load_profile
from applypilot.database import get_connection
from applypilot.role_resumes import (
    resolve_job_resume,
    resolve_job_resume_path,
    resolve_job_resume_text,
    role_resumes_available,
)
from applypilot.apply import apply_budget, apply_settings, chrome, dashboard, prompt as prompt_mod
from applypilot.apply.eligibility import (
    ApplyDecision,
    ats_only_where_clause,
    ats_priority_sql_case,
    direct_adapter_priority_sql,
    classify_apply_target,
    priority_boards_only_enabled,
    excluded_ats_families_where_clause,
    priority_boards_only_where_clause,
)
from applypilot.apply.chrome import (
    launch_chrome, cleanup_worker, kill_all_chrome,
    reset_worker_dir, cleanup_on_exit, _kill_process_tree,
    BASE_CDP_PORT,
)
from applypilot.apply.dashboard import (
    init_worker, update_state, add_event, get_state,
    render_full, get_totals,
)

logger = logging.getLogger(__name__)

# Blocked sites loaded from config/sites.yaml
def _load_blocked():
    from applypilot.config import load_blocked_sites
    return load_blocked_sites()

# How often to poll the DB when the queue is empty (seconds)
POLL_INTERVAL = config.DEFAULTS["poll_interval"]
# Jobs scanned per acquire pass (paginate past cap-blocked direct URLs)
ACQUIRE_CANDIDATE_BATCH = 80

# Thread-safe shutdown coordination
_stop_event = threading.Event()

# Track active Claude Code processes for skip (Ctrl+C) handling
_claude_procs: dict[int, subprocess.Popen] = {}
_claude_lock = threading.Lock()

# Register cleanup on exit (signal handlers only in main thread — e.g. FastAPI workers import this module)
atexit.register(cleanup_on_exit)
if (
    platform.system() != "Windows"
    and threading.current_thread() is threading.main_thread()
):
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))


# ---------------------------------------------------------------------------
# MCP config
# ---------------------------------------------------------------------------

def _resolve_npx_command() -> str:
    """Find npx even when ApplyPilot is launched from a sparse GUI PATH."""
    found = shutil.which("npx")
    if found:
        return found
    for candidate in (
        "/opt/homebrew/bin/npx",
        "/usr/local/bin/npx",
        str(Path.home() / ".local/bin/npx"),
    ):
        if Path(candidate).exists():
            return candidate
    return "npx"


def _make_mcp_config(cdp_port: int, *, include_gmail: bool | None = None) -> dict:
    """Build MCP config dict for a specific CDP port."""
    npx = _resolve_npx_command()
    if include_gmail is None:
        include_gmail = apply_settings.gmail_mcp_enabled()
    servers: dict = {
        "playwright": {
            "command": npx,
            "args": [
                "-y",
                "@playwright/mcp@latest",
                f"--cdp-endpoint=http://localhost:{cdp_port}",
                f"--viewport-size={config.DEFAULTS['viewport']}",
            ],
        },
    }
    if include_gmail:
        servers["gmail"] = {
            "command": npx,
            "args": ["-y", "@gongrzhe/server-gmail-autoauth-mcp"],
        }
    return {"mcpServers": servers}


_GMAIL_DISALLOWED_TOOLS = (
    "mcp__gmail__draft_email,mcp__gmail__modify_email,"
    "mcp__gmail__delete_email,mcp__gmail__download_attachment,"
    "mcp__gmail__batch_modify_emails,mcp__gmail__batch_delete_emails,"
    "mcp__gmail__create_label,mcp__gmail__update_label,"
    "mcp__gmail__delete_label,mcp__gmail__get_or_create_label,"
    "mcp__gmail__list_email_labels,mcp__gmail__create_filter,"
    "mcp__gmail__list_filters,mcp__gmail__get_filter,"
    "mcp__gmail__delete_filter"
)


def build_claude_apply_command(
    *,
    model: str,
    mcp_config_path: Path,
    worker_id: int,
) -> list[str]:
    """Assemble Claude CLI argv for one apply job (testable)."""
    cmd = [
        "claude",
        "--model",
        model,
        "-p",
        "--mcp-config",
        str(mcp_config_path),
        "--permission-mode",
        "bypassPermissions",
        "--disallowedTools",
        _GMAIL_DISALLOWED_TOOLS,
        "--output-format",
        "stream-json",
        "--verbose",
        "-",
    ]
    if apply_settings.session_reuse_enabled():
        session_id = apply_settings.load_session_id(worker_id)
        if session_id:
            cmd.extend(["--resume", session_id])
        # First run: omit --session-id; persist id from stream-json when Claude creates it.
    else:
        cmd.append("--no-session-persistence")
    return cmd


# ---------------------------------------------------------------------------
# Database operations
# ---------------------------------------------------------------------------

def _persist_ineligible_job(conn, row: dict, result) -> None:
    url = row["url"]
    if result.decision == ApplyDecision.MANUAL:
        conn.execute(
            "UPDATE jobs SET apply_status = 'manual', apply_error = ?, agent_id = NULL WHERE url = ?",
            (result.reason or "manual", url),
        )
        conn.commit()
        logger.info("Skipping manual apply (%s): %s", result.reason, url[:80])
        return
    if result.decision == ApplyDecision.SKIP_PERMANENT:
        conn.execute(
            """
            UPDATE jobs SET apply_status = 'failed', apply_error = ?,
                           apply_attempts = 99, agent_id = NULL
            WHERE url = ?
            """,
            (result.reason or "ineligible", url),
        )
        conn.commit()
        logger.info("Skipping permanent ineligible (%s): %s", result.reason, url[:80])


def _acquirable_jobs_where(
    *,
    min_score: int | None = None,
    ats_only: bool = False,
    priority_boards_only: bool = False,
    include_untailored: bool = False,
) -> tuple[str, list]:
    """SQL WHERE fragment matching acquire_job queue selection (before eligibility loop)."""
    blocked_sites, blocked_patterns = _load_blocked()
    max_attempts = config.DEFAULTS["max_apply_attempts"]
    if min_score is None:
        min_score = int(config.DEFAULTS.get("apply_min_score", 0))
    params: list = [max_attempts]
    score_clause = ""
    if min_score > 0:
        score_clause = "AND fit_score >= ?"
        params.append(min_score)
    site_clause = ""
    if blocked_sites:
        placeholders = ",".join("?" * len(blocked_sites))
        site_clause = f"AND site NOT IN ({placeholders})"
        params.extend(blocked_sites)
    url_clauses = ""
    if blocked_patterns:
        url_clauses = " ".join("AND url NOT LIKE ?" for _ in blocked_patterns)
        params.extend(blocked_patterns)
    ats_clause = ats_only_where_clause() if ats_only else ""
    boards_clause = ""
    if priority_boards_only or priority_boards_only_enabled():
        boards_clause = priority_boards_only_where_clause()
    skip_ats_clause = ""
    if apply_settings.deterministic_only_enabled():
        skip_ats_clause = excluded_ats_families_where_clause()
    if include_untailored:
        tailored_clause = ""
    elif role_resumes_available():
        role_min = int(config.DEFAULTS.get("role_resume_apply_min_score", 7))
        tailored_clause = (
            "AND (tailored_resume_path IS NOT NULL "
            f"OR (fit_score IS NOT NULL AND fit_score >= {role_min}))"
        )
    else:
        tailored_clause = "AND tailored_resume_path IS NOT NULL"
    where = f"""
        WHERE 1=1
          {tailored_clause}
          AND applied_at IS NULL
          AND (
            apply_status IS NULL
            OR apply_status = 'failed'
            OR apply_status = 'needs_adapter'
          )
          AND (
            apply_not_before IS NULL
            OR datetime(apply_not_before) <= datetime('now')
          )
          AND (apply_attempts IS NULL OR apply_attempts < ?)
          {score_clause}
          {site_clause}
          {url_clauses}
          {ats_clause}
          {boards_clause}
          {skip_ats_clause}
    """
    return where, params


def acquire_job_order_sql() -> str:
    """ORDER BY for acquire_job: direct-capable first, then ATS priority, score."""
    direct_tier = direct_adapter_priority_sql()
    priority = ats_priority_sql_case()
    parked_tail = (
        "CASE WHEN apply_status = 'needs_adapter' THEN 1 ELSE 0 END"
    )
    claude_rescue_tail = (
        "CASE WHEN COALESCE(apply_error, '') LIKE 'pending_claude_rescue%' "
        "THEN 1 ELSE 0 END"
    )
    day_like = "strftime('%Y-%m-%d', 'now') || '%'"
    # Deprioritize sites already submitted today so one employer doesn't dominate a run.
    site_load = f"""(
        SELECT COUNT(*) FROM apply_outcomes ao
        INNER JOIN jobs jx ON jx.url = ao.url
        WHERE jx.site = jobs.site
          AND ao.created_at LIKE {day_like}
          AND (ao.result LIKE 'applied%' OR ao.result LIKE 'submitted_unverified%')
    )"""
    return (
        f"{direct_tier} ASC, "
        f"{parked_tail} ASC, "
        f"{claude_rescue_tail} ASC, "
        f"{site_load} ASC, "
        f"CASE WHEN last_attempted_at IS NOT NULL "
        f"AND datetime(last_attempted_at) > datetime('now', '-60 minutes') "
        f"THEN 1 ELSE 0 END, {priority}, fit_score DESC, url"
    )


def _job_apply_url(job: dict) -> str:
    return _resolve_job_apply_url(job)


def _resolve_job_apply_url(job: dict, *, persist: bool = False) -> str:
    """Return the best apply URL for a job, recovering ATS links from board text.

    Board rows such as Wellfound can keep the board URL as ``url`` while the
    actual employer ATS link is embedded in ``full_description`` or
    ``description``. Resolve that before direct adapter detection so the
    deterministic engine gets a chance to apply without Claude.
    """
    from applypilot.apply.apply_url_extract import (
        coerce_application_url,
        extract_best_apply_url_from_text,
    )
    from applypilot.apply.direct import fingerprint

    current = coerce_application_url(job.get("application_url"))
    if current and fingerprint.has_adapter(fingerprint.ats_family(current)):
        return current

    extracted = extract_best_apply_url_from_text(
        "\n".join(
            str(job.get(key) or "")
            for key in ("full_description", "description")
        )
    )
    if extracted:
        job["application_url"] = extracted
        if persist:
            row_url = (job.get("url") or "").strip()
            if row_url:
                try:
                    conn = get_connection()
                    conn.execute(
                        """
                        UPDATE jobs
                        SET application_url = ?
                        WHERE url = ?
                        """,
                        (extracted, row_url),
                    )
                    conn.commit()
                except Exception:  # noqa: BLE001
                    logger.debug(
                        "failed to persist recovered apply URL for %s",
                        row_url[:80],
                        exc_info=True,
                    )
        return extracted

    if current:
        return current
    return (coerce_application_url(job.get("url")) or "").strip()


def _job_row_url(job: dict) -> str:
    """SQLite primary key for jobs — always job['url'], not application_url."""
    return (job.get("url") or _job_apply_url(job) or "").strip()


def job_has_direct_adapter(job: dict) -> bool:
    """True when the deterministic Playwright adapter can handle this URL."""
    from applypilot.apply.direct import fingerprint
    from applypilot.apply.direct.adapters import get_adapter

    return get_adapter(fingerprint.ats_family(_job_apply_url(job))) is not None


def job_runnable_in_deterministic_only(job: dict) -> bool:
    """True when Direct Apply may run without Claude (known adapter or content-sniff unknown)."""
    from applypilot.apply.direct import fingerprint
    from applypilot.apply.direct.adapters import get_adapter

    family = fingerprint.ats_family(_job_apply_url(job))
    return get_adapter(family) is not None or family == fingerprint.UNKNOWN_FAMILY


def _persist_needs_adapter(conn, row: dict, detail: str) -> None:
    """Mark job needs_adapter inside acquire_job (reversible, not attempts=99)."""
    url = row["url"]
    conn.execute(
        """
        UPDATE jobs
        SET apply_status = 'needs_adapter',
            apply_error = ?,
            apply_not_before = NULL,
            agent_id = NULL
        WHERE url = ?
        """,
        (detail.strip()[:200], url),
    )
    conn.commit()
    apply_budget.governor().note_parked_needs_adapter()


def _job_pending_claude_rescue(job: dict) -> bool:
    return str(job.get("apply_error") or "").startswith("pending_claude_rescue")


def _should_defer_claude_rescue(
    job: dict,
    *,
    min_score: int | None = None,
    ats_only: bool = False,
    priority_boards_only: bool = False,
    include_untailored: bool = False,
) -> bool:
    """Defer inline Claude only while other direct-capable jobs still need Playwright.

    Jobs already marked pending_claude_rescue must not be deferred again (otherwise
    they spin forever while any direct URL remains in the DB). Jobs with no direct
    adapter must run Claude immediately when this worker holds them.
    """
    if apply_settings.deterministic_only_enabled() or not apply_budget.governor().claude_allowed():
        return False
    if count_acquirable_direct_adapter_jobs(
        min_score=min_score,
        ats_only=ats_only,
        priority_boards_only=priority_boards_only,
        include_untailored=include_untailored,
    ) <= 0:
        return False
    if _job_pending_claude_rescue(job):
        return False
    if not job_has_direct_adapter(job):
        return False
    return True


def count_acquirable_direct_adapter_jobs(
    *,
    min_score: int | None = None,
    ats_only: bool = False,
    priority_boards_only: bool = False,
    include_untailored: bool = False,
) -> int:
    """Acquirable jobs that still need a direct Playwright attempt (not parked for Claude)."""
    direct_tier = direct_adapter_priority_sql()
    where, params = _acquirable_jobs_where(
        min_score=min_score,
        ats_only=ats_only,
        priority_boards_only=priority_boards_only,
        include_untailored=include_untailored,
    )
    conn = get_connection()
    row = conn.execute(
        f"""
        SELECT COUNT(*) FROM jobs
        {where}
          AND ({direct_tier}) = 0
          AND COALESCE(apply_error, '') NOT LIKE 'pending_claude_rescue%'
        """,
        params,
    ).fetchone()
    return int(row[0] or 0)


def count_acquirable_jobs(
    *,
    min_score: int | None = None,
    ats_only: bool = False,
    priority_boards_only: bool = False,
    include_untailored: bool = False,
) -> int:
    """Count jobs matching acquire_job SQL filters (eligibility may skip more at runtime)."""
    where, params = _acquirable_jobs_where(
        min_score=min_score,
        ats_only=ats_only,
        priority_boards_only=priority_boards_only,
        include_untailored=include_untailored,
    )
    conn = get_connection()
    return int(conn.execute(f"SELECT COUNT(*) FROM jobs {where}", params).fetchone()[0])


def apply_queue_snapshot() -> dict[str, int]:
    """Summarize why the apply queue may look empty."""
    conn = get_connection()
    max_attempts = int(config.DEFAULTS["max_apply_attempts"])
    row = conn.execute(
        """
        SELECT
          SUM(CASE WHEN tailored_resume_path IS NOT NULL AND applied_at IS NULL
                    THEN 1 ELSE 0 END),
          SUM(CASE WHEN apply_status = 'in_progress' THEN 1 ELSE 0 END),
          SUM(CASE WHEN apply_status = 'failed'
                    AND COALESCE(apply_attempts, 0) >= ?
                    AND COALESCE(apply_attempts, 0) < 99 THEN 1 ELSE 0 END),
          SUM(CASE WHEN apply_status = 'failed'
                    AND COALESCE(apply_attempts, 0) < 99 THEN 1 ELSE 0 END),
          SUM(CASE WHEN apply_status = 'failed'
                    AND COALESCE(apply_attempts, 0) >= 99 THEN 1 ELSE 0 END),
          SUM(CASE WHEN apply_status = 'submitted_unverified' THEN 1 ELSE 0 END),
          SUM(CASE WHEN apply_status = 'manual' THEN 1 ELSE 0 END),
          SUM(CASE WHEN apply_status = 'needs_adapter' THEN 1 ELSE 0 END)
        FROM jobs
        """,
        (max_attempts,),
    ).fetchone()
    return {
        "tailored_pending": int(row[0] or 0),
        "in_progress": int(row[1] or 0),
        "failed_exhausted": int(row[2] or 0),
        "failed_resettable": int(row[3] or 0),
        "failed_permanent": int(row[4] or 0),
        "submitted_unverified": int(row[5] or 0),
        "manual": int(row[6] or 0),
        "needs_adapter": int(row[7] or 0),
    }


def format_apply_queue_hint(
    *,
    min_score: int | None = None,
    ats_only: bool = False,
    priority_boards_only: bool = False,
    include_untailored: bool = False,
) -> str:
    """Human-readable hint when apply cannot start."""
    snap = apply_queue_snapshot()
    acquirable = count_acquirable_jobs(
        min_score=min_score,
        ats_only=ats_only,
        priority_boards_only=priority_boards_only,
        include_untailored=include_untailored,
    )
    lines = [
        f"Acquirable now (score/min filters): {acquirable}",
        f"Tailored, not applied: {snap['tailored_pending']}",
        f"In progress (stale locks cleared on start): {snap['in_progress']}",
        f"Failed — retryable with --reset-failed: {snap['failed_resettable']}",
        f"Failed — hit max attempts ({config.DEFAULTS['max_apply_attempts']}): {snap['failed_exhausted']}",
        f"Failed — permanent/skip (attempts=99): {snap['failed_permanent']}",
        f"Needs check (submitted_unverified): {snap['submitted_unverified']}",
        f"Manual apply only: {snap['manual']}",
        f"Parked — needs adapter (re-queue when shipped): {snap['needs_adapter']}",
    ]
    if acquirable == 0 and snap["failed_resettable"] > 0:
        lines.append(
            "Try: applypilot apply --reset-failed   (or --reset-pre-filter for attempts=99 skips)"
        )
    if snap["tailored_pending"] == 0:
        lines.append("Run: applypilot run score tailor cover pdf")
    return "\n".join(lines)


def _persist_resume_pdf_missing(conn, row: dict, detail: str) -> None:
    """Skip jobs whose tailored resume has no PDF and cannot be generated."""
    url = row["url"]
    conn.execute(
        """
        UPDATE jobs SET apply_status = 'failed', apply_error = ?,
                       apply_attempts = 99, agent_id = NULL
        WHERE url = ?
        """,
        (detail, url),
    )
    conn.commit()
    logger.info("Skipping job — resume PDF missing: %s", url[:80])


def acquire_job(
    target_url: str | None = None,
    min_score: int | None = None,
    worker_id: int = 0,
    ats_only: bool = False,
    priority_boards_only: bool = False,
    min_experience_years: int | None = None,
    include_untailored: bool = False,
) -> dict | None:
    """Atomically acquire the next job to apply to.

    Args:
        target_url: Apply to a specific URL instead of picking from queue.
        min_score: Minimum fit_score threshold.
        worker_id: Worker claiming this job (for tracking).

    Returns:
        Job dict or None if the queue is empty.
    """
    conn = get_connection()
    try:
        try:
            apply_profile = config.load_profile()
        except Exception:
            apply_profile = {}
        if min_score is None:
            min_score = int(config.DEFAULTS.get("apply_min_score", 0))
        conn.execute("BEGIN IMMEDIATE")

        while True:
            if target_url:
                like = f"%{target_url.split('?')[0].rstrip('/')}%"
                if include_untailored or role_resumes_available():
                    tailored_clause = ""
                else:
                    tailored_clause = "AND tailored_resume_path IS NOT NULL"
                row = conn.execute("""
                    SELECT url, title, site, application_url, tailored_resume_path,
                           fit_score, location, full_description, cover_letter_path, salary,
                           strategy, score_role_key, score_jd_fit,
                           apply_status, apply_error, apply_attempts
                    FROM jobs
                    WHERE (url = ? OR application_url = ? OR application_url LIKE ? OR url LIKE ?)
                      {tailored_clause}
                      AND applied_at IS NULL
                      AND (
                        apply_status IS NULL
                        OR apply_status NOT IN ('in_progress', 'applied', 'submitted_unverified')
                      )
                    LIMIT 1
                """.format(tailored_clause=tailored_clause), (target_url, target_url, like, like)).fetchone()
            else:
                where, params = _acquirable_jobs_where(
                    min_score=min_score,
                    ats_only=ats_only,
                    priority_boards_only=priority_boards_only,
                    include_untailored=include_untailored,
                )
                use_direct = apply_settings.apply_engine() == "direct"
                if use_direct:
                    from applypilot.apply.direct.throttle import check_caps

                row = None
                job_row = None
                offset = 0
                while row is None:
                    candidates = conn.execute(
                        f"""
                        SELECT url, title, site, application_url, tailored_resume_path,
                               fit_score, location, full_description, cover_letter_path, salary,
                               strategy, score_role_key, score_jd_fit,
                               apply_status, apply_error, apply_attempts
                        FROM jobs
                        {where}
                        ORDER BY {acquire_job_order_sql()}
                        LIMIT ? OFFSET ?
                        """,
                        (*params, ACQUIRE_CANDIDATE_BATCH, offset),
                    ).fetchall()
                    if not candidates:
                        break
                    for cand in candidates:
                        job_cand = dict(cand)
                        if use_direct and job_has_direct_adapter(job_cand):
                            allowed, _cap = check_caps(
                                _job_apply_url(job_cand), conn=conn
                            )
                            if not allowed:
                                continue
                        candidate_row = dict(cand)
                        eligibility = classify_apply_target(
                            candidate_row,
                            ats_only=ats_only,
                            profile=apply_profile,
                            min_experience_years=min_experience_years,
                        )
                        if eligibility.decision != ApplyDecision.ELIGIBLE:
                            _persist_ineligible_job(conn, candidate_row, eligibility)
                            continue
                        resolution = resolve_job_resume(
                            candidate_row,
                            allow_base=include_untailored,
                        )
                        resume_path = resolution.path
                        if not resume_path:
                            detail = (
                                "needs_tailor"
                                if resolution.source == "needs_tailor"
                                else "resume_unresolved"
                            )
                            _persist_resume_pdf_missing(conn, candidate_row, detail)
                            continue
                        try:
                            prompt_mod.ensure_resume_pdf(resume_path)
                        except (ValueError, OSError) as exc:
                            logger.warning(
                                "Resume PDF not ready for %s: %s",
                                candidate_row.get("url", "")[:80],
                                exc,
                            )
                            _persist_resume_pdf_missing(
                                conn, candidate_row, "resume_pdf_missing"
                            )
                            continue
                        if resume_path:
                            candidate_row["tailored_resume_path"] = resume_path
                        if apply_settings.deterministic_only_enabled() and use_direct:
                            status = str(candidate_row.get("apply_status") or "")
                            if status == "needs_adapter":
                                if not job_runnable_in_deterministic_only(
                                    candidate_row
                                ):
                                    continue
                            elif not job_runnable_in_deterministic_only(
                                candidate_row
                            ):
                                _persist_needs_adapter(
                                    conn,
                                    candidate_row,
                                    "deterministic_only",
                                )
                                continue
                        row = cand
                        job_row = candidate_row
                        break
                    if row is not None:
                        break
                    offset += ACQUIRE_CANDIDATE_BATCH

            if not row:
                conn.rollback()
                return None

            if target_url:
                job_row = dict(row)
                eligibility = classify_apply_target(
                    job_row,
                    ats_only=ats_only,
                    profile=apply_profile,
                    min_experience_years=min_experience_years,
                )
                if eligibility.decision != ApplyDecision.ELIGIBLE:
                    _persist_ineligible_job(conn, job_row, eligibility)
                    conn.commit()
                    return None
                resolution = resolve_job_resume(
                    job_row,
                    allow_base=include_untailored,
                )
                resume_path = resolution.path
                if not resume_path:
                    detail = (
                        "needs_tailor"
                        if resolution.source == "needs_tailor"
                        else "resume_unresolved"
                    )
                    _persist_resume_pdf_missing(conn, job_row, detail)
                    conn.commit()
                    return None
                try:
                    prompt_mod.ensure_resume_pdf(resume_path)
                except (ValueError, OSError) as exc:
                    logger.warning(
                        "Resume PDF not ready for %s: %s",
                        job_row.get("url", "")[:80],
                        exc,
                    )
                    _persist_resume_pdf_missing(conn, job_row, "resume_pdf_missing")
                    conn.commit()
                    return None
                if resume_path:
                    job_row["tailored_resume_path"] = resume_path

            now = datetime.now(timezone.utc).isoformat()
            conn.execute("""
                UPDATE jobs SET apply_status = 'in_progress',
                               agent_id = ?,
                               last_attempted_at = ?
                WHERE url = ?
            """, (f"worker-{worker_id}", now, row["url"]))
            conn.commit()

            return job_row
    except Exception:
        conn.rollback()
        raise


def mark_result(url: str, status: str, error: str | None = None,
                permanent: bool = False, duration_ms: int | None = None,
                task_id: str | None = None,
                log_path: str | Path | None = None) -> None:
    """Update a job's apply status in the database."""
    import json

    from applypilot.apply.apply_log_parser import (
        form_filled_from_log_text,
        extract_result_json,
        extract_first_external_apply_url_from_log,
    )

    conn = get_connection()
    now = datetime.now(timezone.utc).isoformat()
    log_value = str(log_path) if log_path else None
    form_json: str | None = None
    company_apply_url: str | None = None
    if log_path:
        path = Path(log_path)
        if path.is_file():
            try:
                log_text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                log_text = ""
            if log_text:
                result_json = extract_result_json(log_text) or {}
                raw_company = str(result_json.get("company_apply_url") or "").strip()
                if raw_company.startswith(("http://", "https://")):
                    company_apply_url = raw_company
                if not company_apply_url:
                    company_apply_url = extract_first_external_apply_url_from_log(log_text)
                record = form_filled_from_log_text(log_text)
                if record:
                    form_json = json.dumps(record, ensure_ascii=False)

    if company_apply_url:
        conn.execute(
            "UPDATE jobs SET application_url = COALESCE(?, application_url) WHERE url = ?",
            (company_apply_url, url),
        )

    if status == "applied":
        conn.execute("""
            UPDATE jobs SET apply_status = 'applied', applied_at = ?,
                           apply_error = NULL, agent_id = NULL,
                           apply_duration_ms = ?, apply_task_id = ?,
                           apply_log_path = COALESCE(?, apply_log_path),
                           apply_form_filled = COALESCE(?, apply_form_filled),
                           verification_confidence = COALESCE(verification_confidence, 'gmail_confirmed'),
                           apply_not_before = NULL
            WHERE url = ?
        """, (now, duration_ms, task_id, log_value, form_json, url))
    elif status == "submitted_unverified":
        conn.execute("""
            UPDATE jobs SET apply_status = 'submitted_unverified', applied_at = ?,
                           apply_error = ?, apply_attempts = COALESCE(apply_attempts, 0) + 1,
                           agent_id = NULL, apply_duration_ms = ?, apply_task_id = ?,
                           apply_log_path = COALESCE(?, apply_log_path),
                           apply_form_filled = COALESCE(?, apply_form_filled)
            WHERE url = ?
        """, (now, error or "unverified", duration_ms, task_id, log_value, form_json, url))
    elif permanent:
        # Permanent skip: park hard (attempts=99) and clear any retry window.
        conn.execute("""
            UPDATE jobs SET apply_status = ?, apply_error = ?,
                           apply_attempts = 99, agent_id = NULL,
                           apply_not_before = NULL,
                           apply_duration_ms = ?, apply_task_id = ?,
                           apply_log_path = COALESCE(?, apply_log_path),
                           apply_form_filled = COALESCE(?, apply_form_filled)
            WHERE url = ?
        """, (status, error or "unknown", duration_ms, task_id, log_value, form_json, url))
    else:
        # Retryable failure: increment attempts AND set a cooldown so the same
        # job is not re-acquired in a tight loop during a continuous/overnight run.
        cooldown_h = apply_settings.apply_retry_cooldown_hours()
        not_before = (
            datetime.now(timezone.utc) + timedelta(hours=cooldown_h)
        ).isoformat()
        conn.execute("""
            UPDATE jobs SET apply_status = ?, apply_error = ?,
                           apply_attempts = COALESCE(apply_attempts, 0) + 1,
                           agent_id = NULL, apply_not_before = ?,
                           apply_duration_ms = ?, apply_task_id = ?,
                           apply_log_path = COALESCE(?, apply_log_path),
                           apply_form_filled = COALESCE(?, apply_form_filled)
            WHERE url = ?
        """, (status, error or "unknown", not_before, duration_ms, task_id, log_value, form_json, url))
    conn.commit()


def release_lock(url: str) -> None:
    """Release the in_progress lock without changing status."""
    conn = get_connection()
    conn.execute(
        "UPDATE jobs SET apply_status = NULL, agent_id = NULL WHERE url = ? AND apply_status = 'in_progress'",
        (url,),
    )
    conn.commit()


def release_stale_locks(max_age_minutes: int = 45) -> int:
    """Release in_progress locks left by crashed workers."""
    conn = get_connection()
    cur = conn.execute(
        """
        UPDATE jobs
        SET apply_status = NULL, agent_id = NULL
        WHERE apply_status = 'in_progress'
          AND last_attempted_at IS NOT NULL
          AND datetime(last_attempted_at) < datetime('now', ?)
        """,
        (f"-{max_age_minutes} minutes",),
    )
    conn.commit()
    return cur.rowcount


def release_orphan_in_progress_locks() -> int:
    """Mark interrupted in_progress jobs failed so they are not re-acquired at attempts=0."""
    conn = get_connection()
    cur = conn.execute(
        """
        UPDATE jobs SET apply_status = 'failed',
                       apply_error = COALESCE(apply_error, 'worker_interrupted'),
                       apply_attempts = COALESCE(apply_attempts, 0) + 1,
                       agent_id = NULL
        WHERE apply_status = 'in_progress'
        """
    )
    conn.commit()
    return cur.rowcount


# ---------------------------------------------------------------------------
# Utility modes (--gen, --mark-applied, --mark-failed, --reset-failed)
# ---------------------------------------------------------------------------

def gen_prompt(
    target_url: str,
    min_score: int = 7,
    model: str = "haiku",
    worker_id: int = 0,
    include_untailored: bool = False,
) -> Path | None:
    """Generate a prompt file and print the Claude CLI command for manual debugging.

    Returns:
        Path to the generated prompt file, or None if no job found.
    """
    job = acquire_job(
        target_url=target_url,
        min_score=min_score,
        worker_id=worker_id,
        include_untailored=include_untailored,
    )
    if not job:
        return None

    resume_text = resolve_job_resume_text(job, allow_base=False)
    prompt = prompt_mod.build_prompt(job=job, tailored_resume=resume_text)

    # Release the lock so the job stays available
    release_lock(job["url"])

    # Write prompt file
    config.ensure_dirs()
    site_slug = (job.get("site") or "unknown")[:20].replace(" ", "_")
    prompt_file = config.LOG_DIR / f"prompt_{site_slug}_{job['title'][:30].replace(' ', '_')}.txt"
    prompt_file.write_text(prompt, encoding="utf-8")

    # Write MCP config for reference
    port = BASE_CDP_PORT + worker_id
    mcp_path = config.APP_DIR / f".mcp-apply-{worker_id}.json"
    mcp_path.write_text(json.dumps(_make_mcp_config(port)), encoding="utf-8")

    return prompt_file


def mark_job(url: str, status: str, reason: str | None = None) -> None:
    """Manually mark a job's apply status in the database.

    Args:
        url: Job URL to mark.
        status: Either 'applied' or 'failed'.
        reason: Failure reason (only for status='failed').
    """
    conn = get_connection()
    now = datetime.now(timezone.utc).isoformat()
    if status == "applied":
        conn.execute("""
            UPDATE jobs SET apply_status = 'applied', applied_at = ?,
                           apply_error = NULL, agent_id = NULL
            WHERE url = ? OR application_url = ?
        """, (now, url, url))
    else:
        conn.execute("""
            UPDATE jobs SET apply_status = 'failed', apply_error = ?,
                           apply_attempts = 99, agent_id = NULL
            WHERE url = ? OR application_url = ?
        """, (reason or "manual", url, url))
    conn.commit()


def reset_failed() -> int:
    """Reset failed jobs for retry (excludes permanent skips with apply_attempts=99).

    Returns:
        Number of jobs reset.
    """
    conn = get_connection()
    cursor = conn.execute(
        """
        UPDATE jobs SET apply_status = NULL, apply_error = NULL,
                       apply_attempts = 0, agent_id = NULL
        WHERE apply_status = 'failed'
          AND COALESCE(apply_attempts, 0) < 99
        """
    )
    conn.commit()
    return cursor.rowcount


def reset_pre_filter_skips() -> int:
    """Re-queue tailored jobs stuck with apply_attempts=99 (pre-filter or old skips)."""
    conn = get_connection()
    cursor = conn.execute(
        """
        UPDATE jobs SET apply_status = NULL, apply_error = NULL,
                       apply_attempts = 0, agent_id = NULL
        WHERE tailored_resume_path IS NOT NULL
          AND applied_at IS NULL
          AND apply_status = 'failed'
          AND COALESCE(apply_attempts, 0) >= 99
        """,
    )
    conn.commit()
    return cursor.rowcount


def triage_apply_queue(
    *,
    min_score: int | None = None,
    min_experience_years: int | None = None,
) -> dict[str, int]:
    """Classify tailored jobs without launching Chrome; mark manual / permanent skip.

    Reclassifies never-tried and retryable failed rows so the dashboard ready count
    matches what auto-apply will actually pick up.
    """
    conn = get_connection()
    max_attempts = config.DEFAULTS["max_apply_attempts"]
    if min_score is None:
        min_score = int(config.DEFAULTS.get("apply_min_score", 5))
    try:
        profile = config.load_profile()
    except Exception:
        profile = {}
    rows = conn.execute(
        """
        SELECT url, title, site, application_url, tailored_resume_path,
               fit_score, location, full_description, cover_letter_path, salary,
               strategy, apply_status, apply_error, apply_attempts
        FROM jobs
        WHERE tailored_resume_path IS NOT NULL
          AND applied_at IS NULL
          AND (
            apply_status IS NULL
            OR apply_status IN ('failed', 'manual')
          )
          AND (apply_attempts IS NULL OR apply_attempts < ?)
          AND fit_score >= ?
        """,
        (max_attempts, min_score),
    ).fetchall()

    summary: dict[str, int] = {
        "scanned": 0,
        "eligible": 0,
        "marked_manual": 0,
        "marked_permanent": 0,
        "unchanged": 0,
    }
    for row in rows:
        summary["scanned"] += 1
        job = dict(row)
        result = classify_apply_target(
            job,
            min_experience_years=min_experience_years,
            profile=profile,
            strict=True,
        )
        if result.decision == ApplyDecision.ELIGIBLE:
            summary["eligible"] += 1
            if job.get("apply_status") in ("failed", "manual") and (
                job.get("apply_attempts", 0) or 0
            ) < 99:
                conn.execute(
                    """
                    UPDATE jobs SET apply_status = NULL, apply_error = NULL,
                                   apply_attempts = 0, agent_id = NULL
                    WHERE url = ?
                    """,
                    (job["url"],),
                )
                if job.get("apply_status") == "manual":
                    summary["reopened_manual"] = summary.get("reopened_manual", 0) + 1
            continue
        if result.decision == ApplyDecision.MANUAL:
            if (
                job.get("apply_status") == "manual"
                and (job.get("apply_error") or "") == (result.reason or "manual")
            ):
                summary["unchanged"] += 1
                continue
            _persist_ineligible_job(conn, job, result)
            summary["marked_manual"] += 1
            continue
        if result.decision == ApplyDecision.SKIP_PERMANENT:
            if (
                job.get("apply_status") == "failed"
                and job.get("apply_error") == result.reason
                and job.get("apply_attempts") == 99
            ):
                summary["unchanged"] += 1
                continue
            _persist_ineligible_job(conn, job, result)
            summary["marked_permanent"] += 1
    conn.commit()
    return summary


# ---------------------------------------------------------------------------
# Per-job execution
# ---------------------------------------------------------------------------

def _resolve_apply_result(
    output: str,
    worker_id: int,
    job: dict,
    elapsed: int,
    job_log: Path,
) -> str:
    """Map agent output to launcher result string (with Tier 1 verification)."""
    from applypilot.apply.apply_log_parser import extract_result_json, parse_apply_log
    from applypilot.apply.verification import VerificationRecord, evaluate as verify_apply

    def _clean_reason(s: str) -> str:
        return re.sub(r'[*`"]+$', '', s).strip()

    result_json = extract_result_json(output)
    if result_json:
        parsed = parse_apply_log(output)
        record = VerificationRecord(
            status=str(result_json.get("status", "failed")),
            submit_click_ref=result_json.get("submit_click_ref"),
            submit_button_text=result_json.get("submit_button_text"),
            pre_submit_url=result_json.get("pre_submit_url"),
            post_submit_url=result_json.get("post_submit_url"),
            post_submit_snapshot=result_json.get("post_submit_snapshot"),
            confirmation_copy=result_json.get("confirmation_copy"),
            screenshot_path=result_json.get("screenshot_path"),
            verification_code_used=result_json.get("verification_code_used"),
            fill_actions=parsed["fill_actions"],
        )
        verdict = verify_apply(record)

        if record.status == "applied":
            if verdict.decision == "verified":
                if apply_settings.require_gmail_confirmation():
                    from applypilot.apply.gmail_auth import wait_for_application_receipt

                    receipt = wait_for_application_receipt(job)
                    if receipt.confirmed:
                        if receipt.message:
                            logger.info(
                                "Gmail receipt confirmed for %s via %s (%s)",
                                job.get("title"),
                                receipt.message.from_,
                                receipt.message.subject,
                            )
                        return "applied"
                    return f"submitted_unverified:{receipt.reason}"
                return "applied"
            if verdict.decision == "unverified":
                return "submitted_unverified:" + ";".join(verdict.reasons)

        status = record.status
        if status == "dry_run":
            return "failed:dry_run"
        if status in ("captcha", "login_issue", "expired"):
            return status
        if status == "failed":
            reason = _clean_reason(str(result_json.get("reason", "unknown")))
            return f"failed:{reason}"
        if status == "pause_for_human":
            reason = _clean_reason(str(result_json.get("reason", "pause_for_human")))
            return f"failed:{reason}"
        return f"failed:{status}"

    from applypilot.apply.playbook_results import resolve_playbook_result

    playbook_status = resolve_playbook_result(output)
    if playbook_status is not None:
        return playbook_status

    if "RESULT:APPLIED" in output:
        logger.warning(
            "[W%s] Legacy RESULT:APPLIED without RESULT_JSON for %s — downgrading to submitted_unverified",
            worker_id,
            job.get("title", "")[:30],
        )
        return "submitted_unverified:legacy RESULT:APPLIED without structured proof"

    for result_status in ["EXPIRED", "CAPTCHA", "LOGIN_ISSUE"]:
        if f"RESULT:{result_status}" in output:
            return result_status.lower()

    if "RESULT:FAILED" in output:
        for out_line in output.split("\n"):
            if "RESULT:FAILED" in out_line:
                reason = (
                    out_line.split("RESULT:FAILED:")[-1].strip()
                    if ":" in out_line[out_line.index("FAILED") + 6:]
                    else "unknown"
                )
                reason = _clean_reason(reason)
                promote = {"captcha", "expired", "login_issue"}
                if reason in promote:
                    return reason
                return f"failed:{reason}"
        return "failed:unknown"

    return "failed:no_result_line"


FAST_FAIL_TEXT_PATTERNS: dict[str, tuple[str, ...]] = {
    "claude_quota_exhausted": (
        "you've hit your limit",
        "you have hit your limit",
        "session limit · resets",
    ),
    "claude_auth_failed": (
        "please run `claude login`",
        "not authenticated",
        "invalid api key",
    ),
    "claude_stale_session": (
        "no conversation found with session",
    ),
}


def _detect_fast_fail(text: str) -> str | None:
    lower = text.lower()
    for reason, needles in FAST_FAIL_TEXT_PATTERNS.items():
        if any(n in lower for n in needles):
            return reason
    return None


def _stream_stdout_reader(stdout, q: queue.Queue) -> None:
    try:
        for line in stdout:
            q.put(("line", line))
    finally:
        q.put(("eof", None))


def _sync_worker_line(worker_id: int, detail: str, **state) -> None:
    """Update in-memory dashboard state and emit a line for web SSE."""
    update_state(worker_id, **state)
    status = state.get("status")
    if status is not None:
        logger.info("[worker-%d] status=%s %s", worker_id, status, detail)
    else:
        logger.info("[worker-%d] %s", worker_id, detail)


def run_job(
    job: dict,
    port: int,
    worker_id: int = 0,
    model: str = "haiku",
    dry_run: bool = False,
    pace_seconds: float = 0.0,
    confirm_submit: bool = False,
) -> tuple[str, int, Path | None]:
    """Spawn a Claude Code session for one job application.

    Returns:
        Tuple of (status_string, duration_ms, session_log_path). Status is one of:
        'applied', 'expired', 'captcha', 'login_issue',
        'failed:reason', or 'skipped'.
    """
    if not apply_budget.governor().claude_allowed():
        return "parked:needs_adapter:claude_budget_capped", 0, None

    resume_text = resolve_job_resume_text(job, allow_base=False)
    worker_dir = reset_worker_dir(worker_id)

    try:
        if apply_settings.apply_prompt_mode() == "playbook":
            from applypilot.apply import worker_playbook

            agent_prompt = worker_playbook.build_worker_apply_prompt(
                job,
                upload_dir=worker_dir,
            )
        else:
            agent_prompt = prompt_mod.build_prompt(
                job=job,
                tailored_resume=resume_text,
                dry_run=dry_run,
                pace_seconds=pace_seconds,
                confirm_submit=confirm_submit,
                upload_dir=worker_dir,
            )
    except ValueError as exc:
        msg = str(exc)
        if "resume" in msg.lower() or "tailored" in msg.lower():
            logger.warning("Cannot build apply prompt for %s: %s", job.get("url", "")[:80], msg)
            return "failed:resume_pdf_missing", 0, None
        raise

    include_gmail = apply_settings.job_likely_needs_gmail(job)
    mcp_config_path = config.APP_DIR / f".mcp-apply-{worker_id}.json"
    mcp_config_path.write_text(
        json.dumps(_make_mcp_config(port, include_gmail=include_gmail)),
        encoding="utf-8",
    )

    cmd = build_claude_apply_command(
        model=model,
        mcp_config_path=mcp_config_path,
        worker_id=worker_id,
    )

    env = os.environ.copy()
    env.pop("CLAUDECODE", None)
    env.pop("CLAUDE_CODE_ENTRYPOINT", None)

    update_state(worker_id, status="applying", job_title=job["title"],
                 company=job.get("site", ""), score=job.get("fit_score", 0),
                 start_time=time.time(), actions=0, last_action="starting")
    add_event(f"[W{worker_id}] Starting: {job['title'][:40]} @ {job.get('site', '')}")

    worker_log = config.LOG_DIR / f"worker-{worker_id}.log"
    ts_header = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_header = (
        f"\n{'=' * 60}\n"
        f"[{ts_header}] {job['title']} @ {job.get('site', '')}\n"
        f"URL: {job.get('application_url') or job['url']}\n"
        f"Score: {job.get('fit_score', 'N/A')}/10\n"
        f"{'=' * 60}\n"
    )

    start = time.time()
    stats: dict = {}
    proc = None
    # Track Claude spawn so the per-run governor counts EVERY attempt (incl.
    # timeouts / quota / inactivity aborts), not just runs that emit usage stats.
    claude_spawned = False
    claude_cost_seen = 0.0

    try:
        popen_kwargs: dict = {}
        if platform.system() != "Windows":
            popen_kwargs["start_new_session"] = True
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            cwd=str(worker_dir),
            **popen_kwargs,
        )
        with _claude_lock:
            _claude_procs[worker_id] = proc
        claude_spawned = True

        proc.stdin.write(agent_prompt)
        proc.stdin.close()

        inactivity = config.DEFAULTS.get("apply_inactivity_timeout", 120)
        wall_deadline = start + config.DEFAULTS["apply_timeout"]
        stream_q: queue.Queue = queue.Queue()
        reader = threading.Thread(
            target=_stream_stdout_reader,
            args=(proc.stdout, stream_q),
            daemon=True,
        )
        reader.start()

        def _abort_apply(reason: str) -> tuple[str, int, None]:
            add_event(f"[W{worker_id}] {reason.upper().replace('_', ' ')}")
            nonlocal proc
            if proc is not None and proc.poll() is None:
                _kill_process_tree(proc.pid)
            proc = None
            return (
                f"failed:{reason}",
                int((time.time() - start) * 1000),
                None,
            )

        def _abort_quota(text_hint: str) -> tuple[str, int, None]:
            not_before = _parse_quota_reset_not_before(text_hint) or _quota_backoff_not_before()
            add_event(f"[W{worker_id}] FAST_FAIL: claude_quota_exhausted until {not_before}")
            apply_settings.clear_session_id(worker_id)
            nonlocal proc
            if proc is not None and proc.poll() is None:
                _kill_process_tree(proc.pid)
            proc = None
            return (
                f"failed:claude_quota_exhausted:{not_before}",
                int((time.time() - start) * 1000),
                None,
            )

        def _abort_stale_session() -> tuple[str, int, None]:
            add_event(f"[W{worker_id}] FAST_FAIL: claude_stale_session (clearing persisted id)")
            apply_settings.clear_session_id(worker_id)
            nonlocal proc
            if proc is not None and proc.poll() is None:
                _kill_process_tree(proc.pid)
            proc = None
            return (
                "failed:claude_stale_session",
                int((time.time() - start) * 1000),
                None,
            )

        text_parts: list[str] = []
        with open(worker_log, "a", encoding="utf-8") as lf:
            lf.write(log_header)

            while True:
                if time.time() > wall_deadline:
                    return _abort_apply("wall_timeout")

                try:
                    kind, item = stream_q.get(timeout=inactivity)
                except queue.Empty:
                    return _abort_apply("inactivity_timeout")

                if kind == "eof":
                    break

                line = item.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                    if sid := apply_settings.parse_session_id_from_message(msg):
                        apply_settings.save_session_id(worker_id, sid)
                    msg_type = msg.get("type")
                    if msg_type == "assistant":
                        for block in msg.get("message", {}).get("content", []):
                            bt = block.get("type")
                            if bt == "text":
                                text = block["text"]
                                text_parts.append(text)
                                lf.write(text + "\n")
                                if fail_reason := _detect_fast_fail(text):
                                    if fail_reason == "claude_quota_exhausted":
                                        return _abort_quota(text)
                                    if fail_reason == "claude_stale_session":
                                        return _abort_stale_session()
                                    add_event(f"[W{worker_id}] FAST_FAIL: {fail_reason}")
                                    return _abort_apply(fail_reason)
                            elif bt == "tool_use":
                                name = (
                                    block.get("name", "")
                                    .replace("mcp__playwright__", "")
                                    .replace("mcp__gmail__", "gmail:")
                                )
                                inp = block.get("input", {})
                                if "url" in inp:
                                    desc = f"{name} {inp['url'][:60]}"
                                elif "ref" in inp:
                                    desc = f"{name} {inp.get('element', inp.get('text', ''))}"[:50]
                                elif "fields" in inp:
                                    desc = f"{name} ({len(inp['fields'])} fields)"
                                elif "paths" in inp:
                                    desc = f"{name} upload"
                                else:
                                    desc = name

                                lf.write(f"  >> {desc}\n")
                                ws = get_state(worker_id)
                                cur_actions = ws.actions if ws else 0
                                update_state(worker_id,
                                             actions=cur_actions + 1,
                                             last_action=desc[:35])
                    elif msg_type == "result":
                        stats = {
                            "input_tokens": msg.get("usage", {}).get("input_tokens", 0),
                            "output_tokens": msg.get("usage", {}).get("output_tokens", 0),
                            "cache_read": msg.get("usage", {}).get("cache_read_input_tokens", 0),
                            "cache_create": msg.get("usage", {}).get("cache_creation_input_tokens", 0),
                            "cost_usd": msg.get("total_cost_usd", 0),
                            "turns": msg.get("num_turns", 0),
                        }
                        text_parts.append(msg.get("result", ""))
                except json.JSONDecodeError:
                    text_parts.append(line)
                    lf.write(line + "\n")
                    if fail_reason := _detect_fast_fail(line):
                        if fail_reason == "claude_quota_exhausted":
                            return _abort_quota(line)
                        if fail_reason == "claude_stale_session":
                            return _abort_stale_session()
                        add_event(f"[W{worker_id}] FAST_FAIL: {fail_reason}")
                        return _abort_apply(fail_reason)

        remaining = max(0.1, wall_deadline - time.time())
        proc.wait(timeout=remaining)
        returncode = proc.returncode
        proc = None

        if returncode and returncode < 0:
            return "skipped", int((time.time() - start) * 1000), None

        output = "\n".join(text_parts)
        elapsed = int(time.time() - start)
        duration_ms = int((time.time() - start) * 1000)

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        job_log = config.LOG_DIR / f"claude_{ts}_w{worker_id}_{job.get('site', 'unknown')[:20]}.txt"
        job_log.write_text(output, encoding="utf-8")

        if stats:
            claude_cost_seen = float(stats.get("cost_usd") or 0.0)
            try:
                from applypilot.database import record_llm_usage

                telemetry = apply_settings.apply_telemetry_flags()
                record_llm_usage(
                    provider="anthropic",
                    model=model,
                    operation="apply",
                    input_tokens=int(stats.get("input_tokens") or 0),
                    output_tokens=int(stats.get("output_tokens") or 0),
                    cache_read_tokens=int(stats.get("cache_read") or 0),
                    cache_create_tokens=int(stats.get("cache_create") or 0),
                    estimated=False,
                    cost_usd=float(stats.get("cost_usd") or 0.0),
                    metadata={
                        **telemetry,
                        "worker_id": worker_id,
                        "job_url": job.get("url"),
                        "site": job.get("site"),
                        "model_used": model,
                        "num_turns": int(stats.get("turns") or 0),
                    },
                )
            except Exception:
                logger.debug("Failed to record apply cost telemetry", exc_info=True)
            cost = stats.get("cost_usd", 0)
            ws = get_state(worker_id)
            prev_cost = ws.total_cost if ws else 0.0
            update_state(worker_id, total_cost=prev_cost + cost)

        result = _resolve_apply_result(output, worker_id, job, elapsed, job_log)

        if result == "applied":
            add_event(f"[W{worker_id}] APPLIED ({elapsed}s): {job['title'][:30]}")
            update_state(worker_id, status="applied",
                         last_action=f"APPLIED ({elapsed}s)")
            return "applied", duration_ms, job_log

        if result.startswith("submitted_unverified"):
            reasons = result.split(":", 1)[-1] if ":" in result else "unverified"
            add_event(f"[W{worker_id}] UNVERIFIED ({elapsed}s): {reasons[:60]}")
            update_state(worker_id, status="submitted_unverified",
                         last_action=f"UNVERIFIED ({elapsed}s)")
            return result, duration_ms, job_log

        if result in ("expired", "captcha", "login_issue"):
            label = result.upper()
            add_event(f"[W{worker_id}] {label} ({elapsed}s): {job['title'][:30]}")
            update_state(worker_id, status=result,
                         last_action=f"{label} ({elapsed}s)")
            return result, duration_ms, job_log

        if result.startswith("failed:"):
            reason = result.split(":", 1)[-1]
            add_event(f"[W{worker_id}] FAILED ({elapsed}s): {reason[:30]}")
            update_state(worker_id, status="failed",
                         last_action=f"FAILED: {reason[:25]}")
            return result, duration_ms, job_log

        from applypilot.apply.apply_log_parser import session_log_incomplete

        add_event(f"[W{worker_id}] NO RESULT ({elapsed}s)")
        update_state(worker_id, status="failed", last_action=f"no result ({elapsed}s)")
        if session_log_incomplete(job_log):
            return "failed:incomplete", duration_ms, job_log
        return "failed:no_result_line", duration_ms, job_log

    except subprocess.TimeoutExpired:
        duration_ms = int((time.time() - start) * 1000)
        elapsed = int(time.time() - start)
        add_event(f"[W{worker_id}] TIMEOUT ({elapsed}s)")
        update_state(worker_id, status="failed", last_action=f"TIMEOUT ({elapsed}s)")
        return "failed:timeout", duration_ms, None
    except Exception as e:
        duration_ms = int((time.time() - start) * 1000)
        add_event(f"[W{worker_id}] ERROR: {str(e)[:40]}")
        update_state(worker_id, status="failed", last_action=f"ERROR: {str(e)[:25]}")
        return f"failed:{str(e)[:100]}", duration_ms, None
    finally:
        # Count every spawned Claude run against the per-run cap exactly once,
        # even when an abort/timeout returned before usage stats were parsed.
        if claude_spawned:
            try:
                apply_budget.governor().record_claude_apply(claude_cost_seen)
            except Exception:
                logger.debug("Failed to record Claude apply in governor", exc_info=True)
        with _claude_lock:
            _claude_procs.pop(worker_id, None)
        if proc is not None and proc.poll() is None:
            _kill_process_tree(proc.pid)


# ---------------------------------------------------------------------------
# Permanent failure classification
# ---------------------------------------------------------------------------

PERMANENT_FAILURES: set[str] = {
    "expired", "captcha", "login_issue",
    "not_eligible_location", "not_eligible_salary", "not_eligible_experience",
    "not_eligible_sponsorship",
    "already_applied", "account_required",
    "not_a_job_application", "unsafe_permissions",
    "unsafe_verification",
    "site_blocked", "cloudflare_blocked", "blocked_by_cloudflare",
    "claude_auth_failed",
    "inactivity_timeout", "wall_timeout",
    "resume_pdf_missing",
}

# Do not burn apply_attempts or session-log-retry on these infrastructure outcomes.
QUOTA_SESSION_FAILURES: frozenset[str] = frozenset({"claude_quota_exhausted"})

PERMANENT_PREFIXES: tuple[str, ...] = ("site_blocked", "cloudflare", "blocked_by")


_QUOTA_RESET_TIME_RE = re.compile(
    r"resets\s+(?P<h>\d{1,2})(?::(?P<m>\d{2}))?\s*(?P<ampm>am|pm)",
    re.IGNORECASE,
)


def _parse_quota_reset_not_before(text: str) -> str | None:
    """Parse a quota reset hint into a UTC ISO timestamp."""
    match = _QUOTA_RESET_TIME_RE.search(text)
    if not match:
        return None

    hour = int(match.group("h"))
    minute = int(match.group("m") or "0")
    ampm = (match.group("ampm") or "").lower()

    if ampm == "pm" and hour != 12:
        hour += 12
    if ampm == "am" and hour == 12:
        hour = 0

    local_now = datetime.now().astimezone()
    candidate = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= local_now:
        candidate = candidate + timedelta(days=1)
    return candidate.astimezone(timezone.utc).isoformat()


def _quota_backoff_not_before() -> str:
    """Fallback backoff when no reset time is provided by Claude."""
    return (datetime.now(timezone.utc) + timedelta(hours=5)).isoformat()


def _parse_worker_result(result: str) -> tuple[str, str | None]:
    """Return (reason, detail) while preserving colon-heavy detail strings."""
    if result.startswith("failed:"):
        rest = result[len("failed:") :]
        if ":" in rest:
            reason, detail = rest.split(":", 1)
            return reason, detail
        return rest, None
    return result, None


def _park_job_for_retry(url: str, *, not_before: str, error: str) -> None:
    """Mark a job as retryable, but not acquirable until not_before."""
    conn = get_connection()
    row = conn.execute(
        "SELECT apply_error FROM jobs WHERE url = ?",
        (url,),
    ).fetchone()
    existing = str((row["apply_error"] if row else None) or "")
    if existing.startswith("pending_claude_rescue"):
        error = f"{existing} quota_retry_after={not_before}"
    conn.execute(
        """
        UPDATE jobs
        SET apply_status = 'failed',
            apply_error = ?,
            apply_not_before = ?,
            agent_id = NULL
        WHERE url = ?
        """,
        (error, not_before, url),
    )
    conn.commit()


def _park_job_needs_adapter(url: str, reason: str) -> None:
    """Park a job until a deterministic adapter exists (reversible, not attempts=99)."""
    detail = (reason or "no_adapter").strip()[:200]
    conn = get_connection()
    conn.execute(
        """
        UPDATE jobs
        SET apply_status = 'needs_adapter',
            apply_error = ?,
            apply_not_before = NULL,
            agent_id = NULL
        WHERE url = ?
        """,
        (detail, url),
    )
    conn.commit()
    apply_budget.governor().note_parked_needs_adapter()


def _park_job_awaiting_login(
    url: str,
    domain: str,
    *,
    reason: str = "login_required",
) -> None:
    """Park a job until the human logs into the provider (reversible)."""
    reason = (reason or "login_required").strip()[:80]
    detail = f"awaiting_login:{(domain or '').strip()[:120]};{reason}"
    conn = get_connection()
    conn.execute(
        """
        UPDATE jobs
        SET apply_status = 'awaiting_login',
            apply_error = ?,
            apply_not_before = NULL,
            agent_id = NULL
        WHERE url = ?
        """,
        (detail, url),
    )
    conn.commit()


def requeue_awaiting_login(domain: str | None = None) -> int:
    """Re-queue jobs parked awaiting_login (all, or one domain) after you log in."""
    conn = get_connection()
    if domain:
        cur = conn.execute(
            """
            UPDATE jobs SET apply_status = NULL, apply_error = NULL, agent_id = NULL
            WHERE apply_status = 'awaiting_login'
              AND COALESCE(apply_error, '') LIKE ?
            """,
            (f"awaiting_login:{domain.strip().lower()}%",),
        )
    else:
        cur = conn.execute(
            """
            UPDATE jobs SET apply_status = NULL, apply_error = NULL, agent_id = NULL
            WHERE apply_status = 'awaiting_login'
            """
        )
    conn.commit()
    return cur.rowcount


def resume_login(domain: str | None = None) -> dict:
    """Resume after login: clear the gate AND re-queue awaiting_login jobs.

    Called by the dashboard Resume button and the CLI/script.
    """
    from applypilot.apply import login_gate

    requeued = requeue_awaiting_login(domain)
    login_gate.resume(domain)
    return {"resumed_domain": domain or "all", "requeued": requeued}


def _defer_job_for_claude_rescue(url: str, reason: str) -> None:
    """Park job at the back of the queue for a later Claude pass (direct tier drained)."""
    detail = (reason or "escalated").strip()[:120]
    conn = get_connection()
    conn.execute(
        """
        UPDATE jobs
        SET apply_status = 'failed',
            apply_error = ?,
            apply_not_before = NULL,
            agent_id = NULL
        WHERE url = ?
        """,
        (f"pending_claude_rescue:{detail}", url),
    )
    conn.commit()


def repair_invalid_quota_retry_windows() -> int:
    """Release quota retry rows whose not-before timestamp is not SQLite-parseable."""
    conn = get_connection()
    cur = conn.execute(
        """
        UPDATE jobs
        SET apply_not_before = NULL,
            apply_error = COALESCE(apply_error, 'claude_quota_exhausted') || ' (retry window repaired)'
        WHERE apply_status = 'failed'
          AND apply_not_before IS NOT NULL
          AND datetime(apply_not_before) IS NULL
          AND COALESCE(apply_error, '') LIKE '%claude_quota_exhausted%'
        """
    )
    conn.commit()
    return cur.rowcount


def _is_permanent_failure(result: str) -> bool:
    """Determine if a failure should never be retried."""
    reason = result.split(":", 1)[-1] if ":" in result else result
    return (
        result in PERMANENT_FAILURES
        or reason in PERMANENT_FAILURES
        or any(reason.startswith(p) for p in PERMANENT_PREFIXES)
    )


def _pause_worker_for_quota(worker_id: int, *, not_before: str) -> None:
    """Briefly pause this worker after Claude quota; then continue with other jobs."""
    pause_msg = f"PAUSED: Claude quota — retry after {not_before}"
    _sync_worker_line(
        worker_id,
        pause_msg,
        status="paused_quota",
        last_action=pause_msg,
    )
    add_event(f"[W{worker_id}] {pause_msg}")
    pause_s = config.DEFAULTS.get("apply_quota_pause", 1800)
    try:
        target = datetime.fromisoformat(not_before.replace("Z", "+00:00"))
        sleep_s = max(0, (target - datetime.now(timezone.utc)).total_seconds())
        _stop_event.wait(timeout=min(float(pause_s), float(sleep_s)))
    except Exception:
        _stop_event.wait(timeout=pause_s)


# ---------------------------------------------------------------------------
# Worker loop
# ---------------------------------------------------------------------------

def _try_direct_apply(
    job: dict,
    *,
    port: int,
    worker_id: int,
    dry_run: bool,
    defer_claude_rescue: bool = False,
) -> tuple[str, int, Path | None] | None:
    """Attempt the deterministic Direct Apply engine ($0 Claude/apply).

    When defer_claude_rescue is True, jobs that would need Claude are parked at
    the back of the queue (pending_claude_rescue) so the worker can take the next
    direct-capable job instead of spending Claude budget inline.
    """
    from applypilot.apply.direct import fingerprint
    from applypilot.apply.direct.adapters import get_adapter
    from applypilot.apply.direct.throttle import check_caps, is_cap_defer
    from applypilot.database import record_apply_outcome

    row_url = _job_row_url(job)
    apply_url = _resolve_job_apply_url(job, persist=True)
    family = fingerprint.ats_family(apply_url)
    # 'unknown' may still be a content-detectable ATS (e.g. Greenhouse embedded on
    # a custom career domain like dropbox.jobs / stripe.com/jobs): let the Driver
    # navigate and content-sniff before giving up. Other adapter-less families
    # (workday, icims, ...) can't be rescued that way, so they defer/fail here.
    if get_adapter(family) is None and family != fingerprint.UNKNOWN_FAMILY:
        if (
            apply_settings.deterministic_only_enabled()
            or not apply_budget.governor().claude_allowed()
        ):
            _park_job_needs_adapter(row_url, f"no_adapter:{family}")
            return f"parked:needs_adapter:no_adapter:{family}", 0, None
        if defer_claude_rescue:
            add_event(
                f"[W{worker_id}] Direct: no adapter for {family} — "
                "deferred to Claude pass (direct queue first)"
            )
            _defer_job_for_claude_rescue(row_url, f"no_adapter:{family}")
            return f"deferred:claude_rescue:no_adapter:{family}", 0, None
        return f"failed:direct_no_adapter:{family}", 0, None

    allowed, cap_reason = check_caps(apply_url)
    if not allowed:
        add_event(f"[W{worker_id}] Direct: daily cap reached ({cap_reason})")
        return cap_reason, 0, None

    from applypilot.apply.direct.driver import DriverResult, apply_via_direct

    # Run the in-process Driver under a hard wall-clock guard: a hung Playwright
    # call on an unfamiliar form must not stall the worker overnight. On timeout
    # we abandon the (daemon) thread — the next launch_chrome recycles port 9222,
    # which unblocks and ends the orphan — and treat the job as escalatable.
    _holder: dict = {}

    def _run() -> None:
        try:
            _holder["dr"] = apply_via_direct(
                job, port=port, worker_id=worker_id, dry_run=dry_run
            )
        except Exception as exc:  # noqa: BLE001
            _holder["err"] = exc

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout=apply_settings.direct_job_timeout())
    fp = fingerprint.provider_fingerprint(apply_url)
    if t.is_alive():
        add_event(
            f"[W{worker_id}] Direct timed out "
            f"(> {apply_settings.direct_job_timeout():.0f}s)"
        )
        # Free the orphan: killing Chrome on this port makes the stuck
        # Playwright call raise, so the daemon thread unwinds instead of
        # lingering and blocking clean process exit.
        try:
            chrome._kill_on_port(port)
        except Exception:  # noqa: BLE001
            pass
        # Park (don't escalate): the orphan thread may still hold Chrome, so a
        # same-iteration Claude rescue could collide. Next pass relaunches Chrome
        # clean and retries the job.
        dr = DriverResult(
            result="failed:direct_timeout", escalate=False,
            escalate_reason="timeout", ats_family=family, fingerprint=fp,
        )
    elif "err" in _holder:
        dr = DriverResult(
            result="failed:direct_exception", escalate=True,
            escalate_reason=str(_holder["err"])[:80],
            ats_family=family, fingerprint=fp,
        )
    else:
        dr = _holder["dr"]

    would_claude_rescue = bool(dr.escalate)
    inline_claude = would_claude_rescue and apply_settings.direct_escalate_to_claude()
    if is_cap_defer(dr.result):
        return dr.result, dr.elapsed_ms, None
    try:
        record_apply_outcome(
            url=apply_url,
            ats_family=dr.ats_family or family,
            fingerprint=dr.fingerprint,
            result=dr.result,
            tier_resolved=dr.tier_resolved,
            escalated=inline_claude and not defer_claude_rescue,
            escalate_reason=dr.escalate_reason,
            fields_total=dr.fields_total,
            fields_llm=dr.fields_llm,
            elapsed_ms=dr.elapsed_ms,
        )
    except Exception:  # noqa: BLE001
        logger.debug("record_apply_outcome failed", exc_info=True)

    if dr.result.startswith("skipped"):
        return "skipped", dr.elapsed_ms, None
    if would_claude_rescue and (
        apply_settings.deterministic_only_enabled()
        or not apply_budget.governor().claude_allowed()
    ):
        reason = dr.escalate_reason or dr.result[:40]
        _park_job_needs_adapter(row_url, reason)
        return f"parked:needs_adapter:{reason}", dr.elapsed_ms, None
    if would_claude_rescue and defer_claude_rescue:
        reason = dr.escalate_reason or dr.result[:40]
        add_event(
            f"[W{worker_id}] Direct: deferred Claude rescue ({reason}) — next job"
        )
        _defer_job_for_claude_rescue(row_url, reason)
        return f"deferred:claude_rescue:{reason}", dr.elapsed_ms, None
    if inline_claude and would_claude_rescue:
        add_event(
            f"[W{worker_id}] Direct -> Claude rescue "
            f"({dr.escalate_reason or dr.result[:30]})"
        )
        return None
    return dr.result, dr.elapsed_ms, None


def _run_job_with_optional_fallback(
    job: dict,
    *,
    port: int,
    worker_id: int,
    primary_model: str,
    dry_run: bool,
    pace_seconds: float,
    confirm_submit: bool,
    min_score: int | None = None,
    ats_only: bool = False,
    priority_boards_only: bool = False,
    include_untailored: bool = False,
) -> tuple[str, int, Path | None]:
    """Run apply once on primary model; escalate to fallback on retriable failure."""
    # Excluded ATS families (e.g. greenhouse, ashby) are never applied to and never
    # escalate to Claude — park them as needs_adapter (reversible) regardless of
    # engine/mode. Configured via APPLYPILOT_SKIP_ATS_FAMILIES (apply_settings).
    excluded_families = apply_settings.skipped_ats_families()
    if excluded_families:
        from applypilot.apply.direct import fingerprint

        family = fingerprint.ats_family(_job_apply_url(job))
        if family in excluded_families:
            _park_job_needs_adapter(_job_row_url(job), f"excluded_ats:{family}")
            return f"parked:needs_adapter:excluded_ats:{family}", 0, None

    if apply_settings.apply_engine() == "direct":
        defer_claude = _should_defer_claude_rescue(
            job,
            min_score=min_score,
            ats_only=ats_only,
            priority_boards_only=priority_boards_only,
            include_untailored=include_untailored,
        )
        skip_direct = _job_pending_claude_rescue(job) and not job_has_direct_adapter(job)
        if not skip_direct:
            direct = _try_direct_apply(
                job,
                port=port,
                worker_id=worker_id,
                dry_run=dry_run,
                defer_claude_rescue=defer_claude,
            )
            if direct is not None:
                return direct
        # Direct queue drained, Claude-only rescue, or APPLYPILOT_DIRECT_ESCALATE tier.

    if (
        apply_settings.deterministic_only_enabled()
        or not apply_budget.governor().claude_allowed()
    ):
        cap_reason = (
            "deterministic_only"
            if apply_settings.deterministic_only_enabled()
            else "claude_budget_capped"
        )
        _park_job_needs_adapter(_job_row_url(job), cap_reason)
        return f"parked:needs_adapter:{cap_reason}", 0, None

    fallback_model = apply_settings.apply_fallback_model()
    result, duration_ms, session_log = run_job(
        job,
        port=port,
        worker_id=worker_id,
        model=primary_model,
        dry_run=dry_run,
        pace_seconds=pace_seconds,
        confirm_submit=confirm_submit,
    )

    if result == "failed:claude_stale_session":
        apply_settings.clear_session_id(worker_id)
        add_event(
            f"[W{worker_id}] Retrying after stale Claude session cleared "
            f"(primary {primary_model})"
        )
        result, duration_ms, session_log = run_job(
            job,
            port=port,
            worker_id=worker_id,
            model=primary_model,
            dry_run=dry_run,
            pace_seconds=pace_seconds,
            confirm_submit=confirm_submit,
        )

    if apply_settings.should_escalate_to_fallback(
        result,
        primary=primary_model,
        fallback=fallback_model,
        is_permanent_failure=_is_permanent_failure,
    ):
        add_event(
            f"[W{worker_id}] Retrying on {fallback_model} "
            f"(primary {primary_model} -> {result[:40]})"
        )
        fb_result, fb_duration, fb_log = run_job(
            job,
            port=port,
            worker_id=worker_id,
            model=fallback_model,
            dry_run=dry_run,
            pace_seconds=pace_seconds,
            confirm_submit=confirm_submit,
        )
        return fb_result, fb_duration, fb_log or session_log

    return result, duration_ms, session_log


def worker_loop(
    worker_id: int = 0,
    limit: int = 0,
    target_url: str | None = None,
    min_score: int | None = None,
    headless: bool = False,
    model: str = "haiku",
    dry_run: bool = False,
    pace_seconds: float = 0.0,
    keep_open_seconds: float = 0.0,
    confirm_submit: bool = False,
    ats_only: bool = False,
    priority_boards_only: bool = False,
    min_experience_years: int | None = None,
    include_untailored: bool = False,
) -> tuple[int, int]:
    """Run jobs sequentially until limit is reached or queue is empty.

    Args:
        worker_id: Numeric worker identifier.
        limit: Max jobs to process (0 = continuous).
        target_url: Apply to a specific URL.
        min_score: Minimum fit_score threshold.
        headless: Run Chrome headless.
        model: Claude model name.
        dry_run: Don't click Submit.
        pace_seconds: Delay between browser actions (prompt-level).
        keep_open_seconds: Leave Chrome open after each job for review.
        confirm_submit: Long pause before Submit for human review.

    Returns:
        Tuple of (applied_count, failed_count).
    """
    applied = 0
    failed = 0
    continuous = limit == 0
    jobs_done = 0
    empty_polls = 0
    quota_retry_until: str | None = None
    port = BASE_CDP_PORT + worker_id
    primary_model = apply_settings.apply_model_default(model)

    while not _stop_event.is_set():
        if not continuous and jobs_done >= limit:
            break

        update_state(worker_id, status="idle", job_title="", company="",
                     last_action="waiting for job", actions=0)

        job = acquire_job(
            target_url=target_url,
            min_score=min_score,
            worker_id=worker_id,
            ats_only=ats_only,
            priority_boards_only=priority_boards_only,
            min_experience_years=min_experience_years,
            include_untailored=include_untailored,
        )
        if not job:
            if quota_retry_until and not continuous:
                try:
                    target = datetime.fromisoformat(quota_retry_until.replace("Z", "+00:00"))
                    if target > datetime.now(timezone.utc):
                        update_state(
                            worker_id,
                            status="paused_quota",
                            last_action=f"waiting until {quota_retry_until}",
                        )
                        if _stop_event.wait(timeout=POLL_INTERVAL):
                            break
                        continue
                except Exception:
                    quota_retry_until = None
            remaining = count_acquirable_jobs(
                min_score=min_score,
                ats_only=ats_only,
                priority_boards_only=priority_boards_only,
                include_untailored=include_untailored,
            )
            should_poll = continuous or remaining > 0
            if not should_poll:
                add_event(f"[W{worker_id}] Queue empty")
                update_state(worker_id, status="done", last_action="queue empty")
                break
            empty_polls += 1
            update_state(worker_id, status="idle",
                         last_action=f"polling ({empty_polls})")
            if empty_polls == 1:
                add_event(f"[W{worker_id}] Queue empty, polling every {POLL_INTERVAL}s...")
            # Use Event.wait for interruptible sleep
            if _stop_event.wait(timeout=POLL_INTERVAL):
                break  # Stop was requested during wait
            continue

        empty_polls = 0

        chrome_proc = None
        try:
            add_event(f"[W{worker_id}] Launching Chrome...")
            chrome_proc = launch_chrome(worker_id, port=port, headless=headless)
            logger.info("[worker-%d] Running apply agent for %s", worker_id, job.get("title", "")[:80])

            result, duration_ms, session_log = _run_job_with_optional_fallback(
                job,
                port=port,
                worker_id=worker_id,
                primary_model=primary_model,
                dry_run=dry_run,
                pace_seconds=pace_seconds,
                confirm_submit=confirm_submit,
                min_score=min_score,
                ats_only=ats_only,
                priority_boards_only=priority_boards_only,
                include_untailored=include_untailored,
            )

            reason, quota_not_before = _parse_worker_result(result)
            if reason in QUOTA_SESSION_FAILURES:
                not_before = quota_not_before or _quota_backoff_not_before()
                quota_retry_until = not_before
                release_lock(job["url"])
                _park_job_for_retry(
                    job["url"],
                    not_before=not_before,
                    error=f"claude_quota_exhausted retry_after={not_before}",
                )
                _pause_worker_for_quota(worker_id, not_before=not_before)
                continue

            if result in ("failed:no_result_line", "failed:incomplete") and session_log:
                from applypilot.apply.apply_log_parser import session_log_incomplete

                if session_log_incomplete(session_log):
                    add_event(f"[W{worker_id}] Retrying incomplete session once…")
                    result, duration_ms, session_log = _run_job_with_optional_fallback(
                        job,
                        port=port,
                        worker_id=worker_id,
                        primary_model=primary_model,
                        dry_run=dry_run,
                        pace_seconds=pace_seconds,
                        confirm_submit=confirm_submit,
                        min_score=min_score,
                        ats_only=ats_only,
                        priority_boards_only=priority_boards_only,
                        include_untailored=include_untailored,
                    )
                    reason, quota_not_before = _parse_worker_result(result)
                    if reason in QUOTA_SESSION_FAILURES:
                        not_before = quota_not_before or _quota_backoff_not_before()
                        quota_retry_until = not_before
                        release_lock(job["url"])
                        _park_job_for_retry(
                            job["url"],
                            not_before=not_before,
                            error=f"claude_quota_exhausted retry_after={not_before}",
                        )
                        _pause_worker_for_quota(worker_id, not_before=not_before)
                        continue

            if result == "skipped":
                release_lock(job["url"])
                add_event(f"[W{worker_id}] Skipped: {job['title'][:30]}")
                jobs_done += 1
                continue
            elif result.startswith("parked:needs_adapter"):
                add_event(
                    f"[W{worker_id}] Parked (needs adapter): "
                    f"{result.split(':', 1)[-1][:40]}"
                )
                jobs_done += 1
                continue
            elif result.startswith("awaiting_login"):
                from applypilot.apply import login_gate

                domain = result.split(":", 1)[-1] if ":" in result else "provider"
                info = next(
                    (
                        p for p in login_gate.pending()
                        if (p.get("domain") or "").lower() == domain.lower()
                    ),
                    {},
                )
                reason_detail = str(info.get("reason") or "login_required")
                _park_job_awaiting_login(job["url"], domain, reason=reason_detail)
                suffix = (
                    " (no Google sign-in)"
                    if reason_detail == "login_required_no_google"
                    else ""
                )
                add_event(
                    f"[W{worker_id}] AWAITING LOGIN: {domain}{suffix} — "
                    "log in then Resume from the dashboard"
                )
                update_state(
                    worker_id, status="awaiting_login",
                    last_action=f"login: {domain[:24]}",
                )
                # Pause this worker until you log in and Resume (or timeout).
                login_gate.wait_for_resume(domain, timeout_s=1800.0)
                release_lock(job["url"])
                continue
            elif result.startswith("deferred:"):
                release_lock(job["url"])
                if result.startswith("deferred:claude_rescue"):
                    add_event(
                        f"[W{worker_id}] Deferred Claude rescue: "
                        f"{result.split(':', 1)[-1][:40]}"
                    )
                else:
                    add_event(
                        f"[W{worker_id}] Deferred (cap): "
                        f"{result.split(':', 1)[-1][:40]}"
                    )
                jobs_done += 1
                continue
            elif result == "applied":
                mark_result(
                    job["url"],
                    "applied",
                    duration_ms=duration_ms,
                    log_path=session_log,
                )
                applied += 1
                update_state(worker_id, jobs_applied=applied,
                             jobs_done=applied + failed)
            elif result.startswith("submitted_unverified"):
                reasons = result.split(":", 1)[-1] if ":" in result else "unverified"
                mark_result(
                    job["url"],
                    "submitted_unverified",
                    error=reasons,
                    duration_ms=duration_ms,
                    log_path=session_log,
                )
                failed += 1
                update_state(worker_id, jobs_failed=failed,
                             jobs_done=applied + failed)
            else:
                reason = result.split(":", 1)[-1] if ":" in result else result
                mark_result(
                    job["url"],
                    "failed",
                    reason,
                    permanent=_is_permanent_failure(result),
                    duration_ms=duration_ms,
                    log_path=session_log,
                )
                failed += 1
                update_state(worker_id, jobs_failed=failed,
                             jobs_done=applied + failed)

        except KeyboardInterrupt:
            release_lock(job["url"])
            if _stop_event.is_set():
                break
            add_event(f"[W{worker_id}] Job skipped (Ctrl+C)")
            continue
        except Exception as e:
            logger.exception("Worker %d launcher error", worker_id)
            add_event(f"[W{worker_id}] Launcher error: {str(e)[:40]}")
            release_lock(job["url"])
            failed += 1
            update_state(worker_id, jobs_failed=failed)
            jobs_done += 1
        finally:
            if chrome_proc and keep_open_seconds > 0:
                add_event(
                    f"[W{worker_id}] Chrome open {keep_open_seconds:.0f}s — review in browser"
                )
                update_state(
                    worker_id,
                    last_action=f"review browser ({keep_open_seconds:.0f}s)",
                )
                _stop_event.wait(timeout=keep_open_seconds)
            if chrome_proc:
                cleanup_worker(worker_id, chrome_proc)

        jobs_done += 1
        if target_url:
            break

    update_state(worker_id, status="done", last_action="finished")
    return applied, failed


# ---------------------------------------------------------------------------
# Main entry point (called from cli.py)
# ---------------------------------------------------------------------------

def main(
    limit: int = 0,
    target_url: str | None = None,
    min_score: int | None = None,
    headless: bool = False,
    model: str = "haiku",
    dry_run: bool = False,
    continuous: bool = True,
    poll_interval: int = 60,
    workers: int = 1,
    pace_seconds: float = 0.0,
    keep_open_seconds: float = 0.0,
    confirm_submit: bool = False,
    plain: bool = False,
    ats_only: bool = False,
    priority_boards_only: bool = False,
    min_experience_years: int | None = None,
    include_untailored: bool = False,
) -> None:
    """Launch the apply pipeline.

    Args:
        limit: Max jobs to apply to (0 or with continuous=True means run forever).
        target_url: Apply to a specific URL.
        min_score: Minimum fit_score threshold.
        headless: Run Chrome in headless mode.
        model: Claude model name.
        dry_run: Don't click Submit.
        continuous: Run forever, polling for new jobs.
        poll_interval: Seconds between DB polls when queue is empty.
        workers: Number of parallel workers (default 1).
        pace_seconds: Delay between browser actions for human tracking.
        keep_open_seconds: Keep Chrome open after each job ends.
        confirm_submit: Pause before Submit for human review.
        plain: Log to stdout instead of Rich Live dashboard (for nohup/background).
    """
    global POLL_INTERVAL
    POLL_INTERVAL = poll_interval
    _stop_event.clear()

    try:
        apply_profile = config.load_profile()
    except Exception:
        apply_profile = {}
    budget_snap = apply_budget.governor().reset(
        deterministic_only=apply_settings.deterministic_only_enabled(),
        profile=apply_profile,
    )

    config.ensure_dirs()
    console = Console()
    use_live = not plain and sys.stdout.isatty()

    stale = release_stale_locks()
    if stale:
        logger.info("Released %d stale in_progress lock(s)", stale)
        console.print(f"[dim]Released {stale} stale lock(s) from a previous run[/dim]")
    orphans = release_orphan_in_progress_locks()
    if orphans:
        logger.info("Released %d orphan in_progress lock(s)", orphans)
        console.print(f"[dim]Cleared {orphans} in_progress lock(s) from an interrupted run[/dim]")
    repaired = repair_invalid_quota_retry_windows()
    if repaired:
        logger.info("Repaired %d invalid Claude quota retry window(s)", repaired)
        console.print(f"[dim]Repaired {repaired} Claude quota retry window(s)[/dim]")

    if not target_url:
        acquirable = count_acquirable_jobs(
            min_score=min_score,
            ats_only=ats_only,
            priority_boards_only=priority_boards_only,
            include_untailored=include_untailored,
        )
        if acquirable == 0:
            console.print("[red bold]No jobs available to apply.[/red bold]")
            console.print(
                format_apply_queue_hint(
                    min_score=min_score,
                    ats_only=ats_only,
                    priority_boards_only=priority_boards_only,
                    include_untailored=include_untailored,
                )
            )
            sys.exit(1)

    if limit > 0:
        effective_limit = limit
        mode_label = f"{limit} jobs"
    elif continuous:
        effective_limit = 0
        mode_label = "continuous"
    else:
        effective_limit = count_acquirable_jobs(
            min_score=min_score,
            ats_only=ats_only,
            priority_boards_only=priority_boards_only,
            include_untailored=include_untailored,
        )
        mode_label = f"{effective_limit} jobs (queue)"

    # Initialize dashboard for all workers
    for i in range(workers):
        init_worker(i)

    worker_label = f"{workers} worker{'s' if workers > 1 else ''}"
    primary_model = apply_settings.apply_model_default(model)
    flags = apply_settings.apply_telemetry_flags()
    console.print(f"Launching apply pipeline ({mode_label}, {worker_label}, poll every {POLL_INTERVAL}s)...")
    console.print(
        f"[dim]Apply model: {primary_model} "
        f"(fallback {flags['apply_fallback_model']}) | "
        f"prompt_slim={flags['prompt_slim']} session_reuse={flags['session_reuse']} "
        f"gmail_mcp={flags['gmail_mcp']}[/dim]"
    )
    if budget_snap.deterministic_only:
        console.print(
            "[dim]Deterministic-only: Claude disabled; non-adapter jobs -> needs_adapter[/dim]"
        )
    if budget_snap.claude_max_attempts is not None:
        console.print(
            f"[dim]Claude cap: {budget_snap.claude_max_attempts} apply(s) per run[/dim]"
        )
    if budget_snap.claude_max_cost_usd is not None:
        console.print(
            f"[dim]Claude cap: ${budget_snap.claude_max_cost_usd:.4f} per run[/dim]"
        )
    console.print("[dim]Ctrl+C = skip current job(s) | Ctrl+C x2 = stop[/dim]")

    # Double Ctrl+C handler
    _ctrl_c_count = 0

    def _sigint_handler(sig, frame):
        nonlocal _ctrl_c_count
        _ctrl_c_count += 1
        if _ctrl_c_count == 1:
            console.print("\n[yellow]Skipping current job(s)... (Ctrl+C again to STOP)[/yellow]")
            # Kill all active Claude processes to skip current jobs
            with _claude_lock:
                for wid, cproc in list(_claude_procs.items()):
                    if cproc.poll() is None:
                        _kill_process_tree(cproc.pid)
        else:
            console.print("\n[red bold]STOPPING[/red bold]")
            _stop_event.set()
            with _claude_lock:
                for wid, cproc in list(_claude_procs.items()):
                    if cproc.poll() is None:
                        _kill_process_tree(cproc.pid)
            kill_all_chrome()
            raise KeyboardInterrupt

    signal.signal(signal.SIGINT, _sigint_handler)

    def _run_workers() -> tuple[int, int]:
        if workers == 1:
            return worker_loop(
                worker_id=0,
                limit=effective_limit,
                target_url=target_url,
                min_score=min_score,
                headless=headless,
                model=model,
                dry_run=dry_run,
                pace_seconds=pace_seconds,
                keep_open_seconds=keep_open_seconds,
                confirm_submit=confirm_submit,
                ats_only=ats_only,
                priority_boards_only=priority_boards_only,
                min_experience_years=min_experience_years,
                include_untailored=include_untailored,
            )

        if effective_limit:
            base = effective_limit // workers
            extra = effective_limit % workers
            limits = [base + (1 if i < extra else 0) for i in range(workers)]
        else:
            limits = [0] * workers

        results: list[tuple[int, int]] = []
        with ThreadPoolExecutor(max_workers=workers,
                                thread_name_prefix="apply-worker") as executor:
            futures = {
                executor.submit(
                    worker_loop,
                    worker_id=i,
                    limit=limits[i],
                    target_url=target_url,
                    min_score=min_score,
                    headless=headless,
                    model=model,
                    dry_run=dry_run,
                    pace_seconds=pace_seconds,
                    keep_open_seconds=keep_open_seconds,
                    confirm_submit=confirm_submit,
                    ats_only=ats_only,
                    priority_boards_only=priority_boards_only,
                    min_experience_years=min_experience_years,
                    include_untailored=include_untailored,
                ): i
                for i in range(workers)
            }
            for future in as_completed(futures):
                wid = futures[future]
                try:
                    results.append(future.result())
                except Exception:
                    logger.exception("Worker %d crashed", wid)
                    results.append((0, 0))

        return sum(r[0] for r in results), sum(r[1] for r in results)

    try:
        if use_live:
            with Live(render_full(), console=console, refresh_per_second=2) as live:
                _dashboard_running = True

                def _refresh():
                    while _dashboard_running:
                        live.update(render_full())
                        time.sleep(0.5)

                refresh_thread = threading.Thread(target=_refresh, daemon=True)
                refresh_thread.start()
                total_applied, total_failed = _run_workers()
                _dashboard_running = False
                refresh_thread.join(timeout=2)
                live.update(render_full())
        else:
            logger.info(
                "Apply running in plain mode (%s). Tail %s",
                mode_label,
                config.LOG_DIR / "worker-0.log",
            )
            total_applied, total_failed = _run_workers()

        totals = get_totals()
        run_snap = apply_budget.governor().snapshot()
        console.print(
            f"\n[bold]Done: {total_applied} applied, {total_failed} failed "
            f"(${totals['cost']:.3f} Claude in DB)[/bold]"
        )
        if run_snap.deterministic_only:
            console.print(
                f"[dim]Run Claude spend (governor): ${run_snap.claude_cost_usd:.4f} "
                f"({run_snap.claude_attempts} attempts)[/dim]"
            )
        elif run_snap.claude_attempts or run_snap.claude_cost_usd:
            console.print(
                f"[dim]Run Claude spend (governor): ${run_snap.claude_cost_usd:.4f} "
                f"({run_snap.claude_attempts} attempts)"
                + (" — cap reached" if run_snap.claude_capped else "")
                + "[/dim]"
            )
        if run_snap.parked_needs_adapter:
            console.print(
                f"[yellow]Parked needs_adapter (re-queue when adapter ships): "
                f"{run_snap.parked_needs_adapter}[/yellow]"
            )
        console.print(f"Logs: {config.LOG_DIR}")

    except KeyboardInterrupt:
        pass
    finally:
        _stop_event.set()
        kill_all_chrome()
