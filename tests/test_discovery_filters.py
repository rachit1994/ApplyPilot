"""Tests for universal discover title/location filters."""

from __future__ import annotations

import sqlite3
from hashlib import md5

import pytest

from applypilot.discovery import _filters
from applypilot.database import ensure_columns
from applypilot.database import init_db
from applypilot.database import store_jobs


@pytest.fixture(autouse=True)
def _clear_filter_cache():
    _filters.clear_filter_cache()
    yield
    _filters.clear_filter_cache()


def test_title_passes_exclude_substring():
    assert not _filters.title_passes(
        "Junior Software Engineer",
        excludes=["junior"],
        includes=[],
    )
    assert _filters.title_passes(
        "Staff AI Engineer",
        excludes=["junior"],
        includes=[],
    )


def test_title_passes_include_allowlist():
    assert not _filters.title_passes(
        "Generic Engineer",
        excludes=[],
        includes=["react", "frontend"],
    )
    assert _filters.title_passes(
        "Senior React Developer",
        excludes=[],
        includes=["react", "frontend"],
    )


def test_location_passes_remote_always_ok():
    accept = ["bengaluru"]
    reject = ["new york"]
    assert _filters.location_passes("Remote, India", accept=accept, reject=reject)
    assert not _filters.location_passes("New York, NY", accept=accept, reject=reject)


def test_location_passes_multi_segment_any_match():
    accept = ["bengaluru", "bangalore"]
    reject = ["new york"]
    assert _filters.location_passes(
        "Remote - US; London; Bangalore, Karnataka",
        accept=accept,
        reject=reject,
    )
    assert not _filters.location_passes(
        "New York, NY; London, UK",
        accept=accept,
        reject=reject,
    )


def test_init_db_creates_content_dedup_columns(tmp_path):
    conn = init_db(tmp_path / "applypilot.db")

    columns = {row[1] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()}
    assert {"content_hash", "sources"}.issubset(columns)


def test_store_jobs_skips_filtered_titles(monkeypatch):
    monkeypatch.setattr(
        _filters,
        "load_title_filters",
        lambda: (["intern"], []),
    )
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE jobs (
            url TEXT PRIMARY KEY,
            title TEXT,
            salary TEXT,
            description TEXT,
            location TEXT,
            site TEXT,
            strategy TEXT,
            discovered_at TEXT
        );
        """
    )
    jobs = [
        {"url": "https://a.example/j1", "title": "Software Intern", "location": "Remote"},
        {"url": "https://a.example/j2", "title": "Staff Engineer", "location": "Remote"},
    ]
    new, existing = store_jobs(conn, jobs, "Test", "test")
    assert new == 1
    assert existing == 0
    rows = conn.execute("SELECT title FROM jobs").fetchall()
    assert [r[0] for r in rows] == ["Staff Engineer"]


def test_store_jobs_adds_content_hash_and_sources():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE jobs (url TEXT PRIMARY KEY)")
    ensure_columns(conn)

    new, existing = store_jobs(
        conn,
        [
            {
                "url": "https://a.example/j1",
                "title": " Staff Engineer ",
                "location": " Remote ",
            }
        ],
        "RemoteOK",
        "api",
    )

    expected_hash = md5("staff engineer|remoteok|remote".encode("utf-8")).hexdigest()
    row = conn.execute("SELECT content_hash, sources FROM jobs").fetchone()
    assert (new, existing) == (1, 0)
    assert row == (expected_hash, "RemoteOK")


def test_store_jobs_dedupes_by_company_content_hash_before_url_and_appends_source():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE jobs (url TEXT PRIMARY KEY)")
    ensure_columns(conn)

    first = {
        "url": "https://remoteok.example/job",
        "title": "Staff Engineer",
        "company": "Acme",
        "location": "Remote",
    }
    second = {
        "url": "https://greenhouse.example/job",
        "title": " staff engineer ",
        "company": " acme ",
        "location": " remote ",
    }

    assert store_jobs(conn, [first], "RemoteOK", "api") == (1, 0)
    assert store_jobs(conn, [second], "Greenhouse", "api") == (0, 1)

    rows = conn.execute("SELECT url, site, sources FROM jobs").fetchall()
    assert rows == [("https://remoteok.example/job", "RemoteOK", "RemoteOK,Greenhouse")]


def test_store_jobs_keeps_same_title_location_from_different_companies():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE jobs (url TEXT PRIMARY KEY)")
    ensure_columns(conn)

    first = {
        "url": "https://a.example/job",
        "title": "Staff Engineer",
        "company": "Acme",
        "location": "Remote",
    }
    second = {
        "url": "https://b.example/job",
        "title": "Staff Engineer",
        "company": "Globex",
        "location": "Remote",
    }

    assert store_jobs(conn, [first], "BoardA", "api") == (1, 0)
    assert store_jobs(conn, [second], "BoardB", "api") == (1, 0)


def test_store_jobs_tolerates_legacy_null_content_hash_and_sources_on_url_duplicate():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE jobs (url TEXT PRIMARY KEY)")
    ensure_columns(conn)
    conn.execute(
        "INSERT INTO jobs (url, title, location, site, content_hash, sources) VALUES (?, ?, ?, ?, ?, ?)",
        ("https://legacy.example/job", "Staff Engineer", "Remote", "Legacy", None, None),
    )

    new, existing = store_jobs(
        conn,
        [{"url": "https://legacy.example/job", "title": "Staff Engineer", "location": "Remote"}],
        "RemoteOK",
        "api",
    )

    row = conn.execute(
        "SELECT content_hash, sources FROM jobs WHERE url = ?",
        ("https://legacy.example/job",),
    ).fetchone()
    assert (new, existing) == (0, 1)
    assert row == (None, "Legacy,RemoteOK")
