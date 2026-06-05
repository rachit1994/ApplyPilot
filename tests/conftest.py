"""Shared pytest fixtures."""

from __future__ import annotations

import pytest


@pytest.fixture
def no_skip_ats(monkeypatch):
    """Ensure all deterministic ATS adapters are enabled."""
    monkeypatch.setenv("APPLYPILOT_SKIP_ATS_FAMILIES", "off")
