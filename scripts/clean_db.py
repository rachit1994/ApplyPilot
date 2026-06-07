#!/usr/bin/env python3
"""Wipe the local ApplyPilot Postgres database and re-create an empty schema.

Personal local project — no backup. Removes ALL jobs, apply outcomes, inbox
data, and telemetry, then re-initializes empty tables.

Usage:
    python scripts/clean_db.py            # prompts
    python scripts/clean_db.py --yes      # no prompt
"""

from __future__ import annotations

import argparse

from applypilot import config, database
from applypilot.db.status import redact_database_url


def main() -> None:
    ap = argparse.ArgumentParser(description="Wipe and re-init the local Postgres DB")
    ap.add_argument("--yes", action="store_true", help="Skip confirmation")
    args = ap.parse_args()

    dsn = redact_database_url(config.DATABASE_URL)
    if not args.yes:
        resp = input(f"TRUNCATE all tables on {dsn}? [y/N] ").strip().lower()
        if resp not in ("y", "yes"):
            print("Aborted.")
            return

    database.close_connection()
    database.wipe_all_data()
    database.init_db()
    print(f"Re-initialized empty schema on {dsn}")


if __name__ == "__main__":
    main()
