#!/usr/bin/env python3
"""Print compact pipeline metrics for stage tracking."""
from __future__ import annotations

from applypilot.database import get_stats, init_db


def main() -> None:
    init_db()
    s = get_stats()
    print(
        f"total={s['total']} "
        f"pending_enrich={s['pending_detail']} "
        f"unscored={s['unscored']} "
        f"tailored={s['tailored']} "
        f"untailored_7+={s['untailored_eligible']} "
        f"cover={s['with_cover_letter']} "
        f"ready_apply={s['ready_to_apply']} "
        f"recruiter={s.get('referral_recruiter_scraped', 0)} "
        f"ref_pending={s.get('referral_pending_connect', 0)}"
    )


if __name__ == "__main__":
    main()
