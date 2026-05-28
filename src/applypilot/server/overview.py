"""Aggregate dashboard home overview (GET /api/overview)."""

from __future__ import annotations

import json
import statistics
import time
from datetime import datetime, timezone
from sqlite3 import Connection
from typing import Any

from applypilot import __version__
from applypilot.database import get_connection, get_stats, init_db
from applypilot.orchestration.events import init_run_schema
from applypilot.orchestration.run_controller import get_active_run
from applypilot.pipeline import STAGE_ORDER, _stage_progress_snapshot
from applypilot.server import jobs as jobs_module
from applypilot.server.activity import list_dashboard_activity
from applypilot.server.stats import fetch_source_stats, fetch_stats
from applypilot.server.workers import fetch_workers_for_run


def _utc_today_prefix() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _fmt_duration_short(seconds: int) -> str:
    seconds = max(0, int(seconds))
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h}h {m:02d}m"
    return f"{m}m {s:02d}s"


def _fmt_money(amount: float | None) -> str:
    if amount is None:
        return "—"
    return f"${amount:.2f}"


def _jobs_discovered_today(conn: Connection) -> int:
    today = _utc_today_prefix()
    row = conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE discovered_at IS NOT NULL AND substr(discovered_at, 1, 10) = ?",
        (today,),
    ).fetchone()
    return int(row[0] or 0)


def _count_score_ge(conn: Connection, threshold: int) -> int:
    row = conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE fit_score IS NOT NULL AND fit_score >= ?",
        (threshold,),
    ).fetchone()
    return int(row[0] or 0)


def _count_tailored(conn: Connection) -> int:
    row = conn.execute("SELECT COUNT(*) FROM jobs WHERE tailored_resume_path IS NOT NULL").fetchone()
    return int(row[0] or 0)


def _count_applied_30d(conn) -> int:
    row = conn.execute(
        """
        SELECT COUNT(*) FROM jobs
        WHERE apply_status = 'applied'
          AND applied_at IS NOT NULL
          AND date(substr(applied_at, 1, 10)) >= date('now', '-30 days')
        """
    ).fetchone()
    return int(row[0] or 0)


def _llm_spend_today(conn) -> float:
    ensure = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='llm_usage_events'"
    ).fetchone()
    if not ensure:
        return 0.0
    today = _utc_today_prefix()
    row = conn.execute(
        """
        SELECT COALESCE(SUM(cost_usd), 0) FROM llm_usage_events
        WHERE substr(created_at, 1, 10) = ?
        """,
        (today,),
    ).fetchone()
    return float(row[0] or 0.0)


def _llm_spend_run_window(conn, started_at: str | None) -> float | None:
    if not started_at:
        return None
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='llm_usage_events'"
    ).fetchone()
    if not row:
        return None
    r2 = conn.execute(
        """
        SELECT COALESCE(SUM(cost_usd), 0) FROM llm_usage_events
        WHERE created_at >= ?
        """,
        (started_at,),
    ).fetchone()
    return float(r2[0] or 0.0)


def _apply_tailor_today(conn) -> tuple[int, int]:
    today = _utc_today_prefix()
    apply_row = conn.execute(
        """
        SELECT COUNT(*) FROM jobs
        WHERE last_attempted_at IS NOT NULL
          AND substr(last_attempted_at, 1, 10) = ?
          AND apply_status IN ('applied', 'failed', 'submitted_unverified', 'manual')
        """,
        (today,),
    ).fetchone()
    tailor_row = conn.execute(
        """
        SELECT COUNT(*) FROM jobs
        WHERE tailored_resume_path IS NOT NULL
          AND tailored_at IS NOT NULL
          AND substr(tailored_at, 1, 10) = ?
        """,
        (today,),
    ).fetchone()
    return int(apply_row[0] or 0), int(tailor_row[0] or 0)


def _latest_stage_progress_map(run_id: str) -> dict[str, dict[str, Any]]:
    init_run_schema()
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT stage, payload_json, message, id
        FROM run_events
        WHERE run_id = ? AND event_type = 'stage_progress' AND stage IS NOT NULL
        ORDER BY id DESC
        LIMIT 800
        """,
        (run_id,),
    ).fetchall()
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        st = row["stage"]
        if not st or st in out:
            continue
        pl: dict[str, Any] = {}
        if row["payload_json"]:
            try:
                pl = json.loads(row["payload_json"])
            except json.JSONDecodeError:
                pl = {}
        out[st] = {"payload": pl, "message": row["message"]}
    return out


def _run_event_error_count(run_id: str) -> int:
    init_run_schema()
    conn = get_connection()
    row = conn.execute(
        """
        SELECT COUNT(*) FROM run_events
        WHERE run_id = ?
          AND (
            event_type LIKE '%error%'
            OR lower(COALESCE(level, '')) LIKE '%error%'
            OR lower(COALESCE(level, '')) = 'critical'
          )
        """,
        (run_id,),
    ).fetchone()
    return int(row[0] or 0)


def _step_label(stage: str) -> str:
    return {
        "discover": "Discover",
        "filter": "Filter",
        "enrich": "Enrich",
        "score": "Score",
        "tailor": "Tailor",
        "pdf": "PDF",
        "refer": "Refer",
        "cover": "Cover",
        "apply": "Apply",
    }.get(stage, stage.title())


def _ui_step_index_for_stage(stage: str | None) -> int | None:
    """Map internal run stages to the 7-step Mission Control stepper."""
    if not stage:
        return None

    st = str(stage).strip().lower()
    if st == "discover":
        return 0
    if st == "filter":
        return 1
    if st == "enrich":
        return 2
    if st == "score":
        return 3
    if st in {"tailor", "pdf"}:
        return 4
    if st == "cover":
        return 5
    if st == "apply":
        return 6
    if st == "refer":
        # Referral outreach is outside Mission Control; treat it as apply-adjacent.
        return 6
    return None


def _progress_percent(done: int, denom: int) -> int | None:
    if denom <= 0:
        return None
    return min(100, max(0, int(round(100 * done / denom))))


def _filter_step_snapshot(conn: Connection, total: int) -> dict[str, Any]:
    # There is no explicit "filter" stage in the pipeline yet. For Mission Control,
    # treat "has a full description" as "passed filter".
    row = conn.execute("SELECT COUNT(*) FROM jobs WHERE full_description IS NOT NULL").fetchone()
    passed = int(row[0] or 0)
    pending = max(0, total - passed)
    denom = total if total > 0 else passed + pending
    return {
        "stage": "filter",
        "done": passed,
        "pending": pending,
        "total": denom,
        "percent": _progress_percent(passed, denom),
        "detail": f"{passed}/{denom} passed · {pending} left",
    }


def _apply_step_snapshot(conn: Connection, stats_payload: Any) -> dict[str, Any]:
    # "Apply" is not part of STAGE_ORDER; approximate with ready + applied.
    pipeline = getattr(stats_payload, "pipeline", {}) or {}
    ready = int(pipeline.get("ready_to_apply") or 0)
    applied = int(pipeline.get("applied") or 0)
    denom = ready + applied
    return {
        "stage": "apply",
        "done": applied,
        "pending": ready,
        "total": denom,
        "percent": _progress_percent(applied, denom),
        "detail": f"{applied} applied · {ready} ready",
    }


def _build_steps(
    *,
    run_id: str | None,
    running: bool,
    current_stage: str | None,
    min_score: int = 7,
) -> list[dict[str, Any]]:
    progress_map: dict[str, dict[str, Any]] = {}
    if run_id and running:
        progress_map = _latest_stage_progress_map(run_id)

    init_db()
    conn = get_connection()

    steps: list[dict[str, Any]] = []
    # Keep this in sync with designs/dashboard-20260527/finalized.html stepper.
    stages = ["discover", "filter", "enrich", "score", "tailor", "cover", "apply"]
    cur_ui_idx = _ui_step_index_for_stage(current_stage) if running else None
    for stage in stages:
        if stage == "filter":
            snap = _filter_step_snapshot(conn, int(get_stats(conn).get("total") or 0))
        elif stage == "apply":
            snap = _apply_step_snapshot(conn, fetch_stats())
        else:
            snap = _stage_progress_snapshot(stage, min_score)
        live = progress_map.get(stage, {}).get("payload") or {}
        merged = {**snap, **live}
        done = merged.get("done")
        pending = merged.get("pending")
        total = merged.get("total")
        pct = merged.get("percent")
        detail = merged.get("detail") or progress_map.get(stage, {}).get("message")
        state = "pending"
        if running and cur_ui_idx is not None:
            st_ui_idx = _ui_step_index_for_stage(stage)
            if st_ui_idx is not None:
                if st_ui_idx < cur_ui_idx:
                    state = "done"
                elif st_ui_idx == cur_ui_idx:
                    state = "active"
        count_text: str | None = None
        if stage == "discover":
            total_jobs = int(snap.get("total") or 0)
            srcs = int(snap.get("sources") or 0) if isinstance(snap.get("sources"), int) else None
            if srcs is not None and srcs > 0:
                count_text = f"{total_jobs:,} jobs · {srcs} sources"
            else:
                count_text = f"{total_jobs:,} jobs"
        elif stage == "filter":
            passed = int(snap.get("done") or 0) if snap.get("done") is not None else None
            if passed is None:
                passed = int(snap.get("total") or 0) or None
            count_text = f"{passed:,} passed" if passed else None
        elif stage == "apply":
            if done is not None and pending is not None:
                count_text = f"{int(done):,} applied · {int(pending):,} ready"
        elif stage == "score" and (done is not None) and (total is not None):
            count_text = f"{int(done):,}/{int(total):,}"
        elif total is not None and done is not None:
            count_text = f"{int(done):,}/{int(total):,}"

        steps.append({
            "id": stage,
            "label": _step_label(stage),
            "done": int(done) if done is not None else None,
            "pending": int(pending) if pending is not None else None,
            "total": int(total) if total is not None else None,
            "percent": int(pct) if pct is not None else None,
            "detail": detail,
            "count_text": count_text,
            "state": state,
        })
    return steps


def _build_funnel(raw: dict[str, Any], conn: Connection) -> list[dict[str, Any]]:
    total = int(raw.get("total") or 0)
    passed_filter = int(raw.get("with_description") or 0)
    scored_ge7_row = conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE fit_score IS NOT NULL AND fit_score >= 7"
    ).fetchone()
    scored_ge7 = int(scored_ge7_row[0] or 0)
    tailored = int(raw.get("tailored") or 0)
    cover = int(raw.get("with_cover_letter") or 0)
    applied = int(raw.get("applied") or 0)
    callback = 0

    def rate(n: int, denom: int) -> float | None:
        if denom <= 0:
            return None
        return round(100.0 * n / denom, 1)

    return [
        {"id": "discovered", "label": "Discovered", "count": total, "rate_percent": 100.0 if total else None},
        {"id": "passed_filter", "label": "Passed filter", "count": passed_filter, "rate_percent": rate(passed_filter, total)},
        {"id": "scored_ge7", "label": "Scored ≥ 7", "count": scored_ge7, "rate_percent": rate(scored_ge7, passed_filter)},
        {"id": "tailored", "label": "Tailored", "count": tailored, "rate_percent": rate(tailored, scored_ge7)},
        {"id": "cover_written", "label": "Cover written", "count": cover, "rate_percent": rate(cover, tailored)},
        {"id": "applied", "label": "Applied", "count": applied, "rate_percent": rate(applied, cover)},
        {"id": "callback", "label": "Callback", "count": callback, "rate_percent": rate(callback, applied) if applied else None},
    ]


def _score_dist_detail(raw: dict[str, Any], conn: Connection) -> dict[str, Any]:
    dist_raw = raw.get("score_distribution") or []
    buckets: list[dict[str, int]] = [{"score": s, "count": 0} for s in range(1, 11)]
    idx = {b["score"]: i for i, b in enumerate(buckets)}
    flat: list[int] = []
    for score, cnt in dist_raw:
        si = int(score)
        c = int(cnt)
        if 1 <= si <= 10:
            buckets[idx[si]]["count"] = c
        flat.extend([si] * c)
    mean = float(statistics.mean(flat)) if flat else None
    stdev = float(statistics.pstdev(flat)) if len(flat) > 1 else (0.0 if flat else None)
    elig_row = conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE fit_score IS NOT NULL AND fit_score >= 7"
    ).fetchone()
    apply_eligible = int(elig_row[0] or 0)
    return {
        "buckets": buckets,
        "mean": mean,
        "stdev": stdev,
        "total_scored": len(flat),
        "apply_eligible_count": apply_eligible,
    }


def build_overview() -> dict[str, Any]:
    t0 = time.perf_counter()
    init_db()
    conn = get_connection()
    raw = get_stats(conn)
    stats_payload = fetch_stats()

    active = get_active_run()
    run_id = active["id"] if active else None
    running = bool(active and active.get("status") == "running")
    current_stage = active.get("current_stage") if active else None

    pipeline = stats_payload.pipeline
    needs_verify = int(pipeline.get("submitted_unverified") or 0)
    ready = int(pipeline.get("ready_to_apply") or 0)
    applied_30d = _count_applied_30d(conn)
    spend_today = _llm_spend_today(conn)
    apply_today, tailor_today = _apply_tailor_today(conn)
    # Keep these aligned with the copy in finalized.html (can be made configurable later).
    spend_cap = 10.0
    apply_cap = 60
    tailor_cap = 250

    run_cost = _llm_spend_run_window(conn, active.get("started_at") if active else None)
    err_run = _run_event_error_count(run_id) if run_id and running else 0
    err_db = int(pipeline.get("apply_errors") or 0) + int(pipeline.get("detail_errors") or 0)

    title = "Discover & score pipeline" if running else "Ready"
    subtitle = "—"
    started_at = active.get("started_at") if active else None
    elapsed_part = None
    if started_at:
        try:
            dt = datetime.fromisoformat(str(started_at).replace("Z", "+00:00"))
            elapsed_part = _fmt_duration_short(int((datetime.now(timezone.utc) - dt).total_seconds()))
        except Exception:
            elapsed_part = None
    if run_id:
        subtitle_bits = [f"Run {run_id[:8]}"]
        if elapsed_part:
            subtitle_bits.append(f"{elapsed_part} elapsed")
        subtitle_bits.append("est. — to apply queue")
        subtitle = " · ".join(subtitle_bits)

    runband = {
        "status": "running" if running else "idle",
        "title": title,
        "subtitle": subtitle,
        "run_id": run_id,
        "run_type": active.get("run_type") if active else None,
        "current_stage": current_stage,
        "dry_run": bool(active.get("dry_run")) if active else False,
        "steps": _build_steps(
            run_id=run_id,
            running=running,
            current_stage=current_stage,
            min_score=7,
        ),
        "metrics": {
            "throughput_per_min": None,
            "score_pass_rate_percent": None,
            "run_cost_usd": run_cost,
            "error_count": err_run if running else err_db,
            "eta_to_apply_text": None,
            "score_pass_rate_delta_text": None,
            "throughput_delta_text": None,
            "run_cost_delta_text": None,
            "error_rate_text": None,
        },
    }

    discovered_today = _jobs_discovered_today(conn)
    scored_ge8 = _count_score_ge(conn, 8)

    kpis = {
        "applied_30d": applied_30d,
        "applied_30d_delta_text": None,
        "needs_verify": needs_verify,
        "ready_to_apply": ready,
        "ready_to_apply_subtitle": f"{scored_ge8} score ≥ 8 · cap {apply_cap}/day" if apply_cap else None,
        "ready_to_apply_delta_text": None,
        "pipeline_total": int(stats_payload.total),
        "pipeline_total_subtitle": f"+{discovered_today:,} today" if discovered_today else None,
        "spend_today_usd": spend_today,
        "spend_cap_usd": spend_cap,
        "spend_today_subtitle": f"{min(100, round((spend_today / max(0.01, spend_cap)) * 100))}% of ${spend_cap:.0f} cap" if spend_cap else None,
        "spend_today_delta_text": None,
        "callback_rate_14d": None,
        "callback_rate_14d_delta_text": None,
    }

    funnel = _build_funnel(raw, conn)
    score_distribution = _score_dist_detail(raw, conn)
    total_scored = int(score_distribution.get("total_scored") or 0)
    apply_eligible = int(score_distribution.get("apply_eligible_count") or 0)
    if total_scored > 0:
        runband["metrics"]["score_pass_rate_percent"] = round((apply_eligible / total_scored) * 100.0, 1)

    top_rows, _ = jobs_module.query_jobs(
        stage="ready",
        sort="fit_score_desc",
        limit=10,
        offset=0,
    )
    top_opportunities = [
        {
            "url": r["url"],
            "title": r.get("title"),
            "site": r.get("site"),
            "location": r.get("location"),
            "salary": r.get("salary"),
            "fit_score": r.get("fit_score"),
            "apply_status": r.get("apply_status"),
            "activity_at": r.get("activity_at"),
        }
        for r in top_rows
    ]

    sources = fetch_source_stats(days=7)

    activity = list_dashboard_activity(limit=25)

    caps = {
        "spend_today_usd": spend_today,
        "spend_cap_usd": spend_cap,
        "apply_today": apply_today,
        "apply_cap": apply_cap,
        "tailor_today": tailor_today,
        "tailor_cap": tailor_cap,
        "llm_provider_hint": "Gemini",
        "llm_spend_subtitle": "batch scoring",
        "apply_subtitle": "submissions queued today",
        "tailor_subtitle": "per-job rewrite",
    }

    workers, _ = fetch_workers_for_run(run_id)

    build_ms = (time.perf_counter() - t0) * 1000.0
    last_event_ts: str | None = None
    try:
        row = conn.execute(
            "SELECT ts FROM dashboard_activity_events ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row and row[0]:
            last_event_ts = str(row[0])
    except Exception:
        last_event_ts = None
    last_age_s: int | None = None
    if last_event_ts:
        try:
            dt = datetime.fromisoformat(last_event_ts.replace("Z", "+00:00"))
            last_age_s = int((datetime.now(timezone.utc) - dt).total_seconds())
        except Exception:
            last_age_s = None
    footer_right = f"API {round(build_ms)}ms"
    if last_age_s is not None:
        footer_right = f"{footer_right} · updated {last_age_s}s ago"
    footer = {
        "app_version": __version__,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "build_ms": round(build_ms, 2),
        "right_text": footer_right,
    }

    return {
        "runband": runband,
        "kpis": kpis,
        "funnel_subtitle": f"7-day rolling · {funnel[0]['count']:,} in · {funnel[5]['count']:,} out" if len(funnel) > 5 else None,
        "funnel_meta": (
            f"end-to-end {round((funnel[5]['count'] / max(1, funnel[0]['count'])) * 100.0, 1)}%"
            if len(funnel) > 5 and funnel[0]["count"] > 0
            else None
        ),
        "funnel": funnel,
        "score_distribution": score_distribution,
        "score_distribution_subtitle": (
            f"30 days · μ {score_distribution.get('mean', 0):.1f} · σ {score_distribution.get('stdev', 0):.1f}"
            if score_distribution.get("mean") is not None and score_distribution.get("stdev") is not None
            else "30 days"
        ),
        "score_distribution_meta": f"{score_distribution.get('total_scored', 0):,} scored",
        "top_opportunities": top_opportunities,
        "top_opportunities_subtitle": f"{ready} ready · sorted by fit score",
        "top_opportunities_chip_counts": {
            "ready": int(ready),
            "tailored": int(_count_tailored(conn)),
            "needs_check": int(needs_verify),
            "applied": int(applied_30d),
        },
        "sources": sources,
        "activity": activity,
        "activity_subtitle": f"Live · {len(activity)} events",
        "caps": caps,
        "workers": workers,
        "workers_subtitle": f"{len(workers)} active · all healthy" if workers else "0 active",
        "footer": footer,
    }
