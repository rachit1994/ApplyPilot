"""Concurrent single-writer tests for apply/direct/review_log.py."""

from __future__ import annotations

import sqlite3
import threading

import pytest

from applypilot.apply.direct import review_log as rl


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:", check_same_thread=False)
    c.row_factory = sqlite3.Row
    rl.ensure_review_log_table(c)
    yield c
    rl.stop_writer()
    c.close()


def test_concurrent_writer_flushes_all_rows(conn):
    rl.start_writer(conn)

    errors: list[BaseException] = []

    def worker(tier: str) -> None:
        try:
            for i in range(100):
                rl.log_event(
                    conn,
                    state_sig=f"sig-{tier}-{i}",
                    tier=tier,
                    action_type="click",
                    outcome="advanced",
                )
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [
        threading.Thread(target=worker, args=(f"t{idx}",))
        for idx in range(3)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors

    rl.flush()
    rows = rl.list_recent(conn, limit=500)
    assert len(rows) == 300
