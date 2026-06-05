"""Pre-seed nav_playbook rows from config/nav_playbooks.yaml.

Idempotent: re-running refreshes seeded recipes via playbook.record_nav upsert.
Seeds start as status=trusted, source=seed so Tier-1 replay works from job #1.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from applypilot import config
from applypilot.apply.direct import playbook
from applypilot.database import get_connection

logger = logging.getLogger(__name__)

SEED_SCOPE = "family"
SEED_STATUS = "trusted"
SEED_SOURCE = "seed"

# Tools the unblock loop (unblock._execute) can actually replay. Everything else
# in the YAML (fill_all_known / upload / submit / login_provider / next_page)
# describes the Tier-0 ATS adapter's form-fill + submit flow, which the nav cache
# does NOT execute — those are seeded as no-ops, so we skip them here.
_UNBLOCK_EXECUTABLE: frozenset[str] = frozenset(
    {"click", "accept_cookies", "goto", "wait", "login_google"}
)


def default_nav_playbooks_path() -> Path:
    return config.CONFIG_DIR / "nav_playbooks.yaml"


def load_nav_playbooks_yaml(path: Path | str | None = None) -> dict[str, Any]:
    """Load ATS-family navigation seed recipes from YAML."""
    yaml_path = Path(path) if path is not None else default_nav_playbooks_path()
    if not yaml_path.exists():
        raise FileNotFoundError(f"missing nav playbook seed file: {yaml_path}")
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError("nav_playbooks.yaml must be a mapping of ats_family -> steps")
    return data


def _snapshot_from_preconditions(preconditions: dict[str, Any] | None) -> dict[str, Any]:
    pre = preconditions or {}
    clickables = pre.get("clickables") or []
    if not isinstance(clickables, list):
        clickables = []
    return {
        "clickables": clickables,
        "has_application_form": bool(pre.get("has_application_form")),
        "has_password_field": bool(pre.get("has_password_field")),
        "has_cookie_banner": bool(pre.get("has_cookie_banner")),
    }


def _seed_state_sig(
    *,
    ats_family: str,
    snapshot: dict[str, Any],
) -> str:
    # Family-scope signature: drop apex_host AND step_name so it matches the
    # resolver's family-scope lookup (unblock_learning._family_state_sig). The
    # snapshot's clickables + flags carry the state identity; the human step name
    # is kept only in the step_name column for display.
    return playbook.state_signature(
        snapshot,
        ats_family=ats_family,
        apex_host=None,
        step_name=None,
    )


def seed_nav_playbooks(
    conn=None,
    *,
    families: list[str] | None = None,
    path: Path | str | None = None,
) -> int:
    """Insert or refresh seeded nav_playbook rows. Returns rows written."""
    if conn is None:
        conn = get_connection()
    playbook.ensure_playbook_tables(conn)

    data = load_nav_playbooks_yaml(path)
    target = [f.strip().lower() for f in (families or []) if f and str(f).strip()]
    if not target:
        target = [str(k).strip().lower() for k in data.keys()]

    written = 0
    for family in target:
        family_cfg = data.get(family)
        if not isinstance(family_cfg, dict):
            logger.warning("Skipping unknown or invalid nav playbook family: %s", family)
            continue
        steps = family_cfg.get("steps") or []
        if not isinstance(steps, list):
            logger.warning("Skipping %s — steps must be a list", family)
            continue

        for step in steps:
            if not isinstance(step, dict):
                continue
            step_name = (step.get("name") or "").strip()
            if not step_name:
                continue
            preconditions = step.get("preconditions") or {}
            if preconditions and not isinstance(preconditions, dict):
                preconditions = {}
            snapshot = _snapshot_from_preconditions(preconditions)
            actions = step.get("actions") or []
            if not isinstance(actions, list):
                continue

            # One page-state -> one action: a step's actions share one snapshot,
            # so they collapse to one family signature. Seed only the FIRST
            # unblock-executable nav action (the reveal). The rest of a step's
            # actions (fill/upload/submit/next_page) are Tier-0 adapter work.
            seeded_step = False
            for action in actions:
                if seeded_step or not isinstance(action, dict):
                    continue
                tool = (action.get("tool") or action.get("action_type") or "").strip().lower()
                if not tool:
                    continue
                if tool not in _UNBLOCK_EXECUTABLE:
                    logger.debug(
                        "seed skip non-executable nav tool %r (%s/%s) — adapter-level",
                        tool, family, step_name,
                    )
                    continue
                args = action.get("args") or {}
                if not isinstance(args, dict):
                    args = {}

                sig = _seed_state_sig(ats_family=family, snapshot=snapshot)
                playbook.record_nav(
                    sig,
                    ats_family=family,
                    apex_host=None,
                    step_name=step_name,
                    action_type=tool,
                    action_args=args,
                    preconditions=preconditions,
                    scope=SEED_SCOPE,
                    source=SEED_SOURCE,
                    status=SEED_STATUS,
                    force_update=True,  # owner-authoritative seed refresh
                    conn=conn,
                )
                written += 1
                seeded_step = True

    return written


def list_nav_playbooks(
    conn=None,
    *,
    status: str | None = None,
) -> list[playbook.NavEntry]:
    """Return nav_playbook rows, optionally filtered by status."""
    if conn is None:
        conn = get_connection()
    playbook.ensure_playbook_tables(conn)

    if status:
        rows = conn.execute(
            "SELECT * FROM nav_playbook WHERE status = ? ORDER BY ats_family, step_name",
            (status.strip().lower(),),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM nav_playbook ORDER BY ats_family, step_name, action_type"
        ).fetchall()
    return [playbook._row_to_nav_entry(row) for row in rows]


def playbook_stats(conn=None) -> dict[str, Any]:
    """Aggregate nav_playbook counts by status, source, and ats_family."""
    if conn is None:
        conn = get_connection()
    playbook.ensure_playbook_tables(conn)

    def _count_group(column: str) -> dict[str, int]:
        rows = conn.execute(
            f"""
            SELECT COALESCE({column}, '') AS key, COUNT(*) AS n
            FROM nav_playbook
            GROUP BY COALESCE({column}, '')
            ORDER BY key
            """
        ).fetchall()
        return {str(row["key"]): int(row["n"]) for row in rows}

    total = conn.execute("SELECT COUNT(*) AS n FROM nav_playbook").fetchone()
    return {
        "total": int(total["n"] if total else 0),
        "by_status": _count_group("status"),
        "by_source": _count_group("source"),
        "by_ats_family": _count_group("ats_family"),
    }
