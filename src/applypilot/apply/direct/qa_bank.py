"""Resolver Tier-1: SQLite Q&A answer cache.

Maps a normalized question key -> stored answer so the Driver fills standard
screening fields with zero LLM calls after warm-up. Schema lives in
database.py::ensure_qa_bank_table.

The whole correctness story is in the KEY. A naive lowercase(label) key
over-collapses and serves wrong answers:

    "Total years of experience"        -> "8"
    "Years of experience with Python"  -> "4"

both reduce to "years of experience" and one shared answer is wrong in both
directions. So the key folds in the section header, the input name/autocomplete
attribute, and the answer type:

    question_key = sha1( norm(label) | norm(section) | norm(name_attr) | type )

answer_type contract (enforced by lookup):
  - text | select | bool | number  -> answer served verbatim from cache.
  - template                        -> answer is a Gemini prompt template;
    lookup() refuses to serve it (returns None) so the Resolver always
    re-renders company-specific prose at fill time. This is the anti-boilerplate
    guarantee: a recruiter never sees a cached "Why do you want to work here".
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha1

from applypilot.database import ensure_qa_bank_table, get_connection

# answer_types whose stored answer is safe to serve verbatim from cache.
_SERVABLE_TYPES: frozenset[str] = frozenset({"text", "select", "bool", "number"})
TEMPLATE_TYPE = "template"
VALID_TYPES: frozenset[str] = _SERVABLE_TYPES | {TEMPLATE_TYPE}

_WS_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[^\w\s]")


def normalize_text(value: str | None) -> str:
    """Lowercase, strip punctuation, collapse whitespace. Stable + idempotent."""
    if not value:
        return ""
    lowered = str(value).strip().lower()
    lowered = _PUNCT_RE.sub(" ", lowered)
    return _WS_RE.sub(" ", lowered).strip()


def question_key(
    label: str | None,
    *,
    section_header: str | None = None,
    name_attr: str | None = None,
    answer_type: str = "text",
) -> str:
    """Compute the collision-safe primary key for a question.

    Folds the disambiguating context into the hash so "Email under Referrer"
    and "Email under Personal" never collide, and a text answer can't be
    served to a select field.
    """
    parts = "|".join(
        (
            normalize_text(label),
            normalize_text(section_header),
            normalize_text(name_attr),
            (answer_type or "text").strip().lower(),
        )
    )
    return sha1(parts.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class QAEntry:
    question_key: str
    question_text: str | None
    answer: str | None
    answer_type: str
    section_header: str | None
    name_attr: str | None
    scope: str
    source: str
    hit_count: int


def lookup(
    label: str | None,
    *,
    section_header: str | None = None,
    name_attr: str | None = None,
    answer_type: str = "text",
    conn: sqlite3.Connection | None = None,
    bump_hit: bool = True,
) -> str | None:
    """Return a cached answer string, or None to fall through to Tier 2.

    Returns None for `template` rows on purpose — the Resolver must re-render
    those via Gemini with live context, never serve cached prose.
    """
    if conn is None:
        conn = get_connection()
    ensure_qa_bank_table(conn)
    key = question_key(
        label,
        section_header=section_header,
        name_attr=name_attr,
        answer_type=answer_type,
    )
    row = conn.execute(
        "SELECT answer, answer_type FROM qa_bank WHERE question_key = ?",
        (key,),
    ).fetchone()
    if row is None:
        return None
    stored_type = (row["answer_type"] or "text").strip().lower()
    if stored_type not in _SERVABLE_TYPES:
        # template (or anything non-servable) -> force re-render upstream.
        return None
    if bump_hit:
        conn.execute(
            "UPDATE qa_bank SET hit_count = hit_count + 1, updated_at = ? "
            "WHERE question_key = ?",
            (datetime.now(timezone.utc).isoformat(), key),
        )
        conn.commit()
    return row["answer"]


def store(
    label: str | None,
    answer: str | None,
    *,
    answer_type: str = "text",
    section_header: str | None = None,
    name_attr: str | None = None,
    scope: str = "generic",
    source: str = "gemini",
    conn: sqlite3.Connection | None = None,
) -> str:
    """Upsert a Q&A row. Returns the question_key written.

    Idempotent on the key: re-storing the same (label, section, name, type)
    refreshes the answer/text/updated_at but preserves hit_count and created_at.
    """
    if answer_type not in VALID_TYPES:
        raise ValueError(f"invalid answer_type: {answer_type!r}")
    if conn is None:
        conn = get_connection()
    ensure_qa_bank_table(conn)
    key = question_key(
        label,
        section_header=section_header,
        name_attr=name_attr,
        answer_type=answer_type,
    )
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO qa_bank (
            question_key, question_text, answer, answer_type,
            section_header, name_attr, scope, source, hit_count,
            created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
        ON CONFLICT(question_key) DO UPDATE SET
            question_text = excluded.question_text,
            answer        = excluded.answer,
            section_header = excluded.section_header,
            name_attr     = excluded.name_attr,
            scope         = excluded.scope,
            source        = excluded.source,
            updated_at    = excluded.updated_at
        """,
        (
            key,
            label,
            answer,
            answer_type,
            section_header,
            name_attr,
            scope,
            source,
            now,
            now,
        ),
    )
    conn.commit()
    return key


def count(conn: sqlite3.Connection | None = None) -> int:
    """Number of rows in the Q&A bank (telemetry / seed verification)."""
    if conn is None:
        conn = get_connection()
    ensure_qa_bank_table(conn)
    return int(conn.execute("SELECT COUNT(*) FROM qa_bank").fetchone()[0])
