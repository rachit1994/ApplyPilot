#!/usr/bin/env python3
"""Run full inbox flow and print per-thread send results."""

from __future__ import annotations

import json
import sys

from applypilot.config import ensure_dirs, load_env
from applypilot.database import init_db
from applypilot.inbox.config import load_inbox_config
from applypilot.inbox.runner import run_inbox_pipeline


def main() -> int:
    dry_run = "--send" not in sys.argv
    load_env()
    ensure_dirs()
    init_db()
    cfg = load_inbox_config()
    report = run_inbox_pipeline(settings=cfg, dry_run=dry_run)
    print(json.dumps(report, indent=2, default=str))
    send = report.get("send") or {}
    for row in send.get("results") or []:
        print("\n---")
        print(f"to: {row.get('public_id')}")
        print(f"status: {row.get('status')}")
        if row.get("message"):
            print(f"message: {row['message']}")
        if row.get("error"):
            print(f"error: {row['error']}")
    return 0 if send.get("errors", 0) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
