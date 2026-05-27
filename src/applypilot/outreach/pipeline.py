"""Referral outreach pipeline entrypoints."""

from __future__ import annotations

import logging
import time

from rich.console import Console

from applypilot.database import get_connection
from applypilot.outreach.config import OutreachSettings, load_outreach_config, outreach_is_configured
from applypilot.outreach.openoutreach_client import check_openoutreach_health
from applypilot.outreach.orchestrator import (
    _eligible_connect_rows,
    _eligible_message_rows,
    run_referral_connect,
    run_referral_message,
)
from applypilot.outreach.recruiter_scrape import _eligible_scrape_rows, run_recruiter_scrape
from applypilot.outreach.referral_draft import _eligible_draft_rows, run_referral_draft

log = logging.getLogger(__name__)
console = Console()

REFERRAL_STAGES = ("scrape", "draft", "connect", "message")
PREPARE_STAGES = ("scrape", "draft")
SEND_STAGES = ("connect", "message")


def _resolve_stages(stage_names: list[str] | None) -> list[str]:
    if not stage_names or "all" in stage_names:
        return list(REFERRAL_STAGES)
    return [s for s in stage_names if s in REFERRAL_STAGES]


def _needs_openoutreach(stage_list: list[str]) -> bool:
    return "connect" in stage_list or "message" in stage_list


def _openoutreach_unreachable_detail(settings: OutreachSettings) -> str | None:
    """Return a user-facing reason when connect/message cannot run, else None."""
    ok, detail = check_openoutreach_health(
        settings.openoutreach_base_url,
        settings.openoutreach_api_key,
    )
    if ok:
        return None
    return detail


def _skipped_openoutreach(detail: str) -> dict:
    return {"skipped": "openoutreach_unreachable", "detail": detail}


def _referral_candidate_counts(settings: OutreachSettings) -> dict[str, int]:
    """How many jobs each referral sub-stage could act on (for quiet logging)."""
    conn = get_connection()
    return {
        "scrape": len(_eligible_scrape_rows(conn, settings)),
        "draft": len(_eligible_draft_rows(conn, settings)),
        "connect": len(_eligible_connect_rows(conn, settings)),
        "message": len(_eligible_message_rows(conn, settings)),
    }


def _run_stages(
    stage_list: list[str],
    *,
    settings: OutreachSettings,
    dry_run: bool,
    headless: bool,
    urls: list[str] | None = None,
) -> dict:
    run_summary: dict = {}
    oo_blocked: str | None = None
    counts = _referral_candidate_counts(settings)
    if not dry_run and _needs_openoutreach(stage_list):
        if not outreach_is_configured(settings):
            detail = "OpenOutreach not configured (set OPENOUTREACH_API_KEY and outreach.yaml)"
            console.print(f"[yellow]{detail}[/yellow]")
            oo_blocked = detail
        else:
            oo_blocked = _openoutreach_unreachable_detail(settings)
            if oo_blocked:
                console.print(
                    "[yellow]OpenOutreach is not reachable — skipping connect/message stages.[/yellow]"
                )
                console.print(f"[dim]{oo_blocked}[/dim]")
                console.print(
                    "[dim]Fix: applypilot openoutreach start  (or start OpenOutreach manually)[/dim]"
                )

    if "scrape" in stage_list:
        if dry_run or counts["scrape"] > 0:
            console.print("[cyan]Referral: scraping LinkedIn job posters...[/cyan]")
        run_summary["scrape"] = run_recruiter_scrape(
            settings=settings, dry_run=dry_run, headless=headless, urls=urls
        )
    if "draft" in stage_list:
        if dry_run or counts["draft"] > 0:
            console.print("[cyan]Referral: filling referral message templates...[/cyan]")
        run_summary["draft"] = run_referral_draft(
            settings=settings, dry_run=dry_run, urls=urls
        )
    if "connect" in stage_list:
        if oo_blocked:
            run_summary["connect"] = {
                **_skipped_openoutreach(oo_blocked),
                "connect_sent": 0,
            }
        else:
            if dry_run or counts["connect"] > 0:
                console.print(
                    "[cyan]Referral: sending connection requests via OpenOutreach...[/cyan]"
                )
            run_summary["connect"] = run_referral_connect(
                settings=settings, dry_run=dry_run, urls=urls
            )
    if "message" in stage_list:
        if oo_blocked:
            run_summary["message"] = {
                **_skipped_openoutreach(oo_blocked),
                "messages_sent": 0,
            }
        else:
            if dry_run or counts["message"] > 0:
                console.print("[cyan]Referral: messaging connected recruiters...[/cyan]")
            run_summary["message"] = run_referral_message(
                settings=settings, dry_run=dry_run, urls=urls
            )
            msg = run_summary["message"]
            waiting = int(msg.get("candidates") or 0) - int(msg.get("messages_sent") or 0)
            if waiting > 0 and not msg.get("messages_sent"):
                console.print(
                    f"[dim]Referral: {waiting} connect(s) sent — waiting for LinkedIn accept "
                    f"before message (use Referrals tab or `applypilot refer message`).[/dim]"
                )
    return run_summary


def run_referral_prepare(
    *,
    dry_run: bool = False,
    headless: bool = True,
    urls: list[str] | None = None,
) -> dict:
    """Scrape recruiters and fill template messages (no OpenOutreach)."""
    settings = load_outreach_config()
    if not settings.enabled:
        console.print("[yellow]Referral outreach disabled. Set enabled: true in ~/.applypilot/outreach.yaml[/yellow]")
        return {"skipped": "disabled"}
    return _run_stages(
        list(PREPARE_STAGES),
        settings=settings,
        dry_run=dry_run,
        headless=headless,
        urls=urls,
    )


def run_referral_send(
    *,
    dry_run: bool = False,
    urls: list[str] | None = None,
) -> dict:
    """Connect and message via OpenOutreach (manual/dashboard/CLI only)."""
    settings = load_outreach_config()
    if not settings.enabled:
        return {"skipped": "disabled"}
    if not dry_run and not outreach_is_configured(settings):
        return {"error": "openoutreach_not_configured"}
    return _run_stages(
        list(SEND_STAGES),
        settings=settings,
        dry_run=dry_run,
        headless=True,
        urls=urls,
    )


def run_referral_pipeline(
    stages: list[str] | None = None,
    *,
    dry_run: bool = False,
    headless: bool = True,
    continuous: bool = False,
    poll_minutes: int | None = None,
    urls: list[str] | None = None,
) -> dict:
    """Run referral outreach stages (scrape, draft, connect, message)."""
    settings = load_outreach_config()
    if not settings.enabled:
        console.print("[yellow]Referral outreach disabled. Set enabled: true in ~/.applypilot/outreach.yaml[/yellow]")
        return {"skipped": "disabled"}

    stage_list = _resolve_stages(stages)
    poll = poll_minutes if poll_minutes is not None else settings.poll_connected_every_minutes

    def _run_once() -> dict:
        return _run_stages(
            stage_list,
            settings=settings,
            dry_run=dry_run,
            headless=headless,
            urls=urls,
        )

    if not continuous:
        summary = _run_once()
        if any(
            (summary.get(stage) or {}).get("scraped")
            or (summary.get(stage) or {}).get("drafted")
            or (summary.get(stage) or {}).get("queued")
            or (summary.get(stage) or {}).get("connect_sent")
            or (summary.get(stage) or {}).get("messages_sent")
            for stage in REFERRAL_STAGES
        ):
            console.print(f"[green]Referral pipeline complete.[/green] {summary}")
        else:
            console.print(f"[dim]Referral: nothing to do this pass.[/dim] {summary}")
        return summary

    console.print(f"[cyan]Referral continuous mode (poll every {poll} min). Ctrl+C to stop.[/cyan]")
    try:
        while True:
            summary = _run_once()
            console.print(f"[dim]Cycle done: {summary}[/dim]")
            time.sleep(poll * 60)
    except KeyboardInterrupt:
        console.print("\n[yellow]Referral continuous mode stopped.[/yellow]")
    return summary
