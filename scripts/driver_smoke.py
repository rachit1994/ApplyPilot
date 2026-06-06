#!/usr/bin/env python3
"""Dry-run the Direct Apply driver over captured jobs (fills, never submits).

Validates the generic filler + login detection on real forms without submitting.
Uses the base resume; disables the Gemini tier (no key needed).
"""

from __future__ import annotations

import sys

from applypilot import config
from applypilot.apply.direct.driver import apply_via_direct
from applypilot.database import get_connection


def main() -> None:
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    c = get_connection()
    rows = c.execute(
        "SELECT url, title, site, location, full_description, application_url, salary "
        "FROM jobs ORDER BY discovered_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    # This automation shell has no LLM key; stub cover-letter generation so we can
    # validate the deterministic form fill (basic fields need no LLM).
    import applypilot.apply.cover_resolve as _cover

    _cover.resolve_apply_cover_letter = lambda job: ("", "", None)

    resume = str(config.APP_DIR / "resume.pdf")
    print(f"Dry-running {len(rows)} job(s) (no submit)\n")
    for r in rows:
        job = dict(r)
        job["tailored_resume_path"] = resume
        job["fit_score"] = 8
        try:
            dr = apply_via_direct(
                job, port=9222, worker_id=0, dry_run=True, gemini_enabled=False
            )
            print(
                f"[{(dr.ats_family or '?'):12}] result={dr.result:38} "
                f"reason={dr.escalate_reason or '-':22} fields={dr.fields_total} "
                f"| {(job.get('title') or '')[:30]}"
            )
        except Exception as e:  # noqa: BLE001
            print(f"[ERROR] {type(e).__name__}: {str(e)[:80]} | {(job.get('title') or '')[:30]}")


if __name__ == "__main__":
    main()
