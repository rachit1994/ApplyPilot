"""Referral outreach pipeline entrypoints."""

from __future__ import annotations

import logging
import time

from rich.console import Console

from applypilot.outreach.config import OutreachSettings, load_outreach_config, outreach_is_configured
from applypilot.outreach.openoutreach_client import check_openoutreach_health
from applypilot.outreach.orchestrator import run_referral_connect, run_referral_message
from applypilot.outreach.recruiter_scrape import run_recruiter_scrape
from applypilot.outreach.referral_draft import run_referral_draft

log = logging.getLogger(__name__)
console = Console()

REFERRAL_STAGES = ("scrape", "draft", "connect", "message")


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


def run_referral_pipeline(
    stages: list[str] | None = None,
    *,
    dry_run: bool = False,
    headless: bool = True,
    continuous: bool = False,
    poll_minutes: int | None = None,
) -> dict:
    """Run referral outreach stages (scrape, draft, connect, message)."""
    settings = load_outreach_config()
    if not settings.enabled:
        console.print("[yellow]Referral outreach disabled. Set enabled: true in ~/.applypilot/outreach.yaml[/yellow]")
        return {"skipped": "disabled"}

    if not dry_run and not outreach_is_configured(settings):
        console.print(
            "[red]OpenOutreach not configured.[/red] Set OPENOUTREACH_API_KEY and enable outreach in outreach.yaml"
        )
        return {"error": "openoutreach_not_configured"}

    stage_list = _resolve_stages(stages)
    poll = poll_minutes if poll_minutes is not None else settings.poll_connected_every_minutes
    summary: dict = {}

    def _run_once() -> dict:
        run_summary: dict = {}
        oo_blocked: str | None = None
        if not dry_run and _needs_openoutreach(stage_list):
            oo_blocked = _openoutreach_unreachable_detail(settings)
            if oo_blocked:
                console.print(
                    "[yellow]OpenOutreach is not reachable — skipping connect/message stages.[/yellow]"
                )
                console.print(f"[dim]{oo_blocked}[/dim]")
                console.print(
                    "[dim]Fix: applypilot openoutreach start  (or start OpenOutreach manually: "
                    "cd OpenOutreach && .venv/bin/python manage.py runapi --no-daemon)[/dim]"
                )

        if "scrape" in stage_list:
            console.print("[cyan]Referral: scraping LinkedIn job posters...[/cyan]")
            run_summary["scrape"] = run_recruiter_scrape(
                settings=settings, dry_run=dry_run, headless=headless
            )
        if "draft" in stage_list:
            console.print("[cyan]Referral: drafting messages...[/cyan]")
            run_summary["draft"] = run_referral_draft(settings=settings, dry_run=dry_run)
        if "connect" in stage_list:
            if oo_blocked:
                run_summary["connect"] = {
                    **_skipped_openoutreach(oo_blocked),
                    "connect_sent": 0,
                }
            else:
                console.print("[cyan]Referral: sending connection requests via OpenOutreach...[/cyan]")
                run_summary["connect"] = run_referral_connect(settings=settings, dry_run=dry_run)
        if "message" in stage_list:
            if oo_blocked:
                run_summary["message"] = {
                    **_skipped_openoutreach(oo_blocked),
                    "messages_sent": 0,
                }
            else:
                console.print("[cyan]Referral: messaging connected recruiters...[/cyan]")
                run_summary["message"] = run_referral_message(settings=settings, dry_run=dry_run)
        return run_summary

    if not continuous:
        summary = _run_once()
        console.print(f"[green]Referral pipeline complete.[/green] {summary}")
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
