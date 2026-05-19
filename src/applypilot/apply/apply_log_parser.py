"""Parse Claude apply session logs for form snapshots and outcomes."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from applypilot.config import LOG_DIR


def _extract_json_object(text: str, start: int) -> dict[str, Any] | None:
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                blob = text[start : i + 1]
                try:
                    parsed = json.loads(blob)
                except json.JSONDecodeError:
                    return None
                return parsed if isinstance(parsed, dict) else None
    return None


def extract_last_form_snapshot(log_text: str) -> dict[str, Any] | None:
    """Return the last browser_evaluate form snapshot embedded in a log."""
    marker = '"fieldCount"'
    idx = log_text.rfind(marker)
    if idx < 0:
        return None
    start = log_text.rfind("{", 0, idx)
    if start < 0:
        return None
    return _extract_json_object(log_text, start)


def extract_fill_actions(log_text: str) -> list[str]:
    actions: list[str] = []
    for line in log_text.splitlines():
        stripped = line.strip()
        if stripped.startswith(">>"):
            action = stripped[2:].strip()
            if action and action not in actions:
                actions.append(action)
    return actions


def extract_result_status(log_text: str) -> str | None:
    for line in reversed(log_text.splitlines()):
        if "RESULT:" in line:
            pos = line.find("RESULT:")
            return line[pos:].strip()
    return None


def parse_apply_log(log_text: str) -> dict[str, Any]:
    snapshot = extract_last_form_snapshot(log_text)
    fields = []
    if snapshot and isinstance(snapshot.get("fields"), list):
        for item in snapshot["fields"]:
            if isinstance(item, dict):
                fields.append(
                    {
                        "label": item.get("label", ""),
                        "value": item.get("value", ""),
                        "type": item.get("type", ""),
                        "empty": bool(item.get("empty")),
                    }
                )
    return {
        "result_line": extract_result_status(log_text),
        "fill_actions": extract_fill_actions(log_text),
        "form_url": snapshot.get("url") if snapshot else None,
        "page_title": snapshot.get("title") if snapshot else None,
        "fields": fields,
        "visible_errors": snapshot.get("visibleErrors", []) if snapshot else [],
        "empty_required": snapshot.get("emptyRequired") if snapshot else None,
    }


def resolve_apply_log_path(
    stored_path: str | None,
    *,
    job_url: str,
    title: str | None = None,
) -> Path | None:
    if stored_path:
        path = Path(stored_path)
        if path.is_file():
            return path

    if not LOG_DIR.is_dir():
        return None

    url_needle = job_url[:80]
    title_needle = (title or "")[:40]
    candidates = sorted(
        LOG_DIR.glob("claude_*.txt"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for path in candidates[:150]:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if url_needle in text or (title_needle and title_needle in text):
            return path
    return None


def _worker_log_section(job_url: str) -> str:
    if not LOG_DIR.is_dir():
        return ""
    for path in sorted(
        LOG_DIR.glob("worker-*.log"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )[:5]:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        marker = f"URL: {job_url}"
        pos = text.rfind(marker)
        if pos < 0:
            continue
        section = text[pos:]
        next_sep = section.find("\n" + "=" * 60, 10)
        if next_sep > 0:
            section = section[:next_sep]
        return section
    return ""


def load_apply_log_detail(
    stored_path: str | None,
    *,
    job_url: str,
    title: str | None = None,
) -> dict[str, Any]:
    path = resolve_apply_log_path(stored_path, job_url=job_url, title=title)
    parts: list[str] = []
    if path:
        parts.append(path.read_text(encoding="utf-8", errors="ignore"))
    worker_section = _worker_log_section(job_url)
    if worker_section:
        parts.append(worker_section)
    if not parts:
        return {
            "log_path": None,
            "log_excerpt": None,
            "parsed": None,
        }
    text = "\n\n".join(parts)
    excerpt = text[-16_000:] if len(text) > 16_000 else text
    return {
        "log_path": str(path) if path else None,
        "log_excerpt": excerpt,
        "parsed": parse_apply_log(text),
    }
