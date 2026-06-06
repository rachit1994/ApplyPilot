"""Self-learning navigation + field-strategy cache (Tier 1).

Mirrors the qa_bank pattern: record what worked, replay at $0 on cache hit,
promote/retire entries from receipt-weighted feedback. Side-effecting actions
(submit, next_page, login, goto, apply) replay only when trusted; submit is
never replayed from cache.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha1
from typing import Any

from applypilot.apply.direct.qa_bank import normalize_text, question_key
from applypilot.database import get_connection

PROMOTE_K = 2
RETIRE_FAIL_RATE = 0.5
SIG_VERSION = 2

_NAV_VOCAB = (
    "apply",
    "next",
    "continue",
    "submit",
    "save",
    "sign in",
    "log in",
    "login",
    "accept",
    "agree",
    "review",
    "back",
    "upload",
    "create account",
    "register",
    "google",
)

SIDE_EFFECTING_ACTIONS: frozenset[str] = frozenset(
    {
        "submit",
        "next_page",
        "login_provider",
        "login_google",
        "goto",
        "apply",
        # 'click' is side-effecting too: in the unblock vocabulary it targets
        # Apply / Continue / off-page links, so a one-shot trial click that
        # navigated must NOT replay until the entry is trusted.
        "click",
    }
)

_VALID_STATUSES: frozenset[str] = frozenset(
    {"trial", "trusted", "retired", "banned", "pinned"}
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _json_loads(raw: str | None, default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default


def is_side_effecting(action_type: str) -> bool:
    return (action_type or "").strip().lower() in SIDE_EFFECTING_ACTIONS


def is_replay_allowed(action_type: str, status: str) -> bool:
    """Return True when a cached action may be replayed."""
    action = (action_type or "").strip().lower()
    st = (status or "").strip().lower()
    if action == "submit":
        return False
    if st not in {"trial", "trusted", "pinned"}:
        return False
    if is_side_effecting(action):
        return st in {"trusted", "pinned"}
    return True


def _normalize_clickables(clickables: list[str] | None) -> list[str]:
    if not clickables:
        return []
    normalized = [normalize_text(c) for c in clickables if c and str(c).strip()]
    return sorted(set(normalized))


def _canonical_nav_token(normalized_label: str) -> str | None:
    """Return the longest matching nav-vocab token for a normalized label."""
    for token in sorted(_NAV_VOCAB, key=len, reverse=True):
        if token in normalized_label:
            return token
    return None


def _salient_clickables(clickables: list[str] | None) -> list[str]:
    """Keep only nav-vocab labels, canonicalized, deduped, sorted."""
    if not clickables:
        return []
    found: set[str] = set()
    for raw in clickables:
        if not raw or not str(raw).strip():
            continue
        token = _canonical_nav_token(normalize_text(raw))
        if token:
            found.add(token)
    return sorted(found)


def state_signature(
    page_snapshot: dict[str, Any],
    *,
    ats_family: str,
    apex_host: str | None = None,
    step_name: str | None = None,
) -> str:
    """Hash navigation state for playbook lookup (narrow default scope)."""
    clickables = _salient_clickables(page_snapshot.get("clickables"))
    parts = "|".join(
        (
            str(SIG_VERSION),
            normalize_text(ats_family),
            normalize_text(apex_host),
            normalize_text(step_name),
            ",".join(clickables),
            "1" if page_snapshot.get("has_application_form") else "0",
            "1" if page_snapshot.get("has_password_field") else "0",
            "1" if page_snapshot.get("has_cookie_banner") else "0",
        )
    )
    return sha1(parts.encode("utf-8")).hexdigest()


def field_sig(
    label: str | None,
    *,
    section_header: str | None = None,
    name_attr: str | None = None,
    answer_type: str = "text",
) -> str:
    """Delegate to qa_bank.question_key for collision-safe field identity."""
    return question_key(
        label,
        section_header=section_header,
        name_attr=name_attr,
        answer_type=answer_type,
    )


def ensure_playbook_tables(conn: sqlite3.Connection | None = None) -> None:
    if conn is None:
        conn = get_connection()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS nav_playbook (
            state_sig        TEXT NOT NULL,
            sig_version      INTEGER NOT NULL DEFAULT 1,
            scope            TEXT NOT NULL DEFAULT 'host',
            ats_family       TEXT,
            apex_host        TEXT,
            step_name        TEXT,
            preconditions    TEXT,
            action_type      TEXT,
            action_args      TEXT,
            side_effecting   INTEGER NOT NULL DEFAULT 0,
            goto_allowlist   TEXT,
            status           TEXT NOT NULL DEFAULT 'trial',
            promote_score    REAL NOT NULL DEFAULT 0.0,
            success_weak     INTEGER NOT NULL DEFAULT 0,
            success_receipt  INTEGER NOT NULL DEFAULT 0,
            distinct_hosts   INTEGER NOT NULL DEFAULT 0,
            fail_count       INTEGER NOT NULL DEFAULT 0,
            source           TEXT,
            created_at       TEXT,
            last_used_at     TEXT,
            last_verified_at TEXT,
            PRIMARY KEY (state_sig, scope)
        );

        CREATE TABLE IF NOT EXISTS field_strategy (
            field_sig      TEXT NOT NULL,
            ats_family     TEXT NOT NULL,
            fill_method    TEXT NOT NULL,
            match_rule     TEXT,
            status         TEXT NOT NULL DEFAULT 'trial',
            success_count  INTEGER NOT NULL DEFAULT 0,
            fail_count     INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (field_sig, ats_family)
        );
        """
    )
    conn.commit()


def _fail_rate(success_weak: int, success_receipt: int, fail_count: int) -> float:
    total = success_weak + success_receipt + fail_count
    if total <= 0:
        return 0.0
    return fail_count / total


@dataclass(frozen=True)
class NavEntry:
    state_sig: str
    sig_version: int
    scope: str
    ats_family: str | None
    apex_host: str | None
    step_name: str | None
    preconditions: dict[str, Any]
    action_type: str
    action_args: dict[str, Any]
    side_effecting: bool
    goto_allowlist: list[str]
    status: str
    promote_score: float
    success_weak: int
    success_receipt: int
    distinct_hosts: int
    fail_count: int
    source: str | None
    created_at: str | None
    last_used_at: str | None
    last_verified_at: str | None


@dataclass(frozen=True)
class FieldStrategyEntry:
    field_sig: str
    ats_family: str
    fill_method: str
    match_rule: dict[str, Any]
    status: str
    success_count: int
    fail_count: int


def _row_to_nav_entry(row: sqlite3.Row) -> NavEntry:
    return NavEntry(
        state_sig=row["state_sig"],
        sig_version=int(row["sig_version"]),
        scope=row["scope"],
        ats_family=row["ats_family"],
        apex_host=row["apex_host"],
        step_name=row["step_name"],
        preconditions=_json_loads(row["preconditions"], {}),
        action_type=row["action_type"] or "",
        action_args=_json_loads(row["action_args"], {}),
        side_effecting=bool(row["side_effecting"]),
        goto_allowlist=_json_loads(row["goto_allowlist"], []),
        status=row["status"] or "trial",
        promote_score=float(row["promote_score"] or 0.0),
        success_weak=int(row["success_weak"] or 0),
        success_receipt=int(row["success_receipt"] or 0),
        distinct_hosts=int(row["distinct_hosts"] or 0),
        fail_count=int(row["fail_count"] or 0),
        source=row["source"],
        created_at=row["created_at"],
        last_used_at=row["last_used_at"],
        last_verified_at=row["last_verified_at"],
    )


def lookup_nav(
    state_sig: str,
    scope: str = "host",
    *,
    conn: sqlite3.Connection | None = None,
) -> NavEntry | None:
    if conn is None:
        conn = get_connection()
    ensure_playbook_tables(conn)
    row = conn.execute(
        "SELECT * FROM nav_playbook WHERE state_sig = ? AND scope = ?",
        (state_sig, scope),
    ).fetchone()
    if row is None:
        return None
    return _row_to_nav_entry(row)


def record_nav(
    state_sig: str,
    *,
    ats_family: str | None = None,
    apex_host: str | None = None,
    step_name: str | None = None,
    action_type: str,
    action_args: dict[str, Any] | None = None,
    preconditions: dict[str, Any] | None = None,
    goto_allowlist: list[str] | None = None,
    scope: str = "host",
    source: str = "gemini",
    status: str = "trial",
    force_update: bool = False,
    conn: sqlite3.Connection | None = None,
) -> NavEntry:
    """Insert or upsert a nav recipe.

    By default a conflicting write CANNOT clobber an owner ``banned``/``pinned``
    entry or a promoted ``trusted`` one — only ``trial``/``retired`` rows are
    re-learnable (the auto-discovery / Gemini path). ``force_update=True`` (the
    owner-authoritative seed path) overwrites regardless.
    """
    if conn is None:
        conn = get_connection()
    ensure_playbook_tables(conn)
    if status not in _VALID_STATUSES:
        raise ValueError(f"invalid nav status: {status!r}")
    action = (action_type or "").strip().lower()
    now = _now_iso()
    side_effecting = 1 if is_side_effecting(action) else 0
    # Guard re-records from the discovery path; the seed path bypasses it.
    conflict_guard = (
        "" if force_update
        else "WHERE nav_playbook.status NOT IN ('banned', 'pinned', 'trusted')"
    )
    conn.execute(
        f"""
        INSERT INTO nav_playbook (
            state_sig, sig_version, scope, ats_family, apex_host, step_name,
            preconditions, action_type, action_args, side_effecting,
            goto_allowlist, status, promote_score, success_weak, success_receipt,
            distinct_hosts, fail_count, source, created_at, last_used_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0.0, 0, 0, 0, 0, ?, ?, ?)
        ON CONFLICT(state_sig, scope) DO UPDATE SET
            sig_version = excluded.sig_version,
            ats_family = excluded.ats_family,
            apex_host = excluded.apex_host,
            step_name = excluded.step_name,
            preconditions = excluded.preconditions,
            action_type = excluded.action_type,
            action_args = excluded.action_args,
            side_effecting = excluded.side_effecting,
            goto_allowlist = excluded.goto_allowlist,
            status = excluded.status,
            source = excluded.source,
            last_used_at = excluded.last_used_at
        {conflict_guard}
        """,
        (
            state_sig,
            SIG_VERSION,
            scope,
            ats_family,
            apex_host,
            step_name,
            _json_dumps(preconditions or {}),
            action,
            _json_dumps(action_args or {}),
            side_effecting,
            _json_dumps(goto_allowlist or []),
            status,
            source,
            now,
            now,
        ),
    )
    conn.commit()
    entry = lookup_nav(state_sig, scope=scope, conn=conn)
    assert entry is not None
    return entry


def bump_success(
    state_sig: str,
    *,
    scope: str = "host",
    weak: bool = True,
    receipt: bool = False,
    conn: sqlite3.Connection | None = None,
) -> NavEntry | None:
    if conn is None:
        conn = get_connection()
    ensure_playbook_tables(conn)
    if weak:
        conn.execute(
            """
            UPDATE nav_playbook
            SET success_weak = success_weak + 1,
                promote_score = promote_score + 0.25,
                last_used_at = ?
            WHERE state_sig = ? AND scope = ?
            """,
            (_now_iso(), state_sig, scope),
        )
    if receipt:
        conn.execute(
            """
            UPDATE nav_playbook
            SET success_receipt = success_receipt + 1,
                promote_score = promote_score + 1.0,
                last_used_at = ?
            WHERE state_sig = ? AND scope = ?
            """,
            (_now_iso(), state_sig, scope),
        )
    conn.commit()
    maybe_promote(state_sig, scope=scope, conn=conn)
    return lookup_nav(state_sig, scope=scope, conn=conn)


def bump_fail(
    state_sig: str,
    *,
    scope: str = "host",
    conn: sqlite3.Connection | None = None,
) -> NavEntry | None:
    if conn is None:
        conn = get_connection()
    ensure_playbook_tables(conn)
    conn.execute(
        """
        UPDATE nav_playbook
        SET fail_count = fail_count + 1,
            promote_score = MAX(0.0, promote_score - 0.5),
            last_used_at = ?
        WHERE state_sig = ? AND scope = ?
        """,
        (_now_iso(), state_sig, scope),
    )
    conn.commit()
    entry = lookup_nav(state_sig, scope=scope, conn=conn)
    if entry is None:
        return None
    if _fail_rate(entry.success_weak, entry.success_receipt, entry.fail_count) > RETIRE_FAIL_RATE:
        retire(state_sig, scope=scope, conn=conn)
        return lookup_nav(state_sig, scope=scope, conn=conn)
    return entry


def promote(
    state_sig: str,
    *,
    scope: str = "host",
    status: str = "trusted",
    conn: sqlite3.Connection | None = None,
) -> NavEntry | None:
    if conn is None:
        conn = get_connection()
    ensure_playbook_tables(conn)
    if status not in _VALID_STATUSES:
        raise ValueError(f"invalid nav status: {status!r}")
    conn.execute(
        """
        UPDATE nav_playbook
        SET status = ?, last_used_at = ?
        WHERE state_sig = ? AND scope = ?
        """,
        (status, _now_iso(), state_sig, scope),
    )
    conn.commit()
    return lookup_nav(state_sig, scope=scope, conn=conn)


def retire(
    state_sig: str,
    *,
    scope: str = "host",
    conn: sqlite3.Connection | None = None,
) -> NavEntry | None:
    return promote(state_sig, scope=scope, status="retired", conn=conn)


def maybe_promote(
    state_sig: str,
    *,
    scope: str = "host",
    conn: sqlite3.Connection | None = None,
) -> NavEntry | None:
    entry = lookup_nav(state_sig, scope=scope, conn=conn)
    if entry is None or entry.status in {"trusted", "pinned", "retired", "banned"}:
        return entry
    rate = _fail_rate(entry.success_weak, entry.success_receipt, entry.fail_count)
    should_promote = entry.success_receipt >= 1 or (
        entry.success_weak >= PROMOTE_K and rate < RETIRE_FAIL_RATE
    )
    if should_promote:
        return promote(state_sig, scope=scope, status="trusted", conn=conn)
    return entry


def stamp_verified(
    state_sigs: list[str],
    *,
    scope: str = "host",
    conn: sqlite3.Connection | None = None,
) -> None:
    if not state_sigs:
        return
    if conn is None:
        conn = get_connection()
    ensure_playbook_tables(conn)
    now = _now_iso()
    placeholders = ",".join("?" for _ in state_sigs)
    conn.execute(
        f"""
        UPDATE nav_playbook
        SET last_verified_at = ?, success_receipt = success_receipt + 1,
            promote_score = promote_score + 1.0
        WHERE scope = ? AND state_sig IN ({placeholders})
        """,
        (now, scope, *state_sigs),
    )
    conn.commit()
    for sig in state_sigs:
        maybe_promote(sig, scope=scope, conn=conn)


def lookup_field_strategy(
    field_sig: str,
    ats_family: str,
    *,
    conn: sqlite3.Connection | None = None,
) -> str | None:
    if conn is None:
        conn = get_connection()
    ensure_playbook_tables(conn)
    row = conn.execute(
        """
        SELECT fill_method, status FROM field_strategy
        WHERE field_sig = ? AND ats_family = ?
        """,
        (field_sig, ats_family),
    ).fetchone()
    if row is None:
        return None
    status = (row["status"] or "trial").strip().lower()
    if status in {"retired", "banned"}:
        return None
    return row["fill_method"]


def record_field_strategy(
    field_sig: str,
    ats_family: str,
    fill_method: str,
    *,
    match_rule: dict[str, Any] | None = None,
    status: str = "trial",
    conn: sqlite3.Connection | None = None,
) -> FieldStrategyEntry:
    if conn is None:
        conn = get_connection()
    ensure_playbook_tables(conn)
    conn.execute(
        """
        INSERT INTO field_strategy (
            field_sig, ats_family, fill_method, match_rule, status,
            success_count, fail_count
        )
        VALUES (?, ?, ?, ?, ?, 1, 0)
        ON CONFLICT(field_sig, ats_family) DO UPDATE SET
            fill_method = excluded.fill_method,
            match_rule = excluded.match_rule,
            status = excluded.status,
            success_count = field_strategy.success_count + 1
        """,
        (
            field_sig,
            ats_family,
            fill_method,
            _json_dumps(match_rule or {}),
            status,
        ),
    )
    conn.commit()
    entry = get_field_strategy(field_sig, ats_family, conn=conn)
    assert entry is not None
    return entry


def bump_field_fail(
    field_sig: str,
    ats_family: str,
    *,
    conn: sqlite3.Connection | None = None,
) -> FieldStrategyEntry | None:
    if conn is None:
        conn = get_connection()
    ensure_playbook_tables(conn)
    conn.execute(
        """
        UPDATE field_strategy
        SET fail_count = fail_count + 1
        WHERE field_sig = ? AND ats_family = ?
        """,
        (field_sig, ats_family),
    )
    conn.commit()
    row = conn.execute(
        """
        SELECT fail_count, success_count FROM field_strategy
        WHERE field_sig = ? AND ats_family = ?
        """,
        (field_sig, ats_family),
    ).fetchone()
    if row is None:
        return None
    total = int(row["success_count"] or 0) + int(row["fail_count"] or 0)
    if total > 0 and (int(row["fail_count"] or 0) / total) > RETIRE_FAIL_RATE:
        conn.execute(
            """
            UPDATE field_strategy SET status = 'retired'
            WHERE field_sig = ? AND ats_family = ?
            """,
            (field_sig, ats_family),
        )
        conn.commit()
    return get_field_strategy(field_sig, ats_family, conn=conn)


def get_field_strategy(
    field_sig: str,
    ats_family: str,
    *,
    conn: sqlite3.Connection | None = None,
) -> FieldStrategyEntry | None:
    if conn is None:
        conn = get_connection()
    ensure_playbook_tables(conn)
    row = conn.execute(
        "SELECT * FROM field_strategy WHERE field_sig = ? AND ats_family = ?",
        (field_sig, ats_family),
    ).fetchone()
    if row is None:
        return None
    return FieldStrategyEntry(
        field_sig=row["field_sig"],
        ats_family=row["ats_family"],
        fill_method=row["fill_method"],
        match_rule=_json_loads(row["match_rule"], {}),
        status=row["status"] or "trial",
        success_count=int(row["success_count"] or 0),
        fail_count=int(row["fail_count"] or 0),
    )
