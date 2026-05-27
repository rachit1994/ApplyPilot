"""Company watchlist for Greenhouse / Lever API polling."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from applypilot.config import APP_DIR, CONFIG_DIR


def load_watchlist() -> list[dict[str, Any]]:
    rows: list[dict] = []
    seen: set[str] = set()
    for path in (APP_DIR / "watchlist.yaml", CONFIG_DIR / "watchlist.example.yaml"):
        if not path.exists():
            continue
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for row in data.get("companies") or []:
            if not isinstance(row, dict):
                continue
            name = (row.get("name") or "").strip()
            if not name or name.lower() in seen:
                continue
            seen.add(name.lower())
            rows.append(row)
    return rows
