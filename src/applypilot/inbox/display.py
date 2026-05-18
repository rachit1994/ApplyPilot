"""Rich tables for ranked inbox queue (mirrors job fit_score listing)."""

from __future__ import annotations

from rich.console import Console
from rich.table import Table

from applypilot.inbox.config import DEFAULT_FIXED_REPLY


def render_ranked_queue_table(
    rows: list[dict],
    *,
    fixed_message: str = DEFAULT_FIXED_REPLY,
) -> Table:
    table = Table(
        title="LinkedIn Other (inboxType=SECONDARY) — ranked apply requests",
        show_header=True,
        header_style="bold cyan",
        expand=True,
    )
    table.add_column("#", style="dim", width=4, justify="right")
    table.add_column("Score", justify="right", width=6)
    table.add_column("Intent", width=12)
    table.add_column("Contact", min_width=16)
    table.add_column("Role / ATS", min_width=16)
    table.add_column("OK?", width=6)
    table.add_column("Approved", width=8)
    table.add_column("Why / skip", min_width=24)

    eligible = 0
    for row in rows:
        if row.get("eligible_to_send"):
            eligible += 1
        role_bits = []
        if row.get("extracted_title"):
            role_bits.append(str(row["extracted_title"]))
        if row.get("extracted_company"):
            role_bits.append(str(row["extracted_company"]))
        if row.get("ats_vendor"):
            role_bits.append(f"[{row['ats_vendor']}]")
        role_col = " · ".join(role_bits) if role_bits else "—"

        send_cell = "[green]yes[/green]" if row.get("eligible_to_send") else "[yellow]no[/yellow]"
        approved_cell = "[green]yes[/green]" if row.get("approved_at") else "—"
        why = row.get("reasoning") or ""
        if row.get("skip_reason"):
            why = f"{why} [dim](skip: {row['skip_reason']})[/dim]"
        breakdown = row.get("score_breakdown") or {}
        if breakdown:
            why = (
                f"{why} [dim](+{breakdown.get('confidence_pts', 0)} conf, "
                f"+{breakdown.get('ats_pts', 0)} ats)[/dim]"
            )

        table.add_row(
            str(row.get("rank", "")),
            str(row.get("fit_score", 0)),
            row.get("intent") or "—",
            row.get("participant_public_id") or "—",
            role_col,
            send_cell,
            approved_cell,
            why[:140] + ("…" if len(why) > 140 else ""),
        )

    table.caption = (
        f"{len(rows)} apply_request · {eligible} eligible · "
        f"approve IDs then: applypilot inbox send --send --approved-only"
    )
    return table


def print_ranked_queue(
    rows: list[dict],
    *,
    console: Console | None = None,
    fixed_message: str = DEFAULT_FIXED_REPLY,
) -> None:
    out = console or Console()
    if not rows:
        out.print(
            "[yellow]No qualified threads[/yellow] in the Other tab "
            "(no apply_request intents)."
        )
        return
    out.print(render_ranked_queue_table(rows, fixed_message=fixed_message))
    out.print()


def print_audit_table(events: list[dict], *, console: Console | None = None) -> None:
    out = console or Console()
    if not events:
        out.print("[yellow]No audit events.[/yellow]")
        return
    table = Table(title="Inbox audit log", show_header=True, header_style="bold")
    table.add_column("When", width=22)
    table.add_column("Type", width=14)
    table.add_column("Contact", width=18)
    table.add_column("Payload", min_width=30)
    for ev in events:
        payload = ev.get("payload") or {}
        summary = ", ".join(f"{k}={v}" for k, v in list(payload.items())[:4])
        table.add_row(
            (ev.get("created_at") or "")[:22],
            ev.get("event_type") or "",
            ev.get("participant_public_id") or "—",
            summary[:120],
        )
    out.print(table)
