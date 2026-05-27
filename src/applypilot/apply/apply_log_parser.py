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
    browser_marker = "browser snapshot "
    idx = log_text.rfind(browser_marker)
    if idx >= 0:
        start = log_text.find("{", idx + len(browser_marker))
        if start >= 0:
            snap = _extract_json_object(log_text, start)
            if snap is not None:
                return snap

    marker = '"fieldCount"'
    idx = log_text.rfind(marker)
    if idx < 0:
        return None
    start = log_text.rfind("{", 0, idx)
    if start < 0:
        return None
    return _extract_json_object(log_text, start)


_FILL_ACTION_PREFIXES = ("browser_fill ", "browser_type ", "fill ")
_FIELD_TYPE_PREFIXES = ("textarea", "input", "select")


def field_key(label: str) -> str:
    return (label or "").strip().lower()


def extract_fields_from_fill_actions(actions: list[str]) -> list[dict[str, Any]]:
    """Turn >> fill lines into structured label/value rows."""
    fields: list[dict[str, Any]] = []
    seen: set[str] = set()
    for action in actions:
        row = _parse_fill_action_line(action)
        if not row:
            continue
        key = field_key(row["label"])
        if not key or key in seen:
            continue
        seen.add(key)
        fields.append(row)
    return fields


def _parse_fill_action_line(action: str) -> dict[str, Any] | None:
    raw = action.strip()
    rest: str | None = None

    for prefix in _FILL_ACTION_PREFIXES:
        if raw.lower().startswith(prefix):
            rest = raw[len(prefix) :].strip()
            break

    if rest is None:
        match = re.match(r"Filled\s+(.+?)\s+with\s+(.+)$", raw, flags=re.IGNORECASE)
        if match:
            label = match.group(1).strip()
            value = match.group(2).strip()
            return _form_field_row(label, value, source="fill_action")
        return None

    parts = rest.split(maxsplit=2)
    if not parts:
        return None
    if len(parts) == 1:
        return _form_field_row(parts[0], "", source="fill_action")
    if parts[0] in _FIELD_TYPE_PREFIXES and len(parts) >= 3:
        label = f"{parts[0]} {parts[1]}"
        value = parts[2]
    elif parts[0] in _FIELD_TYPE_PREFIXES:
        label = parts[0]
        value = parts[1] if len(parts) > 1 else ""
    else:
        label = parts[0]
        value = parts[1] if len(parts) > 1 else ""
    return _form_field_row(label, value, source="fill_action")


def _form_field_row(
    label: str,
    value: str,
    *,
    source: str,
    field_type: str = "",
    empty: bool | None = None,
) -> dict[str, Any]:
    is_empty = empty if empty is not None else not str(value or "").strip()
    inferred = field_type or _infer_field_type(label)
    return {
        "label": label,
        "value": value,
        "type": inferred,
        "empty": is_empty,
        "source": source,
    }


def _infer_field_type(label: str) -> str:
    lower = label.lower()
    if "email" in lower:
        return "email"
    if "phone" in lower or "tel" in lower:
        return "tel"
    if "textarea" in lower or "message" in lower or "cover" in lower:
        return "textarea"
    if "resume" in lower or "upload" in lower or "file" in lower:
        return "file"
    return "text"


def merge_form_fields(
    snapshot_fields: list[dict[str, Any]],
    action_fields: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge browser snapshot rows with fill-action rows (snapshot wins when both set)."""
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    action_by_key = {
        field_key(f["label"]): f for f in action_fields if f.get("label")
    }

    for item in snapshot_fields:
        label = str(item.get("label") or "")
        key = field_key(label)
        if not key:
            continue
        row = {
            "label": label,
            "value": str(item.get("value") or ""),
            "type": str(item.get("type") or _infer_field_type(label)),
            "empty": bool(item.get("empty")),
            "source": "snapshot",
        }
        action = action_by_key.get(key)
        if action and action.get("value") and not row["value"]:
            row["value"] = str(action["value"])
        seen.add(key)
        result.append(row)

    for item in action_fields:
        key = field_key(str(item.get("label") or ""))
        if not key or key in seen:
            continue
        result.append(dict(item))
        seen.add(key)

    return result


def build_form_filled_record(log_text: str) -> dict[str, Any] | None:
    """Structured form values captured from an apply session log."""
    snapshot = extract_last_form_snapshot(log_text)
    snapshot_fields: list[dict[str, Any]] = []
    if snapshot and isinstance(snapshot.get("fields"), list):
        for item in snapshot["fields"]:
            if isinstance(item, dict):
                snapshot_fields.append(
                    _form_field_row(
                        str(item.get("label") or ""),
                        str(item.get("value") or ""),
                        source="snapshot",
                        field_type=str(item.get("type") or ""),
                        empty=bool(item.get("empty")),
                    )
                )

    fill_actions = extract_fill_actions(log_text)
    action_fields = extract_fields_from_fill_actions(fill_actions)
    merged = merge_form_fields(snapshot_fields, action_fields)

    if not merged and not fill_actions:
        return None

    return {
        "form_url": snapshot.get("url") if snapshot else None,
        "page_title": snapshot.get("title") if snapshot else None,
        "fields": merged,
        "fill_actions": fill_actions,
        "visible_errors": snapshot.get("visibleErrors", []) if snapshot else [],
        "empty_required": snapshot.get("emptyRequired") if snapshot else None,
        "field_count": len(merged),
    }


def form_filled_from_log_text(log_text: str) -> dict[str, Any] | None:
    return build_form_filled_record(log_text)


def form_filled_from_stored_json(raw: str | None) -> dict[str, Any] | None:
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def extract_fill_actions(log_text: str) -> list[str]:
    actions: list[str] = []
    for line in log_text.splitlines():
        stripped = line.strip()
        if stripped.startswith(">>"):
            action = stripped[2:].strip()
            if action and action not in actions:
                actions.append(action)
    return actions


def session_log_incomplete(log_path: Path | None) -> bool:
    """True when the agent made form progress but never emitted a RESULT line."""
    if log_path is None or not log_path.exists():
        return False
    try:
        text = log_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    if extract_result_status(text) or extract_result_json(text):
        return False
    return '"fieldCount"' in text or ">> browser_fill" in text


def extract_result_json(log_text: str) -> dict[str, Any] | None:
    """Parse the last RESULT_JSON:{...} object from agent output.

    Claude usually emits compact one-line JSON, but the prompt examples are
    multi-line. Scan the whole output from the last marker backward so pretty
    printed final lines are still accepted.
    """
    marker = "RESULT_JSON:"
    positions = [m.start() for m in re.finditer(re.escape(marker), log_text)]
    for pos in reversed(positions):
        payload_start = pos + len(marker)
        brace = log_text.find("{", payload_start)
        if brace < 0:
            continue
        parsed = _extract_json_object(log_text, brace)
        if isinstance(parsed, dict):
            return parsed
    return None


def extract_result_status(log_text: str) -> str | None:
    for line in reversed(log_text.splitlines()):
        if "RESULT_JSON:" in line:
            continue
        if "RESULT:" in line:
            pos = line.find("RESULT:")
            return line[pos:].strip()
    result_json = extract_result_json(log_text)
    if result_json:
        status = str(result_json.get("status", "failed"))
        reason = result_json.get("reason")
        if reason:
            return f"RESULT_JSON:{status}:{reason}"
        return f"RESULT_JSON:{status}"
    return None


def _verification_summary(
    log_text: str,
    *,
    result_json: dict[str, Any] | None,
    fill_actions: list[str],
) -> dict[str, Any] | None:
    """Re-run Tier-1 verification for dashboard display (mirrors launcher)."""
    from applypilot.apply.verification import (
        evaluate as verify_apply,
        record_from_legacy_applied,
        record_from_result_json,
    )

    if result_json:
        record = record_from_result_json(result_json, fill_actions=fill_actions)
    else:
        result_line = extract_result_status(log_text) or ""
        if "applied" not in result_line.lower():
            return None
        record = record_from_legacy_applied(fill_actions=fill_actions)

    verdict = verify_apply(record)
    return {
        "decision": verdict.decision,
        "reasons": list(verdict.reasons),
        "status": record.status,
        "submit_click_ref": record.submit_click_ref,
        "submit_button_text": record.submit_button_text,
        "pre_submit_url": record.pre_submit_url,
        "post_submit_url": record.post_submit_url,
        "confirmation_copy": record.confirmation_copy,
        "screenshot_path": record.screenshot_path,
        "verification_code_used": record.verification_code_used,
    }


def parse_apply_log(log_text: str) -> dict[str, Any]:
    form_filled = build_form_filled_record(log_text)
    fill_actions = form_filled["fill_actions"] if form_filled else extract_fill_actions(log_text)
    fields = list(form_filled["fields"]) if form_filled else []
    snapshot = extract_last_form_snapshot(log_text)
    result_json = extract_result_json(log_text)
    verification = _verification_summary(
        log_text,
        result_json=result_json,
        fill_actions=fill_actions,
    )
    return {
        "result_line": extract_result_status(log_text),
        "result_json": result_json,
        "verification": verification,
        "fill_actions": fill_actions,
        "form_url": snapshot.get("url") if snapshot else None,
        "page_title": snapshot.get("title") if snapshot else None,
        "fields": fields,
        "form_filled": form_filled,
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
    elif not stored_path:
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
