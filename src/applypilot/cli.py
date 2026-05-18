"""ApplyPilot CLI — the main entry point."""

from __future__ import annotations

import logging
import subprocess
import sys
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from applypilot import __version__
from applypilot.llm import DEFAULT_GEMINI_MODEL

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%H:%M:%S",
)

app = typer.Typer(
    name="applypilot",
    help="AI-powered end-to-end job application pipeline.",
    no_args_is_help=True,
)
console = Console()
log = logging.getLogger(__name__)

# Valid pipeline stages (in execution order)
VALID_STAGES = ("discover", "enrich", "score", "tailor", "pdf", "refer", "cover")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _bootstrap() -> None:
    """Common setup: load env, create dirs, init DB."""
    from applypilot.config import load_env, ensure_dirs
    from applypilot.database import init_db

    load_env()
    ensure_dirs()
    init_db()


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"[bold]applypilot[/bold] {__version__}")
        raise typer.Exit()


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

@app.callback()
def main(
    version: bool = typer.Option(
        False, "--version", "-V",
        help="Show version and exit.",
        callback=_version_callback,
        is_eager=True,
    ),
) -> None:
    """ApplyPilot — AI-powered end-to-end job application pipeline."""


@app.command()
def init() -> None:
    """Run the first-time setup wizard (profile, resume, search config)."""
    from applypilot.wizard.init import run_wizard

    run_wizard()


@app.command("install-discovery")
def install_discovery() -> None:
    """Install python-jobspy for the discover stage (separate from main deps)."""
    from applypilot.discovery.jobspy_install import install_jobspy, jobspy_importable

    if jobspy_importable():
        console.print("[green]python-jobspy is already installed.[/green]")
        return

    console.print("Installing python-jobspy (no-deps) and runtime packages…")
    try:
        install_jobspy()
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Install failed (exit {e.returncode}).[/red]")
        raise typer.Exit(1) from e

    if jobspy_importable():
        console.print("[green]Done.[/green] Re-run discover: applypilot run discover")
    else:
        console.print("[red]Install finished but jobspy still cannot be imported.[/red]")
        raise typer.Exit(1)


@app.command()
def run(
    stages: Optional[list[str]] = typer.Argument(
        None,
        help=(
            "Pipeline stages to run. "
            f"Valid: {', '.join(VALID_STAGES)}, all. "
            "Defaults to 'all' if omitted."
        ),
    ),
    min_score: int = typer.Option(7, "--min-score", help="Minimum fit score for tailor/cover stages."),
    workers: int = typer.Option(1, "--workers", "-w", help="Parallel threads for discovery/enrichment stages."),
    stream: bool = typer.Option(False, "--stream", help="Run stages concurrently (streaming mode)."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview stages without executing."),
    validation: str = typer.Option(
        "normal",
        "--validation",
        help=(
            "Validation strictness for tailor/cover stages. "
            "strict: banned words = errors, judge must pass. "
            "normal: banned words = warnings only (default, recommended for Gemini free tier). "
            "lenient: banned words ignored, LLM judge skipped (fastest, fewest API calls)."
        ),
    ),
) -> None:
    """Run pipeline stages: discover, enrich, score, tailor, cover, pdf."""
    _bootstrap()

    from applypilot.pipeline import run_pipeline

    stage_list = stages if stages else ["all"]

    # Validate stage names
    for s in stage_list:
        if s != "all" and s not in VALID_STAGES:
            console.print(
                f"[red]Unknown stage:[/red] '{s}'. "
                f"Valid stages: {', '.join(VALID_STAGES)}, all"
            )
            raise typer.Exit(code=1)

    # Gate AI stages behind Tier 2
    llm_stages = {"score", "tailor", "cover"}
    if any(s in stage_list for s in llm_stages) or "all" in stage_list:
        from applypilot.config import check_tier
        check_tier(2, "AI scoring/tailoring")

    # Validate the --validation flag value
    valid_modes = ("strict", "normal", "lenient")
    if validation not in valid_modes:
        console.print(
            f"[red]Invalid --validation value:[/red] '{validation}'. "
            f"Choose from: {', '.join(valid_modes)}"
        )
        raise typer.Exit(code=1)

    result = run_pipeline(
        stages=stage_list,
        min_score=min_score,
        dry_run=dry_run,
        stream=stream,
        workers=workers,
        validation_mode=validation,
    )

    if result.get("errors"):
        raise typer.Exit(code=1)


@app.command()
def apply(
    limit: Optional[int] = typer.Option(None, "--limit", "-l", help="Max applications to submit."),
    workers: int = typer.Option(1, "--workers", "-w", help="Number of parallel browser workers."),
    min_score: int = typer.Option(7, "--min-score", help="Minimum fit score for job selection."),
    model: str = typer.Option("sonnet", "--model", "-m", help="Claude model name."),
    continuous: bool = typer.Option(False, "--continuous", "-c", help="Run forever, polling for new jobs."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview actions without submitting."),
    headless: bool = typer.Option(False, "--headless", help="Run browsers in headless mode."),
    pace: float = typer.Option(
        0.0, "--pace",
        help="Seconds to wait between browser actions (e.g. 2). Use with visible Chrome.",
    ),
    keep_open: float = typer.Option(
        0.0, "--keep-open",
        help="Seconds to leave Chrome open after each job so you can review (e.g. 60).",
    ),
    confirm_submit: bool = typer.Option(
        False, "--confirm-submit",
        help="Pause ~45s+ before Submit with snapshot so you can review the form.",
    ),
    watch: bool = typer.Option(
        False, "--watch",
        help="Human-friendly mode: --pace 2 --keep-open 45 --confirm-submit --workers 1.",
    ),
    url: Optional[str] = typer.Option(None, "--url", help="Apply to a specific job URL."),
    gen: bool = typer.Option(False, "--gen", help="Generate prompt file for manual debugging instead of running."),
    mark_applied: Optional[str] = typer.Option(None, "--mark-applied", help="Manually mark a job URL as applied."),
    mark_failed: Optional[str] = typer.Option(None, "--mark-failed", help="Manually mark a job URL as failed (provide URL)."),
    fail_reason: Optional[str] = typer.Option(None, "--fail-reason", help="Reason for --mark-failed."),
    reset_failed: bool = typer.Option(False, "--reset-failed", help="Reset all failed jobs for retry."),
    plain: bool = typer.Option(
        False, "--plain",
        help="Plain logging (no live dashboard). Use for nohup/background runs.",
    ),
) -> None:
    """Launch auto-apply to submit job applications."""
    _bootstrap()

    from applypilot.config import check_tier, PROFILE_PATH as _profile_path
    from applypilot.database import get_connection

    # --- Utility modes (no Chrome/Claude needed) ---

    if mark_applied:
        from applypilot.apply.launcher import mark_job
        mark_job(mark_applied, "applied")
        console.print(f"[green]Marked as applied:[/green] {mark_applied}")
        return

    if mark_failed:
        from applypilot.apply.launcher import mark_job
        mark_job(mark_failed, "failed", reason=fail_reason)
        console.print(f"[yellow]Marked as failed:[/yellow] {mark_failed} ({fail_reason or 'manual'})")
        return

    if reset_failed:
        from applypilot.apply.launcher import reset_failed as do_reset
        count = do_reset()
        console.print(f"[green]Reset {count} failed job(s) for retry.[/green]")

    # --- Full apply mode ---

    # Check 1: Tier 3 required (Claude Code CLI + Chrome)
    check_tier(3, "auto-apply")

    # Check 2: Profile exists
    if not _profile_path.exists():
        console.print(
            "[red]Profile not found.[/red]\n"
            "Run [bold]applypilot init[/bold] to create your profile first."
        )
        raise typer.Exit(code=1)

    # Check 3: Tailored resumes exist (skip for --gen with --url, or --continuous which polls)
    if not (gen and url) and not continuous:
        conn = get_connection()
        ready = conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE tailored_resume_path IS NOT NULL AND applied_at IS NULL"
        ).fetchone()[0]
        if ready == 0:
            console.print(
                "[red]No tailored resumes ready.[/red]\n"
                "Run [bold]applypilot run score tailor[/bold] first to prepare applications."
            )
            raise typer.Exit(code=1)

    if gen:
        from applypilot.apply.launcher import gen_prompt, BASE_CDP_PORT
        target = url or ""
        if not target:
            console.print("[red]--gen requires --url to specify which job.[/red]")
            raise typer.Exit(code=1)
        prompt_file = gen_prompt(target, min_score=min_score, model=model)
        if not prompt_file:
            console.print("[red]No matching job found for that URL.[/red]")
            raise typer.Exit(code=1)
        mcp_path = _profile_path.parent / ".mcp-apply-0.json"
        console.print(f"[green]Wrote prompt to:[/green] {prompt_file}")
        console.print(f"\n[bold]Run manually:[/bold]")
        console.print(
            f"  claude --model {model} -p "
            f"--mcp-config {mcp_path} "
            f"--permission-mode bypassPermissions < {prompt_file}"
        )
        return

    from applypilot.apply.launcher import main as apply_main

    effective_limit = limit if limit is not None else (0 if continuous else 1)

    if watch:
        if pace <= 0:
            pace = 2.0
        if keep_open <= 0:
            keep_open = 45.0
        confirm_submit = True
        workers = 1

    effective_pace = pace
    effective_keep_open = keep_open
    effective_confirm = confirm_submit

    console.print("\n[bold blue]Launching Auto-Apply[/bold blue]")
    console.print(f"  Limit:    {'unlimited' if continuous else effective_limit}")
    console.print(f"  Workers:  {workers}")
    console.print(f"  Model:    {model}")
    console.print(f"  Headless: {headless}")
    console.print(f"  Dry run:  {dry_run}")
    if effective_pace > 0:
        console.print(f"  Pace:     {effective_pace}s between actions")
    if effective_keep_open > 0:
        console.print(f"  Keep open: {effective_keep_open:.0f}s after each job")
    if effective_confirm:
        console.print("  Confirm:  pause before Submit for review")
    if watch:
        console.print("  Watch:    on (slow + review-friendly)")
    if url:
        console.print(f"  Target:   {url}")
    console.print()

    apply_main(
        limit=effective_limit,
        target_url=url,
        min_score=min_score,
        headless=headless,
        model=model,
        dry_run=dry_run,
        continuous=continuous,
        workers=workers,
        pace_seconds=effective_pace,
        keep_open_seconds=effective_keep_open,
        confirm_submit=effective_confirm,
        plain=plain or not sys.stdout.isatty(),
    )


@app.command()
def status() -> None:
    """Show pipeline statistics from the database."""
    _bootstrap()

    from applypilot.database import get_stats

    stats = get_stats()

    console.print("\n[bold]ApplyPilot Pipeline Status[/bold]\n")

    # Summary table
    summary = Table(title="Pipeline Overview", show_header=True, header_style="bold cyan")
    summary.add_column("Metric", style="bold")
    summary.add_column("Count", justify="right")

    summary.add_row("Total jobs discovered", str(stats["total"]))
    summary.add_row("With full description", str(stats["with_description"]))
    summary.add_row("Pending enrichment", str(stats["pending_detail"]))
    summary.add_row("Enrichment errors", str(stats["detail_errors"]))
    summary.add_row("Scored by LLM", str(stats["scored"]))
    summary.add_row("Pending scoring", str(stats["unscored"]))
    summary.add_row("Tailored resumes", str(stats["tailored"]))
    summary.add_row("Pending tailoring (7+)", str(stats["untailored_eligible"]))
    summary.add_row("Cover letters", str(stats["with_cover_letter"]))
    summary.add_row("Ready to apply", str(stats["ready_to_apply"]))
    summary.add_row("Applied", str(stats["applied"]))
    summary.add_row("Apply errors", str(stats["apply_errors"]))

    console.print(summary)

    if stats.get("referral_recruiter_scraped") is not None:
        from applypilot.outreach.config import load_outreach_config

        outreach = load_outreach_config()
        weekly = stats.get("referral_connects_this_week", 0)
        target = outreach.weekly_connect_target if outreach.enabled else 12
        ref_table = Table(
            title="\nReferral Outreach (LinkedIn / OpenOutreach)",
            show_header=True,
            header_style="bold green",
        )
        ref_table.add_column("Metric")
        ref_table.add_column("Count", justify="right")
        ref_table.add_row("Recruiters identified", str(stats["referral_recruiter_scraped"]))
        ref_table.add_row("Pending connect", str(stats["referral_pending_connect"]))
        ref_table.add_row("Connect sent (awaiting accept)", str(stats["referral_connect_sent"]))
        ref_table.add_row("Referral message sent", str(stats["referral_message_sent"]))
        ref_table.add_row("Failed", str(stats["referral_failed"]))
        ref_table.add_row("Skipped (scrape)", str(stats["referral_skipped"]))
        ref_table.add_row(
            f"Connects this week (target {target})",
            str(weekly),
        )
        console.print(ref_table)

    # Score distribution
    if stats["score_distribution"]:
        dist_table = Table(title="\nScore Distribution", show_header=True, header_style="bold yellow")
        dist_table.add_column("Score", justify="center")
        dist_table.add_column("Count", justify="right")
        dist_table.add_column("Bar")

        max_count = max(count for _, count in stats["score_distribution"]) or 1
        for score, count in stats["score_distribution"]:
            bar_len = int(count / max_count * 30)
            if score >= 7:
                color = "green"
            elif score >= 5:
                color = "yellow"
            else:
                color = "red"
            bar = f"[{color}]{'=' * bar_len}[/{color}]"
            dist_table.add_row(str(score), str(count), bar)

        console.print(dist_table)

    # By site
    if stats["by_site"]:
        site_table = Table(title="\nJobs by Source", show_header=True, header_style="bold magenta")
        site_table.add_column("Site")
        site_table.add_column("Count", justify="right")

        for site, count in stats["by_site"]:
            site_table.add_row(site or "Unknown", str(count))

        console.print(site_table)

    console.print()


inbox_app = typer.Typer(help="LinkedIn Other-tab job-opportunity replies (independent lifecycle).")
app.add_typer(inbox_app, name="inbox")


@inbox_app.command("scan")
def inbox_scan(
    limit: int = typer.Option(50, "--limit", help="Max threads to sync from Other tab."),
    fresh: bool = typer.Option(
        False,
        "--fresh",
        help="Clear cached inbox DB before scan (use after fixing Other vs Focused).",
    ),
) -> None:
    """Fetch threads from LinkedIn Other tab via OpenOutreach."""
    _bootstrap()
    from applypilot.inbox.config import load_inbox_config
    from applypilot.inbox.scanner import scan_inbox
    from applypilot.inbox.store import clear_inbox_data

    cfg = load_inbox_config()
    if fresh:
        clear_inbox_data()
        console.print("[yellow]Cleared cached inbox threads.[/yellow]")
    console.print(
        "[dim]Syncing LinkedIn Other tab only (inboxType=SECONDARY)…[/dim]"
    )
    result = scan_inbox(settings=cfg, limit=limit)
    console.print(f"[green]Scan complete:[/green] {result}")


@inbox_app.command("classify")
def inbox_classify(
    limit: int = typer.Option(50, "--limit", help="Max threads to classify."),
) -> None:
    """LLM: job-related? extract role/company."""
    _bootstrap()
    from applypilot.inbox.classifier import classify_inbox
    from applypilot.inbox.config import load_inbox_config

    result = classify_inbox(settings=load_inbox_config(), limit=limit)
    console.print(f"[green]Classify complete:[/green] {result}")


@inbox_app.command("list")
def inbox_list(
    limit: int = typer.Option(50, "--limit", help="Max Other-tab threads to scan."),
    scan: bool = typer.Option(True, "--scan/--no-scan", help="Refresh from LinkedIn Other tab."),
    fresh: bool = typer.Option(
        False,
        "--fresh",
        help="Clear cached inbox DB before scan (recommended once after this fix).",
    ),
    classify: bool = typer.Option(True, "--classify/--no-classify", help="Re-run apply-request classifier."),
    include_replied: bool = typer.Option(
        False,
        "--include-replied",
        help="Mark threads eligible even when your message is last.",
    ),
) -> None:
    """Show ranked list of people who asked you to apply (Other tab only), before sending."""
    _bootstrap()
    from applypilot.inbox.config import load_inbox_config
    from applypilot.inbox.classifier import classify_inbox
    from applypilot.inbox.display import print_ranked_queue
    from applypilot.inbox.ranker import build_ranked_queue
    from applypilot.inbox.scanner import scan_inbox
    from applypilot.inbox.store import clear_inbox_data

    cfg = load_inbox_config()
    if fresh:
        clear_inbox_data()
        console.print("[yellow]Cleared cached inbox threads.[/yellow]")
    if scan:
        console.print("[dim]Scanning LinkedIn Other tab (inboxType=SECONDARY)…[/dim]")
        console.print(f"[green]Scan:[/green] {scan_inbox(settings=cfg, limit=limit)}")
    if classify:
        console.print("[dim]Classifying apply requests…[/dim]")
        console.print(f"[green]Classify:[/green] {classify_inbox(settings=cfg, limit=limit)}")

    rows = build_ranked_queue(
        settings=cfg,
        limit=limit,
        require_unanswered=not include_replied,
    )
    print_ranked_queue(rows, console=console, fixed_message=cfg.fixed_reply_message)
    eligible = sum(1 for row in rows if row.get("eligible_to_send"))
    console.print(
        f"[bold]Summary:[/bold] {len(rows)} qualified · {eligible} ready to send "
        f"(use [bold]applypilot inbox approve <id>[/bold] then [bold]inbox send --send[/bold])"
    )


@inbox_app.command("draft")
def inbox_draft(
    limit: int = typer.Option(50, "--limit", help="Max threads to stage fixed reply on."),
) -> None:
    """Stage fixed reply on Other-tab threads where they asked you to apply."""
    _bootstrap()
    from applypilot.inbox.config import load_inbox_config
    from applypilot.inbox.drafter import apply_fixed_replies

    result = apply_fixed_replies(settings=load_inbox_config(), limit=limit)
    console.print(f"[green]Prepare complete:[/green] {result}")


@inbox_app.command("approve")
def inbox_approve(
    ids: list[str] = typer.Argument(..., help="participant_public_id or conversation URN."),
    draft_on_approve: bool = typer.Option(
        False,
        "--draft-on-approve",
        help="Stage fixed reply before marking approved.",
    ),
) -> None:
    """Approve drafted threads for live send."""
    _bootstrap()
    from applypilot.inbox.config import load_inbox_config
    from applypilot.inbox.store import approve_threads

    cfg = load_inbox_config()
    result = approve_threads(ids, draft_on_approve=draft_on_approve, draft_message=cfg.fixed_reply_message)
    console.print(f"[green]Approved:[/green] {result}")


@inbox_app.command("unapprove")
def inbox_unapprove(
    ids: list[str] = typer.Argument(..., help="participant_public_id or conversation URN."),
) -> None:
    """Clear approval on threads."""
    _bootstrap()
    from applypilot.inbox.store import unapprove_threads

    result = unapprove_threads(ids)
    console.print(f"[green]Unapproved:[/green] {result}")


@inbox_app.command("audit")
def inbox_audit(
    limit: int = typer.Option(50, "--limit", help="Max audit events to show."),
    urn: str | None = typer.Option(None, "--urn", help="Filter by conversation URN."),
    public_id: str | None = typer.Option(None, "--public-id", help="Filter by participant public_id."),
) -> None:
    """Show recent inbox audit events."""
    _bootstrap()
    from applypilot.inbox.audit import list_audit_events
    from applypilot.inbox.display import print_audit_table

    events = list_audit_events(limit=limit, conversation_urn=urn, participant_public_id=public_id)
    print_audit_table(events, console=console)


@inbox_app.command("send")
def inbox_send(
    limit: int = typer.Option(10, "--limit", help="Max sends this run."),
    dry_run: bool = typer.Option(True, "--dry-run/--send", help="Preview only unless --send."),
    approved_only: bool = typer.Option(
        True,
        "--approved-only/--no-approved-only",
        help="Live send requires inbox approve (default on).",
    ),
) -> None:
    """Send eligible drafted replies."""
    _bootstrap()
    from applypilot.inbox.config import load_inbox_config
    from applypilot.inbox.sender import send_inbox

    cfg = load_inbox_config()
    require_approval = cfg.require_approval_for_send if approved_only else False
    result = send_inbox(
        settings=cfg,
        limit=limit,
        dry_run=dry_run,
        approved_only=require_approval and not dry_run,
    )
    console.print(f"[green]Send complete:[/green] {result}")


@inbox_app.command("run")
def inbox_run(
    limit: int = typer.Option(50, "--limit", help="Max threads per stage."),
    dry_run: bool = typer.Option(True, "--dry-run/--send", help="Default preview; use --send to post."),
    include_replied: bool = typer.Option(
        False,
        "--include-replied",
        help="Unsafe: also reply when your message is last. Default only replies when they asked to apply and their message is latest.",
    ),
    approved_only: bool = typer.Option(
        True,
        "--approved-only/--no-approved-only",
        help="Live send requires inbox approve (default on).",
    ),
    continuous: bool = typer.Option(False, "--continuous", help="Repeat pipeline (not implemented)."),
) -> None:
    """Other tab only: classify apply requests, send fixed reply when they asked you to apply."""
    _bootstrap()
    from applypilot.inbox.config import load_inbox_config
    from applypilot.inbox.runner import run_inbox_pipeline

    if continuous:
        console.print("[yellow]--continuous not implemented yet; running once.[/yellow]")
    from applypilot.inbox.display import print_ranked_queue

    cfg = load_inbox_config()
    result = run_inbox_pipeline(
        settings=cfg,
        limit=limit,
        dry_run=dry_run,
        require_unanswered=not include_replied,
        approved_only=approved_only,
    )
    queue = result.get("queue") or []
    console.print("\n[bold]Qualified contacts (ranked)[/bold]")
    print_ranked_queue(queue, console=console, fixed_message=cfg.fixed_reply_message)
    eligible = sum(1 for row in queue if row.get("eligible_to_send"))
    if not dry_run and eligible == 0 and queue:
        console.print("[yellow]No eligible sends — all qualified threads are gated (see Skip).[/yellow]")
    elif dry_run and eligible == 0 and queue:
        console.print("[yellow]Dry run: nobody eligible to send with current gates.[/yellow]")

    send = result.get("send") or {}
    for row in send.get("results") or []:
        console.print(
            f"  [{row.get('status')}] {row.get('public_id')}: "
            f"{(row.get('message') or '')[:60]}..."
        )
    console.print(f"[green]Inbox run complete:[/green] {result}")


@app.command()
def refer(
    stages: Optional[list[str]] = typer.Argument(
        None,
        help="Referral stages: scrape, draft, connect, message, all. Default: all.",
    ),
    continuous: bool = typer.Option(
        False,
        "--continuous",
        help="Loop connect + message passes on a schedule (see outreach.yaml).",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without API or scrape writes."),
    headless: bool = typer.Option(True, "--headless/--no-headless", help="Headless browser for scrape."),
    poll_minutes: Optional[int] = typer.Option(
        None,
        "--poll-minutes",
        help="Minutes between continuous cycles (default from outreach.yaml).",
    ),
) -> None:
    """Run LinkedIn recruiter referral outreach (scrape, draft, connect, message)."""
    _bootstrap()

    from applypilot.outreach.pipeline import run_referral_pipeline

    stage_list = stages if stages else ["all"]
    for s in stage_list:
        if s != "all" and s not in ("scrape", "draft", "connect", "message"):
            console.print(
                f"[red]Unknown referral stage:[/red] '{s}'. "
                "Valid: scrape, draft, connect, message, all"
            )
            raise typer.Exit(code=1)

    run_referral_pipeline(
        stage_list,
        dry_run=dry_run,
        headless=headless,
        continuous=continuous,
        poll_minutes=poll_minutes,
    )


@app.command()
def dashboard() -> None:
    """Generate and open the HTML dashboard in your browser."""
    _bootstrap()

    from applypilot.view import open_dashboard

    open_dashboard()


@app.command()
def doctor() -> None:
    """Check your setup and diagnose missing requirements."""
    import shutil
    from applypilot.config import (
        load_env, PROFILE_PATH, RESUME_PATH, RESUME_PDF_PATH,
        SEARCH_CONFIG_PATH, ENV_PATH, get_chrome_path,
    )

    load_env()

    ok_mark = "[green]OK[/green]"
    fail_mark = "[red]MISSING[/red]"
    warn_mark = "[yellow]WARN[/yellow]"

    results: list[tuple[str, str, str]] = []  # (check, status, note)

    # --- Tier 1 checks ---
    # Profile
    if PROFILE_PATH.exists():
        results.append(("profile.json", ok_mark, str(PROFILE_PATH)))
    else:
        results.append(("profile.json", fail_mark, "Run 'applypilot init' to create"))

    # Resume
    if RESUME_PATH.exists():
        results.append(("resume.txt", ok_mark, str(RESUME_PATH)))
    elif RESUME_PDF_PATH.exists():
        results.append(("resume.txt", warn_mark, "Only PDF found — plain-text needed for AI stages"))
    else:
        results.append(("resume.txt", fail_mark, "Run 'applypilot init' to add your resume"))

    # Search config
    if SEARCH_CONFIG_PATH.exists():
        results.append(("searches.yaml", ok_mark, str(SEARCH_CONFIG_PATH)))
    else:
        results.append(("searches.yaml", warn_mark, "Will use example config — run 'applypilot init'"))

    # jobspy (discovery dep installed separately)
    try:
        import jobspy  # noqa: F401
        results.append(("python-jobspy", ok_mark, "Job board scraping available"))
    except ImportError:
        results.append(("python-jobspy", warn_mark, "Run: applypilot install-discovery"))

    # --- Tier 2 checks ---
    import os
    has_gemini = bool(os.environ.get("GEMINI_API_KEY"))
    has_openai = bool(os.environ.get("OPENAI_API_KEY"))
    has_local = bool(os.environ.get("LLM_URL"))
    if has_gemini:
        model = os.environ.get("LLM_MODEL", DEFAULT_GEMINI_MODEL)
        results.append(("LLM API key", ok_mark, f"Gemini ({model})"))
    elif has_openai:
        model = os.environ.get("LLM_MODEL", "gpt-4o-mini")
        results.append(("LLM API key", ok_mark, f"OpenAI ({model})"))
    elif has_local:
        results.append(("LLM API key", ok_mark, f"Local: {os.environ.get('LLM_URL')}"))
    else:
        results.append(("LLM API key", fail_mark,
                        "Set GEMINI_API_KEY in ~/.applypilot/.env (run 'applypilot init')"))

    # --- Tier 3 checks ---
    # Claude Code CLI
    claude_bin = shutil.which("claude")
    if claude_bin:
        results.append(("Claude Code CLI", ok_mark, claude_bin))
    else:
        results.append(("Claude Code CLI", fail_mark,
                        "Install from https://claude.ai/code (needed for auto-apply)"))

    # Chrome
    try:
        chrome_path = get_chrome_path()
        results.append(("Chrome/Chromium", ok_mark, chrome_path))
    except FileNotFoundError:
        results.append(("Chrome/Chromium", fail_mark,
                        "Install Chrome or set CHROME_PATH env var (needed for auto-apply)"))

    # Node.js / npx (for Playwright MCP)
    npx_bin = shutil.which("npx")
    if npx_bin:
        results.append(("Node.js (npx)", ok_mark, npx_bin))
    else:
        results.append(("Node.js (npx)", fail_mark,
                        "Install Node.js 18+ from nodejs.org (needed for auto-apply)"))

    # CapSolver (optional)
    capsolver = os.environ.get("CAPSOLVER_API_KEY")
    if capsolver:
        results.append(("CapSolver API key", ok_mark, "CAPTCHA solving enabled"))
    else:
        results.append(("CapSolver API key", "[dim]optional[/dim]",
                        "Set CAPSOLVER_API_KEY in .env for CAPTCHA solving"))

    # OpenOutreach (referral automation)
    from applypilot.outreach.config import load_outreach_config, outreach_is_configured
    from applypilot.outreach.openoutreach_client import check_openoutreach_health

    outreach_cfg = load_outreach_config()
    if outreach_cfg.enabled:
        if outreach_is_configured(outreach_cfg):
            oo_ok, oo_note = check_openoutreach_health(
                outreach_cfg.openoutreach_base_url,
                outreach_cfg.openoutreach_api_key,
            )
            results.append((
                "OpenOutreach API",
                ok_mark if oo_ok else fail_mark,
                oo_note,
            ))
        else:
            results.append((
                "OpenOutreach API",
                fail_mark,
                "Set OPENOUTREACH_API_KEY in ~/.applypilot/.env",
            ))
    else:
        results.append((
            "OpenOutreach API",
            "[dim]optional[/dim]",
            "Enable in ~/.applypilot/outreach.yaml for referral automation",
        ))

    # --- Render results ---
    console.print()
    console.print("[bold]ApplyPilot Doctor[/bold]\n")

    col_w = max(len(r[0]) for r in results) + 2
    for check, status, note in results:
        pad = " " * (col_w - len(check))
        console.print(f"  {check}{pad}{status}  [dim]{note}[/dim]")

    console.print()

    # Tier summary
    from applypilot.config import get_tier, TIER_LABELS
    tier = get_tier()
    console.print(f"[bold]Current tier: Tier {tier} — {TIER_LABELS[tier]}[/bold]")

    if tier == 1:
        console.print("[dim]  → Tier 2 unlocks: scoring, tailoring, cover letters (needs LLM API key)[/dim]")
        console.print("[dim]  → Tier 3 unlocks: auto-apply (needs Claude Code CLI + Chrome + Node.js)[/dim]")
    elif tier == 2:
        console.print("[dim]  → Tier 3 unlocks: auto-apply (needs Claude Code CLI + Chrome + Node.js)[/dim]")

    console.print()


@app.command("serve")
def serve(
    host: str = typer.Option("127.0.0.1", help="Bind address (local only)."),
    port: int = typer.Option(9477, help="HTTP port for dashboard API and UI."),
    open_browser: bool = typer.Option(True, "--open/--no-open", help="Open dashboard in browser."),
    reload: bool = typer.Option(False, help="Reload API on code changes (dev)."),
) -> None:
    """Start the local dashboard API (and built React UI if present)."""
    import webbrowser

    import uvicorn

    _bootstrap()
    from applypilot.server.app import create_app

    url = f"http://{host}:{port}/"
    console.print(f"[bold]ApplyPilot dashboard[/bold] at [link={url}]{url}[/link]")
    console.print("[dim]Dev UI: cd dashboard/web && npm run dev (proxies /api)[/dim]")
    if open_browser:
        webbrowser.open(url)
    uvicorn.run(
        create_app(),
        host=host,
        port=port,
        reload=reload,
        log_level="info",
    )


if __name__ == "__main__":
    app()
