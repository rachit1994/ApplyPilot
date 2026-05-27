from __future__ import annotations

import json
from types import SimpleNamespace

import pytest


class FakeBatchClient:
    def __init__(self, responses: list[str] | None = None):
        self.calls: list[list[dict]] = []
        self.responses = responses or []

    def chat(
        self,
        messages: list[dict],
        max_tokens: int,
        temperature: float,
        operation: str = "chat",
    ) -> str:
        self.calls.append(messages)
        if self.responses:
            return self.responses.pop(0)

        expected = messages[0]["content"].split("exactly ", 1)[1].split(" objects", 1)[0]
        count = int(expected)
        return json.dumps(
            [
                {
                    "url": f"https://ignored.example/{idx}",
                    "score": 8 - (idx % 2),
                    "recommendation": "apply",
                    "keywords": f"python, react {idx}",
                    "reasoning": f"Strong match {idx}.",
                }
                for idx in range(count)
            ]
        )


@pytest.fixture()
def scoring_env(tmp_path, monkeypatch):
    monkeypatch.setenv("APPLYPILOT_DIR", str(tmp_path))

    from applypilot import database
    from applypilot.scoring import scorer

    db_path = tmp_path / "applypilot.db"
    conn = database.init_db(db_path)
    resume_path = tmp_path / "resume.txt"
    resume_path.write_text("Python React resume", encoding="utf-8")

    monkeypatch.setattr(scorer, "RESUME_PATH", resume_path)
    monkeypatch.setattr(scorer, "get_connection", lambda: conn)
    monkeypatch.setattr(scorer, "load_search_config", lambda: {})
    monkeypatch.setattr(scorer.embedding_filter, "encode_resume", lambda _text: None)
    monkeypatch.setattr(scorer.embedding_filter, "threshold_from_profile", lambda _profile: 0.25)
    monkeypatch.setattr(
        scorer.embedding_filter,
        "pre_filter_job",
        lambda *_args, **_kwargs: SimpleNamespace(passes=True),
    )

    yield scorer, conn

    database.close_connection(db_path)


def _insert_jobs(conn, count: int, *, long_description: bool = False) -> None:
    description = "x" * 2500 if long_description else "Python React TypeScript"
    for idx in range(count):
        conn.execute(
            """
            INSERT INTO jobs
                (url, title, site, location, full_description, discovered_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                f"https://jobs.example/{idx}",
                f"Senior Frontend Engineer {idx}",
                "Example",
                "Remote",
                description,
                f"2026-05-26T00:00:0{idx}+00:00",
            ),
        )
    conn.commit()


def test_run_scoring_batches_survivors_with_default_size(scoring_env, monkeypatch):
    scorer, conn = scoring_env
    _insert_jobs(conn, 6, long_description=True)
    client = FakeBatchClient()

    monkeypatch.setattr(
        scorer,
        "load_profile",
        lambda: {
            "experience": {"target_roles": ["Senior Frontend Engineer"]},
            "compensation": {"salary_currency": "INR"},
        },
    )
    monkeypatch.setattr(scorer, "get_client", lambda: client)

    summary = scorer.run_scoring()

    assert summary["scored"] == 6
    assert len(client.calls) == 2
    assert "exactly 5 objects" in client.calls[0][0]["content"]
    assert "exactly 1 objects" in client.calls[1][0]["content"]
    assert "x" * 2000 in client.calls[0][1]["content"]
    assert "x" * 2001 not in client.calls[0][1]["content"]

    rows = conn.execute(
        "SELECT url, fit_score, score_reasoning FROM jobs ORDER BY url"
    ).fetchall()
    assert len(rows) == 6
    assert all(row["fit_score"] in (7, 8) for row in rows)
    assert rows[0]["score_reasoning"].startswith("apply\npython, react")


def test_scoring_batch_size_one_uses_single_job_path(scoring_env, monkeypatch):
    scorer, conn = scoring_env
    _insert_jobs(conn, 3)
    single_calls = []

    monkeypatch.setattr(
        scorer,
        "load_profile",
        lambda: {
            "scoring_batch_size": 1,
            "experience": {"target_roles": ["Senior Frontend Engineer"]},
            "compensation": {"salary_currency": "INR"},
        },
    )
    monkeypatch.setattr(
        scorer,
        "score_jobs_batch",
        lambda *_args, **_kwargs: pytest.fail("batch scorer should not be used"),
    )

    def fake_score_job(_resume_text, job, profile=None):
        single_calls.append(job["url"])
        return {
            "score": 7,
            "recommendation": "apply",
            "keywords": "python",
            "reasoning": "Single path.",
        }

    monkeypatch.setattr(scorer, "score_job", fake_score_job)

    summary = scorer.run_scoring()

    assert summary["scored"] == 3
    assert single_calls == [
        "https://jobs.example/2",
        "https://jobs.example/1",
        "https://jobs.example/0",
    ]


def test_malformed_batch_falls_back_to_single_job_path(scoring_env, monkeypatch, caplog):
    scorer, conn = scoring_env
    _insert_jobs(conn, 5)
    client = FakeBatchClient(responses=["not json"])
    single_calls = []

    monkeypatch.setattr(
        scorer,
        "load_profile",
        lambda: {
            "scoring_batch_size": 5,
            "experience": {"target_roles": ["Senior Frontend Engineer"]},
            "compensation": {"salary_currency": "INR"},
        },
    )
    monkeypatch.setattr(scorer, "get_client", lambda: client)

    def fake_score_job(_resume_text, job, profile=None):
        single_calls.append(job["url"])
        return {
            "score": 6,
            "recommendation": "maybe",
            "keywords": "typescript",
            "reasoning": "Fallback path.",
        }

    monkeypatch.setattr(scorer, "score_job", fake_score_job)

    with caplog.at_level("WARNING", logger="applypilot.scoring.scorer"):
        summary = scorer.run_scoring()

    assert summary["scored"] == 5
    assert len(single_calls) == 5
    assert "batch_id=score-batch-1" in caplog.text
    assert "reason=" in caplog.text

    scores = conn.execute("SELECT fit_score FROM jobs").fetchall()
    assert [row["fit_score"] for row in scores] == [6, 6, 6, 6, 6]
