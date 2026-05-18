"""Install python-jobspy outside normal package deps (numpy pin conflict in metadata)."""

from __future__ import annotations

import subprocess
import sys

JOBSPY_PACKAGE = "python-jobspy"
JOBSPY_RUNTIME_DEPS = (
    "pydantic",
    "tls-client",
    "requests",
    "markdownify",
    "regex",
)


def jobspy_importable() -> bool:
    try:
        import jobspy  # noqa: F401
    except ImportError:
        return False
    return True


def install_jobspy() -> None:
    """Install python-jobspy with --no-deps, then its runtime requirements."""
    pip = [sys.executable, "-m", "pip", "install"]
    subprocess.check_call([*pip, "--no-deps", JOBSPY_PACKAGE])
    subprocess.check_call([*pip, *JOBSPY_RUNTIME_DEPS])


def install_hint() -> str:
    return "Run: applypilot install-discovery"
