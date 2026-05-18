#!/usr/bin/env python3
"""Import Work at a Startup jobs from a listing URL, then run pipeline + apply."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

_APPLYPILOT_BIN = Path(__file__).resolve().parents[1] / ".venv" / "bin" / "applypilot"

from applypilot.config import (
    COVER_LETTER_DIR,
    RESUME_PATH,
    TAILORED_DIR,
    ensure_dirs,
    load_env,
    load_profile,
)
from applypilot.database import get_connection, init_db
from applypilot.discovery.workatastartup import (
    DEFAULT_WAAS_LISTING_URLS,
    build_waas_listing_variants,
    run_workatastartup_discovery,
)
from applypilot.scoring.cover_letter import generate_cover_letter
from applypilot.scoring.pdf import convert_to_pdf
from applypilot.scoring.scorer import score_job
from applypilot.scoring.tailor import tailor_resume

LISTING_URL = DEFAULT_WAAS_LISTING_URLS[0]


def _waas_jobs(conn, *, min_score: int = 0, pending_only: bool = False) -> list[dict]:
    clause = "strategy = 'workatastartup'"
    params: list = []
    if min_score > 0:
        clause += " AND (fit_score IS NULL OR fit_score >= ?)"
        params.append(min_score)
    if pending_only:
        clause += " AND applied_at IS NULL"
    rows = conn.execute(
        f"SELECT * FROM jobs WHERE {clause} ORDER BY fit_score DESC NULLS LAST, discovered_at DESC",
        params,
    ).fetchall()
    if not rows:
        return []
    cols = rows[0].keys()
    return [dict(zip(cols, row)) for row in rows]


def _safe_prefix(job: dict) -> str:
    title = re.sub(r"[^\w\s-]", "", job["title"])[:50].strip().replace(" ", "_")
    site = re.sub(r"[^\w\s-]", "", job["site"])[:20].strip().replace(" ", "_")
    return f"{site}_{title}"


def _run_waas_pipeline(min_score: int, validation: str, *, rescore: bool = False) -> None:
    load_env()
    ensure_dirs()
    init_db()
    conn = get_connection()
    resume_text = RESUME_PATH.read_text(encoding="utf-8")
    profile = load_profile()
    jobs = _waas_jobs(conn)
    now = datetime.now(timezone.utc).isoformat()
    TAILORED_DIR.mkdir(parents=True, exist_ok=True)
    COVER_LETTER_DIR.mkdir(parents=True, exist_ok=True)

    for job in jobs:
        if job.get("fit_score") is None or rescore:
            result = score_job(resume_text, job, profile)
            conn.execute(
                "UPDATE jobs SET fit_score = ?, score_reasoning = ?, scored_at = ? WHERE url = ?",
                (
                    result["score"],
                    f"{result['keywords']}\n{result['reasoning']}",
                    now,
                    job["url"],
                ),
            )
            job["fit_score"] = result["score"]
            print(f"scored {job['title'][:50]} -> {result['score']}")

        if job.get("fit_score", 0) < min_score:
            continue

        if not job.get("tailored_resume_path"):
            try:
                tailored, report = tailor_resume(
                    resume_text, job, profile, validation_mode=validation
                )
                prefix = _safe_prefix(job)
                txt_path = TAILORED_DIR / f"{prefix}.txt"
                txt_path.write_text(tailored, encoding="utf-8")
                if report["status"] in ("approved", "approved_with_judge_warning"):
                    conn.execute(
                        "UPDATE jobs SET tailored_resume_path = ?, tailored_at = ? WHERE url = ?",
                        (str(txt_path), now, job["url"]),
                    )
                    convert_to_pdf(txt_path)
                    job["tailored_resume_path"] = str(txt_path)
                else:
                    conn.execute(
                        "UPDATE jobs SET tailored_resume_path = ? WHERE url = ?",
                        (str(RESUME_PATH), job["url"]),
                    )
                    job["tailored_resume_path"] = str(RESUME_PATH)
                    if RESUME_PATH.with_suffix(".pdf").exists() is False:
                        convert_to_pdf(RESUME_PATH)
            except Exception as exc:
                print(f"tailor fallback {job['title'][:40]}: {exc}")
                conn.execute(
                    "UPDATE jobs SET tailored_resume_path = ? WHERE url = ?",
                    (str(RESUME_PATH), job["url"]),
                )
                job["tailored_resume_path"] = str(RESUME_PATH)

        if not job.get("cover_letter_path") or rescore:
            letter = generate_cover_letter(
                resume_text, job, profile, validation_mode=validation
            )
            prefix = _safe_prefix(job)
            cl_path = COVER_LETTER_DIR / f"{prefix}_CL.txt"
            cl_path.write_text(letter, encoding="utf-8")
            convert_to_pdf(cl_path)
            conn.execute(
                "UPDATE jobs SET cover_letter_path = ?, cover_letter_at = ? WHERE url = ?",
                (str(cl_path), now, job["url"]),
            )
            print(f"message {job['title'][:50]}")

    conn.commit()


def _apply_each(min_score: int, *, watch: bool, dry_run: bool, limit: int | None) -> None:
    conn = get_connection()
    jobs = _waas_jobs(conn, min_score=min_score, pending_only=True)
    jobs = [j for j in jobs if j.get("cover_letter_path") and j.get("tailored_resume_path")]
    if limit is not None:
        jobs = jobs[:limit]

    for i, job in enumerate(jobs):
        apply_cmd = [
            str(_APPLYPILOT_BIN),
            "apply",
            "--url",
            job["url"],
            "--min-score",
            str(min_score),
            "--workers",
            "1",
            "--limit",
            "1",
            "--plain",
        ]
        if dry_run:
            apply_cmd.append("--dry-run")
        if watch and i == 0:
            apply_cmd.extend(["--watch", "--pace", "2", "--keep-open", "45"])
        print(
            f"\n>>> Applying ({i + 1}/{len(jobs)}): {job['title']} @ {job['site']}",
            flush=True,
        )
        result = subprocess.run(apply_cmd, check=False)
        if result.returncode != 0:
            print(f"    apply exited {result.returncode} for {job['url']}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Work at a Startup batch runner")
    parser.add_argument("--url", default=LISTING_URL, help="Primary filtered listing URL")
    parser.add_argument(
        "--all-listings",
        action="store_true",
        help="Merge jobs from all listing filter variants (best for 100+ when logged in)",
    )
    parser.add_argument(
        "--use-chrome-session",
        action="store_true",
        help="Use ApplyPilot Chrome worker-0 profile (YC login cookies after apply --watch)",
    )
    parser.add_argument("--max-jobs", type=int, default=None, help="Cap jobs scraped")
    parser.add_argument(
        "--rescore",
        action="store_true",
        help="Re-score all WaaS jobs after resume/role updates",
    )
    parser.add_argument("--min-score", type=int, default=7)
    parser.add_argument("--skip-discover", action="store_true")
    parser.add_argument("--skip-pipeline", action="store_true")
    parser.add_argument("--apply-limit", type=int, default=None)
    parser.add_argument("--dry-run-apply", action="store_true")
    parser.add_argument(
        "--watch",
        action="store_true",
        help="YC login review on first apply only",
    )
    args = parser.parse_args()

    load_env()
    ensure_dirs()
    init_db()

    if not Path(RESUME_PATH).with_suffix(".pdf").exists():
        convert_to_pdf(RESUME_PATH)

    if not args.skip_discover:
        list_urls = (
            build_waas_listing_variants()
            if args.all_listings
            else args.url
        )
        stats = run_workatastartup_discovery(
            list_urls,
            max_jobs=args.max_jobs,
            use_chrome_session=args.use_chrome_session,
        )
        print("Discovery:", stats)

    if not args.skip_pipeline:
        _run_waas_pipeline(
            args.min_score, validation="lenient", rescore=args.rescore
        )

    _apply_each(
        args.min_score,
        watch=args.watch,
        dry_run=args.dry_run_apply,
        limit=args.apply_limit,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
