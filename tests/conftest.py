"""Shared pytest fixtures."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """Point every test at a fresh SQLite DB.

    The DB path is module-level (``config.DB_PATH``, imported into ``database``)
    and connections are thread-local cached, so without isolation tests write to
    the real ``~/.applypilot/applypilot.db`` and rows accumulate across runs
    (counts drift, promote/retire thresholds flake). This redirects each test to
    a tmp-dir DB and clears the cached connections before and after.
    """
    from applypilot import config, database

    db = tmp_path / "applypilot.db"
    monkeypatch.setattr(config, "DB_PATH", db)
    monkeypatch.setattr(database, "DB_PATH", db)

    def _reset_cache() -> None:
        conns = getattr(database._local, "connections", None)
        if conns:
            for c in conns.values():
                try:
                    c.close()
                except Exception:  # noqa: BLE001
                    pass
            database._local.connections = {}

    _reset_cache()
    database.init_db(db)
    yield
    _reset_cache()


@pytest.fixture
def no_skip_ats(monkeypatch):
    """Ensure all deterministic ATS adapters are enabled."""
    monkeypatch.setenv("APPLYPILOT_SKIP_ATS_FAMILIES", "off")
