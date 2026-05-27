"""Run controller dispatch: API kwargs must match each run type."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


def test_start_typed_run_pipeline_does_not_pass_apply_fields(monkeypatch):
    from applypilot.orchestration import run_controller as rc

    captured: dict = {}

    def fake_pipeline(**kwargs):
        captured.update(kwargs)
        return {"id": "pipe-1", "status": "running"}

    monkeypatch.setattr(rc, "start_pipeline_run", fake_pipeline)

    rc.start_typed_run(
        "pipeline",
        stages=["discover"],
        dry_run=True,
        limit=3,
        watch=True,
        pace=True,
        min_score=8,
        workers=2,
        validation_mode="strict",
    )

    assert captured == {
        "stages": ["discover"],
        "stream": False,
        "dry_run": True,
        "force": False,
        "min_score": 8,
        "workers": 2,
        "validation_mode": "strict",
    }
    assert "limit" not in captured
    assert "watch" not in captured


def test_subprocess_cwd_points_at_repo_root():
    from applypilot.orchestration.run_controller import _subprocess_cwd

    from pathlib import Path

    root = Path(_subprocess_cwd())
    assert (root / "pyproject.toml").is_file()
    assert (root / "src" / "applypilot").is_dir()


def test_inbox_pipeline_action_maps_to_run_subcommand():
    from applypilot.orchestration.run_controller import _normalize_inbox_cli_action

    assert _normalize_inbox_cli_action("pipeline") == "run"
    assert _normalize_inbox_cli_action("scan") == "scan"
