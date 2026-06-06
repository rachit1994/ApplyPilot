"""Ad-hoc harness: run the Direct Apply driver on specific jobs (dry-run by default).

Usage:
  uv run python scripts/direct_dryrun.py [--submit] [--match SUBSTR ...]

Launches worker-0 Chrome (visible, persistent profile), then for each matching
job in the DB runs apply_via_direct and prints the DriverResult + the fields the
engine filled (from the apply_form_filled column). Dry-run never submits.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")

from applypilot.config import load_env, ensure_dirs
from applypilot.database import init_db, get_connection
from applypilot.apply import chrome
from applypilot.apply.direct.driver import apply_via_direct
from applypilot.apply.direct import fingerprint
from applypilot.role_resumes import resolve_job_resume

COLS = [
    "url", "application_url", "title", "site", "full_description",
    "description", "location", "salary", "score_role_key",
    "tailored_resume_path", "cover_letter_path", "apply_status",
]


def load_jobs(matches: list[str]) -> list[dict]:
    con = get_connection()
    rows = con.execute(
        f"SELECT {', '.join(COLS)} FROM jobs "
        "WHERE apply_status IN ('needs_adapter','failed') ORDER BY title"
    ).fetchall()
    jobs = [dict(zip(COLS, r)) for r in rows]
    if matches:
        jobs = [j for j in jobs if any(m.lower() in (j["title"] or "").lower() for m in matches)]
    return jobs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--submit", action="store_true", help="Actually submit (default dry-run)")
    ap.add_argument("--match", action="append", default=[], help="Title substring filter")
    ap.add_argument("--worker", type=int, default=0)
    args = ap.parse_args()

    load_env(); ensure_dirs(); init_db()
    jobs = load_jobs(args.match)
    if not jobs:
        print("no matching jobs")
        return 1

    port = chrome.BASE_CDP_PORT + args.worker
    print(f"Launching Chrome worker-{args.worker} on port {port} ...")
    chrome.launch_chrome(args.worker, port=port, headless=False)

    con = get_connection()
    for job in jobs:
        url = job["application_url"] or job["url"]
        fam = fingerprint.ats_family(url)
        res = resolve_job_resume(job, allow_base=True)
        print("\n" + "=" * 90)
        print(f"JOB: {job['title']}")
        print(f"  url={url}")
        print(f"  family={fam}  resume={res.source}/{res.role_key} (jd={res.jd_score}) -> {res.path}")
        try:
            dr = apply_via_direct(job, port=port, worker_id=args.worker, dry_run=not args.submit)
        except Exception as exc:  # noqa: BLE001
            print(f"  EXCEPTION: {exc!r}")
            continue
        print(f"  RESULT: {dr.result}  escalate={dr.escalate} reason={dr.escalate_reason}")
        if args.submit and (dr.result == "applied" or dr.result.startswith("submitted_unverified")):
            from datetime import datetime, timezone
            status = "applied" if dr.result == "applied" else "submitted_unverified"
            con.execute(
                "UPDATE jobs SET apply_status = ?, applied_at = ?, apply_error = NULL, "
                "apply_duration_ms = ? WHERE url = ?",
                (status, datetime.now(timezone.utc).isoformat(), dr.elapsed_ms, job["url"]),
            )
            con.commit()
            print(f"  >>> DB marked {status} for {job['title']!r}")
        print(f"  fields_total={dr.fields_total} fields_llm={dr.fields_llm} tier={dr.tier_resolved} elapsed={dr.elapsed_ms}ms")
        row = con.execute("SELECT apply_form_filled FROM jobs WHERE url = ?", (job["url"],)).fetchone()
        if row and row[0]:
            try:
                rec = json.loads(row[0])
                flds = rec.get("fields", [])
                print(f"  filled {len(flds)} fields, empty_required={rec.get('empty_required')}:")
                for f in flds:
                    print(f"      - {f.get('label','')[:45]:45} = {str(f.get('value',''))[:40]!r} [{f.get('via','')}]")
                if rec.get("visible_errors"):
                    print(f"  visible_errors: {rec['visible_errors']}")
            except Exception:  # noqa: BLE001
                print(f"  apply_form_filled(raw)={row[0][:300]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
