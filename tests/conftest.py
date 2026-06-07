"""Shared pytest fixtures."""

from __future__ import annotations

import os
import uuid

import pytest


def _admin_database_url(url: str) -> str:
    if "/" not in url:
        return url
    return url.rsplit("/", 1)[0] + "/postgres"


def _database_url_with_name(url: str, db_name: str) -> str:
    if "/" not in url:
        return url
    return url.rsplit("/", 1)[0] + f"/{db_name}"


@pytest.fixture(autouse=True)
def isolated_db(monkeypatch):
    """Point every test at a fresh ephemeral Postgres database."""
    import psycopg

    from applypilot import config, database
    from applypilot.db.connection import close_connection

    base_url = os.environ.get("APPLYPILOT_DATABASE_URL", config.DEFAULT_DATABASE_URL)
    admin_url = _admin_database_url(base_url)
    test_db = f"applypilot_test_{uuid.uuid4().hex[:12]}"
    test_url = _database_url_with_name(base_url, test_db)

    try:
        with psycopg.connect(admin_url, autocommit=True) as admin:
            admin.execute(f'CREATE DATABASE "{test_db}"')
    except Exception as exc:
        pytest.skip(f"Postgres not available for tests ({exc}). Start local Postgres first.")

    monkeypatch.setattr(config, "DATABASE_URL", test_url)
    monkeypatch.setenv("APPLYPILOT_DATABASE_URL", test_url)

    close_connection()
    database.init_db()
    yield test_url
    close_connection()
    try:
        with psycopg.connect(admin_url, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE "{test_db}" WITH (FORCE)')
    except Exception:
        pass


@pytest.fixture
def postgres_test_db(isolated_db):
    """Alias for the autouse ephemeral Postgres DB URL."""
    return isolated_db


@pytest.fixture
def no_skip_ats(monkeypatch):
    """Ensure all deterministic ATS adapters are enabled."""
    monkeypatch.setenv("APPLYPILOT_SKIP_ATS_FAMILIES", "off")
