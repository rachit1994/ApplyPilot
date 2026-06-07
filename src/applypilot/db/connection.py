"""Thread-local Postgres connections with ``?`` placeholder compatibility."""

from __future__ import annotations

import re
import threading
from typing import Any

import psycopg
from psycopg.rows import dict_row

_local = threading.local()

_INSERT_RETURNING_RE = re.compile(
    r"^\s*INSERT\s+INTO\s+(\w+)",
    re.IGNORECASE | re.DOTALL,
)


def resolve_database_url(override: str | None = None) -> str:
    """Return DSN from override, env, or ``applypilot.config.DATABASE_URL``."""
    if override:
        text = str(override)
        if text.startswith("postgresql://") or text.startswith("postgres://"):
            return text
    import os

    from applypilot.config import DATABASE_URL

    return os.environ.get("APPLYPILOT_DATABASE_URL", DATABASE_URL)


def postgres_setup_hint() -> str:
    return (
        "Postgres is required. Install and start local Postgres, then:\n"
        "  brew install postgresql@16\n"
        "  brew services start postgresql@16\n"
        "  createdb applypilot\n"
        "  applypilot db init\n"
        "Set APPLYPILOT_DATABASE_URL in ~/.applypilot/.env to override the default DSN."
    )


class DbCursor:
    """Thin wrapper around psycopg cursor."""

    def __init__(self, cur: psycopg.Cursor, lastrowid: int | None = None) -> None:
        self._cur = cur
        self.lastrowid = lastrowid
        self.rowcount = cur.rowcount

    def fetchone(self) -> dict[str, Any] | None:
        return self._cur.fetchone()

    def fetchall(self) -> list[dict[str, Any]]:
        return self._cur.fetchall()


class DbConnection:
    """Postgres connection with ``?`` placeholders and dict rows."""

    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    @staticmethod
    def _adapt_sql(sql: str) -> str:
        """Convert ``?`` placeholders to psycopg ``%s``; escape other ``%``."""

        def _escape_percent(text: str) -> str:
            return re.sub(r"%(?![sbt])", "%%", text)

        if "?" not in sql:
            return _escape_percent(sql)
        parts = [_escape_percent(part) for part in sql.split("?")]
        return "%s".join(parts)

    def _maybe_add_returning(self, sql: str) -> tuple[str, bool]:
        upper = sql.strip().upper()
        if not upper.startswith("INSERT"):
            return sql, False
        if "RETURNING" in upper:
            return sql, True
        match = _INSERT_RETURNING_RE.match(sql)
        if not match:
            return sql, False
        table = match.group(1).lower()
        serial_tables = {
            "run_events",
            "llm_usage_events",
            "dashboard_activity_events",
            "apply_outcomes",
            "review_log",
            "inbox_audit_events",
        }
        if table in serial_tables:
            return sql.rstrip().rstrip(";") + " RETURNING id", True
        return sql, False

    def execute(self, sql: str, params: tuple | list = ()) -> DbCursor:
        sql = self._adapt_sql(sql)
        sql, has_returning = self._maybe_add_returning(sql)
        cur = self._conn.cursor(row_factory=dict_row)
        cur.execute(sql, params)
        lastrowid: int | None = None
        if has_returning:
            row = cur.fetchone()
            if row and "id" in row:
                lastrowid = int(row["id"])
            return DbCursor(cur, lastrowid)
        return DbCursor(cur)

    def executemany(self, sql: str, params_seq: list[tuple] | list[list]) -> DbCursor:
        sql = self._adapt_sql(sql)
        cur = self._conn.cursor(row_factory=dict_row)
        cur.executemany(sql, params_seq)
        return DbCursor(cur)

    def executescript(self, sql: str) -> None:
        statements = [s.strip() for s in sql.split(";") if s.strip()]
        for statement in statements:
            self.execute(statement)

    def commit(self) -> None:
        self._conn.commit()

    def begin_immediate(self) -> None:
        """Start an exclusive acquire transaction (Postgres: plain ``BEGIN``)."""
        self.execute("BEGIN")

    def rollback(self) -> None:
        self._conn.rollback()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> DbConnection:
        return self

    def __exit__(self, *args: object) -> None:
        self.commit()


Connection = DbConnection


def get_connection(database_url: str | None = None) -> DbConnection:
    """Open or reuse a thread-local Postgres connection."""
    url = resolve_database_url(database_url)

    if not hasattr(_local, "connections"):
        _local.connections = {}

    conn = _local.connections.get(url)
    if conn is not None:
        try:
            conn.execute("SELECT 1")
            return conn
        except Exception:
            try:
                conn.close()
            except Exception:
                pass
            _local.connections.pop(url, None)

    try:
        raw = psycopg.connect(url, row_factory=dict_row, autocommit=False)
    except Exception as exc:
        raise ConnectionError(f"{exc}\n\n{postgres_setup_hint()}") from exc

    wrapped = DbConnection(raw)
    _local.connections[url] = wrapped
    return wrapped


def close_connection(database_url: str | None = None) -> None:
    """Close the thread-local connection for *database_url* (or default DSN)."""
    if not hasattr(_local, "connections"):
        return
    url = resolve_database_url(database_url)
    conn = _local.connections.pop(url, None)
    if conn is not None:
        conn.close()
