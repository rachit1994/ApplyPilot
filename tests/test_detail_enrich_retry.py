"""Enrich retry: timeout and transient HTTP errors re-enter the pending queue."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pytest

from applypilot.database import ensure_columns, init_db
from applypilot.enrichment.pending import (
    MAX_DETAIL_ENRICH_ATTEMPTS,
    count_pending_detail,
    detail_pending_clause,
    is_retryable_detail_error,
    persist_detail_scrape_result,
)


@pytest.fixture
def temp_db(monkeypatch, tmp_path):
    from applypilot import config, database

    db_path = tmp_path / "enrich_retry.db"
    monkeypatch.setenv("APPLYPILOT_DIR", str(tmp_path))
    monkeypatch.setattr(database, "DB_PATH", db_path)
    monkeypatch.setattr(config, "DB_PATH", db_path)
    database.close_connection()
    conn = init_db()
    ensure_columns(conn)
    yield conn
    conn.close()
    database.close_connection()
    database.invalidate_stats_cache()


def _insert_job(
    conn: sqlite3.Connection,
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


def test_timeout_with_scraped_at_still_pending(temp_db):
    conn = temp_db
    scraped = datetime.now(timezone.utc).isoformat()
    _insert_job(
        conn,
        "https://example.com/job/1",
        detail_error="timeout",
        detail_scraped_at=scraped,
        detail_enrich_attempts=1,
    )
    assert count_pending_detail(conn) == 1


def test_timeout_exhausted_not_pending(temp_db):
    conn = temp_db
    scraped = datetime.now(timezone.utc).isoformat()
    _insert_job(
        conn,
        "https://example.com/job/2",
        detail_error="timeout",
        detail_scraped_at=scraped,
        detail_enrich_attempts=MAX_DETAIL_ENRICH_ATTEMPTS,
    )
    assert count_pending_detail(conn) == 0


def test_persist_retryable_failure_clears_scraped_at(temp_db):
    conn = temp_db
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
    assert row[0] == "timeout"
    assert row[1] is None
    assert row[2] == 1


def test_persist_retryable_exhausted_sets_scraped_at(temp_db):
    conn = temp_db
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
    assert row[0] == "timeout"
    assert row[1] == now
    assert row[2] == MAX_DETAIL_ENRICH_ATTEMPTS


def test_detail_pending_clause_is_valid_sql(temp_db):
    conn = temp_db
    clause = detail_pending_clause()
    conn.execute(f"SELECT COUNT(*) FROM jobs WHERE {clause}").fetchone()
