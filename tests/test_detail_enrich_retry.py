"""Enrich retry: timeout and transient HTTP errors re-enter the pending queue."""

from __future__ import annotations

from datetime import datetime, timezone

from applypilot.database import ensure_columns, get_connection
from applypilot.db.connection import Connection
from applypilot.enrichment.pending import (
    MAX_DETAIL_ENRICH_ATTEMPTS,
    count_pending_detail,
    detail_pending_clause,
    is_retryable_detail_error,
    persist_detail_scrape_result,
)


def _conn() -> Connection:
    conn = get_connection()
    ensure_columns(conn)
    return conn


def _insert_job(
    conn: Connection,
    url: str,
    *,
    detail_error: str | None = None,
    detail_scraped_at: str | None = None,
    detail_enrich_attempts: int = 0,
    full_description: str | None = None,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO jobs (
            url, title, site, discovered_at,
            detail_error, detail_scraped_at, detail_enrich_attempts, full_description
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            url,
            "Engineer",
            "RemoteOK",
            now,
            detail_error,
            detail_scraped_at,
            detail_enrich_attempts,
            full_description,
        ),
    )
    conn.commit()


def test_is_retryable_detail_error():
    assert is_retryable_detail_error("timeout")
    assert is_retryable_detail_error("HTTP 503")
    assert not is_retryable_detail_error("HTTP 404")
    assert not is_retryable_detail_error(None)


def test_timeout_with_scraped_at_still_pending():
    conn = _conn()
    scraped = datetime.now(timezone.utc).isoformat()
    _insert_job(
        conn,
        "https://example.com/job/1",
        detail_error="timeout",
        detail_scraped_at=scraped,
        detail_enrich_attempts=1,
    )
    assert count_pending_detail(conn) == 1


def test_timeout_exhausted_not_pending():
    conn = _conn()
    scraped = datetime.now(timezone.utc).isoformat()
    _insert_job(
        conn,
        "https://example.com/job/2",
        detail_error="timeout",
        detail_scraped_at=scraped,
        detail_enrich_attempts=MAX_DETAIL_ENRICH_ATTEMPTS,
    )
    assert count_pending_detail(conn) == 0


def test_persist_retryable_failure_clears_scraped_at():
    conn = _conn()
    url = "https://example.com/job/3"
    now = datetime.now(timezone.utc).isoformat()
    _insert_job(conn, url, detail_scraped_at=now, detail_enrich_attempts=0)

    persist_detail_scrape_result(
        conn,
        url,
        {"status": "error", "error": "timeout"},
        now=now,
    )
    conn.commit()

    row = conn.execute(
        "SELECT detail_error, detail_scraped_at, detail_enrich_attempts FROM jobs WHERE url = ?",
        (url,),
    ).fetchone()
    assert row["detail_error"] == "timeout"
    assert row["detail_scraped_at"] is None
    assert row["detail_enrich_attempts"] == 1


def test_persist_retryable_exhausted_sets_scraped_at():
    conn = _conn()
    url = "https://example.com/job/4"
    now = datetime.now(timezone.utc).isoformat()
    _insert_job(
        conn,
        url,
        detail_enrich_attempts=MAX_DETAIL_ENRICH_ATTEMPTS - 1,
    )

    persist_detail_scrape_result(
        conn,
        url,
        {"status": "error", "error": "timeout"},
        now=now,
    )
    conn.commit()

    row = conn.execute(
        "SELECT detail_error, detail_scraped_at, detail_enrich_attempts FROM jobs WHERE url = ?",
        (url,),
    ).fetchone()
    assert row["detail_error"] == "timeout"
    assert row["detail_scraped_at"] == now
    assert row["detail_enrich_attempts"] == MAX_DETAIL_ENRICH_ATTEMPTS


def test_detail_pending_clause_is_valid_sql():
    conn = _conn()
    clause = detail_pending_clause()
    conn.execute(f"SELECT COUNT(*) FROM jobs WHERE {clause}").fetchone()
