#!/usr/bin/env python3
"""Harvest India job apply-URLs from LinkedIn into the ApplyPilot DB.

Opens a VISIBLE Chrome (persistent profile). You log into LinkedIn once; the
session persists and is reused by Direct Apply. We search India jobs, click the
real Apply button, and store ONLY the redirected employer/ATS URL (never the
linkedin.com URL). For each company we also harvest its other open India roles.

Usage:
    python scripts/linkedin_harvest.py --keywords "backend engineer" --max 25
    # then submit deterministically (no Claude, greenhouse/ashby excluded):
    APPLYPILOT_SKIP_ATS_FAMILIES=greenhouse,ashby applypilot apply --deterministic-only
"""

from __future__ import annotations

import argparse
import logging

from applypilot.discovery.linkedin_harvest import run_harvest


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    ap = argparse.ArgumentParser(description="LinkedIn India → company apply-URL harvester")
    ap.add_argument("--keywords", required=True, help="Job search keywords, e.g. 'backend engineer'")
    ap.add_argument("--max", type=int, default=25, help="Max jobs from the main search")
    ap.add_argument("--max-company", type=int, default=15, help="Max extra roles per company")
    ap.add_argument("--max-employer", type=int, default=5, help="Max sibling roles from employer all-jobs pages")
    ap.add_argument("--no-expand", action="store_true", help="Do NOT harvest other roles per company")
    ap.add_argument("--no-employer-expand", action="store_true", help="Do NOT click employer All Jobs / Back to Jobs links")
    args = ap.parse_args()

    result = run_harvest(
        keywords=args.keywords,
        max_jobs=args.max,
        expand_company=not args.no_expand,
        max_company_jobs=args.max_company,
        expand_employer=not args.no_employer_expand,
        max_employer_jobs=args.max_employer,
    )
    print("\nHarvest result:", result)
    if result.get("error"):
        raise SystemExit(1)
    print(
        "\nNext: APPLYPILOT_SKIP_ATS_FAMILIES=greenhouse,ashby "
        "applypilot apply --deterministic-only"
    )


if __name__ == "__main__":
    main()
