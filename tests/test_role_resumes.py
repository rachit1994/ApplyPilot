from __future__ import annotations

import json
from pathlib import Path


def _profile() -> dict:
    return {
        "personal": {
            "full_name": "Test User",
            "city": "Bengaluru",
            "country": "India",
            "phone": "+91 11111",
            "email": "test@example.com",
            "linkedin_url": "https://linkedin.com/in/test",
            "github_url": "https://github.com/test",
        },
        "experience": {
            "target_roles": [
                "Frontend Engineer",
                "Solutions Architect",
                "Engineering Manager",
            ],
            "current_job_title": "Senior Full Stack Engineer",
        },
    }


def _master_resume() -> str:
    return """TEST USER
Senior Full Stack Engineer
Bengaluru · test@example.com

SUMMARY
Senior engineer with React, Node.js, Python, AWS, and technical leadership.

EXPERIENCE

Tech Lead / Senior Full Stack Engineer | 2022 - 2024
Example Co
• Built a React component library and reduced UI delivery time.
• Led technical debt reduction and mentored engineers.
• Designed AWS APIs and integration architecture.

Software Engineer | 2019 - 2022
Second Co
• Built Python services and React dashboards for enterprise workflows; integrated third-party APIs and shipped React frontend modules.

SKILLS
React · TypeScript · Node.js · Python · AWS
"""


def test_generate_role_resumes_writes_manifest_and_pdfs(tmp_path: Path, monkeypatch):
    from applypilot import config
    from applypilot import role_resumes

    resume_path = tmp_path / "resume.txt"
    resume_path.write_text(_master_resume(), encoding="utf-8")
    out_dir = tmp_path / "role_resumes"
    monkeypatch.setattr(config, "ROLE_RESUME_DIR", out_dir)
    monkeypatch.setattr(config, "RESUME_PATH", resume_path)
    monkeypatch.setattr(config, "load_profile", _profile)
    monkeypatch.setattr(
        role_resumes,
        "find_benchmark_job",
        lambda spec, profile, master_resume="": role_resumes.BenchmarkJob(
            source="test",
            url="https://jobs.example/role",
            title=f"Senior {spec.title}",
            company="ExampleCo",
            salary="$160K-$180K",
            salary_usd_max=180000,
            location="Remote",
            description="Must have React, TypeScript, AWS, architecture, team leadership, and customer integration experience.",
            eligibility_reason="eligible: remote",
        ),
    )

    def fake_rewrite(**kwargs):
        return (
            role_resumes.build_role_resume_text(
                kwargs["spec"],
                profile=kwargs["profile"],
                master_resume=kwargs["master_resume"],
                benchmark=kwargs["benchmark"],
                jd_analysis=kwargs["jd_analysis"],
            ),
            [{"claim": "Built a React component library", "evidence": ["Built a React component library"]}],
            ["test rewrite"],
        )

    monkeypatch.setattr(role_resumes, "_gemini_rewrite_resume", fake_rewrite)
    monkeypatch.setattr(
        role_resumes,
        "_gemini_audit_resume",
        lambda **kwargs: {
            "score": 91,
            "pass": True,
            "keyword_coverage_score": 90,
            "critical_rejection_flags": [],
            "unsupported_claims": [],
        },
    )

    def fake_convert(text_path: Path, output_path: Path | None = None, html_only: bool = False) -> Path:
        out = Path(output_path or text_path.with_suffix(".pdf"))
        out.write_bytes(b"%PDF-1.4\n")
        return out

    monkeypatch.setattr("applypilot.scoring.pdf.convert_to_pdf", fake_convert)

    manifest = role_resumes.generate_role_resumes()

    titles = {item["title"] for item in manifest["roles"]}
    assert "Frontend Developer" in titles
    assert "Solutions Architect" in titles
    assert "Engineering Manager" in titles
    assert (out_dir / "manifest.json").is_file()
    assert all(Path(item["pdf_path"]).is_file() for item in manifest["roles"])
    assert all(Path(item["audit_path"]).is_file() for item in manifest["roles"])
    assert all(Path(item["pdf_path"]).name == "resume.pdf" for item in manifest["roles"])
    assert all(Path(item["txt_path"]).name == "resume.txt" for item in manifest["roles"])
    assert all(Path(item["audit_path"]).name == "audit.json" for item in manifest["roles"])
    assert (out_dir / "frontend-developer" / "resume.pdf").is_file()


def _role_resumes_test_hooks(monkeypatch, tmp_path: Path):
    from applypilot import config
    from applypilot import role_resumes

    resume_path = tmp_path / "resume.txt"
    resume_path.write_text(_master_resume(), encoding="utf-8")
    out_dir = tmp_path / "role_resumes"
    monkeypatch.setattr(config, "ROLE_RESUME_DIR", out_dir)
    monkeypatch.setattr(config, "RESUME_PATH", resume_path)
    monkeypatch.setattr(config, "load_profile", _profile)
    monkeypatch.setattr(
        role_resumes,
        "find_benchmark_job",
        lambda spec, profile, master_resume="": role_resumes.BenchmarkJob(
            source="test",
            url="https://jobs.example/role",
            title=f"Senior {spec.title}",
            company="ExampleCo",
            salary="$160K-$180K",
            salary_usd_max=180000,
            location="Remote",
            description="Must have React, TypeScript, AWS, architecture, team leadership, and customer integration experience.",
            eligibility_reason="eligible: remote",
        ),
    )

    def fake_rewrite(**kwargs):
        return (
            role_resumes.build_role_resume_text(
                kwargs["spec"],
                profile=kwargs["profile"],
                master_resume=kwargs["master_resume"],
                benchmark=kwargs["benchmark"],
                jd_analysis=kwargs["jd_analysis"],
            ),
            [{"claim": "Built a React component library", "evidence": ["Built a React component library"]}],
            ["test rewrite"],
        )

    monkeypatch.setattr(role_resumes, "_gemini_rewrite_resume", fake_rewrite)
    monkeypatch.setattr(
        role_resumes,
        "_gemini_audit_resume",
        lambda **kwargs: {
            "score": 91,
            "pass": True,
            "keyword_coverage_score": 90,
            "critical_rejection_flags": [],
            "unsupported_claims": [],
        },
    )
    _deterministic_audit = role_resumes._deterministic_audit

    def lenient_deterministic_audit(spec, resume_text, master_resume, jd_analysis, benchmark):
        audit = _deterministic_audit(spec, resume_text, master_resume, jd_analysis, benchmark)
        if audit.get("experience_role_lens_issues"):
            audit["pass"] = False
            return audit
        audit["score"] = max(int(audit.get("score") or 0), 88)
        audit["pass"] = audit["score"] >= role_resumes.AUDIT_PASS_SCORE and not audit.get(
            "critical_rejection_flags"
        )
        return audit

    monkeypatch.setattr(role_resumes, "_deterministic_audit", lenient_deterministic_audit)

    def fake_convert(text_path: Path, output_path: Path | None = None, html_only: bool = False) -> Path:
        out = Path(output_path or text_path.with_suffix(".pdf"))
        out.write_bytes(b"%PDF-1.4\n")
        return out

    monkeypatch.setattr("applypilot.scoring.pdf.convert_to_pdf", fake_convert)
    return role_resumes, out_dir


def test_generate_role_resumes_skips_when_complete(tmp_path: Path, monkeypatch):
    role_resumes, out_dir = _role_resumes_test_hooks(monkeypatch, tmp_path)
    required = len(
        role_resumes.infer_applicable_roles(_profile(), _master_resume())
    )

    first = role_resumes.generate_role_resumes()
    assert first["generated_this_run"] == required
    assert role_resumes.role_resumes_complete()

    second = role_resumes.generate_role_resumes()
    assert second["generated_this_run"] == 0
    assert second["status"] == "complete"
    assert len(second["roles"]) == required


def test_generate_role_resumes_fills_partial_manifest(tmp_path: Path, monkeypatch):
    role_resumes, out_dir = _role_resumes_test_hooks(monkeypatch, tmp_path)
    frontend_pdf = out_dir / "frontend-developer" / "resume.pdf"
    frontend_pdf.parent.mkdir(parents=True, exist_ok=True)
    frontend_pdf.write_bytes(b"%PDF-1.4\n")
    (out_dir / "manifest.json").write_text(
        json.dumps(
            {
                "roles": [
                    {
                        "key": "frontend-developer",
                        "title": "Frontend Developer",
                        "aliases": ["frontend engineer"],
                        "keywords": ["react", "typescript"],
                        "pdf_path": str(frontend_pdf),
                        "txt_path": str(frontend_pdf.with_suffix(".txt")),
                        "audit_path": str(frontend_pdf.parent / "audit.json"),
                        "audit_pass": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    required_specs = role_resumes.infer_applicable_roles(_profile(), _master_resume())
    required_keys = {spec.key for spec in required_specs}

    manifest = role_resumes.generate_role_resumes()
    assert manifest["generated_this_run"] == len(required_keys) - 1
    assert len(manifest["roles"]) == len(required_keys)
    assert role_resumes.role_resumes_complete()
    assert {item["key"] for item in manifest["roles"]} == required_keys
    assert "frontend-developer" in required_keys


def test_pipeline_stage_order_starts_with_discover():
    from applypilot.pipeline import STAGE_ORDER

    assert STAGE_ORDER[0] == "discover"
    assert "role_resumes" not in STAGE_ORDER


def test_salary_parser_accepts_usd_and_inr_ranges():
    from applypilot import role_resumes

    assert role_resumes.parse_salary_usd_max("$160k - $180k") == 180000
    assert role_resumes.parse_salary_usd_max("", salary_min=90000, salary_max=120000) == 120000
    assert role_resumes.parse_salary_usd_max("$31,2k - $52k") == 52000
    assert role_resumes.parse_salary_usd_max("100 LPA") >= 80000
    assert role_resumes.parse_salary_usd_max("50 LPA") < 80000


def test_benchmark_salary_ignores_years_experience_false_positive():
    from applypilot import role_resumes

    job = {
        "salary": "",
        "description": "Must have 15+ years of backend experience with Python and AWS.",
        "full_description": "",
        "location": "Bengaluru",
    }
    assert role_resumes._benchmark_salary_usd_max(job) == 0


def test_title_role_match_accepts_backend_in_posting_title():
    from applypilot import role_resumes

    spec = next(s for s in role_resumes.ROLE_CATALOG if s.key == "backend-engineer")
    assert role_resumes._title_role_match(spec, "Senior Software Engineer, Backend")


def test_find_db_benchmark_uses_description_without_salary_column(tmp_path, monkeypatch):
    import uuid

    from applypilot import config
    from applypilot import role_resumes
    from applypilot.database import init_db, get_connection

    ap_dir = tmp_path / "ap"
    ap_dir.mkdir()
    monkeypatch.setenv("APPLYPILOT_DIR", str(ap_dir))
    monkeypatch.setattr(config, "APP_DIR", ap_dir)
    init_db()

    slug = uuid.uuid4().hex[:12]
    jd = (
        "Senior Backend Engineer role in Bengaluru. Remote within India. "
        "Compensation: ₹85-95 LPA. Must have Python, Node.js, PostgreSQL, Kafka, "
        "and distributed systems experience building production APIs on AWS. "
        " " * 220
    )
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO jobs (
            url, title, site, application_url, salary, description, location,
            full_description, fit_score, discovered_at, strategy
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), ?)
        """,
        (
            f"https://example.com/backend-{slug}",
            "Senior Software Engineer, Backend",
            "Ashby:Example",
            f"https://example.com/apply/backend-{slug}",
            "",
            jd,
            "Bengaluru",
            jd,
            9,
            "test",
        ),
    )
    conn.commit()

    spec = next(s for s in role_resumes.ROLE_CATALOG if s.key == "backend-engineer")
    benchmark = role_resumes.find_benchmark_job(spec, _profile(), _master_resume())

    assert benchmark.source in ("db", "db_tailoring")
    assert "Backend" in benchmark.title
    assert len(benchmark.description) >= 200
    assert benchmark.salary_usd_max >= role_resumes.MIN_BENCHMARK_USD


def test_jd_analysis_extracts_requirements_keywords_and_domain_terms():
    from applypilot import role_resumes

    spec = next(s for s in role_resumes.ROLE_CATALOG if s.key == "frontend-developer")
    benchmark = role_resumes.BenchmarkJob(
        source="test",
        url="https://jobs.example/frontend",
        title="Senior Frontend Engineer",
        company="Example",
        salary="$160K",
        salary_usd_max=160000,
        location="Remote",
        description=(
            "Must have strong React and TypeScript experience. "
            "Responsible for platform performance, UI reliability, and customer-facing product work. "
            "GraphQL experience preferred."
        ),
        eligibility_reason="eligible",
    )

    analysis = role_resumes.analyze_jd(spec, benchmark)

    assert "react" in analysis["keywords"]
    assert "typescript" in analysis["keywords"]
    assert any("Must have" in req for req in analysis["hard_requirements"])
    assert "performance" in analysis["domain_problem_signals"]


def test_fact_support_validator_flags_unsupported_claims():
    from applypilot import role_resumes

    result = role_resumes.validate_fact_support(
        "EXPERIENCE\n• Invented quantum database for hospitals.\n• Built a React component library.\n",
        _master_resume(),
    )

    assert any("quantum database" in claim for claim in result["unsupported_claims"])
    assert any("React component library" in row["claim"] for row in result["fact_support_map"])


def test_missing_experience_companies_detects_dropped_employer():
    from applypilot import role_resumes

    assert role_resumes.extract_experience_companies(_master_resume()) == [
        "Example Co",
        "Second Co",
    ]
    missing = role_resumes.missing_experience_companies(
        "EXPERIENCE\nTech Lead | 2022 - 2024\nExample Co\n• Built React UI.\n",
        _master_resume(),
    )
    assert missing == ["Second Co"]

    located_master = _master_resume().replace("Example Co", "Example Co · Bengaluru")
    assert role_resumes.extract_experience_companies(located_master)[0] == "Example Co"
    assert role_resumes.missing_experience_companies(
        "EXPERIENCE\nTech Lead | 2022 - 2024\nExample Co\n• Built React UI.\n"
        "Software Engineer | 2019 - 2022\nSecond Co\n• Built Python services.\n",
        located_master,
    ) == []


def test_experience_blocks_preserve_original_titles_and_detect_inflation():
    from applypilot import role_resumes

    blocks = role_resumes.extract_experience_blocks(_master_resume())

    assert blocks[0].title_line == "Tech Lead / Senior Full Stack Engineer | 2022 - 2024"
    assert blocks[0].company == "Example Co"
    assert blocks[1].title_line == "Software Engineer | 2019 - 2022"

    inflated = (
        "EXPERIENCE\n"
        "Engineering Manager | 2022 - 2024\nExample Co\n• Built React UI.\n\n"
        "Engineering Manager | 2019 - 2022\nSecond Co\n• Built Python services.\n"
    )

    assert role_resumes.missing_experience_title_lines(inflated, _master_resume()) == [
        "Tech Lead / Senior Full Stack Engineer | 2022 - 2024",
        "Software Engineer | 2019 - 2022",
    ]


def _ai_heavy_master_resume() -> str:
    return """TEST USER
Senior Full Stack Engineer
Bengaluru · test@example.com

EXPERIENCE

Full Stack Engineer — AI Platform | 2026 – Present
Happening Today
• Building a multi-agent orchestration layer using LangGraph: planner agent decomposes user intent into sub-tasks.
• Architecting an end-to-end RAG pipeline for event discovery — embedding generation, pgvector indexing, and semantic reranking.
• Implementing a streaming inference layer (Server-Sent Events + Node.js) over the Anthropic Claude API — handling backpressure and token-budget management.
• Owning the LLMOps stack: automated evals pipeline, latency/cost dashboards in CloudWatch, and hallucination-rate alerting.

Full Stack Engineer — AI Products | 2024 – 2025
MIRA
• Built and scaled backend services powering generative AI features for 50M+ users — production RAG system using Pinecone, LangChain, and GPT-4 / Claude.
• Built an evaluation framework for LLM output quality: factual accuracy, groundedness, and instruction-following.
• Engineered a fine-tuning pipeline using LoRA/QLoRA on Llama 3 for domain-specific response personalisation.

Tech Lead / Senior Full Stack Engineer | 2022 – 2024
Delta Exchange
• Built a React component library and shared state management layer, cutting UI feature development time significantly.
• Designed core trading engine features — order book rendering, WebSocket feed management, and margin calculation APIs.
"""


def test_non_ai_role_deprioritizes_ai_led_bullets_in_recent_jobs():
    from applypilot import role_resumes

    spec = next(s for s in role_resumes.ROLE_CATALOG if s.key == "frontend-developer")
    benchmark = role_resumes.BenchmarkJob(
        source="test",
        url="https://jobs.example/fe",
        title="Frontend Developer",
        company="Example",
        salary="$160K",
        salary_usd_max=160000,
        location="Remote",
        description="React, TypeScript, component libraries, WebSockets, performance, and UI delivery.",
        eligibility_reason="eligible",
    )
    jd = role_resumes.analyze_jd(spec, benchmark)
    resume = role_resumes.build_role_resume_text(
        spec,
        profile=_profile(),
        master_resume=_ai_heavy_master_resume(),
        benchmark=benchmark,
        jd_analysis=jd,
    )

    happening_section = resume.split("Happening Today", 1)[1].split("MIRA", 1)[0]
    first_bullet = next(
        line for line in happening_section.splitlines() if line.strip().startswith("•")
    ).lower()
    assert "happening today" in resume.lower()
    assert "mira" in resume.lower()
    assert "delta exchange" in resume.lower()
    assert not first_bullet.startswith("• building a multi-agent")
    assert not first_bullet.startswith("• architecting an end-to-end rag")
    assert (
        "streaming" in first_bullet
        or "node.js" in first_bullet
        or "server-sent events" in first_bullet
    )
    assert role_resumes.resume_role_content_issues(resume, spec) == []


def test_backend_and_cloud_resumes_omit_ai_markers():
    from applypilot import role_resumes

    benchmark = role_resumes.BenchmarkJob(
        source="test",
        url="https://jobs.example/backend",
        title="Senior Backend Engineer",
        company="Example",
        salary="$180K",
        salary_usd_max=180000,
        location="Remote",
        description="Python, Node.js, microservices, PostgreSQL, Redis, Kafka, AWS, APIs, distributed systems.",
        eligibility_reason="eligible",
    )
    forbidden = (
        "rag ",
        "langgraph",
        "langchain",
        "llmops",
        " llm ",
        "anthropic",
        "claude api",
        "generative ai",
        "multi-agent",
        "pgvector",
        "pinecone",
    )
    for key in ("backend-engineer", "cloud-architect", "platform-engineer"):
        spec = next(s for s in role_resumes.ROLE_CATALOG if s.key == key)
        jd = role_resumes.analyze_jd(spec, benchmark)
        resume = role_resumes.build_role_resume_text(
            spec,
            profile=_profile(),
            master_resume=_ai_heavy_master_resume(),
            benchmark=benchmark,
            jd_analysis=jd,
        ).lower()
        assert role_resumes.resume_role_content_issues(resume, spec) == []
        for marker in forbidden:
            assert marker not in resume, f"{key} still contains {marker!r}"
        assert "ai platform" not in resume
        assert "ai products" not in resume
        assert "generative product" not in resume


def test_non_ai_resume_reframes_recent_experience_titles():
    from applypilot import role_resumes

    spec = next(s for s in role_resumes.ROLE_CATALOG if s.key == "backend-engineer")
    assert role_resumes._display_experience_title_line(
        "Full Stack Engineer — AI Platform | 2026 – Present",
        spec,
    ) == "Full Stack Engineer — Platform Engineering | 2026 – Present"
    platform_variants = role_resumes._title_line_variants(
        "Full Stack Engineer — AI Platform | 2026 – Present"
    )
    assert role_resumes._norm(
        "Full Stack Engineer — Platform Engineering | 2026 – Present"
    ) in platform_variants


def test_deterministic_resume_keeps_titles_and_expands_dense_old_company_bullet():
    from applypilot import role_resumes

    spec = next(s for s in role_resumes.ROLE_CATALOG if s.key == "engineering-manager")
    benchmark = role_resumes.BenchmarkJob(
        source="test",
        url="https://jobs.example/manager",
        title="Engineering Manager",
        company="Example",
        salary="$160K",
        salary_usd_max=160000,
        location="Remote",
        description="Lead engineering teams, delivery, APIs, integrations, quality, and roadmap.",
        eligibility_reason="eligible",
    )
    jd = role_resumes.analyze_jd(spec, benchmark)

    resume = role_resumes.build_role_resume_text(
        spec,
        profile=_profile(),
        master_resume=_master_resume(),
        benchmark=benchmark,
        jd_analysis=jd,
    )

    assert "Tech Lead / Senior Full Stack Engineer | 2022 - 2024" in resume
    assert "Software Engineer | 2019 - 2022" in resume
    assert "Engineering Manager | 2022 - 2024" not in resume
    assert role_resumes.thin_experience_sections(resume, _master_resume()) == []
    second_section = resume.split("Second Co", 1)[1]
    assert second_section.count("•") >= 2


def test_public_resume_quality_blocks_internal_pipeline_language():
    from applypilot import role_resumes

    bad_resume = (
        "SUMMARY\n"
        "Targeted for Engineering Manager work at Reddit while preserving only verified resume facts.\n\n"
        "TECHNICAL SKILLS\n"
        "JD Alignment: engineering manager, manager, cto, team\n"
    )

    issues = role_resumes.public_resume_quality_issues(bad_resume)

    assert any("targeted for" in issue for issue in issues)
    assert any("jd alignment" in issue for issue in issues)


def test_deterministic_resume_has_professional_public_summary_and_skills():
    from applypilot import role_resumes

    spec = next(s for s in role_resumes.ROLE_CATALOG if s.key == "engineering-manager")
    benchmark = role_resumes.BenchmarkJob(
        source="test",
        url="https://jobs.example/manager",
        title="Engineering Manager",
        company="Example",
        salary="$160K",
        salary_usd_max=160000,
        location="Remote",
        description="Lead engineering teams, delivery, APIs, integrations, quality, and roadmap.",
        eligibility_reason="eligible",
    )
    jd = role_resumes.analyze_jd(spec, benchmark)

    resume = role_resumes.build_role_resume_text(
        spec,
        profile=_profile(),
        master_resume=_master_resume(),
        benchmark=benchmark,
        jd_analysis=jd,
    )

    lowered = resume.lower()
    assert "targeted for" not in lowered
    assert "jd alignment" not in lowered
    assert "verified resume facts" not in lowered
    assert "benchmark" not in lowered
    assert role_resumes.public_resume_quality_issues(resume) == []


def test_supported_skills_filter_blocks_unsupported_transition_claims():
    from applypilot import role_resumes

    spec = next(s for s in role_resumes.ROLE_CATALOG if s.key == "forward-deployed-engineer")
    skills = role_resumes._skills_from_source(spec, _master_resume())

    assert "Technical discovery" not in skills
    assert "customer-facing" not in skills.lower()
    assert "onsite" not in skills.lower()


def test_gemini_rewrite_falls_back_when_company_is_dropped(monkeypatch):
    from applypilot import role_resumes

    spec = next(s for s in role_resumes.ROLE_CATALOG if s.key == "frontend-developer")
    benchmark = role_resumes.BenchmarkJob(
        source="test",
        url="https://jobs.example/frontend",
        title="Senior Frontend Engineer",
        company="Example",
        salary="$160K",
        salary_usd_max=160000,
        location="Remote",
        description="Must have React and TypeScript performance experience.",
        eligibility_reason="eligible",
    )
    jd = role_resumes.analyze_jd(spec, benchmark)

    class FakeClient:
        def ask(self, *args, **kwargs):
            return json.dumps(
                {
                    "resume_text": (
                        "TEST USER\nFrontend Developer\nContact\n\nSUMMARY\nFrontend.\n\n"
                        "TECHNICAL SKILLS\nFrontend: React\n\nEXPERIENCE\n"
                        "Tech Lead | 2022 - 2024\nExample Co\n• Built React UI.\n"
                    ),
                    "fact_support_map": [],
                    "rewrite_notes": [],
                }
            )

    monkeypatch.setattr(role_resumes, "get_direct_gemini_client", lambda: FakeClient())

    resume, _support, notes = role_resumes._gemini_rewrite_resume(
        spec=spec,
        profile=_profile(),
        master_resume=_master_resume(),
        benchmark=benchmark,
        jd_analysis=jd,
        problem_hypothesis={},
        previous_audit=None,
    )

    assert "Example Co" in resume
    assert "Second Co" in resume
    assert any("dropped companies" in note for note in notes)


def test_generate_retries_after_failed_audit(tmp_path: Path, monkeypatch):
    from applypilot import role_resumes

    spec = next(s for s in role_resumes.ROLE_CATALOG if s.key == "ai-engineer")
    benchmark = role_resumes.BenchmarkJob(
        source="test",
        url="https://jobs.example/ai",
        title="Senior AI Engineer",
        company="Example",
        salary="$160K",
        salary_usd_max=160000,
        location="Remote",
        description="Must have RAG, LangChain, and production LLM systems experience.",
        eligibility_reason="eligible",
    )
    monkeypatch.setattr(role_resumes, "find_benchmark_job", lambda _spec, _profile, _master_resume="": benchmark)
    monkeypatch.setattr(
        "applypilot.scoring.pdf.convert_to_pdf",
        lambda text_path, output_path=None, html_only=False: Path(output_path or text_path.with_suffix(".pdf")).write_bytes(b"%PDF") or Path(output_path or text_path.with_suffix(".pdf")),
    )
    rewrites = {"count": 0}
    audits = iter([
        {"score": 70, "pass": False, "critical_rejection_flags": ["tech_mismatch"], "unsupported_claims": []},
        {"score": 90, "pass": True, "critical_rejection_flags": [], "unsupported_claims": []},
    ])

    def fake_rewrite(**kwargs):
        rewrites["count"] += 1
        return (
            role_resumes.build_role_resume_text(
                kwargs["spec"],
                profile=kwargs["profile"],
                master_resume=kwargs["master_resume"],
                benchmark=kwargs["benchmark"],
                jd_analysis=kwargs["jd_analysis"],
            ),
            [],
            [f"rewrite {rewrites['count']}"],
        )

    monkeypatch.setattr(role_resumes, "_gemini_rewrite_resume", fake_rewrite)
    monkeypatch.setattr(role_resumes, "_gemini_audit_resume", lambda **_kwargs: next(audits))

    item = role_resumes.generate_one_role_resume(
        spec,
        profile=_profile(),
        master_resume=_master_resume(),
        output=tmp_path,
    )

    assert rewrites["count"] == 2
    assert item["audit_pass"] is True
    assert item["audit_score"] == 90
    assert Path(item["audit_path"]).is_file()
    assert Path(item["pdf_path"]).parent.name == "ai-engineer"


def test_match_role_resume_prefers_frontend_for_react_job(tmp_path: Path):
    from applypilot import role_resumes

    pdf = tmp_path / "frontend-developer.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "roles": [
                    {
                        "key": "frontend-developer",
                        "title": "Frontend Developer",
                        "aliases": ["frontend developer", "frontend engineer", "react engineer"],
                        "keywords": ["react", "typescript", "ui"],
                        "pdf_path": str(pdf),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    match = role_resumes.match_role_resume(
        {
            "title": "Senior React Frontend Engineer",
            "full_description": "Build TypeScript UI components and frontend performance wins.",
        },
        output_dir=tmp_path,
    )

    assert match is not None
    assert match["pdf_path"] == str(pdf)


def test_match_role_resume_skips_failed_audit_items(tmp_path: Path):
    from applypilot import role_resumes

    failed = tmp_path / "engineering-manager.pdf"
    passed = tmp_path / "senior-full-stack-engineer.pdf"
    failed.write_bytes(b"%PDF-1.4\n")
    passed.write_bytes(b"%PDF-1.4\n")
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "roles": [
                    {
                        "key": "engineering-manager",
                        "title": "Engineering Manager",
                        "aliases": ["engineering manager"],
                        "keywords": ["management"],
                        "pdf_path": str(failed),
                        "audit_pass": False,
                    },
                    {
                        "key": "senior-full-stack-engineer",
                        "title": "Senior Full Stack Engineer",
                        "aliases": ["software engineer"],
                        "keywords": ["engineering"],
                        "pdf_path": str(passed),
                        "audit_pass": True,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    match = role_resumes.match_role_resume(
        {"title": "Engineering Manager", "full_description": "Lead engineering teams."},
        output_dir=tmp_path,
    )

    # Failed-audit role is skipped; weak keyword-only hits must not force a fallback resume.
    assert match is None


def test_score_role_resume_jd_fit_maps_overlap_to_1_10(tmp_path: Path):
    from applypilot import role_resumes

    txt = tmp_path / "frontend.txt"
    txt.write_text(
        "React TypeScript UI components frontend performance CSS webpack",
        encoding="utf-8",
    )
    item = {
        "key": "frontend-developer",
        "txt_path": str(txt),
        "keywords": ["react", "typescript", "ui", "frontend"],
    }
    job = {
        "title": "Senior React Frontend Engineer",
        "full_description": (
            "Build React and TypeScript UI components. Improve frontend performance "
            "and component architecture."
        ),
    }
    score = role_resumes.score_role_resume_jd_fit(item, job)
    assert score >= 8


def test_resolve_job_resume_uses_role_when_jd_score_high(tmp_path: Path):
    from applypilot import role_resumes

    role_dir = tmp_path / "role_resumes"
    role_dir.mkdir()
    pdf = role_dir / "frontend-developer.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    txt = role_dir / "resume.txt"
    txt.write_text(
        "React TypeScript UI components frontend performance CSS webpack",
        encoding="utf-8",
    )
    (role_dir / "manifest.json").write_text(
        json.dumps(
            {
                "roles": [
                    {
                        "key": "frontend-developer",
                        "title": "Frontend Developer",
                        "aliases": ["frontend engineer", "react engineer"],
                        "keywords": ["react", "typescript", "ui"],
                        "pdf_path": str(pdf),
                        "txt_path": str(txt),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    job = {
        "title": "Senior React Frontend Engineer",
        "full_description": (
            "Build React and TypeScript UI components. Improve frontend performance."
        ),
        "tailored_resume_path": "/tmp/per-job-tailored.pdf",
    }
    resolution = role_resumes.resolve_job_resume(job, output_dir=role_dir)
    assert resolution.source == "role_resume"
    assert resolution.path == str(pdf)
    assert resolution.jd_score is not None and resolution.jd_score >= 8
    assert not role_resumes.job_needs_per_job_tailor(job, output_dir=role_dir)
    text = role_resumes.resolve_job_resume_text(job, output_dir=role_dir)
    assert "React" in text


def test_resolve_job_resume_uses_tailored_when_jd_score_low(tmp_path: Path):
    from applypilot import role_resumes

    role_dir = tmp_path / "role_resumes"
    role_dir.mkdir()
    pdf = role_dir / "frontend-developer.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    txt = role_dir / "resume.txt"
    txt.write_text("Python backend APIs and databases only.", encoding="utf-8")
    tailored = tmp_path / "tailored.pdf"
    tailored.write_bytes(b"%PDF-1.4\n")
    (role_dir / "manifest.json").write_text(
        json.dumps(
            {
                "roles": [
                    {
                        "key": "frontend-developer",
                        "title": "Frontend Developer",
                        "aliases": ["frontend engineer", "react engineer"],
                        "keywords": ["react", "typescript", "ui"],
                        "pdf_path": str(pdf),
                        "txt_path": str(txt),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    job = {
        "title": "Senior React Frontend Engineer",
        "full_description": (
            "Build React and TypeScript UI components. Improve frontend performance."
        ),
        "tailored_resume_path": str(tailored),
    }
    resolution = role_resumes.resolve_job_resume(job, output_dir=role_dir)
    assert resolution.source == "tailored"
    assert resolution.path == str(tailored)
    assert resolution.jd_score is not None and resolution.jd_score < 8
    assert not role_resumes.job_needs_per_job_tailor(job, output_dir=role_dir)


def test_resolve_job_resume_prefers_title_match_over_stale_score_role_key(tmp_path: Path):
    from applypilot import role_resumes

    role_dir = tmp_path / "role_resumes"
    role_dir.mkdir()
    frontend_pdf = role_dir / "frontend-developer.pdf"
    frontend_pdf.write_bytes(b"%PDF-1.4\n")
    backend_pdf = role_dir / "backend-engineer.pdf"
    backend_pdf.write_bytes(b"%PDF-1.4\n")
    (role_dir / "manifest.json").write_text(
        json.dumps(
            {
                "roles": [
                    {
                        "key": "frontend-developer",
                        "title": "Frontend Developer",
                        "aliases": ["frontend engineer"],
                        "keywords": ["react", "typescript"],
                        "pdf_path": str(frontend_pdf),
                        "txt_path": str(
                            role_dir / "frontend-developer.txt"
                        ),
                    },
                    {
                        "key": "backend-engineer",
                        "title": "Backend Engineer",
                        "aliases": ["backend engineer"],
                        "keywords": ["python", "postgres"],
                        "pdf_path": str(backend_pdf),
                        "txt_path": str(role_dir / "backend-engineer.txt"),
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    (role_dir / "frontend-developer.txt").write_text(
        "React TypeScript UI", encoding="utf-8"
    )
    (role_dir / "backend-engineer.txt").write_text(
        "Python APIs PostgreSQL", encoding="utf-8"
    )
    tailored = tmp_path / "stale-tailored.pdf"
    tailored.write_bytes(b"%PDF-1.4\n")
    job = {
        "title": "Senior Python Backend Engineer",
        "full_description": "Build Python APIs and PostgreSQL services.",
        "score_role_key": "frontend-developer",
        "score_jd_fit": 9,
        "tailored_resume_path": str(tailored),
    }
    resolution = role_resumes.resolve_job_resume(job, output_dir=role_dir)
    assert resolution.source == "role_resume"
    assert resolution.path == str(backend_pdf)
    assert resolution.role_key == "backend-engineer"
    text = role_resumes.resolve_job_resume_text(job, output_dir=role_dir)
    assert "Python" in text
    assert "React" not in text


def test_resolve_job_resume_uses_score_role_key_when_title_match_agrees(tmp_path: Path):
    from applypilot import role_resumes

    role_dir = tmp_path / "role_resumes"
    role_dir.mkdir()
    frontend_pdf = role_dir / "frontend-developer.pdf"
    frontend_pdf.write_bytes(b"%PDF-1.4\n")
    (role_dir / "manifest.json").write_text(
        json.dumps(
            {
                "roles": [
                    {
                        "key": "frontend-developer",
                        "title": "Frontend Developer",
                        "aliases": ["frontend engineer", "react engineer"],
                        "keywords": ["react", "typescript", "ui"],
                        "pdf_path": str(frontend_pdf),
                        "txt_path": str(role_dir / "frontend-developer.txt"),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (role_dir / "frontend-developer.txt").write_text(
        "React TypeScript UI components", encoding="utf-8"
    )
    job = {
        "title": "Senior React Frontend Engineer",
        "full_description": "Build React and TypeScript UI components.",
        "score_role_key": "frontend-developer",
        "score_jd_fit": 9,
    }
    resolution = role_resumes.resolve_job_resume(job, output_dir=role_dir)
    assert resolution.source == "role_resume"
    assert resolution.path == str(frontend_pdf)
    assert resolution.role_key == "frontend-developer"
    assert resolution.jd_score == 9


def test_bind_role_resume_paths_sets_tailored_resume_path(tmp_path: Path, monkeypatch):
    import uuid

    from applypilot import config
    from applypilot import role_resumes
    from applypilot.database import get_connection, init_db

    ap_dir = tmp_path / "ap"
    ap_dir.mkdir()
    monkeypatch.setenv("APPLYPILOT_DIR", str(ap_dir))
    monkeypatch.setattr(config, "APP_DIR", ap_dir)
    monkeypatch.setattr(config, "ROLE_RESUME_DIR", tmp_path / "role_resumes")
    init_db()

    role_dir = tmp_path / "role_resumes"
    role_dir.mkdir()
    pdf = role_dir / "frontend-developer.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    txt = role_dir / "frontend-developer.txt"
    txt.write_text(
        "React TypeScript UI components frontend performance CSS webpack",
        encoding="utf-8",
    )
    (role_dir / "manifest.json").write_text(
        json.dumps(
            {
                "roles": [
                    {
                        "key": "frontend-developer",
                        "title": "Frontend Developer",
                        "aliases": ["frontend engineer", "react engineer"],
                        "keywords": ["react", "typescript", "ui"],
                        "pdf_path": str(pdf),
                        "txt_path": str(txt),
                        "audit_pass": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    slug = uuid.uuid4().hex[:12]
    url = f"https://example.com/fe-{slug}"
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO jobs (
            url, title, site, full_description, fit_score, discovered_at
        ) VALUES (?, ?, ?, ?, ?, datetime('now'))
        """,
        (
            url,
            "Senior React Frontend Engineer",
            "TestBoard",
            "Build React and TypeScript UI components. Improve frontend performance.",
            9,
        ),
    )
    conn.commit()

    result = role_resumes.bind_role_resume_paths(min_score=7)
    assert result["bound"] == 1

    row = conn.execute(
        "SELECT tailored_resume_path FROM jobs WHERE url = ?",
        (url,),
    ).fetchone()
    assert row[0] == str(pdf.resolve())


def test_job_needs_per_job_tailor_when_role_match_weak(tmp_path: Path):
    from applypilot import role_resumes

    role_dir = tmp_path / "role_resumes"
    role_dir.mkdir()
    pdf = role_dir / "frontend-developer.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    txt = role_dir / "resume.txt"
    txt.write_text("Python backend APIs and databases only.", encoding="utf-8")
    (role_dir / "manifest.json").write_text(
        json.dumps(
            {
                "roles": [
                    {
                        "key": "frontend-developer",
                        "title": "Frontend Developer",
                        "aliases": ["frontend engineer"],
                        "keywords": ["react", "typescript"],
                        "pdf_path": str(pdf),
                        "txt_path": str(txt),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    job = {
        "title": "Senior React Frontend Engineer",
        "full_description": (
            "Build React and TypeScript UI components. Improve frontend performance."
        ),
        "tailor_attempts": 0,
    }
    assert role_resumes.job_needs_per_job_tailor(job, output_dir=role_dir)


def test_resolve_job_resume_base_when_allow_base_and_no_tailor(tmp_path: Path, monkeypatch):
    from applypilot import config
    from applypilot import role_resumes

    base_pdf = tmp_path / "resume.pdf"
    base_pdf.write_bytes(b"%PDF-1.4\n")
    monkeypatch.setattr(config, "RESUME_PDF_PATH", base_pdf)

    role_dir = tmp_path / "role_resumes"
    role_dir.mkdir()
    pdf = role_dir / "frontend-developer.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    txt = role_dir / "resume.txt"
    txt.write_text("Unrelated skills only.", encoding="utf-8")
    (role_dir / "manifest.json").write_text(
        json.dumps(
            {
                "roles": [
                    {
                        "key": "frontend-developer",
                        "title": "Frontend Developer",
                        "aliases": ["frontend engineer"],
                        "keywords": ["react"],
                        "pdf_path": str(pdf),
                        "txt_path": str(txt),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    job = {
        "title": "Senior React Frontend Engineer",
        "full_description": "React TypeScript UI frontend components performance.",
    }
    resolution = role_resumes.resolve_job_resume(job, allow_base=True, output_dir=role_dir)
    assert resolution.source == "base"
    assert resolution.path == str(base_pdf)


def test_acquire_job_uses_role_resume_for_high_fit_untailored_job(tmp_path: Path, monkeypatch):
    from applypilot import config, database
    from applypilot.apply import launcher

    db_path = tmp_path / "applypilot.db"
    role_dir = tmp_path / "role_resumes"
    role_dir.mkdir()
    frontend_pdf = role_dir / "frontend-developer.pdf"
    frontend_pdf.write_bytes(b"%PDF-1.4\n")
    frontend_txt = role_dir / "resume.txt"
    frontend_txt.write_text(
        "React TypeScript UI components frontend performance CSS webpack",
        encoding="utf-8",
    )
    (role_dir / "manifest.json").write_text(
        json.dumps(
            {
                "roles": [
                    {
                        "key": "frontend-developer",
                        "title": "Frontend Developer",
                        "aliases": ["frontend engineer", "react engineer"],
                        "keywords": ["react", "typescript", "ui"],
                        "pdf_path": str(frontend_pdf),
                        "txt_path": str(frontend_txt),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    def fake_ensure_resume_pdf(path: str | Path) -> Path:
        pdf = Path(path)
        if pdf.suffix.lower() != ".pdf":
            pdf = pdf.with_suffix(".pdf")
        pdf.parent.mkdir(parents=True, exist_ok=True)
        if not pdf.exists():
            pdf.write_bytes(b"%PDF-1.4\n")
        return pdf.resolve()

    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "DB_PATH", db_path)
    monkeypatch.setattr(config, "ROLE_RESUME_DIR", role_dir)
    monkeypatch.setattr(database, "DB_PATH", db_path)
    monkeypatch.setattr(launcher, "_load_blocked", lambda: (set(), []))
    monkeypatch.setattr(launcher, "role_resumes_available", lambda: True)
    monkeypatch.setattr(launcher.prompt_mod, "ensure_resume_pdf", fake_ensure_resume_pdf)
    monkeypatch.setattr(config, "load_profile", lambda: {})
    database.close_connection(db_path)
    conn = database.init_db(db_path)
    conn.execute(
        """
        INSERT INTO jobs (
            url, title, site, application_url, tailored_resume_path,
            fit_score, full_description, salary, apply_status, apply_attempts
        )
        VALUES (
            'https://jobs.example/frontend', 'Senior React Frontend Engineer',
            'Example', 'https://jobs.example/frontend/apply', NULL,
            8, 'Build React, TypeScript, and UI components.', '$150K', NULL, 0
        )
        """
    )
    conn.commit()

    job = launcher.acquire_job(min_score=7, worker_id=0)

    assert job is not None
    assert job["tailored_resume_path"] == str(frontend_pdf)
    row = conn.execute(
        "SELECT apply_status FROM jobs WHERE url = 'https://jobs.example/frontend'"
    ).fetchone()
    assert row["apply_status"] == "in_progress"
    database.close_connection(db_path)


def test_role_catalog_includes_ui_architect_and_stack_roles():
    from applypilot import role_resumes

    keys = {spec.key for spec in role_resumes.ROLE_CATALOG}
    assert "ui-architect" in keys
    assert "backend-engineer" in keys
    assert "platform-engineer" in keys
    assert "software-architect" in keys
    assert "cloud-architect" in keys
    assert "principal-engineer" in keys
    assert "tech-lead" in keys
    assert "product-engineer" in keys
    assert len(keys) >= 16


def test_catalog_keys_for_target_phrase_maps_ui_architect():
    from applypilot import role_resumes

    assert role_resumes._catalog_keys_for_target_phrase("UI Architect") == ["ui-architect"]
    assert role_resumes._catalog_keys_for_target_phrase("Cloud Architect") == ["cloud-architect"]
    assert "solutions-architect" in role_resumes._catalog_keys_for_target_phrase(
        "Solutions Architect"
    )


def test_infer_applicable_roles_includes_declared_and_resume_evidence():
    from applypilot import role_resumes

    profile = _profile()
    profile["experience"]["target_roles"] = [
        "UI Architect",
        "Staff Engineer",
        "AI Engineer",
    ]
    keys = {spec.key for spec in role_resumes.infer_applicable_roles(profile, _master_resume())}
    assert "ui-architect" in keys
    assert "staff-engineer" in keys
    assert "ai-engineer" in keys
    assert "senior-full-stack-engineer" in keys
    assert "frontend-developer" in keys


def test_discovery_search_query_entries_cover_role_catalog():
    from applypilot import role_resumes

    entries = role_resumes.discovery_search_query_entries(_profile())
    query_texts = {e["query"] for e in entries}
    for spec in role_resumes.ROLE_CATALOG:
        assert spec.title in query_texts
    assert "UI Architect" in query_texts or any(
        "ui architect" in q.lower() for q in query_texts
    )


def test_load_search_config_merges_role_catalog_queries(monkeypatch, tmp_path: Path):
    import yaml

    from applypilot import config
    from applypilot import role_resumes

    search_path = tmp_path / "searches.yaml"
    search_path.write_text(
        yaml.safe_dump(
            {
                "role_catalog_queries": True,
                "queries": [{"query": "Custom Niche Role", "tier": 1}],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "SEARCH_CONFIG_PATH", search_path)
    monkeypatch.setattr(config, "load_profile", _profile)

    cfg = config.load_search_config()
    queries = [str(q["query"]) for q in cfg["queries"]]
    assert "Custom Niche Role" in queries
    assert "AI Engineer" in queries
    assert len(queries) >= len(role_resumes.ROLE_CATALOG)
    assert cfg.get("include_titles")
    assert any("architect" in t for t in cfg["include_titles"])


def test_load_search_config_can_disable_role_catalog_merge(monkeypatch, tmp_path: Path):
    import yaml

    from applypilot import config

    search_path = tmp_path / "searches.yaml"
    search_path.write_text(
        yaml.safe_dump(
            {
                "role_catalog_queries": False,
                "queries": [{"query": "Only This Role", "tier": 1}],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "SEARCH_CONFIG_PATH", search_path)

    cfg = config.load_search_config()
    assert [q["query"] for q in cfg["queries"]] == ["Only This Role"]
