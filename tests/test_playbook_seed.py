"""Tests for nav_playbook YAML seeding."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from applypilot import config
from applypilot import database
from applypilot.apply.direct import playbook
from applypilot.apply.direct import playbook_seed


@pytest.fixture
def temp_db(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "test.db"
        monkeypatch.setenv("APPLYPILOT_DIR", tmp)
        config.load_env()
        monkeypatch.setattr(config, "APP_DIR", Path(tmp))
        database.close_connection()
        database.init_db()
        conn = database.get_connection()
        playbook.ensure_playbook_tables(conn)
        yield conn
        database.close_connection()


def test_load_nav_playbooks_yaml():
    data = playbook_seed.load_nav_playbooks_yaml()
    assert "workday" in data
    assert "greenhouse" in data
    assert "ashby" in data
    workday_steps = data["workday"]["steps"]
    assert any(step["name"] == "apply_reveal" for step in workday_steps)


def test_seed_nav_playbooks_inserts_rows(temp_db):
    written = playbook_seed.seed_nav_playbooks(temp_db)
    assert written > 0

    row = temp_db.execute("SELECT COUNT(*) AS n FROM nav_playbook").fetchone()
    assert int(row["n"]) == written

    seeded = temp_db.execute(
        "SELECT COUNT(*) AS n FROM nav_playbook WHERE source = 'seed' AND status = 'trusted'"
    ).fetchone()
    assert int(seeded["n"]) == written

    families = {
        row["ats_family"]
        for row in temp_db.execute(
            "SELECT DISTINCT ats_family FROM nav_playbook WHERE source = 'seed'"
        ).fetchall()
    }
    assert {"workday", "greenhouse", "ashby"}.issubset(families)


def test_seed_nav_playbooks_family_filter(temp_db):
    # Only the executable reveal nav action seeds (fill/upload/submit are
    # adapter-level and skipped), so one row per family.
    written = playbook_seed.seed_nav_playbooks(temp_db, families=["greenhouse"])
    assert written == 1
    families = {
        row["ats_family"]
        for row in temp_db.execute("SELECT DISTINCT ats_family FROM nav_playbook").fetchall()
    }
    assert families == {"greenhouse"}


def test_playbook_stats_returns_counts(temp_db):
    playbook_seed.seed_nav_playbooks(temp_db, families=["ashby"])
    stats = playbook_seed.playbook_stats(temp_db)

    assert stats["total"] == 1
    assert stats["by_status"]["trusted"] == 1
    assert stats["by_source"]["seed"] == 1
    assert stats["by_ats_family"]["ashby"] == 1


def test_list_nav_playbooks_status_filter(temp_db):
    playbook_seed.seed_nav_playbooks(temp_db, families=["greenhouse"])
    all_rows = playbook_seed.list_nav_playbooks(temp_db)
    trusted_rows = playbook_seed.list_nav_playbooks(temp_db, status="trusted")

    assert len(all_rows) == 1
    assert len(trusted_rows) == 1
    assert all(entry.status == "trusted" for entry in trusted_rows)
    assert all(entry.source == "seed" for entry in trusted_rows)
