"""Run orchestration for the dashboard: events, subprocess control."""

from applypilot.orchestration.events import emit_run_event, get_active_run_id

__all__ = ["emit_run_event", "get_active_run_id"]
