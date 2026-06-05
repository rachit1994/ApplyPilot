#!/usr/bin/env python3
"""Resume Direct Apply after logging into a provider.

Use when apply is paused on "AWAITING LOGIN: <domain>". Log into that provider in
the visible Chrome, then run this to clear the gate and re-queue the parked jobs.

Usage:
    python scripts/login_resume.py                 # show what's waiting
    python scripts/login_resume.py --resume        # resume ALL pending
    python scripts/login_resume.py --resume --domain naukri.com
"""

from __future__ import annotations

import argparse

from applypilot.apply import login_gate


def main() -> None:
    ap = argparse.ArgumentParser(description="Resume apply after provider login")
    ap.add_argument("--resume", action="store_true", help="Clear the gate and re-queue")
    ap.add_argument("--domain", default=None, help="Only this domain (default: all)")
    args = ap.parse_args()

    pend = login_gate.pending()
    if not pend:
        print("No providers awaiting login.")
    else:
        print("Awaiting login:")
        for p in pend:
            print(f"  - {p.get('domain')}  ({p.get('url', '')[:70]})")

    if args.resume:
        from applypilot.apply.launcher import resume_login

        result = resume_login(args.domain)
        print(f"Resumed: {result}")


if __name__ == "__main__":
    main()
