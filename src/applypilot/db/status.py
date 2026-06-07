"""Postgres connectivity and table statistics."""

from __future__ import annotations

from typing import Any

from applypilot.db.connection import get_connection, resolve_database_url
from applypilot.db.dialect import table_exists
from applypilot.db.schema import TABLES_MIGRATION_ORDER


def _postgres_row_count(conn, table: str) -> int:
    if not table_exists(conn, table):
        return 0
    row = conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()
    return int(row["c"]) if row else 0


def redact_database_url(url: str) -> str:
    if "@" not in url or "://" not in url:
        return url
    prefix, rest = url.split("://", 1)
    if "@" in rest and ":" in rest.split("@", 1)[0]:
        user_host = rest.split("@", 1)
        return f"{prefix}://***@{user_host[1]}"
    if "@" in rest:
        return f"{prefix}://***@{rest.split('@', 1)[1]}"
    return url


def database_status(target_url: str | None = None) -> dict[str, Any]:
    """Postgres connectivity, version, and table row counts."""
    url = resolve_database_url(target_url)
    conn = get_connection(url)
    version_row = conn.execute("SELECT version() AS v").fetchone()
    counts = {
        t: _postgres_row_count(conn, t)
        for t in TABLES_MIGRATION_ORDER
        if table_exists(conn, t)
    }
    return {
        "database_url": redact_database_url(url),
        "postgres_version": version_row["v"] if version_row else None,
        "table_counts": counts,
        "total_rows": sum(counts.values()),
    }
