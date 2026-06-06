"""Lightweight workflow induction — graduate repeated review_log successes."""

from __future__ import annotations

from typing import Any

from applypilot.apply.direct import playbook


def induce_candidates(conn, *, min_support: int = 3) -> list[dict[str, Any]]:
    """Return nav clusters ready for owner promotion.

    Groups successful ``review_log`` rows by ``(ats_family, state_sig, action_type)``
    when support >= ``min_support`` and the signature is not already trusted in
    ``nav_playbook``.
    """
    from applypilot.apply.direct.review_log import ensure_review_log_table

    ensure_review_log_table(conn)
    playbook.ensure_playbook_tables(conn)
    rows = conn.execute(
        """
        SELECT
          ats_family,
          state_sig,
          action_type,
          COUNT(*) AS support
        FROM review_log
        WHERE postcondition_met = 1
          AND state_sig IS NOT NULL
          AND state_sig != ''
          AND action_type IS NOT NULL
          AND action_type != ''
        GROUP BY ats_family, state_sig, action_type
        HAVING COUNT(*) >= ?
        ORDER BY support DESC
        """,
        (min_support,),
    ).fetchall()

    candidates: list[dict[str, Any]] = []
    for row in rows:
        state_sig = row["state_sig"]
        trusted = playbook.lookup_nav(state_sig, scope="host", conn=conn)
        if trusted is not None and trusted.status in {"trusted", "pinned"}:
            continue
        fam_trusted = playbook.lookup_nav(state_sig, scope="family", conn=conn)
        if fam_trusted is not None and fam_trusted.status in {"trusted", "pinned"}:
            continue
        candidates.append(
            {
                "ats_family": row["ats_family"],
                "state_sig": state_sig,
                "action_type": row["action_type"],
                "support": int(row["support"]),
            }
        )
    return candidates
