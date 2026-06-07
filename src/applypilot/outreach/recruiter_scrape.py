"""Scrape LinkedIn job posting pages for the recruiter/hiring-team profile."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from applypilot.config import get_chrome_path
from applypilot.database import get_connection
from applypilot.db.dialect import sql_discovered_hours_param
from applypilot.outreach.config import OutreachSettings, load_outreach_config
from applypilot.outreach.public_id import is_linkedin_job_url, job_linkedin_url, public_id_from_url

log = logging.getLogger(__name__)

_POSTED_BY = re.compile(r"posted\s+by|job\s+poster|hiring\s+team", re.IGNORECASE)


def _collect_profile_slugs(page) -> list[str]:
    """Collect /in/ slugs from visible profile links on the page."""
    slugs: list[str] = []
    for anchor in page.locator('a[href*="/in/"]').all():
        try:
            href = anchor.get_attribute("href") or ""
        except Exception:
            continue
        slug = public_id_from_url(href)
        if slug and slug not in slugs:
            slugs.append(slug)
    return slugs


def _pick_poster_slug(page, slugs: list[str]) -> str | None:
    if not slugs:
        return None
    try:
        html = page.content()
    except Exception:
        return slugs[0]
    if _POSTED_BY.search(html):
        return slugs[0]
    return slugs[0]


def _recruiter_display_name(page, public_id: str) -> str | None:
    try:
        anchor = page.locator(f'a[href*="/in/{public_id}"]').first
        text = (anchor.inner_text(timeout=3000) or "").strip()
        if not text:
            return None
        line = text.split("\n")[0].strip()
        if 1 < len(line) < 80 and "linkedin" not in line.lower():
            return line
    except Exception:
        pass
    return None


def scrape_public_id_for_job_url(
    job_url: str, *, headless: bool = True
) -> tuple[str | None, str | None, str | None]:
    """Open a LinkedIn job URL and return (public_id, recruiter_name, error_message)."""
    if not is_linkedin_job_url(job_url):
        return None, None, "not a LinkedIn job URL"

    from playwright.sync_api import sync_playwright

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                executable_path=get_chrome_path(),
                headless=headless,
            )
            context = browser.new_context()
            page = context.new_page()
            page.goto(job_url, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(2000)
            slugs = _collect_profile_slugs(page)
            public_id = _pick_poster_slug(page, slugs)
            recruiter_name = _recruiter_display_name(page, public_id) if public_id else None
            browser.close()
    except Exception as exc:
        log.warning("Recruiter scrape failed for %s: %s", job_url, exc)
        return None, None, str(exc)

    if not public_id:
        return None, None, "no recruiter profile link found on job page"
    return public_id, recruiter_name, None


def _eligible_scrape_rows(
    conn,
    settings: OutreachSettings,
    *,
    urls: list[str] | None = None,
) -> list[dict]:
    query = f"""
        SELECT * FROM jobs
        WHERE fit_score >= ?
          AND (recruiter_public_id IS NULL OR recruiter_public_id = '')
          AND (referral_status IS NULL OR referral_status = '')
          AND {sql_discovered_hours_param("discovered_at")}
          AND (
            LOWER(COALESCE(site, '')) LIKE '%linkedin%'
            OR LOWER(COALESCE(url, '')) LIKE '%linkedin.com/jobs%'
            OR LOWER(COALESCE(application_url, '')) LIKE '%linkedin.com/jobs%'
          )
    """
    age_param = f"-{settings.max_job_age_hours}"
    params: list = [settings.min_fit_score, age_param]
    if urls:
        placeholders = ",".join("?" * len(urls))
        query += f" AND url IN ({placeholders})"
        params.extend(urls)
    rows = conn.execute(query, params).fetchall()
    jobs = [dict(row) for row in rows]
    return [j for j in jobs if job_linkedin_url(j)]


def run_recruiter_scrape(
    *,
    settings: OutreachSettings | None = None,
    limit: int = 50,
    headless: bool = True,
    dry_run: bool = False,
    urls: list[str] | None = None,
) -> dict:
    """Scrape recruiter public_id for eligible LinkedIn jobs."""
    settings = settings or load_outreach_config()
    conn = get_connection()
    jobs = _eligible_scrape_rows(conn, settings, urls=urls)[:limit]
    scraped = 0
    skipped = 0
    errors = 0

    for job in jobs:
        job_url = job_linkedin_url(job)
        if not job_url:
            continue
        if dry_run:
            log.info("[dry-run] would scrape recruiter from %s", job_url)
            continue

        public_id, recruiter_name, err = scrape_public_id_for_job_url(job_url, headless=headless)
        now = datetime.now(timezone.utc).isoformat()
        if public_id:
            conn.execute(
                """
                UPDATE jobs SET
                    recruiter_public_id = ?,
                    recruiter_name = COALESCE(?, recruiter_name),
                    recruiter_linkedin_url = ?,
                    recruiter_scraped_at = ?,
                    recruiter_scrape_error = NULL,
                    referral_status = COALESCE(referral_status, 'pending_connect')
                WHERE url = ?
                """,
                (
                    public_id,
                    recruiter_name,
                    f"https://www.linkedin.com/in/{public_id}/",
                    now,
                    job["url"],
                ),
            )
            scraped += 1
        else:
            conn.execute(
                """
                UPDATE jobs SET
                    recruiter_scraped_at = ?,
                    recruiter_scrape_error = ?,
                    referral_status = 'skipped'
                WHERE url = ?
                """,
                (now, err or "unknown", job["url"]),
            )
            if err and "no recruiter" in (err or "").lower():
                skipped += 1
            else:
                errors += 1
        conn.commit()

    return {"scraped": scraped, "skipped": skipped, "errors": errors, "candidates": len(jobs)}
