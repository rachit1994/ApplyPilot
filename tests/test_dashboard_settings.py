"""Dashboard agent settings API and persistence."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def temp_settings_dir(monkeypatch):
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        from applypilot import config
        from applypilot import dashboard_settings

        monkeypatch.setenv("APPLYPILOT_DIR", tmp)
        monkeypatch.setattr(config, "APP_DIR", Path(tmp))
        monkeypatch.setattr(dashboard_settings, "SETTINGS_PATH", Path(tmp) / "dashboard_settings.json")
        config.DEFAULTS["apply_min_score"] = 0
        config.DEFAULTS["min_score"] = 7
        yield Path(tmp)


def test_agent_settings_defaults(temp_settings_dir):
    from applypilot.dashboard_settings import load_agent_settings
    from applypilot.server.app import create_app

    client = TestClient(create_app())
    r = client.get("/api/settings/agent")
    assert r.status_code == 200
    body = r.json()
    assert body["agent"]["apply_min_score"] == 7.0
    assert body["agent"]["auto_apply_enabled"] is True
    assert load_agent_settings()["apply_min_score"] == 7.0


def test_agent_settings_patch_persists_and_updates_config(temp_settings_dir):
    from applypilot import config
    from applypilot.dashboard_settings import SETTINGS_PATH
    from applypilot.server.app import create_app

    client = TestClient(create_app())
    r = client.patch("/api/settings/agent", json={"apply_min_score": 8.5})
    assert r.status_code == 200
    assert r.json()["agent"]["apply_min_score"] == 8.5
    assert config.DEFAULTS["apply_min_score"] == 8
    assert config.DEFAULTS["min_score"] == 8

    saved = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    assert saved["agent"]["apply_min_score"] == 8.5
    assert saved.get("updated_at")

    r2 = client.get("/api/settings/agent")
    assert r2.json()["agent"]["apply_min_score"] == 8.5


def test_agent_settings_rejects_empty_patch(temp_settings_dir):
    from applypilot.server.app import create_app

    client = TestClient(create_app())
    r = client.patch("/api/settings/agent", json={})
    assert r.status_code == 400
