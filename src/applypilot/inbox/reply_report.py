"""Weekly reply-rate report by discovery/apply source (site)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from applypilot.database import get_connection, init_db
from applypilot.inbox.intents import INTENT_INTERVIEW_INVITE


def _window_cutoff(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=max(1, days))).isoformat()


def build_reply_rate_report(*, days: int = 7) -> dict[str, Any]:
    """Reply-rate by source over a single cohort: applications applied in-window.

    Numerator (replies) and denominator (applies) are counted over the *same* set
    of rows — applications whose ``applied_at`` falls in the window — so the rate
    is always in [0, 1]. (The previous version counted replies by ``reply_at`` and
    applies by ``applied_at`` over different windows, which could exceed 100% when a
    reply this week answered an application from a prior week.)

    ``replies`` counts applications in the cohort that received a recruiter reply.
    ``jobs.reply_status`` is only ever written for genuine human-reply intents
    (see job_match.record_job_reply), so ``reply_status IS NOT NULL`` is exactly
    "got a human reply".
    """
    init_db()
    conn = get_connection()
    cutoff = _window_cutoff(days)

    rows = conn.execute(
        """
        SELECT COALESCE(NULLIF(trim(site), ''), 'unknown') AS source,
               COUNT(*) AS applies,
               SUM(CASE WHEN apply_status = 'applied' THEN 1 ELSE 0 END) AS verified_applies,
               SUM(CASE WHEN reply_status IS NOT NULL THEN 1 ELSE 0 END) AS replies,
               SUM(CASE WHEN reply_status = ? THEN 1 ELSE 0 END) AS interview_invites
        FROM jobs
        WHERE applied_at IS NOT NULL
          AND applied_at >= ?
        GROUP BY source
        ORDER BY applies DESC, source ASC
        """,
        (INTENT_INTERVIEW_INVITE, cutoff),
    ).fetchall()

    sources: list[dict[str, Any]] = []
    for row in rows:
        applies = int(row["applies"] or 0)
        verified = int(row["verified_applies"] or 0)
        replies = int(row["replies"] or 0)
        rate = (replies / applies) if applies else 0.0
        sources.append(
            {
                "source": row["source"],
                "applies": applies,
                "verified_applies": verified,
                "replies": replies,
                "interview_invites": int(row["interview_invites"] or 0),
                "reply_rate": round(rate, 4),
                "zero_replies_flag": applies >= 5 and replies == 0,
            }
        )

    totals = {
        "applies": sum(s["applies"] for s in sources),
        "verified_applies": sum(s["verified_applies"] for s in sources),
        "replies": sum(s["replies"] for s in sources),
        "interview_invites": sum(s["interview_invites"] for s in sources),
    }
    totals["reply_rate"] = (
        round(totals["replies"] / totals["applies"], 4) if totals["applies"] else 0.0
    )

    return {
        "window_days": days,
        "cutoff": cutoff,
        "sources": sources,
        "totals": totals,
    }


def format_reply_rate_report(report: dict[str, Any]) -> str:
    lines = [
        f"Reply-rate report (last {report['window_days']} days, since {report['cutoff'][:10]})",
        "",
        f"{'Source':<24} {'Applies':>8} {'Verified':>9} {'Replies':>8} {'Interview':>10} {'Rate':>8}",
        "-" * 72,
    ]
    for row in report["sources"]:
        flag = " *" if row["zero_replies_flag"] else ""
        lines.append(
            f"{row['source']:<24} {row['applies']:>8} {row['verified_applies']:>9} "
            f"{row['replies']:>8} {row['interview_invites']:>10} {row['reply_rate']:>7.1%}{flag}"
        )
    t = report["totals"]
    lines.append("-" * 72)
    lines.append(
        f"{'TOTAL':<24} {t['applies']:>8} {t['verified_applies']:>9} "
        f"{t['replies']:>8} {t['interview_invites']:>10} {t.get('reply_rate', 0):>7.1%}"
    )
    lines.append("")
    lines.append("* = 5+ applies and zero replies in window")
    return "\n".join(lines)
