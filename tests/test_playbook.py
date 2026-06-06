"""Unit tests for self-learning nav_playbook + field_strategy cache."""

from __future__ import annotations

from hashlib import sha1

import pytest

from applypilot.apply.direct import playbook
from applypilot.database import get_connection


@pytest.fixture
def conn():
    connection = get_connection()
    playbook.ensure_playbook_tables(connection)
    return connection


def _snapshot(*, clickables: list[str], has_form: bool = False) -> dict:
    return {
        "clickables": clickables,
        "has_application_form": has_form,
        "has_password_field": False,
        "has_cookie_banner": False,
    }


def test_state_signature_stable_and_distinct(conn):
    snap_a = _snapshot(clickables=["Apply Now", "Sign In"])
    snap_b = _snapshot(clickables=["Continue", "Sign In"])
    sig_a1 = playbook.state_signature(
        snap_a, ats_family="workday", apex_host="acme.wd5.myworkdayjobs.com"
    )
    sig_a2 = playbook.state_signature(
        snap_a, ats_family="workday", apex_host="acme.wd5.myworkdayjobs.com"
    )
    sig_b = playbook.state_signature(
        snap_b, ats_family="workday", apex_host="acme.wd5.myworkdayjobs.com"
    )
    assert sig_a1 == sig_a2
    assert sig_a1 != sig_b


def test_salient_clickables_canonicalizes_and_filters():
    assert playbook._salient_clickables(
        ["Apply for this job", "Refer and Earn", "Acme Corp"]
    ) == ["apply"]
    assert playbook._salient_clickables(["Apply now", "Sign in with Google"]) == [
        "apply",
        "sign in",
    ]


def test_state_signature_ignores_noise_clickables(conn):
    base = _snapshot(clickables=["Apply now", "Refer and Earn"])
    noisy = _snapshot(clickables=["Apply now", "Share on LinkedIn", "Job details"])
    kwargs = {
        "ats_family": "workday",
        "apex_host": "acme.wd5.myworkdayjobs.com",
        "step_name": "apply_reveal",
    }
    assert playbook.state_signature(base, **kwargs) == playbook.state_signature(
        noisy, **kwargs
    )


def test_state_signature_differs_when_salient_clickables_differ(conn):
    apply_snap = _snapshot(clickables=["Apply now"])
    next_snap = _snapshot(clickables=["Next"])
    kwargs = {
        "ats_family": "workday",
        "apex_host": "acme.wd5.myworkdayjobs.com",
        "step_name": "apply_reveal",
    }
    assert playbook.state_signature(apply_snap, **kwargs) != playbook.state_signature(
        next_snap, **kwargs
    )


def test_state_signature_uses_sig_version_two(conn):
    snap = _snapshot(clickables=["Apply"])
    sig = playbook.state_signature(snap, ats_family="lever", apex_host="jobs.lever.co")
    parts_v1 = "|".join(("1", "lever", "jobs.lever.co", "", "apply", "0", "0", "0"))
    assert sig != sha1(parts_v1.encode("utf-8")).hexdigest()
    assert playbook.SIG_VERSION == 2


def test_submit_never_replayable(conn):
    assert playbook.is_replay_allowed("submit", "trusted") is False
    assert playbook.is_replay_allowed("submit", "trial") is False


def test_side_effecting_nav_only_replays_when_trusted(conn):
    # 'click' is side-effecting too (it targets Apply/Continue/off-page links),
    # so it must not replay at 'trial' — only once trusted.
    for action in ("next_page", "login_provider", "goto", "apply", "click"):
        assert playbook.is_replay_allowed(action, "trial") is False
        assert playbook.is_replay_allowed(action, "trusted") is True


def test_promote_after_k_weak_successes(conn):
    snap = _snapshot(clickables=["Next"])
    sig = playbook.state_signature(snap, ats_family="greenhouse", apex_host="boards.greenhouse.io")
    playbook.record_nav(
        sig,
        ats_family="greenhouse",
        apex_host="boards.greenhouse.io",
        action_type="click",
        action_args={"text": "Next"},
        conn=conn,
    )
    for _ in range(playbook.PROMOTE_K):
        playbook.bump_success(sig, weak=True, conn=conn)
    entry = playbook.lookup_nav(sig, conn=conn)
    assert entry is not None
    assert entry.status == "trusted"
    assert entry.success_weak == playbook.PROMOTE_K


def test_retire_after_fail_threshold(conn):
    snap = _snapshot(clickables=["Apply"])
    sig = playbook.state_signature(snap, ats_family="lever", apex_host="jobs.lever.co")
    playbook.record_nav(
        sig,
        ats_family="lever",
        apex_host="jobs.lever.co",
        action_type="click",
        action_args={"text": "Apply"},
        status="trusted",
        conn=conn,
    )
    playbook.bump_fail(sig, conn=conn)
    entry = playbook.lookup_nav(sig, conn=conn)
    assert entry is not None
    assert entry.status == "retired"
    assert entry.fail_count == 1


def test_field_strategy_record_and_lookup(conn):
    key = playbook.field_sig(
        "I acknowledge",
        section_header="Legal",
        name_attr="acknowledge",
        answer_type="bool",
    )
    assert key == playbook.question_key(
        "I acknowledge",
        section_header="Legal",
        name_attr="acknowledge",
        answer_type="bool",
    )
    playbook.record_field_strategy(
        key,
        "greenhouse",
        "click_label",
        match_rule={"label_contains": "acknowledge"},
        conn=conn,
    )
    method = playbook.lookup_field_strategy(key, "greenhouse", conn=conn)
    assert method == "click_label"
    entry = playbook.get_field_strategy(key, "greenhouse", conn=conn)
    assert entry is not None
    assert entry.success_count == 1
