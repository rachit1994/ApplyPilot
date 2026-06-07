"""AI browser discover via Claude Code + Playwright MCP (reuse apply Chrome stack)."""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import time
from pathlib import Path

from applypilot import config
from applypilot.apply.chrome import BASE_CDP_PORT, cleanup_worker, launch_chrome
from applypilot.apply.launcher import _make_mcp_config
from applypilot.database import get_connection, init_db, store_jobs
from applypilot.discovery.prompts.discover_agent import DISCOVER_AGENT_PROMPT

log = logging.getLogger(__name__)

JOBS_JSON_RE = re.compile(r"JOBS_JSON:\s*(\[.*\])\s*$", re.MULTILINE | re.DOTALL)
STRATEGY = "agent_browse"


def parse_jobs_json(text: str) -> list[dict]:
    """Extract job list from agent output."""
    match = JOBS_JSON_RE.search(text)
    if not match:
        return []
    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    jobs: list[dict] = []
    for row in data:
        if not isinstance(row, dict):
            continue
        url = (row.get("url") or "").strip()
        if not url:
            continue
        jobs.append(
            {
                "url": url,
                "title": row.get("title"),
                "salary": row.get("salary"),
                "description": row.get("description"),
                "location": row.get("location"),
            }
        )
    return jobs


def build_discover_prompt(
    *,
    site_name: str,
    start_url: str,
    search_terms: list[str] | None = None,
    location: str | None = None,
    max_pages: int = 3,
) -> str:
    terms = ", ".join(search_terms or []) or "senior engineer, staff, principal, architect, AI"
    loc = location or "India, remote, Bangalore"
    return DISCOVER_AGENT_PROMPT.format(
        site_name=site_name,
        start_url=start_url,
        search_terms=terms,
        location=loc,
        max_pages=max_pages,
    )


def run_agent_discover(
    *,
    site_name: str,
    start_url: str,
    search_terms: list[str] | None = None,
    location: str | None = None,
    max_pages: int = 3,
    headless: bool = False,
    worker_id: int = 0,
    timeout_seconds: int = 600,
) -> list[dict]:
    """Run Claude browser session to discover jobs on one careers page."""
    port = BASE_CDP_PORT + worker_id
    chrome_proc = launch_chrome(worker_id, port=port, headless=headless)
    mcp_path = config.APP_DIR / f".mcp-discover-{worker_id}.json"
    mcp_path.write_text(json.dumps(_make_mcp_config(port)), encoding="utf-8")

    prompt = build_discover_prompt(
        site_name=site_name,
        start_url=start_url,
        search_terms=search_terms,
        location=location,
        max_pages=max_pages,
    )

    cmd = [
        "claude",
        "-p",
        "--mcp-config",
        str(mcp_path),
        "--permission-mode",
        "bypassPermissions",
        "--no-session-persistence",
        "--output-format",
        "stream-json",
        "--verbose",
        "-",
    ]
    env = os.environ.copy()
    env.pop("CLAUDECODE", None)
    env.pop("CLAUDE_CODE_ENTRYPOINT", None)

    log_path = config.LOG_DIR / f"claude_discover_{site_name.replace(' ', '_')[:40]}.txt"
    text_parts: list[str] = []
    try:
        proc = subprocess.run(
            cmd,
            input=prompt,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=timeout_seconds,
            cwd=str(config.APP_DIR),
        )
        raw = (proc.stdout or "") + "\n" + (proc.stderr or "")
        log_path.write_text(raw, encoding="utf-8")
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
                if msg.get("type") == "assistant":
                    for block in msg.get("message", {}).get("content", []):
                        if block.get("type") == "text":
                            text_parts.append(block["text"])
            except json.JSONDecodeError:
                text_parts.append(line)
    except subprocess.TimeoutExpired:
        log.warning("Agent discover timed out for %s", site_name)
    except FileNotFoundError:
        log.error("claude CLI not found — install Claude Code for agent discover")
        return []
    finally:
        cleanup_worker(worker_id, chrome_proc)

    combined = "\n".join(text_parts)
    jobs = parse_jobs_json(combined)
    log.info("Agent discover %s: %d jobs parsed", site_name, len(jobs))
    return jobs


def run_agent_discover_and_store(
    *,
    site_name: str,
    start_url: str,
    search_terms: list[str] | None = None,
    location: str | None = None,
    max_pages: int = 3,
    headless: bool = False,
) -> dict:
    init_db()
    conn = get_connection()
    jobs = run_agent_discover(
        site_name=site_name,
        start_url=start_url,
        search_terms=search_terms,
        location=location,
        max_pages=max_pages,
        headless=headless,
    )
    new, dup = store_jobs(conn, jobs, site_name, STRATEGY)
    return {"fetched": len(jobs), "new": new, "duplicate": dup}


def run_agent_sites(
    sites: list[dict],
    *,
    max_pages: int = 3,
    headless: bool = False,
) -> dict:
    """Run agent discover for each site dict with name + url."""
    totals = {"sites": 0, "fetched": 0, "new": 0, "duplicate": 0}
    for i, site in enumerate(sites):
        name = site.get("name") or "Unknown"
        url = site.get("url") or ""
        if not url:
            continue
        totals["sites"] += 1
        stats = run_agent_discover_and_store(
            site_name=name,
            start_url=url,
            search_terms=site.get("search_terms"),
            location=site.get("location"),
            max_pages=max_pages,
            headless=headless,
        )
        totals["fetched"] += stats.get("fetched", 0)
        totals["new"] += stats.get("new", 0)
        totals["duplicate"] += stats.get("duplicate", 0)
        if i < len(sites) - 1:
            time.sleep(2)
    return totals
