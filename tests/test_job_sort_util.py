"""Tests for dashboard job sort URL helpers."""

from applypilot.server.jobs import _SORT_ORDERS


def test_sort_orders_include_asc_and_desc_pairs():
    assert "activity_desc" in _SORT_ORDERS
    assert "activity_asc" in _SORT_ORDERS
    assert "fit_score_desc" in _SORT_ORDERS
    assert "fit_score_asc" in _SORT_ORDERS
    assert "discovered_at_desc" in _SORT_ORDERS
    assert "discovered_at_asc" in _SORT_ORDERS
    assert "scored_at_desc" in _SORT_ORDERS
    assert "scored_at_asc" in _SORT_ORDERS
    assert "title_asc" in _SORT_ORDERS
    assert "title_desc" in _SORT_ORDERS
