"""Rich audit log for self-learning apply — timeline, dedupe clusters, cache stats."""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)


def ensure_review_log_table(conn) -> None:
    """Create ``review_log`` if missing (idempotent)."""
    from applypilot.db.schema import _create_review_log

    _create_review_log(conn)
    conn.commit()


_FLUSH_INTERVAL_S = 1.0
_BATCH_SIZE = 32

_writer_lock = threading.Lock()
_event_queue: queue.Queue[dict[str, Any] | None] = queue.Queue()
_writer_thread: threading.Thread | None = None
_writer_conn: Any = None
_writer_db_path: str | None = None
_stop_writer_event = threading.Event()
_flush_requested = threading.Event()
_flush_done = threading.Event()
_pending_count = 0
_pending_lock = threading.Lock()


def _serialize_event(
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
) -> dict[str, Any]:
    if isinstance(action_args, dict):
        action_args = json.dumps(action_args, ensure_ascii=False)
    if ts is None:
        ts = datetime.now(timezone.utc).isoformat()
    post_val = None
    if postcondition_met is not None:
        post_val = 1 if postcondition_met else 0
    return {
        "ts": ts,
        "job_url": job_url,
        "ats_family": ats_family,
        "apex_host": apex_host,
        "state_sig": state_sig,
        "scope": scope,
        "step_index": step_index,
        "url_before": url_before,
        "url_after": url_after,
        "frame_info": frame_info,
        "tier": tier,
        "action_type": action_type,
        "action_args": action_args,
        "locator": locator,
        "llm_suggestion": llm_suggestion,
        "outcome": outcome,
        "postcondition_met": post_val,
        "receipt_status": receipt_status,
        "screenshot_path": screenshot_path,
        "failure_reason": failure_reason,
        "cost_usd": cost_usd,
    }


def _insert_event(conn, event: dict[str, Any]) -> int:
    ensure_review_log_table(conn)
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
            event["ts"],
            event["job_url"],
            event["ats_family"],
            event["apex_host"],
            event["state_sig"],
            event["scope"],
            event["step_index"],
            event["url_before"],
            event["url_after"],
            event["frame_info"],
            event["tier"],
            event["action_type"],
            event["action_args"],
            event["locator"],
            event["llm_suggestion"],
            event["outcome"],
            event["postcondition_met"],
            event["receipt_status"],
            event["screenshot_path"],
            event["failure_reason"],
            event["cost_usd"],
        ),
    )
    return int(cur.lastrowid)


def _commit_batch(conn, batch: list[dict[str, Any]]) -> None:
    if not batch:
        return
    ensure_review_log_table(conn)
    conn.executemany(
        """
        INSERT INTO review_log (
          ts, job_url, ats_family, apex_host, state_sig, scope, step_index,
          url_before, url_after, frame_info, tier, action_type, action_args,
          locator, llm_suggestion, outcome, postcondition_met, receipt_status,
          screenshot_path, failure_reason, cost_usd
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                e["ts"],
                e["job_url"],
                e["ats_family"],
                e["apex_host"],
                e["state_sig"],
                e["scope"],
                e["step_index"],
                e["url_before"],
                e["url_after"],
                e["frame_info"],
                e["tier"],
                e["action_type"],
                e["action_args"],
                e["locator"],
                e["llm_suggestion"],
                e["outcome"],
                e["postcondition_met"],
                e["receipt_status"],
                e["screenshot_path"],
                e["failure_reason"],
                e["cost_usd"],
            )
            for e in batch
        ],
    )
    conn.commit()


def _decrement_pending(n: int) -> None:
    global _pending_count
    with _pending_lock:
        _pending_count = max(0, _pending_count - n)
        if _pending_count == 0 and _flush_requested.is_set():
            _flush_done.set()


def _should_flush(batch: list[dict[str, Any]], last_flush: float) -> bool:
    if not batch:
        return False
    if len(batch) >= _BATCH_SIZE:
        return True
    if time.monotonic() - last_flush >= _FLUSH_INTERVAL_S:
        return True
    return _flush_requested.is_set()


def _writer_loop() -> None:
    if _writer_conn is not None:
        conn = _writer_conn
        close_on_exit = False
    else:
        from applypilot.database import get_connection

        conn = get_connection(_writer_db_path)
        close_on_exit = True

    batch: list[dict[str, Any]] = []
    last_flush = time.monotonic()
    try:
        while True:
            if _stop_writer_event.is_set() and _event_queue.empty() and not batch:
                break

            timeout = 0.1
            if batch:
                elapsed = time.monotonic() - last_flush
                remaining = _FLUSH_INTERVAL_S - elapsed
                if remaining > 0:
                    timeout = min(timeout, remaining)

            try:
                item = _event_queue.get(timeout=timeout)
            except queue.Empty:
                item = None

            if item is not None:
                batch.append(item)
            elif (
                _flush_requested.is_set()
                and _event_queue.empty()
                and not batch
            ):
                _flush_done.set()
                continue

            if _should_flush(batch, last_flush):
                _commit_batch(conn, batch)
                _decrement_pending(len(batch))
                batch = []
                last_flush = time.monotonic()
                if _flush_requested.is_set() and _event_queue.empty():
                    _flush_done.set()
            elif item is None and _stop_writer_event.is_set() and _event_queue.empty():
                if _flush_requested.is_set():
                    _flush_done.set()
    except Exception:
        logger.exception("review_log writer thread failed")
        _flush_done.set()
    finally:
        if close_on_exit:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass


def _writer_running() -> bool:
    return _writer_thread is not None and _writer_thread.is_alive()


def _db_path_from_conn(conn) -> str:
    from applypilot.config import DATABASE_URL

    return DATABASE_URL


def start_writer(conn=None) -> None:
    """Start the daemon single-writer thread (idempotent)."""
    global _writer_thread, _writer_conn, _writer_db_path

    with _writer_lock:
        if _writer_running():
            return

        if conn is not None:
            _writer_conn = None
            _writer_db_path = _db_path_from_conn(conn)
        else:
            from applypilot import config

            _writer_conn = None
            _writer_db_path = config.DATABASE_URL

        _stop_writer_event.clear()
        _flush_requested.clear()
        _flush_done.clear()

        _writer_thread = threading.Thread(
            target=_writer_loop,
            name="review_log_writer",
            daemon=True,
        )
        _writer_thread.start()


def flush() -> None:
    """Block until all enqueued review_log rows are committed."""
    if not _writer_running():
        return
    _flush_done.clear()
    _flush_requested.set()
    _flush_done.wait(timeout=30.0)
    _flush_requested.clear()


def stop_writer() -> None:
    """Flush pending rows and stop the background writer thread."""
    global _writer_thread, _writer_conn, _writer_db_path

    if not _writer_running():
        return
    flush()
    _stop_writer_event.set()
    thread = _writer_thread
    if thread is not None:
        thread.join(timeout=5.0)
    with _writer_lock:
        _writer_thread = None
        _writer_conn = None
        _writer_db_path = None
    _stop_writer_event.clear()


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
    """Insert one review event; returns the new row id (0 when queued async)."""
    event = _serialize_event(
        job_url=job_url,
        ats_family=ats_family,
        apex_host=apex_host,
        state_sig=state_sig,
        scope=scope,
        step_index=step_index,
        url_before=url_before,
        url_after=url_after,
        frame_info=frame_info,
        tier=tier,
        action_type=action_type,
        action_args=action_args,
        locator=locator,
        llm_suggestion=llm_suggestion,
        outcome=outcome,
        postcondition_met=postcondition_met,
        receipt_status=receipt_status,
        screenshot_path=screenshot_path,
        failure_reason=failure_reason,
        cost_usd=cost_usd,
        ts=ts,
    )
    if _writer_running():
        global _pending_count
        with _pending_lock:
            _pending_count += 1
        _event_queue.put(event)
        return 0
    row_id = _insert_event(conn, event)
    conn.commit()
    return row_id


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


def recent_fail_rate(
    conn,
    *,
    ats_family: str,
    apex_host: str | None = None,
    since_hours: int = 24,
) -> tuple[int, float]:
    """Return ``(attempts, fail_fraction)`` for an ATS family in a time window.

    Failures are nav/unblock rows that did not advance page state. Success is
    ``outcome='advanced'`` or ``postcondition_met=1`` (replay ``clicked`` /
    ``waited`` rows). Rows with ``tier='cap'`` are excluded — they record the cap
    decision itself, not a nav attempt.
    """
    ensure_review_log_table(conn)
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=since_hours)).isoformat()
    where = "ats_family = ? AND ts >= ? AND COALESCE(tier, '') != 'cap'"
    params: list[Any] = [ats_family, cutoff]
    if apex_host:
        where += " AND apex_host = ?"
        params.append(apex_host)
    row = conn.execute(
        f"""
        SELECT
          COUNT(*) AS attempts,
          SUM(
            CASE
              WHEN outcome = 'advanced' OR postcondition_met = 1 THEN 0
              ELSE 1
            END
          ) AS fails
        FROM review_log
        WHERE {where}
        """,
        params,
    ).fetchone()
    attempts = int(row["attempts"] or 0)
    fails = int(row["fails"] or 0)
    fail_fraction = fails / attempts if attempts else 0.0
    return attempts, fail_fraction


def tier_mix(conn, *, since_hours: int = 24) -> dict[str, int]:
    """Count review_log rows per tier over a time window."""
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
    out: dict[str, int] = {}
    for row in rows:
        tier = (row["tier"] or "unknown").lower()
        out[tier] = int(row["n"])
    return out


def escalation_summary(conn, *, since_hours: int = 24) -> list[dict[str, Any]]:
    """Per-family fail rates for dashboard escalation panel."""
    ensure_review_log_table(conn)
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=since_hours)).isoformat()
    rows = conn.execute(
        """
        SELECT DISTINCT ats_family
        FROM review_log
        WHERE ts >= ? AND ats_family IS NOT NULL AND ats_family != ''
        """,
        (cutoff,),
    ).fetchall()
    summary: list[dict[str, Any]] = []
    for row in rows:
        family = row["ats_family"]
        attempts, fail_fraction = recent_fail_rate(
            conn, ats_family=family, since_hours=since_hours
        )
        if attempts == 0:
            continue
        summary.append(
            {
                "ats_family": family,
                "attempts": attempts,
                "fail_fraction": round(fail_fraction, 4),
            }
        )
    summary.sort(key=lambda item: (-item["fail_fraction"], -item["attempts"]))
    return summary
