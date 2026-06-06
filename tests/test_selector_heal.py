"""Unit tests for structural selector self-healing (mocked page, no browser)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from applypilot.apply.direct import field_strategy_fill, selector_heal
from applypilot.apply.direct.profile_binding import Field
from applypilot.apply.direct.selector_heal import heal_locator, xpath_literal


def _miss_locator() -> MagicMock:
    loc = MagicMock()
    loc.count.return_value = 0
    return loc


def _hit_locator() -> MagicMock:
    loc = MagicMock()
    loc.count.return_value = 1
    return loc


class TestXpathLiteral:
    def test_simple_single_quotes(self):
        assert xpath_literal("Apply") == "'Apply'"

    def test_embedded_single_quote_uses_concat(self):
        assert "concat(" in xpath_literal("it's \"fine\"")


class TestHealLocator:
    def test_css_exact_match(self):
        page = MagicMock()
        hit = _hit_locator()
        page.locator.return_value.first = hit

        loc = heal_locator(page, {"css": "#submit-btn"})

        assert loc is hit
        page.locator.assert_called_with("#submit-btn")

    def test_text_falls_back_to_role_name_when_get_by_text_misses(self):
        page = MagicMock()
        miss = _miss_locator()
        hit = _hit_locator()

        def get_by_role(role, name="", exact=False):
            chain = MagicMock()
            chain.first = hit if role == "button" and name == "Apply Now" else miss
            return chain

        page.get_by_role.side_effect = get_by_role
        page.get_by_text.return_value.first = miss
        page.locator.return_value.last = miss

        loc = heal_locator(page, {"text": "Apply Now"})

        assert loc is hit

    def test_role_and_name_explicit(self):
        page = MagicMock()
        hit = _hit_locator()
        page.get_by_role.return_value.first = hit

        loc = heal_locator(page, {"role": "textbox", "name": "Email"})

        assert loc is hit
        page.get_by_role.assert_called_with("textbox", name="Email", exact=False)

    def test_xpath_normalize_space_last_resort_for_text(self):
        page = MagicMock()
        miss = _miss_locator()
        hit = _hit_locator()

        page.get_by_role.return_value.first = miss
        page.get_by_text.return_value.first = miss
        page.locator.return_value.last = hit

        loc = heal_locator(page, {"text": "Continue"})

        assert loc is hit
        xpath_arg = page.locator.call_args[0][0]
        assert "normalize-space(.)" in xpath_arg
        assert "'Continue'" in xpath_arg

    def test_nearby_label_for_form_field(self):
        page = MagicMock()
        miss = _miss_locator()
        hit = _hit_locator()

        page.get_by_role.return_value.first = miss
        page.get_by_text.return_value.first = miss
        page.get_by_label.return_value.first = hit

        loc = heal_locator(
            page,
            {"label": "Work Email", "name_attr": "email", "tag": "input", "type": "email"},
        )

        assert loc is hit
        page.get_by_label.assert_called_with("Work Email", exact=False)

    def test_name_attr_css_when_label_misses(self):
        page = MagicMock()
        miss = _miss_locator()
        hit = _hit_locator()

        page.get_by_label.return_value.first = miss

        def locator(sel):
            chain = MagicMock()
            chain.first = hit if sel == 'input[name="phone"]' else miss
            return chain

        page.locator.side_effect = locator

        loc = heal_locator(
            page,
            {"label": "", "name_attr": "phone", "tag": "input", "type": "tel"},
        )

        assert loc is hit

    def test_returns_none_when_all_strategies_miss(self):
        page = MagicMock()
        miss = _miss_locator()
        page.get_by_role.return_value.first = miss
        page.get_by_text.return_value.first = miss
        page.locator.return_value.last = miss
        page.get_by_label.return_value.first = miss

        assert heal_locator(page, {"text": "Missing"}) is None


class TestFieldStrategyFillLocatorHeal:
    def test_locator_uses_heal_when_ap_markers_miss(self, monkeypatch):
        page = MagicMock()
        miss = _miss_locator()
        hit = _hit_locator()

        page.locator.return_value.first = miss

        def fake_heal(_page, descriptor):
            assert descriptor["label"] == "Phone"
            assert descriptor["name_attr"] == "phone"
            return hit

        monkeypatch.setattr(
            "applypilot.apply.direct.selector_heal.heal_locator",
            fake_heal,
        )
        monkeypatch.setattr(field_strategy_fill.extractor, "restamp", lambda *_: None)

        field = Field(label="Phone", type="tel", tag="input", name_attr="phone", ap_id=9)
        loc = field_strategy_fill._locator(page, field)

        assert loc is hit
