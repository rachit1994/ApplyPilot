#!/usr/bin/env python3
"""Wipe the local ApplyPilot DB and re-create an empty schema.

Personal local project — no backup. Removes ALL jobs, apply outcomes, inbox
data, and telemetry, then re-initializes empty tables.

Usage:
    python scripts/clean_db.py            # prompts
    python scripts/clean_db.py --yes      # no prompt
"""

from __future__ import annotations

import argparse

from applypilot import config
from applypilot import database


def main() -> None:
    ap = argparse.ArgumentParser(description="Wipe and re-init the local DB")
    ap.add_argument("--yes", action="store_true", help="Skip confirmation")
    args = ap.parse_args()

    db_path = config.DB_PATH
    if not args.yes:
        resp = input(f"Delete and re-create {db_path}? [y/N] ").strip().lower()
        if resp not in ("y", "yes"):
            print("Aborted.")
            return

    database.close_connection()
    try:
        database.close_connection(db_path)
    except Exception:  # noqa: BLE001
        pass
    if db_path.exists():
        db_path.unlink()
        print(f"Deleted {db_path}")
    database.init_db()
    print(f"Re-initialized empty schema at {db_path}")


if __name__ == "__main__":
    main()
