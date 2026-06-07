"""Serve local artifact files from the ApplyPilot data directory."""

from __future__ import annotations

import mimetypes
from pathlib import Path

from applypilot import config


def _allowed_roots() -> list[Path]:
    roots = [config.APP_DIR.resolve()]
    role_dir = config.ROLE_RESUME_DIR.resolve()
    if role_dir not in roots:
        roots.append(role_dir)
    return roots


def resolve_artifact_path(raw_path: str) -> Path:
    """Resolve a user artifact path and ensure it stays under an allowed root."""
    text = (raw_path or "").strip()
    if not text:
        raise ValueError("path is required")

    app_dir = config.APP_DIR
    candidate = Path(text).expanduser()
    if not candidate.is_absolute():
        candidate = app_dir / candidate

    resolved = candidate.resolve()
    allowed = _allowed_roots()
    if not any(resolved == root or root in resolved.parents for root in allowed):
        raise ValueError("path outside allowed artifact directories")

    if not resolved.is_file():
        raise FileNotFoundError("file not found")

    return resolved


def media_type_for_path(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(str(path))
    return guessed or "application/octet-stream"
