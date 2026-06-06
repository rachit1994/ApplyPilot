"""Stats endpoint helpers."""

from __future__ import annotations

from applypilot.database import get_connection, get_source_stats_rollup, get_stats, init_db
from applypilot.discovery.site_priority import (
    APPLY_QUEUE_ORDER_LABEL,
    PRIORITY_SITE_NAMES,
    sort_site_count_rows,
    sort_source_count_rows,
)
from applypilot.server.job_triage import fetch_triage_counts
from applypilot.server.low_score_reason import display_reason
from applypilot.server.schemas import (
    LowScoreReason,
    ScoreBucket,
    ScoreDistributionItem,
    SiteCount,
    StatsPayload,
)

_TOP_SITES = 5

_PIPELINE_KEYS = (
    "pending_detail",
    "pre_filter_kept",
    "pre_filter_rejected",
    "with_description",
    "detail_errors",
    "scored",
    "unscored",
    "tailored",
    "untailored_eligible",
    "tailor_exhausted",
    "with_cover_letter",
    "cover_exhausted",
    "applied",
    "submitted_unverified",
    "apply_errors",
    "ready_to_apply",
)

_CARD_KEYS = ("total", "scored", "with_description", "tailored", "ready_to_apply", "applied")


def _score_buckets(dist: list[tuple[int, int]]) -> list[ScoreBucket]:
    totals = {"0-5": 0, "6-7": 0, "8-10": 0}
    for score, count in dist:
        if score <= 5:
            totals["0-5"] += count
        elif score <= 7:
            totals["6-7"] += count
        else:
            totals["8-10"] += count
    return [ScoreBucket(bucket=b, count=c) for b, c in totals.items() if c > 0]


def _low_score_reasons(conn) -> list[LowScoreReason]:
    rows = conn.execute(
        """
        SELECT pre_filter_reason, score_reasoning, COUNT(*) AS cnt
        FROM jobs
        WHERE fit_score IS NOT NULL AND fit_score < 7
        GROUP BY pre_filter_reason, score_reasoning
        """
    ).fetchall()
    counts: dict[str, int] = {}
    for row in rows:
        label = display_reason(row["pre_filter_reason"], row["score_reasoning"])
        counts[label] = counts.get(label, 0) + int(row["cnt"] or 0)
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [LowScoreReason(reason=reason, count=count) for reason, count in ranked[:8]]


def fetch_stats() -> StatsPayload:
    init_db()
    raw = get_stats()
    conn = get_connection()
    triage_counts = fetch_triage_counts(conn)

    by_site_raw = sort_site_count_rows(
        [{"site": site, "count": count} for site, count in (raw.get("by_site") or [])]
    )
    by_site = [
        SiteCount(site=row["site"], count=row["count"])
        for row in by_site_raw[:_TOP_SITES]
    ]

    dist_raw = raw.get("score_distribution") or []
    score_distribution = [
        ScoreDistributionItem(score=int(score), count=int(count))
        for score, count in dist_raw
    ]
    score_buckets = _score_buckets(dist_raw)

    pipeline = {key: int(raw.get(key) or 0) for key in _PIPELINE_KEYS}

    extra: dict[str, int] = {}
    for key, value in raw.items():
        if key in _CARD_KEYS or key in _PIPELINE_KEYS:
            continue
        if key in ("by_site", "score_distribution"):
            continue
        if isinstance(value, int):
            extra[key] = value

    return StatsPayload(
        total=int(raw.get("total") or 0),
        scored=int(raw.get("scored") or 0),
        with_description=int(raw.get("with_description") or 0),
        tailored=int(raw.get("tailored") or 0),
        ready_to_apply=int(raw.get("ready_to_apply") or 0),
        applied=int(raw.get("applied") or 0),
        priority_boards=list(PRIORITY_SITE_NAMES),
        apply_queue_order=APPLY_QUEUE_ORDER_LABEL,
        by_site=by_site,
        score_distribution=score_distribution,
        score_buckets=score_buckets,
        low_score_reasons=_low_score_reasons(conn),
        pipeline=pipeline,
        triage_counts=triage_counts,
        extra=extra,
    )


def fetch_source_stats(days: int = 7) -> list[dict]:
    init_db()
    return sort_source_count_rows(get_source_stats_rollup(days=days))
