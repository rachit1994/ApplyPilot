"""Per-run Claude apply budget and deterministic-only mode."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

from applypilot.apply import apply_settings


@dataclass
class ApplyRunBudgetSnapshot:
    deterministic_only: bool = False
    claude_attempts: int = 0
    claude_cost_usd: float = 0.0
    claude_max_attempts: int | None = None
    claude_max_cost_usd: float | None = None
    claude_capped: bool = False
    parked_needs_adapter: int = 0

    def claude_allowed(self) -> bool:
        if self.deterministic_only:
            return False
        if self.claude_capped:
            return False
        if self.claude_max_attempts is not None and self.claude_attempts >= self.claude_max_attempts:
            return False
        if (
            self.claude_max_cost_usd is not None
            and self.claude_cost_usd >= self.claude_max_cost_usd
        ):
            return False
        return True


class ApplyRunGovernor:
    """Thread-safe per-run Claude spend/attempt limits for apply workers."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._snapshot = ApplyRunBudgetSnapshot()

    def reset(self, *, deterministic_only: bool = False, profile: dict | None = None) -> ApplyRunBudgetSnapshot:
        max_attempts = apply_settings.apply_claude_max_per_run(profile)
        max_cost = apply_settings.apply_claude_max_cost_usd_per_run(profile)
        with self._lock:
            self._snapshot = ApplyRunBudgetSnapshot(
                deterministic_only=deterministic_only,
                claude_max_attempts=max_attempts,
                claude_max_cost_usd=max_cost,
            )
            return self._snapshot_copy()

    def snapshot(self) -> ApplyRunBudgetSnapshot:
        with self._lock:
            return self._snapshot_copy()

    def deterministic_only(self) -> bool:
        with self._lock:
            return self._snapshot.deterministic_only

    def claude_allowed(self) -> bool:
        with self._lock:
            return self._snapshot.claude_allowed()

    def record_claude_apply(self, cost_usd: float) -> ApplyRunBudgetSnapshot:
        with self._lock:
            self._snapshot.claude_attempts += 1
            self._snapshot.claude_cost_usd += max(0.0, float(cost_usd or 0.0))
            if not self._snapshot.claude_allowed():
                self._snapshot.claude_capped = True
            return self._snapshot_copy()

    def note_parked_needs_adapter(self) -> int:
        with self._lock:
            self._snapshot.parked_needs_adapter += 1
            return self._snapshot.parked_needs_adapter

    def _snapshot_copy(self) -> ApplyRunBudgetSnapshot:
        s = self._snapshot
        return ApplyRunBudgetSnapshot(
            deterministic_only=s.deterministic_only,
            claude_attempts=s.claude_attempts,
            claude_cost_usd=round(s.claude_cost_usd, 6),
            claude_max_attempts=s.claude_max_attempts,
            claude_max_cost_usd=s.claude_max_cost_usd,
            claude_capped=s.claude_capped,
            parked_needs_adapter=s.parked_needs_adapter,
        )


_GOVERNOR = ApplyRunGovernor()


def governor() -> ApplyRunGovernor:
    return _GOVERNOR
