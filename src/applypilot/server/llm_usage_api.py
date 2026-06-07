"""Dashboard API payload for LLM / Claude Code usage (GET /api/llm-usage)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from applypilot import __version__
from applypilot.apply import apply_settings
from applypilot.database import get_connection, get_llm_usage_monthly, init_db
from applypilot.db.dialect import scalar, sql_created_at_since_param, table_exists


def _utc_today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _utc_month() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _sum_cost(conn, *, provider: str | None, day: str | None, month: str | None) -> float:
    if not table_exists(conn, "llm_usage_events"):
        return 0.0
    clauses: list[str] = []
    params: list[Any] = []
    if provider:
        clauses.append("provider = ?")
        params.append(provider)
    if day:
        clauses.append("substr(created_at, 1, 10) = ?")
        params.append(day)
    if month:
        clauses.append("substr(created_at, 1, 7) = ?")
        params.append(month)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    row = conn.execute(
        f"SELECT COALESCE(SUM(cost_usd), 0) FROM llm_usage_events {where}",
        params,
    ).fetchone()
    return float(scalar(row) or 0.0)


def _aggregate(
    conn,
    *,
    provider: str | None,
    group_by: str,
    month: str | None,
    day: str | None,
) -> list[dict[str, Any]]:
    if not table_exists(conn, "llm_usage_events"):
        return []
    clauses: list[str] = []
    params: list[Any] = []
    if provider:
        clauses.append("provider = ?")
        params.append(provider)
    if month:
        clauses.append("substr(created_at, 1, 7) = ?")
        params.append(month)
    if day:
        clauses.append("substr(created_at, 1, 10) = ?")
        params.append(day)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = conn.execute(
        f"""
        SELECT
            {group_by} AS key,
            COUNT(*) AS calls,
            SUM(input_tokens) AS input_tokens,
            SUM(output_tokens) AS output_tokens,
            SUM(cache_read_tokens) AS cache_read_tokens,
            SUM(cache_create_tokens) AS cache_create_tokens,
            SUM(cost_usd) AS cost_usd
        FROM llm_usage_events
        {where}
        GROUP BY {group_by}
        ORDER BY cost_usd DESC, calls DESC
        """,
        params,
    ).fetchall()
    return [
        {
            "key": str(r["key"] or ""),
            "calls": int(r["calls"] or 0),
            "input_tokens": int(r["input_tokens"] or 0),
            "output_tokens": int(r["output_tokens"] or 0),
            "cache_read_tokens": int(r["cache_read_tokens"] or 0),
            "cache_create_tokens": int(r["cache_create_tokens"] or 0),
            "cost_usd": float(r["cost_usd"] or 0.0),
        }
        for r in rows
    ]


def _daily_series(conn, *, provider: str, days: int = 7) -> list[dict[str, Any]]:
    if not table_exists(conn, "llm_usage_events"):
        return []
    clauses = [sql_created_at_since_param("created_at")]
    params: list[Any] = [f"-{int(days)} days"]
    if provider:
        clauses.append("provider = ?")
        params.append(provider)
    where = " AND ".join(clauses)
    rows = conn.execute(
        f"""
        SELECT
            substr(created_at, 1, 10) AS day,
            COUNT(*) AS calls,
            SUM(cost_usd) AS cost_usd,
            SUM(input_tokens) AS input_tokens,
            SUM(cache_read_tokens) AS cache_read_tokens
        FROM llm_usage_events
        WHERE {where}
        GROUP BY day
        ORDER BY day ASC
        """,
        params,
    ).fetchall()
    return [
        {
            "day": str(r["day"] or ""),
            "calls": int(r["calls"] or 0),
            "cost_usd": float(r["cost_usd"] or 0.0),
            "input_tokens": int(r["input_tokens"] or 0),
            "cache_read_tokens": int(r["cache_read_tokens"] or 0),
        }
        for r in rows
    ]


def _recent_events(conn, *, provider: str | None, limit: int = 25) -> list[dict[str, Any]]:
    if not table_exists(conn, "llm_usage_events"):
        return []
    clauses: list[str] = []
    params: list[Any] = []
    if provider:
        clauses.append("provider = ?")
        params.append(provider)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = conn.execute(
        f"""
        SELECT
            id, provider, model, operation,
            input_tokens, output_tokens,
            cache_read_tokens, cache_create_tokens,
            estimated, cost_usd, created_at, metadata_json
        FROM llm_usage_events
        {where}
        ORDER BY id DESC
        LIMIT ?
        """,
        (*params, int(limit)),
    ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        meta: dict[str, Any] = {}
        if r["metadata_json"]:
            try:
                meta = json.loads(r["metadata_json"])
            except json.JSONDecodeError:
                meta = {}
        out.append({
            "id": int(r["id"] or 0),
            "provider": str(r["provider"] or ""),
            "model": str(r["model"] or ""),
            "operation": str(r["operation"] or ""),
            "input_tokens": int(r["input_tokens"] or 0),
            "output_tokens": int(r["output_tokens"] or 0),
            "cache_read_tokens": int(r["cache_read_tokens"] or 0),
            "cache_create_tokens": int(r["cache_create_tokens"] or 0),
            "estimated": bool(r["estimated"]),
            "cost_usd": float(r["cost_usd"] or 0.0),
            "created_at": str(r["created_at"] or ""),
            "metadata": meta,
        })
    return out


def _apply_quota_stats(conn) -> dict[str, int]:
    if not table_exists(conn, "jobs"):
        return {"quota_blocked_jobs": 0, "quota_blocked_recent": 0}
    blocked = conn.execute(
        """
        SELECT COUNT(*) AS c FROM jobs
        WHERE COALESCE(apply_error, '') LIKE '%claude_quota_exhausted%'
        """
    ).fetchone()
    recent = conn.execute(
        """
        SELECT COUNT(*) AS c FROM jobs
        WHERE COALESCE(apply_error, '') LIKE '%claude_quota_exhausted%'
          AND last_attempted_at IS NOT NULL
          AND last_attempted_at::timestamptz >= NOW() - INTERVAL '7 days'
        """
    ).fetchone()
    return {
        "quota_blocked_jobs": int(scalar(blocked) or 0),
        "quota_blocked_recent": int(scalar(recent) or 0),
    }


def build_llm_usage_detail(*, month: str | None = None) -> dict[str, Any]:
    """Aggregate usage for dashboard Claude Code monitoring panel."""
    init_db()
    conn = get_connection()
    today = _utc_today()
    selected_month = month or _utc_month()

    anthropic_today = _sum_cost(
        conn, provider="anthropic", day=today, month=None
    )
    anthropic_month = _sum_cost(
        conn, provider="anthropic", day=None, month=selected_month
    )
    all_today = _sum_cost(conn, provider=None, day=today, month=None)
    all_month = _sum_cost(conn, provider=None, day=None, month=selected_month)

    apply_today = _aggregate(
        conn,
        provider="anthropic",
        group_by="operation",
        day=today,
        month=None,
    )
    apply_month_rows = [
        r
        for r in get_llm_usage_monthly(conn, month=selected_month)
        if r.get("provider") == "anthropic"
    ]
    apply_calls_today = sum(int(r["calls"]) for r in apply_today)
    cache_today_row = conn.execute(
        """
        SELECT COALESCE(SUM(cache_read_tokens), 0) AS cache_read,
               COALESCE(SUM(input_tokens), 0) AS input_tokens
        FROM llm_usage_events
        WHERE provider = 'anthropic' AND substr(created_at, 1, 10) = ?
        """,
        (today,),
    ).fetchone() if table_exists(conn, "llm_usage_events") else None
    cache_read_today = int(cache_today_row["cache_read"] or 0) if cache_today_row else 0
    input_today = int(cache_today_row["input_tokens"] or 0) if cache_today_row else 0
    cache_hit_rate = (
        round(100.0 * cache_read_today / max(1, input_today), 1) if input_today else None
    )

    flags = apply_settings.apply_telemetry_flags()

    return {
        "month": selected_month,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "app_version": __version__,
        "ledger_available": table_exists(conn, "llm_usage_events"),
        "summary": {
            "claude_today_usd": anthropic_today,
            "claude_month_usd": anthropic_month,
            "all_providers_today_usd": all_today,
            "all_providers_month_usd": all_month,
            "claude_calls_today": apply_calls_today,
            "cache_read_tokens_today": cache_read_today,
            "cache_hit_rate_percent": cache_hit_rate,
        },
        "apply_config": {
            "primary_model": str(flags.get("apply_model_default", "haiku")),
            "fallback_model": str(flags.get("apply_fallback_model", "sonnet")),
            "prompt_slim": bool(flags.get("prompt_slim", True)),
            "session_reuse": bool(flags.get("session_reuse", True)),
            "gmail_mcp": bool(flags.get("gmail_mcp", False)),
        },
        "by_model_month": _aggregate(
            conn,
            provider="anthropic",
            group_by="model",
            day=None,
            month=selected_month,
        ),
        "by_operation_month": _aggregate(
            conn,
            provider="anthropic",
            group_by="operation",
            day=None,
            month=selected_month,
        ),
        "by_operation_today": apply_today,
        "monthly_ledger": apply_month_rows,
        "daily_claude": _daily_series(conn, provider="anthropic", days=7),
        "recent_events": _recent_events(conn, provider="anthropic", limit=25),
        "quota": _apply_quota_stats(conn),
        "providers_month": _aggregate(
            conn, provider=None, group_by="provider", day=None, month=selected_month
        ),
    }
