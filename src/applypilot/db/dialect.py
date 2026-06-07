"""Postgres-specific SQL helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import psycopg.errors

if TYPE_CHECKING:
    from applypilot.db.connection import Connection


def table_columns(conn: Connection, table: str) -> set[str]:
    """Return column names for *table* (replaces ``PRAGMA table_info``)."""
    rows = conn.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = %s
        """,
        (table,),
    ).fetchall()
    return {str(r["column_name"]) for r in rows}


def table_exists(conn: Connection, table: str) -> bool:
    """Return True if *table* exists in the public schema."""
    row = conn.execute(
        """
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = %s
        LIMIT 1
        """,
        (table,),
    ).fetchone()
    return row is not None


def is_unique_violation(exc: BaseException) -> bool:
    """True when *exc* is a Postgres unique-constraint violation."""
    return isinstance(exc, psycopg.errors.UniqueViolation)


def sql_created_at_since_param(column: str = "created_at") -> str:
    """``column::timestamptz >= NOW() + %s::interval`` with bound param like ``'-7 days'``."""
    return f"{column}::timestamptz >= NOW() + %s::interval"


def sql_discovered_hours_param(column: str = "discovered_at") -> str:
    """``column::timestamptz >= NOW() + (CAST(%s AS text) || ' hours')::interval``."""
    return f"{column}::timestamptz >= NOW() + (CAST(%s AS text) || ' hours')::interval"


def sql_apply_not_before_due(column: str = "apply_not_before") -> str:
    """True when apply-not-before is unset or in the past."""
    return f"({column} IS NULL OR {column}::timestamptz <= NOW())"


def sql_ts_coalesce(*columns: str) -> str:
    """``COALESCE(c1::timestamptz, c2::timestamptz, ...)`` for text ISO timestamp columns."""
    parts = ", ".join(f"{col}::timestamptz" for col in columns)
    return f"COALESCE({parts})"


def sql_ts_before_interval(column: str, interval_param: str = "%s") -> str:
    """``column::timestamptz < NOW() + %s::interval`` (param e.g. ``'-1 hour'``)."""
    return f"{column}::timestamptz < NOW() + {interval_param}::interval"


def scalar(row: dict[str, Any] | None) -> Any:
    """First column value from a single-row dict result."""
    if row is None:
        return None
    return next(iter(row.values()))
