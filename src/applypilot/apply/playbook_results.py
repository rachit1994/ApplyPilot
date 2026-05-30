"""Parse terminal RESULT lines from worker-apply-playbook.md."""

from __future__ import annotations

import re

# Keys are lower-cased payload after "RESULT:" (e.g. "applied", "failed:sso_required").
PLAYBOOK_TO_LAUNCHER: dict[str, str] = {
    "failed:sso_required": "failed:sso_required",
    "failed:unsafe_verification": "failed:unsafe_verification",
    "failed:not_a_job_application": "failed:not_a_job_application",
    "failed:expired": "expired",
    "failed:unsafe_data": "failed:unsafe_data",
    "applied": "submitted_unverified:playbook_applied",
    "needs_email_code": "failed:needs_email_code",
    "captcha": "captcha",
    "failed:stuck": "failed:stuck",
}

_RESULT_LINE_RE = re.compile(r"^RESULT:(.+)$", re.IGNORECASE)


def parse_playbook_result_line(output: str) -> str | None:
    """Return the payload after RESULT: from the last matching line, or None."""
    last: str | None = None
    for line in output.splitlines():
        stripped = line.strip()
        match = _RESULT_LINE_RE.match(stripped)
        if not match:
            continue
        payload = match.group(1).strip()
        # Legacy agent output uses uppercase RESULT:APPLIED (not playbook RESULT:applied).
        if payload == "APPLIED":
            continue
        last = payload
    if not last:
        return None
    return last.lower()


def resolve_playbook_result(output: str) -> str | None:
    """Map playbook terminal line to launcher status string."""
    key = parse_playbook_result_line(output)
    if key is None:
        return None
    return PLAYBOOK_TO_LAUNCHER.get(key)
