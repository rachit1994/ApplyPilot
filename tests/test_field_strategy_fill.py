"""Tests for field_strategy_fill integration wrapper (mocked, no browser)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from applypilot.apply.direct import field_strategy_fill
from applypilot.apply.direct.profile_binding import Field


@pytest.fixture
def mock_playbook(monkeypatch):
    store: dict[tuple[str, str], str] = {}

    pb = MagicMock()

    def lookup(field_sig: str, family: str) -> str | None:
        return store.get((field_sig, family))

    def record(field_sig: str, family: str, method: str, **_kwargs) -> None:
        store[(field_sig, family)] = method

    pb.lookup_field_strategy.side_effect = lookup
    pb.record_field_strategy.side_effect = record
    monkeypatch.setattr(field_strategy_fill, "_playbook", pb)
    return pb, store


def _checkbox_field() -> Field:
    return Field(
        label="I acknowledge",
        type="checkbox",
        tag="input",
        name_attr="ack",
        section_header="Legal",
        key="chk-key",
        ap_id=1,
    )


def test_record_click_label_then_lookup_returns_it(mock_playbook):
    pb, store = mock_playbook
    field = _checkbox_field()
    sig = field_strategy_fill.field_sig(field)

    field_strategy_fill.record_fill_outcome(field, "greenhouse", "click_label", True)

    assert pb.record_field_strategy.called
    assert store[(sig, "greenhouse")] == "click_label"
    assert pb.lookup_field_strategy(sig, "greenhouse") == "click_label"


def test_infer_fill_method_checkbox_click_label():
    field = _checkbox_field()
    method = field_strategy_fill.infer_fill_method(
        field,
        "greenhouse",
        succeeded=True,
        used_click_label=True,
    )
    assert method == "click_label"


def test_infer_fill_method_tel_press_sequentially():
    field = Field(label="Phone", type="tel", tag="input", name_attr="phone")
    method = field_strategy_fill.infer_fill_method(
        field,
        "greenhouse",
        succeeded=True,
        used_click_label=False,
    )
    assert method == "press_sequentially"


def test_fill_field_with_strategy_uses_cached_method(mock_playbook, monkeypatch):
    pb, _store = mock_playbook
    field = _checkbox_field()
    field_strategy_fill.record_fill_outcome(field, "greenhouse", "click_label", True)

    page = MagicMock()
    called = {"click_label": False}

    def fake_click_label(page, fld, answer, *, family):
        called["click_label"] = True
        return True

    monkeypatch.setattr(
        field_strategy_fill,
        "_fill_click_label",
        fake_click_label,
    )

    ok = field_strategy_fill.fill_field_with_strategy(
        page,
        field,
        "yes",
        family="greenhouse",
    )

    assert ok is True
    assert called["click_label"] is True
    pb.lookup_field_strategy.assert_called()
