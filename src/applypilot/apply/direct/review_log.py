"""Rich audit log for self-learning apply — timeline, dedupe clusters, cache stats."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

_REVIEW_LOG_DDL = """
CREATE TABLE IF NOT EXISTS review_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT,
  job_url TEXT,
  ats_family TEXT,
  apex_host TEXT,
  state_sig TEXT,
  scope TEXT,
  step_index INTEGER,
  url_before TEXT,
  url_after TEXT,
  frame_info TEXT,
  tier TEXT,
  action_type TEXT,
  action_args TEXT,
  locator TEXT,
  llm_suggestion TEXT,
  outcome TEXT,
  postcondition_met INTEGER,
  receipt_status TEXT,
  screenshot_path TEXT,
  failure_reason TEXT,
  cost_usd REAL
);
"""


def ensure_review_log_table(conn) -> None:
    """Create ``review_log`` if missing (idempotent)."""
    conn.executescript(_REVIEW_LOG_DDL)
    conn.commit()


def log_event(
    conn,
    *,
    job_url: str | None = None,
    ats_family: str | None = None,
    apex_host: str | None = None,
    state_sig: str | None = None,
    scope: str | None = None,
    step_index: int | None = None,
    url_before: str | None = None,
    url_after: str | None = None,
    frame_info: str | None = None,
    tier: str | None = None,
    action_type: str | None = None,
    action_args: dict | str | None = None,
    locator: str | None = None,
    llm_suggestion: str | None = None,
    outcome: str | None = None,
    postcondition_met: bool | None = None,
    receipt_status: str | None = None,
    screenshot_path: str | None = None,
    failure_reason: str | None = None,
    cost_usd: float | None = None,
    ts: str | None = None,
) -> int:
    """Insert one review event; returns the new row id."""
    ensure_review_log_table(conn)
    if isinstance(action_args, dict):
        action_args = json.dumps(action_args, ensure_ascii=False)
    if ts is None:
        ts = datetime.now(timezone.utc).isoformat()
    post_val = None
    if postcondition_met is not None:
        post_val = 1 if postcondition_met else 0
    cur = conn.execute(
        """
        INSERT INTO review_log (
          ts, job_url, ats_family, apex_host, state_sig, scope, step_index,
          url_before, url_after, frame_info, tier, action_type, action_args,
          locator, llm_suggestion, outcome, postcondition_met, receipt_status,
          screenshot_path, failure_reason, cost_usd
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            ts,
            job_url,
            ats_family,
            apex_host,
            state_sig,
            scope,
            step_index,
            url_before,
            url_after,
            frame_info,
            tier,
            action_type,
            action_args,
            locator,
            llm_suggestion,
            outcome,
            post_val,
            receipt_status,
            screenshot_path,
            failure_reason,
            cost_usd,
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def list_recent(conn, *, limit: int = 50) -> list[dict[str, Any]]:
    """Newest review events first."""
    ensure_review_log_table(conn)
    rows = conn.execute(
        """
        SELECT *
        FROM review_log
        ORDER BY id DESC
        LIMIT ?
        """,
        (max(1, min(limit, 500)),),
    ).fetchall()
    return [dict(r) for r in rows]


def dedupe_clusters(conn, *, limit: int = 50) -> list[dict[str, Any]]:
    """Group events by ``state_sig``; highest counts first."""
    ensure_review_log_table(conn)
    rows = conn.execute(
        """
        SELECT
          state_sig,
          COUNT(*) AS count,
          MAX(ats_family) AS ats_family,
          MAX(apex_host) AS apex_host,
          MAX(action_type) AS action_type,
          MAX(tier) AS tier,
          MAX(outcome) AS outcome
        FROM review_log
        WHERE state_sig IS NOT NULL AND state_sig != ''
        GROUP BY state_sig
        ORDER BY count DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


_LLM_TIERS: frozenset[str] = frozenset({"gemini", "claude"})


def cache_hit_rate(conn, *, since_hours: int = 24) -> dict[str, float | int]:
    """Replay vs LLM tier counts and replay percentage over a time window."""
    ensure_review_log_table(conn)
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=since_hours)).isoformat()
    rows = conn.execute(
        """
        SELECT tier, COUNT(*) AS n
        FROM review_log
        WHERE ts >= ?
        GROUP BY tier
        """,
        (cutoff,),
    ).fetchall()
    replay_count = 0
    llm_count = 0
    for row in rows:
        tier = (row["tier"] or "").lower()
        n = int(row["n"])
        if tier == "replay":
            replay_count += n
        elif tier in _LLM_TIERS:
            llm_count += n
    total = replay_count + llm_count
    replay_pct = round(100.0 * replay_count / total, 2) if total else 0.0
    return {
        "replay_count": replay_count,
        "llm_count": llm_count,
        "replay_pct": replay_pct,
    }
