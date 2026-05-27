"""We Work Remotely RSS ingest."""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET

from applypilot.database import get_connection, init_db, store_jobs
from applypilot.discovery.feeds._http import get_text

log = logging.getLogger(__name__)

SITE = "We Work Remotely"
STRATEGY = "wwr_rss"
RSS_URL = "https://weworkremotely.com/categories/remote-programming-jobs.rss"


def _parse_rss(xml_text: str) -> list[dict]:
    root = ET.fromstring(xml_text)
    channel = root.find("channel")
    if channel is None:
        return []
    jobs: list[dict] = []
    for item in channel.findall("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        if not link:
            continue
        region = item.find("{http://weworkremotely.com}region")
        location = region.get("name") if region is not None else "Remote"
        desc = (item.findtext("description") or "").strip()
        desc = re.sub(r"<[^>]+>", " ", desc)
        jobs.append(
            {
                "url": link,
                "title": title,
                "salary": None,
                "description": desc[:2000] if desc else None,
                "location": location,
            }
        )
    return jobs


def run_wwr_discovery() -> dict:
    init_db()
    conn = get_connection()
    xml_text = get_text(RSS_URL)
    jobs = _parse_rss(xml_text)
    new, dup = store_jobs(conn, jobs, SITE, STRATEGY)
    log.info("WWR: %d fetched, +%d new, %d dup", len(jobs), new, dup)
    return {"fetched": len(jobs), "new": new, "duplicate": dup}
