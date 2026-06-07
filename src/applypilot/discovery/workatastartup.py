"""Discover jobs from Y Combinator Work at a Startup listing URLs."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright

from pathlib import Path

from applypilot import config
from applypilot.apply.salary import salary_meets_regional_minimum
from applypilot.db.connection import Connection
from applypilot.db.dialect import is_unique_violation
from applypilot.database import get_connection, init_db

WAAS_STORAGE_STATE = config.APP_DIR / "waas_storage_state.json"

log = logging.getLogger(__name__)

SITE_LABEL = "Work at a Startup"
STRATEGY = "workatastartup"

_WAAS_BASE = (
    "https://www.workatastartup.com/companies?"
    "demographic=any&hasEquity=any&hasSalary=true&industry=any&"
    "interviewProcess=any&jobType=any&layout=list-compact&"
    "remote=yes&role=eng&sortBy=most_active&tab=any&usVisaNotRequired=any"
)

# Multiple listings merge unique job IDs (pagination + role coverage).
DEFAULT_WAAS_LISTING_URLS: list[str] = [
    _WAAS_BASE
    + "&minExperience=6&minExperience=11&minExperience=3&"
    "role_type=fs&role_type=be&role_type=fe&role_type=eng_mgmt",
    _WAAS_BASE,
    _WAAS_BASE + "&role_type=ml",
]


def build_waas_listing_variants() -> list[str]:
    """Distinct listing URLs to merge when logged in (each may surface different jobs)."""
    variants: list[str] = list(DEFAULT_WAAS_LISTING_URLS)
    for role_type in ("fs", "be", "fe", "eng_mgmt", "ml"):
        variants.append(f"{_WAAS_BASE}&role_type={role_type}")
    for sort_by in ("newest", "salary"):
        variants.append(f"{_WAAS_BASE}&sortBy={sort_by}")
    for exp in (3, 6, 11):
        variants.append(f"{_WAAS_BASE}&minExperience={exp}")
    variants.append(_WAAS_BASE.replace("remote=yes&", ""))
    return list(dict.fromkeys(variants))


def _open_listing_page(p, *, headless: bool, use_chrome_session: bool, storage_state: Path | None):
    """Return (handle_to_close, page). handle is Browser or BrowserContext."""
    if use_chrome_session:
        profile = config.CHROME_WORKER_DIR / "worker-0"
        if (profile / "Default").exists():
            ctx = p.chromium.launch_persistent_context(
                str(profile),
                headless=headless,
                channel="chrome",
                args=["--disable-blink-features=AutomationControlled"],
            )
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            return ctx, page
        log.warning("use_chrome_session set but worker-0 profile missing; using fresh browser")

    if storage_state and storage_state.exists():
        browser = p.chromium.launch(headless=headless)
        ctx = browser.new_context(storage_state=str(storage_state))
        page = ctx.new_page()
        return (ctx, browser), page

    browser = p.chromium.launch(headless=headless)
    return browser, browser.new_page()


def _close_listing_handle(handle) -> None:
    if isinstance(handle, tuple):
        ctx, browser = handle
        ctx.close()
        browser.close()
    else:
        handle.close()


_LOAD_MORE_SELECTORS = (
    'button:has-text("Load more")',
    'button:has-text("Show more")',
    'a:has-text("Load more")',
    '[data-testid="load-more"]',
)


def _job_id_from_url(url: str) -> str | None:
    m = re.search(r"/jobs/(\d+)", url)
    return m.group(1) if m else None


def _parse_header(body: str) -> tuple[str, str, str | None]:
    """Return title, company, salary line from job page text."""
    lines = [ln.strip() for ln in body.split("\n") if ln.strip()]
    header = ""
    for ln in lines:
        if " at " in ln and not ln.startswith("Work at"):
            header = ln
            break
    if not header:
        return "Unknown role", SITE_LABEL, None
    m = re.match(r"^(.+?)\s+at\s+(.+?)(?:\([A-Z]\d+\))?$", header)
    if not m:
        return header, SITE_LABEL, None
    title = m.group(1).strip()
    company = re.sub(r"\([A-Z]\d+\)$", "", m.group(2)).strip()
    salary = None
    for ln in lines[:40]:
        if ln.startswith("$") or "₹" in ln or re.search(r"\d+\s*(?:k|lpa|lakhs?)", ln, re.I):
            salary = ln
            break
    if not salary:
        for ln in lines:
            if re.search(r"\$\s*\d{2,3}(?:,\d{3})+|\d+\s*lpa|₹\s*\d", ln, re.I):
                salary = ln
                break
    return title, company, salary


def _extract_location(body: str) -> str:
    hints: list[str] = []
    for ln in body.split("\n"):
        ln = ln.strip()
        if not ln or len(ln) > 120:
            continue
        low = ln.lower()
        if any(
            k in low
            for k in (
                "remote",
                "bengaluru",
                "bangalore",
                "india",
                "karnataka",
                "san francisco",
                "new york",
                "london",
                "europe",
                "us citizen",
                "visa",
                "hybrid",
            )
        ):
            if ln not in hints:
                hints.append(ln)
    return " | ".join(hints[:6]) if hints else ""


def _scrape_job_detail(page, job_url: str) -> dict | None:
    page.goto(job_url, wait_until="networkidle", timeout=90000)
    page.wait_for_timeout(800)
    body = page.inner_text("body")
    job_id = _job_id_from_url(job_url)
    if not job_id:
        return None
    title, company, salary = _parse_header(body)
    location = _extract_location(body)
    about_idx = body.find("About the role")
    if about_idx < 0:
        about_idx = body.find("About ")
    description = body[about_idx : about_idx + 12000] if about_idx >= 0 else body[:8000]
    application_url = f"https://www.workatastartup.com/application?signup_job_id={job_id}"
    return {
        "url": job_url,
        "title": title,
        "salary": salary,
        "description": description[:2000],
        "location": location,
        "site": company or SITE_LABEL,
        "full_description": description,
        "application_url": application_url,
    }


def _gather_job_links(page) -> list[str]:
    return page.eval_on_selector_all(
        'a[href*="/jobs/"]',
        """els => {
          const out = [];
          const seen = new Set();
          const numeric = /\\/jobs\\/\\d+\\/?$/;
          for (const e of els) {
            const href = e.href.split('?')[0];
            if (!numeric.test(href) || seen.has(href)) continue;
            seen.add(href);
            out.push(href);
          }
          return out;
        }""",
    )


def _click_load_more(page) -> bool:
    for sel in _LOAD_MORE_SELECTORS:
        try:
            loc = page.locator(sel).first
            if loc.is_visible(timeout=500):
                loc.click(timeout=5000)
                page.wait_for_timeout(2500)
                return True
        except Exception:
            continue
    return False


def _collect_listing_urls(
    page,
    list_url: str,
    *,
    max_links: int = 500,
    max_scroll_rounds: int = 100,
    stable_rounds_to_stop: int = 5,
) -> list[str]:
    """Scroll / load-more until job link count stabilizes (handles 100+ jobs)."""
    page.goto(list_url, wait_until="domcontentloaded", timeout=120000)
    page.wait_for_timeout(2500)
    seen: set[str] = set()
    stable = 0

    for href in _gather_job_links(page):
        seen.add(href)

    for _ in range(max_scroll_rounds):
        if len(seen) >= max_links:
            break
        before = len(seen)
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(1400)
        _click_load_more(page)
        for href in _gather_job_links(page):
            seen.add(href)
        if len(seen) == before:
            stable += 1
            if stable >= stable_rounds_to_stop:
                break
        else:
            stable = 0

    return sorted(seen)


def _merge_listing_job_urls(page, list_urls: list[str], *, max_links: int = 500) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for list_url in list_urls:
        for href in _collect_listing_urls(page, list_url, max_links=max_links):
            if href in seen:
                continue
            seen.add(href)
            merged.append(href)
            if len(merged) >= max_links:
                return merged
    return merged


def _store_job(conn: Connection, job: dict, now: str) -> str:
    try:
        conn.execute(
            """
            INSERT INTO jobs (
                url, title, salary, description, location, site, strategy,
                discovered_at, full_description, application_url, detail_scraped_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job["url"],
                job["title"],
                job.get("salary"),
                job.get("description"),
                job.get("location"),
                job.get("site"),
                STRATEGY,
                now,
                job.get("full_description"),
                job.get("application_url"),
                now,
            ),
        )
        conn.commit()
        return "new"
    except Exception as exc:
        if not is_unique_violation(exc):
            raise
        conn.execute(
            """
            UPDATE jobs SET
                title = ?, salary = ?, description = ?, location = ?, site = ?,
                full_description = ?, application_url = ?, detail_scraped_at = ?
            WHERE url = ?
            """,
            (
                job["title"],
                job.get("salary"),
                job.get("description"),
                job.get("location"),
                job.get("site"),
                job.get("full_description"),
                job.get("application_url"),
                now,
                job["url"],
            ),
        )
        conn.commit()
        return "updated"


def _listing_prefilters_salary(list_url: str) -> bool:
    """True when the listing URL already requires disclosed salary on the site."""
    return "hassalary=true" in list_url.lower().replace("_", "")


def run_workatastartup_discovery(
    list_url: str | list[str],
    *,
    headless: bool = True,
    max_jobs: int | None = None,
    filter_salary: bool | None = None,
    max_listing_links: int = 500,
    use_chrome_session: bool = False,
    storage_state_path: Path | str | None = None,
) -> dict:
    """Scrape a Work at a Startup filtered listing and import eligible jobs.

    When filter_salary is False (default for URLs with hasSalary=true), every job
    on the listing is stored; salary gates run at apply time only.
    """
    init_db()
    conn = get_connection()
    now = datetime.now(timezone.utc).isoformat()

    list_urls = [list_url] if isinstance(list_url, str) else list(list_url)
    if filter_salary is None:
        filter_salary = not any(_listing_prefilters_salary(u) for u in list_urls)

    stats = {
        "listed": 0,
        "new": 0,
        "updated": 0,
        "skipped_salary": 0,
        "errors": 0,
        "listing_pages": len(list_urls),
    }

    storage_state: Path | None = None
    if storage_state_path:
        candidate = Path(storage_state_path)
        storage_state = candidate if candidate.exists() else None
    elif WAAS_STORAGE_STATE.exists():
        storage_state = WAAS_STORAGE_STATE

    with sync_playwright() as p:
        handle, page = _open_listing_page(
            p,
            headless=headless,
            use_chrome_session=use_chrome_session,
            storage_state=storage_state,
        )
        urls = (
            _merge_listing_job_urls(page, list_urls, max_links=max_listing_links)
            if len(list_urls) > 1
            else _collect_listing_urls(page, list_urls[0], max_links=max_listing_links)
        )
        stats["listed"] = len(urls)
        if stats["listed"] <= 35 and not use_chrome_session and not (
            storage_state and storage_state.exists()
        ):
            log.warning(
                "Only %s jobs found without a YC login session. "
                "Log in once via `applypilot apply --watch` on a WaaS job, then re-run "
                "discovery with --use-chrome-session for 100+ listings.",
                stats["listed"],
            )
        if max_jobs:
            urls = urls[:max_jobs]

        for job_url in urls:
            try:
                job = _scrape_job_detail(page, job_url)
                if not job:
                    stats["errors"] += 1
                    continue
                from applypilot.discovery._filters import discover_job_passes

                if not discover_job_passes(job):
                    stats["skipped_filter"] = stats.get("skipped_filter", 0) + 1
                    continue
                if filter_salary and not salary_meets_regional_minimum(
                    job.get("salary"),
                    job.get("full_description") or job.get("description"),
                    job.get("location"),
                ):
                    stats["skipped_salary"] += 1
                    log.info(
                        "Skip salary: %s — %s | %s",
                        job["title"],
                        job.get("salary"),
                        job.get("location"),
                    )
                    continue
                result = _store_job(conn, job, now)
                if result == "new":
                    stats["new"] += 1
                else:
                    stats["updated"] += 1
            except Exception as e:
                log.warning("WaaS scrape failed %s: %s", job_url, e)
                stats["errors"] += 1

        _close_listing_handle(handle)

    log.info("Work at a Startup discovery: %s", stats)
    return stats
