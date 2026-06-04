"""Tests for Below-7 reason display + list filter."""

from applypilot.server.low_score_reason import (
    display_reason,
    low_score_reason_filter_clause,
)


def test_display_reason_pre_filter_key():
    assert display_reason("title:junior_or_intern", None) == "Junior or intern title"


def test_display_reason_junior_signal_in_jd():
    assert display_reason("description:junior_signal", None) == "Junior signal in JD"


def test_low_score_reason_filter_clause_known_label():
    clause = low_score_reason_filter_clause("Junior or intern title")
    assert clause is not None
    assert "fit_score" in clause
    assert "title:junior_or_intern" in clause


def test_low_score_reason_filter_clause_unknown_label():
    assert low_score_reason_filter_clause("Not a real label") is None


def test_api_jobs_low_score_reason_filter(monkeypatch, tmp_path):
    monkeypatch.setenv("APPLYPILOT_DIR", str(tmp_path))
    from applypilot.database import get_connection, init_db
    from applypilot.server.app import create_app
    from fastapi.testclient import TestClient

    init_db()
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO jobs (url, title, site, fit_score, discovered_at, pre_filter_reason)
        VALUES
          ('https://a.example/low', 'Junior Dev', 'Acme', 4,
           '2026-05-18T10:00:00+00:00', 'title:junior_or_intern'),
          ('https://a.example/high', 'Staff Eng', 'Acme', 9,
           '2026-05-18T11:00:00+00:00', NULL)
        """
    )
    conn.commit()

    client = TestClient(create_app())
    resp = client.get(
        "/api/jobs",
        params={"low_score_reason": "Junior or intern title"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["jobs"][0]["url"] == "https://a.example/low"
