"""Tests for optional T2 embedding pre-filter."""

from __future__ import annotations

import pytest

from applypilot import config, database
from applypilot.scoring import embedding_filter


class FakeSentenceTransformer:
    encode_calls: list[str] = []

    def __init__(self, model_name: str, cache_folder: str):
        self.model_name = model_name
        self.cache_folder = cache_folder

    def encode(self, text: str) -> list[float]:
        self.encode_calls.append(text)
        if "UNRELATED_JOB" in text:
            return [0.0, 1.0]
        return [1.0, 0.0]


@pytest.fixture(autouse=True)
def _reset_embedding_filter(monkeypatch, tmp_path):
    FakeSentenceTransformer.encode_calls = []
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(embedding_filter, "_SentenceTransformer", FakeSentenceTransformer)
    embedding_filter.reset_cache()
    yield
    embedding_filter.reset_cache()


@pytest.fixture
def temp_db(monkeypatch, tmp_path):
    db_path = tmp_path / "applypilot.db"
    monkeypatch.setenv("APPLYPILOT_DIR", str(tmp_path))
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "DB_PATH", db_path)
    monkeypatch.setattr(database, "DB_PATH", db_path)
    database.close_connection()
    database.init_db(db_path)
    yield db_path
    database.close_connection(db_path)


def test_encode_resume_caches_in_process():
    first = embedding_filter.encode_resume("RESUME")
    second = embedding_filter.encode_resume("RESUME")

    assert first == [1.0, 0.0]
    assert second == [1.0, 0.0]
    assert FakeSentenceTransformer.encode_calls == ["RESUME"]


def test_embedding_filter_gracefully_passes_when_dependency_missing(monkeypatch):
    monkeypatch.setattr(embedding_filter, "_SentenceTransformer", None)
    embedding_filter.reset_cache()

    resume_embedding = embedding_filter.encode_resume("RESUME")
    verdict = embedding_filter.pre_filter_job(
        {"title": "UNRELATED_JOB", "full_description": "UNRELATED_JOB"},
        resume_embedding,
    )

    assert resume_embedding is None
    assert verdict.passes


def test_run_scoring_marks_low_similarity_without_llm(monkeypatch, tmp_path, temp_db):
    from applypilot.scoring import scorer

    resume_path = tmp_path / "resume.txt"
    resume_path.write_text("RESUME", encoding="utf-8")
    monkeypatch.setattr(scorer, "RESUME_PATH", resume_path)
    monkeypatch.setattr(
        scorer,
        "load_profile",
        lambda: {"embedding_threshold": 0.5, "scoring_batch_size": 1},
    )
    monkeypatch.setattr(scorer, "load_search_config", lambda: {})

    scored_by_llm: list[str] = []

    def fake_score_job(resume_text: str, job: dict, profile: dict | None = None) -> dict:
        scored_by_llm.append(job["url"])
        return {
            "score": 8,
            "recommendation": "apply",
            "keywords": "python",
            "reasoning": "Strong match.",
        }

    monkeypatch.setattr(scorer, "score_job", fake_score_job)

    conn = database.get_connection(temp_db)
    conn.execute(
        """
        INSERT INTO jobs (url, title, site, location, full_description)
        VALUES
          ('https://jobs.example/good', 'Relevant Engineer', 'Acme', 'Remote', 'Build with Python.'),
          ('https://jobs.example/low', 'UNRELATED_JOB', 'Beta', 'Remote', 'UNRELATED_JOB')
        """
    )
    conn.commit()

    result = scorer.run_scoring()

    rows = {
        row["url"]: dict(row)
        for row in conn.execute(
            "SELECT url, fit_score, score_reasoning FROM jobs ORDER BY url"
        ).fetchall()
    }
    assert result["scored"] == 1
    assert result["skipped_pre"] == 1
    assert scored_by_llm == ["https://jobs.example/good"]
    assert rows["https://jobs.example/good"]["fit_score"] == 8
    assert rows["https://jobs.example/low"]["fit_score"] == 0
    assert rows["https://jobs.example/low"]["score_reasoning"] == "pre_filter:embedding_low"
