"""Tests for local artifact file serving."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from applypilot.server.artifacts import resolve_artifact_path


@pytest.fixture
def temp_app_dir(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        monkeypatch.setenv("APPLYPILOT_DIR", str(root))
        from applypilot import config

        config.load_env()
        monkeypatch.setattr(config, "APP_DIR", root)
        yield root


def test_resolve_artifact_path_under_app_dir(temp_app_dir):
    pdf = temp_app_dir / "tailored_resumes" / "job.pdf"
    pdf.parent.mkdir(parents=True)
    pdf.write_bytes(b"%PDF-1.4 test")

    resolved = resolve_artifact_path(str(pdf))
    assert resolved == pdf.resolve()


def test_resolve_artifact_path_rejects_outside_app_dir(temp_app_dir):
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        outside = Path(f.name)
    try:
        with pytest.raises(ValueError, match="outside"):
            resolve_artifact_path(str(outside))
    finally:
        outside.unlink(missing_ok=True)


def test_api_artifact_file_redirects_to_file_uri(temp_app_dir):
    from applypilot.server.app import create_app

    pdf = temp_app_dir / "cover_letters" / "cover.pdf"
    pdf.parent.mkdir(parents=True)
    pdf.write_bytes(b"%PDF cover")

    client = TestClient(create_app(), follow_redirects=False)
    res = client.get("/api/artifacts/file", params={"path": str(pdf)})
    assert res.status_code == 302
    assert res.headers.get("location") == pdf.resolve().as_uri()


def test_resolve_artifact_path_allows_role_resume_dir(temp_app_dir, monkeypatch):
    from applypilot import config

    role_root = temp_app_dir / "role_resumes"
    role_root.mkdir()
    monkeypatch.setattr(config, "ROLE_RESUME_DIR", role_root)
    pdf = role_root / "backend-engineer" / "backend-engineer.pdf"
    pdf.parent.mkdir(parents=True)
    pdf.write_bytes(b"%PDF role")

    resolved = resolve_artifact_path(str(pdf))
    assert resolved == pdf.resolve()
