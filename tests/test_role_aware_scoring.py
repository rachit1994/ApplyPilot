from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest


def _write_manifest(role_dir, roles: list[dict]) -> None:
    role_dir.mkdir(parents=True, exist_ok=True)
    (role_dir / "manifest.json").write_text(
        json.dumps({"roles": roles}),
        encoding="utf-8",
    )


def _frontend_role(role_dir) -> dict:
    pdf = role_dir / "frontend-developer.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    txt = role_dir / "frontend-developer.txt"
    txt.write_text("React TypeScript frontend UI components CSS webpack", encoding="utf-8")
    return {
        "key": "frontend-developer",
        "title": "Frontend Developer",
        "aliases": ["frontend engineer", "react engineer"],
        "keywords": ["react", "typescript", "ui"],
        "pdf_path": str(pdf),
        "txt_path": str(txt),
        "audit_pass": True,
    }


def _backend_role(role_dir) -> dict:
    pdf = role_dir / "backend-engineer.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    txt = role_dir / "backend-engineer.txt"
    txt.write_text("Python APIs PostgreSQL backend services", encoding="utf-8")
    return {
        "key": "backend-engineer",
        "title": "Backend Engineer",
        "aliases": ["backend engineer"],
        "keywords": ["python", "postgres", "api"],
        "pdf_path": str(pdf),
        "txt_path": str(txt),
        "audit_pass": True,
    }


@pytest.fixture()
def scoring_ap_dir(tmp_path, monkeypatch):
    from applypilot import config
    from applypilot import database

    ap_dir = tmp_path / "ap"
    ap_dir.mkdir()
    role_dir = ap_dir / "role_resumes"
    role_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("APPLYPILOT_DIR", str(ap_dir))
    monkeypatch.setattr(config, "APP_DIR", ap_dir)
    monkeypatch.setattr(config, "PROFILE_PATH", ap_dir / "profile.json")
    monkeypatch.setattr(config, "ROLE_RESUME_DIR", role_dir)
    resume_path = ap_dir / "resume.txt"
    resume_path.write_text("AI engineer LLM Python cloud architecture", encoding="utf-8")
    monkeypatch.setattr(config, "RESUME_PATH", resume_path)
    monkeypatch.setattr(config, "RESUME_PDF_PATH", ap_dir / "resume.pdf")
    (ap_dir / "profile.json").write_text(
        json.dumps(
            {
                "personal": {"full_name": "Test User"},
                "experience": {"target_roles": ["Software Engineer"]},
                "work_authorization": {},
                "compensation": {},
                "scoring": {"role_aware": True},
            }
        ),
        encoding="utf-8",
    )
    return ap_dir


def test_match_role_resume_scored_real_match_vs_unrelated(scoring_ap_dir):
    from applypilot import role_resumes

    role_dir = scoring_ap_dir / "role_resumes"
    _write_manifest(role_dir, [_frontend_role(role_dir)])

    frontend_job = {
        "title": "Senior React Frontend Engineer",
        "full_description": "Build React and TypeScript UI components.",
    }
    scored = role_resumes.match_role_resume_scored(frontend_job, output_dir=role_dir)
    assert scored.match_score > 0
    assert scored.item is not None
    assert scored.item["key"] == "frontend-developer"

    unrelated = role_resumes.match_role_resume_scored(
        {"title": "Dental hygienist", "full_description": "Clean teeth and educate patients."},
        output_dir=role_dir,
    )
    assert unrelated.match_score == 0
    assert unrelated.item is None


def test_resolve_job_resume_for_scoring_uses_base_without_match(scoring_ap_dir):
    from applypilot import role_resumes

    role_dir = scoring_ap_dir / "role_resumes"
    _write_manifest(role_dir, [_frontend_role(role_dir)])

    with patch.object(role_resumes, "role_resumes_complete", return_value=True):
        resolution = role_resumes.resolve_job_resume_for_scoring(
            {"title": "Dental hygienist", "full_description": "Oral care."},
            output_dir=role_dir,
        )

    assert resolution.source == "base"
    assert resolution.role_key is None
    text = role_resumes.resume_text_for_scoring(resolution, {}, output_dir=role_dir)
    assert "AI engineer" in text


def test_score_job_prompt_uses_role_resume_text(scoring_ap_dir, monkeypatch):
    from applypilot.scoring import scorer

    captured: list[list[dict]] = []

    class FakeClient:
        def chat(self, messages, max_tokens, temperature, operation="chat"):
            captured.append(messages)
            return (
                "SCORE: 8\nRECOMMENDATION: apply\nKEYWORDS: react\nREASONING: Strong frontend fit."
            )

    monkeypatch.setattr(scorer, "get_client", lambda: FakeClient())
    profile = {"experience": {"target_roles": ["Frontend Developer"]}}

    result = scorer.score_job(
        "React TypeScript frontend UI components CSS webpack",
        {"title": "React Engineer", "site": "Acme", "full_description": "React UI work."},
        profile=profile,
        role_title="Frontend Developer",
    )

    assert result["score"] == 8
    user_content = captured[0][1]["content"]
    assert "RESUME (for Frontend Developer):" in user_content
    assert "React TypeScript frontend" in user_content
    assert "AI engineer" not in user_content


def test_batch_grouping_uses_one_resume_per_role(scoring_ap_dir, monkeypatch):
    from applypilot.role_resumes import ResumeResolution
    from applypilot.scoring import scorer

    role_dir = scoring_ap_dir / "role_resumes"
    _write_manifest(role_dir, [_frontend_role(role_dir), _backend_role(role_dir)])

    batch_calls: list[tuple[str, int]] = []

    def fake_batch(resume_text, jobs, *, batch_id, role_title=None):
        batch_calls.append((resume_text[:40], len(jobs)))
        return [
            {
                "url": job["url"],
                "score": 8,
                "recommendation": "apply",
                "keywords": "k",
                "reasoning": "ok",
            }
            for job in jobs
        ]

    monkeypatch.setattr(scorer, "score_jobs_batch", fake_batch)
    monkeypatch.setattr(scorer, "load_search_config", lambda: {})
    monkeypatch.setattr(scorer, "role_aware_scoring_enabled", lambda output_dir=None: True)

    def resolve(job, output_dir=None):
        if "React" in job["title"]:
            return ResumeResolution(
                path=str(role_dir / "frontend-developer.pdf"),
                source="role_resume",
                jd_score=9,
                role_key="frontend-developer",
            )
        return ResumeResolution(
            path=str(scoring_ap_dir / "resume.txt"),
            source="base",
            jd_score=None,
            role_key=None,
        )

    monkeypatch.setattr(scorer, "resolve_job_resume_for_scoring", resolve)

    def fake_resume_text(resolution, job, output_dir=None):
        if resolution.role_key == "frontend-developer":
            return "React TypeScript frontend UI"
        return "AI engineer base resume"

    monkeypatch.setattr(scorer, "resume_text_for_scoring", fake_resume_text)
    monkeypatch.setattr(
        scorer.embedding_filter,
        "encode_resume_for_key",
        lambda _text, _key: [1.0, 0.0],
    )
    monkeypatch.setattr(
        scorer.embedding_filter,
        "threshold_from_profile",
        lambda _profile: 0.25,
    )
    monkeypatch.setattr(
        scorer.embedding_filter,
        "pre_filter_job",
        lambda *_args, **_kwargs: SimpleNamespace(passes=True),
    )
    monkeypatch.setattr(
        scorer,
        "pre_score_filter",
        lambda *_args, **_kwargs: SimpleNamespace(
            passes=True,
            pre_score=8,
            reason=None,
            notes=[],
        ),
    )

    from applypilot import database

    conn = database.init_db()
    monkeypatch.setattr(scorer, "get_connection", lambda: conn)
    jobs = [
        {
            "url": "https://jobs.example/1",
            "title": "React Engineer",
            "site": "A",
            "full_description": "React UI",
            "discovered_at": "2026-01-01",
        },
        {
            "url": "https://jobs.example/2",
            "title": "React Frontend Dev",
            "site": "B",
            "full_description": "React UI",
            "discovered_at": "2026-01-02",
        },
        {
            "url": "https://jobs.example/3",
            "title": "Unrelated role",
            "site": "C",
            "full_description": "Something else",
            "discovered_at": "2026-01-03",
        },
    ]
    for job in jobs:
        conn.execute(
            """
            INSERT INTO jobs (url, title, site, full_description, discovered_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (job["url"], job["title"], job["site"], job["full_description"], job["discovered_at"]),
        )
    conn.commit()

    scorer.run_scoring()

    assert len(batch_calls) == 2
    assert sorted(size for _, size in batch_calls) == [1, 2]
    resume_snippets = {snippet for snippet, _ in batch_calls}
    assert any("React TypeScript" in snippet for snippet in resume_snippets)
    assert any("AI engineer" in snippet for snippet in resume_snippets)


def test_embedding_uses_per_role_cache(scoring_ap_dir, monkeypatch):
    from applypilot.scoring import embedding_filter

    embedding_filter.reset_cache()

    class FakeModel:
        def encode(self, text):
            return [1.0, 0.0]

    monkeypatch.setattr(embedding_filter, "_load_model", lambda: FakeModel())

    frontend = embedding_filter.encode_resume_for_key(
        "frontend resume",
        "role_resume:frontend-developer",
    )
    base = embedding_filter.encode_resume_for_key("base resume", "base:base")
    frontend_again = embedding_filter.encode_resume_for_key(
        "frontend resume",
        "role_resume:frontend-developer",
    )

    assert frontend is frontend_again
    assert base is not frontend
    assert len(embedding_filter._embedding_by_key) == 2


def test_all_score_write_paths_set_role_columns(scoring_ap_dir, monkeypatch):
    from applypilot.role_resumes import ResumeResolution
    from applypilot.scoring import scorer

    role_dir = scoring_ap_dir / "role_resumes"
    _write_manifest(role_dir, [_frontend_role(role_dir)])

    monkeypatch.setattr(scorer, "load_search_config", lambda: {})
    monkeypatch.setattr(scorer, "role_aware_scoring_enabled", lambda output_dir=None: True)

    frontend_resolution = ResumeResolution(
        path=str(role_dir / "frontend-developer.pdf"),
        source="role_resume",
        jd_score=9,
        role_key="frontend-developer",
    )
    base_resolution = ResumeResolution(
        path=str(scoring_ap_dir / "resume.txt"),
        source="base",
        jd_score=None,
        role_key=None,
    )

    def resolve(job, output_dir=None):
        if "React" in job["title"]:
            return frontend_resolution
        return base_resolution

    monkeypatch.setattr(scorer, "resolve_job_resume_for_scoring", resolve)
    monkeypatch.setattr(
        scorer,
        "resume_text_for_scoring",
        lambda resolution, job, output_dir=None: "resume text",
    )

    pre_calls = {"count": 0}

    def pre_filter(job, profile, search_cfg):
        pre_calls["count"] += 1
        if pre_calls["count"] == 1:
            return SimpleNamespace(
                passes=False,
                pre_score=3,
                reason="blocked",
                notes=["visa"],
            )
        if "React" in job["title"]:
            return SimpleNamespace(passes=True, pre_score=8, reason=None, notes=[])
        return SimpleNamespace(passes=True, pre_score=7, reason=None, notes=[])

    monkeypatch.setattr(scorer, "pre_score_filter", pre_filter)

    embed_calls = {"count": 0}

    def embed_filter(job, embedding, threshold=0.25):
        embed_calls["count"] += 1
        if embed_calls["count"] == 1:
            return SimpleNamespace(passes=False)
        return SimpleNamespace(passes=True)

    monkeypatch.setattr(scorer.embedding_filter, "encode_resume_for_key", lambda _t, _k: [1.0])
    monkeypatch.setattr(scorer.embedding_filter, "threshold_from_profile", lambda _p: 0.25)
    monkeypatch.setattr(scorer.embedding_filter, "pre_filter_job", embed_filter)

    monkeypatch.setattr(
        scorer,
        "score_job",
        lambda resume_text, job, profile=None, role_title=None: {
            "score": 8,
            "recommendation": "apply",
            "keywords": "react",
            "reasoning": "Good fit.",
            "url": job["url"],
        },
    )

    from applypilot import database

    conn = database.init_db()
    monkeypatch.setattr(scorer, "get_connection", lambda: conn)
    jobs = [
        {
            "url": "https://jobs.example/pre",
            "title": "Blocked job",
            "site": "X",
            "full_description": "desc",
            "discovered_at": "2026-01-01",
        },
        {
            "url": "https://jobs.example/embed",
            "title": "React Engineer",
            "site": "Y",
            "full_description": "React UI",
            "discovered_at": "2026-01-02",
        },
        {
            "url": "https://jobs.example/llm",
            "title": "Other job",
            "site": "Z",
            "full_description": "Other",
            "discovered_at": "2026-01-03",
        },
    ]
    for job in jobs:
        conn.execute(
            """
            INSERT INTO jobs (url, title, site, full_description, discovered_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (job["url"], job["title"], job["site"], job["full_description"], job["discovered_at"]),
        )
    conn.commit()

    with patch.object(scorer, "get_jobs_by_stage", return_value=jobs):
        scorer.run_scoring()

    pre_row = conn.execute(
        "SELECT score_role_key, score_jd_fit, score_reasoning FROM jobs WHERE url = ?",
        (jobs[0]["url"],),
    ).fetchone()
    assert pre_row["score_role_key"] is None
    assert pre_row["score_jd_fit"] is None
    assert pre_row["score_reasoning"].startswith("pre_filter:blocked")

    embed_row = conn.execute(
        "SELECT score_role_key, score_jd_fit, score_reasoning FROM jobs WHERE url = ?",
        (jobs[1]["url"],),
    ).fetchone()
    assert embed_row["score_role_key"] == "frontend-developer"
    assert embed_row["score_jd_fit"] == 9
    assert embed_row["score_reasoning"].startswith("pre_filter:embedding_low")

    llm_row = conn.execute(
        "SELECT score_role_key, score_jd_fit, score_reasoning FROM jobs WHERE url = ?",
        (jobs[2]["url"],),
    ).fetchone()
    assert llm_row["score_role_key"] is None
    assert llm_row["score_jd_fit"] is None
    assert llm_row["score_reasoning"].startswith("apply\n")


def test_role_aware_disabled_when_manifest_incomplete(scoring_ap_dir, monkeypatch):
    from applypilot import role_resumes

    role_dir = scoring_ap_dir / "role_resumes"
    _write_manifest(role_dir, [_frontend_role(role_dir)])

    with patch.object(role_resumes, "role_resumes_complete", return_value=False):
        assert role_resumes.role_aware_scoring_enabled(role_dir) is False

    with patch.object(role_resumes, "role_resumes_complete", return_value=True):
        resolution = role_resumes.resolve_job_resume_for_scoring(
            {"title": "React Engineer", "full_description": "React UI"},
            output_dir=role_dir,
        )
    assert resolution.source == "role_resume"


def test_one_time_rescore_marker(scoring_ap_dir, monkeypatch):
    from applypilot import role_resumes
    from applypilot.pipeline import _run_score

    marker = role_resumes.ROLE_AWARE_RESCORE_MARKER
    if marker.is_file():
        marker.unlink()

    run_calls: list[bool] = []

    def fake_run_scoring(*, rescore=False):
        run_calls.append(rescore)
        return {"scored": 0, "skipped_pre": 0, "errors": 0, "elapsed": 0.0, "distribution": []}

    monkeypatch.setattr("applypilot.scoring.scorer.run_scoring", fake_run_scoring)
    rescore_checks = {"count": 0}

    def should_rescore(output_dir=None):
        rescore_checks["count"] += 1
        return rescore_checks["count"] == 1

    monkeypatch.setattr(role_resumes, "should_one_time_rescore", should_rescore)

    _run_score()
    assert run_calls == [True]
    assert marker.is_file()

    run_calls.clear()
    _run_score()
    assert run_calls == [False]


def test_bind_role_resume_paths_prefers_score_role_key(scoring_ap_dir, monkeypatch):
    from applypilot import config
    from applypilot import role_resumes
    from applypilot.database import get_connection, init_db

    role_dir = scoring_ap_dir / "role_resumes"
    frontend = _frontend_role(role_dir)
    backend = _backend_role(role_dir)
    _write_manifest(role_dir, [frontend, backend])
    monkeypatch.setattr(config, "ROLE_RESUME_DIR", role_dir)

    init_db()
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO jobs
            (url, title, site, full_description, fit_score, score_role_key, discovered_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "https://jobs.example/scored",
            "Python backend APIs",
            "Co",
            "Python postgres services",
            9,
            "frontend-developer",
            "2026-01-01",
        ),
    )
    conn.commit()

    result = role_resumes.bind_role_resume_paths(conn, min_score=7)
    assert result["bound"] == 1
    row = conn.execute(
        "SELECT tailored_resume_path FROM jobs WHERE url = ?",
        ("https://jobs.example/scored",),
    ).fetchone()
    assert row["tailored_resume_path"] == str(Path(backend["pdf_path"]).resolve())


def test_jobs_api_includes_score_role_key(scoring_ap_dir):
    from applypilot.database import get_connection, init_db
    from applypilot.server.jobs import query_jobs

    init_db()
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO jobs
            (url, title, fit_score, score_role_key, score_jd_fit, discovered_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            "https://jobs.example/1",
            "React Engineer",
            8,
            "frontend-developer",
            9,
            "2026-01-01",
        ),
    )
    conn.commit()

    payload = query_jobs(limit=10)
    job = payload[0][0]
    assert job["score_role_key"] == "frontend-developer"
    assert job["score_jd_fit"] == 9
