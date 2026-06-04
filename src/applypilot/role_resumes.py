"""JD-driven role-specific resume variants used before discovery and during apply."""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from bs4 import BeautifulSoup

from applypilot import config
from applypilot.scoring.keyword_extractor import keyword_overlap_ratio

log = logging.getLogger(__name__)

MANIFEST_NAME = "manifest.json"
MIN_BENCHMARK_USD = 80_000
MIN_BENCHMARK_JD_CHARS = 400
_RELATED_BENCHMARK_ROLE_KEY: dict[str, str] = {
    "ui-architect": "frontend-developer",
}
AUDIT_PASS_SCORE = 85
MAX_GEMINI_ITERATIONS = 2
USD_TO_INR = 83.0
FORBIDDEN_PUBLIC_PHRASES = (
    "targeted for",
    "jd alignment",
    "while preserving only verified resume facts",
    "no eligible live benchmark",
    "high-paying ",
    "fallback benchmark",
    "research_only",
    "benchmark_job",
    "master_resume",
    "role_resume",
)
_GENERIC_SKILL_TOKENS = {
    "architecture",
    "architectures",
    "cloud",
    "customer",
    "data",
    "delivery",
    "engineering",
    "implementation",
    "leadership",
    "planning",
    "product",
    "production",
    "strategy",
    "support",
    "system",
    "systems",
    "technical",
}
_UNSUPPORTED_TRANSITION_PHRASES = (
    "technical discovery",
    "customer-facing",
    "customer engineering",
    "stakeholder communication",
    "rapid prototyping",
    "onsite",
)
_AI_LED_MARKERS = (
    "rag",
    "llm",
    "langgraph",
    "langchain",
    "embedding",
    "pgvector",
    "pinecone",
    "multi-agent",
    "agentic",
    "lora",
    "qlora",
    "llama",
    "fine-tuning",
    "fine tuning",
    "gpt-4",
    "gpt-4o",
    "tool-calling",
    "hallucination",
    "llmops",
    "vector store",
    "semantic rerank",
    "llm-as-judge",
    "golden dataset",
    "generative ai",
    "langchain for",
    "agentic",
    "inference-as-judge",
    "golden dataset",
    "prompt versioning",
    "tool-use",
    "tool use",
    "vector store",
)
_AI_SKILL_CATEGORY_HINTS = ("ai", "llm", "ml ", "rag", "genai", "generative")
_SHARED_NON_AI_BULLET_REFRAMES: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r"Implementing a streaming inference layer \(Server-Sent Events \+ Node\.js\) over the Anthropic Claude API",
            re.I,
        ),
        "Implementing a streaming API layer (Server-Sent Events + Node.js) for high-volume product responses",
    ),
    (
        re.compile(r"^Building a multi-agent orchestration layer across Node.js services", re.I),
        "Building workflow orchestration with validation steps across Node.js services",
    ),
    (
        re.compile(r"^Architecting an end-to-end RAG pipeline", re.I),
        "Architecting an end-to-end search and content-delivery pipeline",
    ),
    (
        re.compile(
            r"^Built and scaled backend services powering generative AI features",
            re.I,
        ),
        "Built and scaled backend services powering high-scale product features",
    ),
    (
        re.compile(r"^Designing prompt engineering architecture", re.I),
        "Designing API and workflow configuration for production services",
    ),
    (
        re.compile(r"^Built an evaluation framework for LLM output quality", re.I),
        "Built an evaluation framework for production output quality",
    ),
    (
        re.compile(r"^Engineered a fine-tuning pipeline", re.I),
        "Engineered a personalization and training pipeline",
    ),
    (
        re.compile(r"^Owning the LLMOps stack", re.I),
        "Owning the production platform operations stack",
    ),
    (
        re.compile(
            r"Reduced LLM inference costs by 35%",
            re.I,
        ),
        "Reduced inference and API costs by 35%",
    ),
    (
        re.compile(r"catch prompt-drift before deployment", re.I),
        "catch deployment regressions before release",
    ),
    (re.compile(r"production RAG system", re.I), "production search and content system"),
    (re.compile(r"using Pinecone, LangChain", re.I), "using vector search and service orchestration"),
    (re.compile(r"tool-calling agents", re.I), "integration services"),
    (re.compile(r"agentic workflows", re.I), "multi-step workflows"),
    (re.compile(r"\bplanner agent\b", re.I), "planning service"),
    (re.compile(r"\bcritic agent\b", re.I), "review service"),
    (re.compile(r"\bintegration agents\b", re.I), "integration services"),
    (re.compile(r"token-budget", re.I), "request budget"),
    (re.compile(r"context-window", re.I), "payload limit"),
    (re.compile(r"hallucination-rate", re.I), "quality regression rate"),
    (re.compile(r"automated evals pipeline", re.I), "automated quality checks"),
    (re.compile(r"(?<!content )retrieval store", re.I), "indexed content store"),
)
_ROLE_LEADING_REFRAMES: dict[str, tuple[tuple[re.Pattern[str], str], ...]] = {
    "frontend-developer": (
        (
            re.compile(
                r"^Building a multi-agent orchestration layer across Node.js services",
                re.I,
            ),
            "Building product workflow orchestration with planner and validation steps across Node.js services",
        ),
        (
            re.compile(r"^Architecting an end-to-end RAG pipeline", re.I),
            "Architecting an end-to-end search and content-delivery pipeline",
        ),
        (
            re.compile(
                r"^Built and scaled backend services powering generative AI features",
                re.I,
            ),
            "Built and scaled backend services powering product features",
        ),
        (
            re.compile(r"^Built an evaluation framework for LLM output quality", re.I),
            "Built an evaluation framework for model output quality",
        ),
        (
            re.compile(r"^Engineered a fine-tuning pipeline", re.I),
            "Engineered a personalization pipeline",
        ),
        (
            re.compile(r"^Owning the LLMOps stack", re.I),
            "Owning the production platform operations stack",
        ),
        (re.compile(r"production RAG system", re.I), "production search and content system"),
        (re.compile(r"using Pinecone, LangChain", re.I), "using Pinecone and LangChain orchestration"),
    ),
    "solutions-architect": (
        (
            re.compile(r"^Building a multi-agent orchestration layer across Node.js services", re.I),
            "Building integration orchestration with planner and validation steps across Node.js services",
        ),
        (
            re.compile(r"^Architecting an end-to-end RAG pipeline", re.I),
            "Architecting an end-to-end retrieval and integration pipeline",
        ),
        (
            re.compile(
                r"^Built and scaled backend services powering generative AI features",
                re.I,
            ),
            "Built and scaled platform services powering high-scale product features",
        ),
    ),
    "senior-full-stack-engineer": (),
    "forward-deployed-engineer": (
        (
            re.compile(r"^Architecting an end-to-end RAG pipeline", re.I),
            "Architecting an end-to-end customer-facing retrieval pipeline",
        ),
    ),
    "founding-engineer": (
        (
            re.compile(r"^Architecting an end-to-end RAG pipeline", re.I),
            "Architecting an end-to-end product retrieval pipeline",
        ),
    ),
    "staff-engineer": (
        (
            re.compile(r"^Building a multi-agent orchestration layer across Node.js services", re.I),
            "Building platform workflow orchestration with planner and validation steps across Node.js services",
        ),
        (
            re.compile(r"^Architecting an end-to-end RAG pipeline", re.I),
            "Architecting an end-to-end platform retrieval pipeline",
        ),
    ),
    "engineering-manager": (
        (
            re.compile(r"^Architecting an end-to-end RAG pipeline", re.I),
            "Architecting an end-to-end platform retrieval pipeline",
        ),
    ),
    "ui-architect": (
        (
            re.compile(r"^Building a multi-agent orchestration layer across Node.js services", re.I),
            "Building product workflow orchestration with planner and validation steps across Node.js services",
        ),
        (
            re.compile(r"^Architecting an end-to-end RAG pipeline", re.I),
            "Architecting an end-to-end information architecture and content-delivery pipeline",
        ),
        (re.compile(r"production RAG system", re.I), "production content and discovery system"),
    ),
    "backend-engineer": (),
    "platform-engineer": (
        (
            re.compile(r"^Owning the LLMOps stack", re.I),
            "Owning the production platform and reliability stack",
        ),
    ),
    "software-architect": (
        (
            re.compile(r"^Architecting an end-to-end RAG pipeline", re.I),
            "Architecting an end-to-end application and integration architecture",
        ),
    ),
    "cloud-architect": (),
    "principal-engineer": (
        (
            re.compile(r"^Building a multi-agent orchestration layer across Node.js services", re.I),
            "Building cross-team platform workflow orchestration across Node.js services",
        ),
    ),
    "tech-lead": (
        (
            re.compile(r"^Architecting an end-to-end RAG pipeline", re.I),
            "Architecting an end-to-end platform delivery pipeline",
        ),
    ),
    "product-engineer": (
        (
            re.compile(r"^Architecting an end-to-end RAG pipeline", re.I),
            "Architecting an end-to-end product delivery pipeline",
        ),
    ),
}

# Profile target_roles phrases → catalog keys (longer phrases first).
_TARGET_PHRASE_TO_KEY: tuple[tuple[str, str], ...] = (
    ("forward deployed engineer", "forward-deployed-engineer"),
    ("forward-deployed engineer", "forward-deployed-engineer"),
    ("senior full stack engineer", "senior-full-stack-engineer"),
    ("full stack engineer", "senior-full-stack-engineer"),
    ("full stack developer", "senior-full-stack-engineer"),
    ("design systems architect", "ui-architect"),
    ("software architect", "software-architect"),
    ("solutions architect", "solutions-architect"),
    ("solution architect", "solutions-architect"),
    ("cloud architect", "cloud-architect"),
    ("ui architect", "ui-architect"),
    ("ux architect", "ui-architect"),
    ("principal engineer", "principal-engineer"),
    ("distinguished engineer", "principal-engineer"),
    ("staff engineer", "staff-engineer"),
    ("engineering manager", "engineering-manager"),
    ("head of engineering", "engineering-manager"),
    ("vp engineering", "engineering-manager"),
    ("founding engineer", "founding-engineer"),
    ("platform engineer", "platform-engineer"),
    ("backend engineer", "backend-engineer"),
    ("machine learning engineer", "ai-engineer"),
    ("ml engineer", "ai-engineer"),
    ("llm engineer", "ai-engineer"),
    ("ai engineer", "ai-engineer"),
    ("frontend engineer", "frontend-developer"),
    ("frontend developer", "frontend-developer"),
    ("react developer", "frontend-developer"),
    ("technical lead", "tech-lead"),
    ("tech lead", "tech-lead"),
    ("product engineer", "product-engineer"),
    ("deployed engineer", "forward-deployed-engineer"),
    ("cto", "engineering-manager"),
)
_REMOTEOK_CACHE: list[dict[str, Any]] | None = None
_REMOTIVE_CACHE: list[dict[str, Any]] | None = None
_JOBICY_CACHE: list[dict[str, Any]] | None = None


@dataclass(frozen=True)
class RoleResumeSpec:
    key: str
    title: str
    aliases: tuple[str, ...]
    keywords: tuple[str, ...]
    summary: str
    skills: tuple[tuple[str, str], ...]


@dataclass
class BenchmarkJob:
    source: str
    url: str
    title: str
    company: str
    salary: str
    salary_usd_max: int
    location: str
    description: str
    eligibility_reason: str


@dataclass(frozen=True)
class ExperienceBlock:
    title_line: str
    company: str
    bullets: tuple[str, ...]


ROLE_CATALOG: tuple[RoleResumeSpec, ...] = (
    RoleResumeSpec(
        key="ai-engineer",
        title="AI Engineer",
        aliases=("ai engineer", "machine learning engineer", "ml engineer", "llm engineer"),
        keywords=("rag", "llm", "langchain", "langgraph", "openai", "claude", "embedding", "vector", "eval"),
        summary=(
            "Senior AI engineer with 10+ years building high-scale products and recent production work across "
            "RAG, agentic workflows, LLMOps, streaming inference, and model cost control."
        ),
        skills=(
            ("AI / LLM Engineering", "RAG, LangChain, LangGraph, OpenAI API, Anthropic Claude, pgvector, Pinecone, LLM evals, prompt engineering"),
            ("Backend", "Python, Node.js, TypeScript, REST, GraphQL, Redis, PostgreSQL"),
            ("Cloud", "AWS, Docker, Kubernetes, CI/CD, CloudWatch"),
            ("Frontend", "React, Next.js, WebSockets, performance optimization"),
        ),
    ),
    RoleResumeSpec(
        key="frontend-developer",
        title="Frontend Developer",
        aliases=("frontend developer", "front end developer", "frontend engineer", "react developer", "react engineer"),
        keywords=("react", "next.js", "typescript", "javascript", "ui", "component", "frontend", "websocket", "performance"),
        summary=(
            "Senior frontend-focused engineer with 10+ years shipping React, TypeScript, and real-time web "
            "products, including component libraries, performance improvements, and high-scale product UX."
        ),
        skills=(
            ("Frontend", "React, Next.js, TypeScript, JavaScript, component libraries, state management, WebSockets, performance optimization"),
            ("Backend", "Node.js, Python, REST, GraphQL, PostgreSQL, Redis"),
            ("Product Engineering", "A/B-oriented delivery, conversion improvements, accessibility-minded UI, monitoring"),
            ("Cloud", "AWS, Docker, CI/CD"),
        ),
    ),
    RoleResumeSpec(
        key="ui-architect",
        title="UI Architect",
        aliases=("ui architect", "ux architect", "design systems architect", "frontend architect", "web architect"),
        keywords=("design system", "ui architecture", "ux", "information architecture", "react", "typescript", "component", "accessibility", "figma"),
        summary=(
            "UI architect and senior frontend leader with 10+ years shaping design systems, React/TypeScript "
            "platforms, real-time product UX, and measurable interface performance at scale."
        ),
        skills=(
            ("UI Architecture", "Design systems, component libraries, information architecture, UX patterns, accessibility, design tokens"),
            ("Frontend Engineering", "React, Next.js, TypeScript, JavaScript, WebSockets, performance optimization, conversion-focused UX"),
            ("Collaboration", "Engineering partnership, design-to-code standards, cross-functional product delivery"),
            ("Platform", "Node.js, Python, AWS, CI/CD, monitoring"),
        ),
    ),
    RoleResumeSpec(
        key="senior-full-stack-engineer",
        title="Senior Full Stack Engineer",
        aliases=("senior full stack engineer", "full stack engineer", "software engineer", "senior software engineer"),
        keywords=("full stack", "react", "node", "python", "typescript", "aws", "distributed", "backend", "frontend"),
        summary=(
            "Senior full stack engineer with 10+ years building AI, fintech, and SaaS systems across React, "
            "Node.js, Python, TypeScript, AWS, distributed systems, and production monitoring."
        ),
        skills=(
            ("Languages & Frameworks", "TypeScript, JavaScript, Python, Node.js, React, Next.js, Django, Flask, REST, GraphQL"),
            ("Infrastructure", "AWS, Docker, Kubernetes, CI/CD, Terraform"),
            ("Data", "PostgreSQL, Redis, MongoDB, Elasticsearch, Kafka, RabbitMQ"),
            ("AI", "RAG, LangChain, LangGraph, OpenAI, Claude, LLMOps"),
        ),
    ),
    RoleResumeSpec(
        key="backend-engineer",
        title="Backend Engineer",
        aliases=("backend engineer", "backend developer", "senior backend engineer", "server engineer"),
        keywords=("backend", "python", "node", "api", "microservices", "postgresql", "redis", "kafka", "distributed", "rest"),
        summary=(
            "Senior backend engineer with 10+ years building Python and Node.js services, APIs, data pipelines, "
            "distributed systems, and production platforms on AWS."
        ),
        skills=(
            ("Backend", "Python, Node.js, TypeScript, REST, GraphQL, microservices, event-driven systems"),
            ("Data", "PostgreSQL, Redis, MongoDB, Elasticsearch, Kafka, RabbitMQ"),
            ("Cloud", "AWS, Docker, Kubernetes, CI/CD, Terraform, observability"),
            ("Reliability", "Production monitoring, caching, rate limiting, autoscaling, incident response"),
        ),
    ),
    RoleResumeSpec(
        key="platform-engineer",
        title="Platform Engineer",
        aliases=("platform engineer", "infrastructure engineer", "devops engineer", "site reliability engineer", "sre"),
        keywords=("platform", "kubernetes", "docker", "ci/cd", "terraform", "observability", "reliability", "aws", "infrastructure"),
        summary=(
            "Platform engineer with 10+ years improving reliability, deployment velocity, observability, and "
            "cloud-native operations for high-scale SaaS products."
        ),
        skills=(
            ("Platform", "Kubernetes, Docker, CI/CD, Terraform, release engineering, SLOs, incident response"),
            ("Cloud", "AWS, networking, autoscaling, CloudWatch, cost optimization"),
            ("Backend", "Python, Node.js, PostgreSQL, Redis, Kafka, distributed systems"),
            ("Operations", "Latency dashboards, deployment gates, capacity planning, on-call runbooks"),
        ),
    ),
    RoleResumeSpec(
        key="product-engineer",
        title="Product Engineer",
        aliases=("product engineer", "product software engineer", "full stack product engineer"),
        keywords=("product", "full stack", "react", "node", "python", "ownership", "shipping", "conversion", "experimentation"),
        summary=(
            "Product engineer with 10+ years owning end-to-end delivery across React, Node.js, Python, AWS, and "
            "measurable product outcomes including conversion and performance."
        ),
        skills=(
            ("Product Delivery", "Roadmap execution, experimentation, conversion optimization, stakeholder alignment"),
            ("Full Stack", "React, Next.js, Node.js, Python, TypeScript, REST, GraphQL"),
            ("Data & Cloud", "PostgreSQL, Redis, AWS, Docker, CI/CD"),
            ("Delivery Quality", "Feature flags, production monitoring, regression gates, performance tuning"),
        ),
    ),
    RoleResumeSpec(
        key="solutions-architect",
        title="Solutions Architect",
        aliases=("solutions architect", "solution architect", "customer engineer", "sales engineer"),
        keywords=("solution", "architect", "customer", "stakeholder", "aws", "integration", "system design", "api", "technical discovery"),
        summary=(
            "Hands-on solutions architect and senior engineer with 10+ years designing scalable SaaS, "
            "fintech, cloud, and integration architectures."
        ),
        skills=(
            ("Architecture", "System design, distributed systems, API design, integration architecture, scalability, reliability"),
            ("Cloud & Data", "AWS, Docker, Kubernetes, PostgreSQL, Redis, Kafka, Elasticsearch"),
            ("Integrations", "Third-party APIs, event-driven workflows, security boundaries, migration planning"),
            ("Delivery", "Stakeholder alignment, technical discovery, implementation planning, production support"),
        ),
    ),
    RoleResumeSpec(
        key="software-architect",
        title="Software Architect",
        aliases=("software architect", "application architect", "technical architect", "enterprise architect"),
        keywords=("software architect", "architecture", "system design", "integration", "microservices", "api", "scalability", "reliability"),
        summary=(
            "Software architect with 10+ years designing scalable application architectures, API platforms, "
            "and integration boundaries for production systems."
        ),
        skills=(
            ("Architecture", "Application architecture, system design, API design, integration patterns, scalability, reliability"),
            ("Engineering", "React, Node.js, Python, TypeScript, distributed systems, data platforms"),
            ("Cloud", "AWS, Docker, Kubernetes, CI/CD, observability"),
            ("Platform Quality", "Reliability patterns, performance budgets, security boundaries, technical standards"),
        ),
    ),
    RoleResumeSpec(
        key="cloud-architect",
        title="Cloud Architect",
        aliases=(
            "cloud architect",
            "aws architect",
            "cloud solutions architect",
            "infrastructure architect",
            "solutions architect",
            "solution architect",
        ),
        keywords=(
            "cloud",
            "aws",
            "gcp",
            "google cloud",
            "kubernetes",
            "terraform",
            "networking",
            "security",
            "scalability",
            "architecture",
            "migration",
        ),
        summary=(
            "Cloud architect with 10+ years designing AWS-native platforms, migration paths, reliability patterns, "
            "and cost-aware infrastructure for SaaS workloads."
        ),
        skills=(
            ("Cloud Architecture", "AWS, VPC design, IAM, autoscaling, multi-region patterns, networking, scalability, cost optimization"),
            ("Platform", "Kubernetes, Docker, Terraform, CI/CD, observability, disaster recovery"),
            ("Applications", "Microservices, APIs, event streaming, PostgreSQL, Redis, Kafka"),
            ("Operations", "Capacity planning, disaster recovery drills, cost governance, security baselines"),
        ),
    ),
    RoleResumeSpec(
        key="forward-deployed-engineer",
        title="Forward Deployed Engineer",
        aliases=("forward deployed engineer", "deployed engineer", "fde", "field engineer"),
        keywords=("deployed", "customer", "implementation", "prototype", "integration", "onsite", "stakeholder", "api", "automation"),
        summary=(
            "Forward deployed engineer profile combining senior full stack execution, API integrations, "
            "AI workflow implementation, and production ownership."
        ),
        skills=(
            ("Customer Engineering", "Technical discovery, implementation, integrations, stakeholder communication, rapid prototyping"),
            ("Full Stack", "React, Node.js, Python, TypeScript, REST, GraphQL"),
            ("AI / Automation", "RAG, LangChain, LangGraph, tool-calling agents, OpenAI, Claude"),
            ("Cloud", "AWS, Docker, CI/CD, PostgreSQL, Redis"),
        ),
    ),
    RoleResumeSpec(
        key="founding-engineer",
        title="Founding Engineer",
        aliases=("founding engineer", "founding software engineer", "early engineer", "startup engineer"),
        keywords=("founding", "startup", "0 to 1", "full stack", "product", "ownership", "architecture", "shipping"),
        summary=(
            "Founding engineer profile with 10+ years building and scaling full-stack, AI, fintech, and SaaS "
            "products from architecture through production ownership."
        ),
        skills=(
            ("0-to-1 Product Engineering", "Product ownership, rapid iteration, architecture, full stack delivery, production monitoring"),
            ("Stack", "React, Next.js, Node.js, Python, TypeScript, AWS"),
            ("AI", "RAG, LangChain, LangGraph, OpenAI, Claude, LLMOps"),
            ("Systems", "Distributed systems, performance, databases, messaging, CI/CD"),
        ),
    ),
    RoleResumeSpec(
        key="staff-engineer",
        title="Staff Engineer",
        aliases=("staff engineer", "staff software engineer", "senior staff engineer"),
        keywords=("staff", "architecture", "distributed", "system design", "mentoring", "technical strategy", "platform"),
        summary=(
            "Staff-level engineer and technical lead with 10+ years designing distributed systems, leading technical "
            "direction, reducing latency, and shipping measurable product outcomes."
        ),
        skills=(
            ("Technical Leadership", "Architecture, system design, technical strategy, code review, mentoring, execution planning"),
            ("Systems", "Distributed systems, high-concurrency systems, performance profiling, reliability"),
            ("Stack", "React, Node.js, Python, TypeScript, AWS, PostgreSQL, Redis, Kafka"),
            ("AI", "RAG, LangChain, LangGraph, OpenAI, Claude, LLMOps"),
        ),
    ),
    RoleResumeSpec(
        key="principal-engineer",
        title="Principal Engineer",
        aliases=("principal engineer", "principal software engineer", "distinguished engineer", "fellow engineer"),
        keywords=("principal", "distinguished", "architecture", "technical strategy", "system design", "cross-team", "mentoring", "platform"),
        summary=(
            "Principal engineer with 10+ years setting technical direction across distributed systems, platform "
            "architecture, AI-enabled products, and measurable engineering outcomes."
        ),
        skills=(
            ("Principal IC", "Technical strategy, architecture review, cross-team alignment, execution planning, mentorship"),
            ("Systems", "Distributed systems, performance, reliability, observability, API platforms"),
            ("Stack", "React, Node.js, Python, TypeScript, AWS, PostgreSQL, Redis, Kafka"),
            ("AI", "RAG, LangChain, LangGraph, OpenAI, Claude, LLMOps"),
        ),
    ),
    RoleResumeSpec(
        key="tech-lead",
        title="Tech Lead",
        aliases=("tech lead", "technical lead", "engineering lead", "lead engineer", "team lead engineer"),
        keywords=("tech lead", "technical lead", "leadership", "mentoring", "architecture", "delivery", "code review", "roadmap"),
        summary=(
            "Technical lead with 10+ years leading delivery teams, mentoring engineers, driving architecture decisions, "
            "and shipping React, Node.js, Python, and AWS platforms."
        ),
        skills=(
            ("Technical Leadership", "Team delivery, mentoring, code review, technical planning, cross-functional execution"),
            ("Engineering", "React, Node.js, Python, TypeScript, REST, GraphQL, distributed systems"),
            ("Platform Quality", "Technical debt reduction, performance, reliability, CI/CD"),
            ("AI Delivery", "RAG, LangChain, LangGraph, production monitoring"),
        ),
    ),
    RoleResumeSpec(
        key="engineering-manager",
        title="Engineering Manager",
        aliases=("engineering manager", "vp engineering", "head of engineering", "cto", "engineering lead"),
        keywords=("engineering manager", "manager", "vp engineering", "cto", "leadership", "team", "roadmap", "delivery", "technical debt"),
        summary=(
            "Engineering leadership profile with 10+ years of hands-on software delivery, tech lead experience, "
            "technical debt reduction, system modernization, and cross-functional product execution."
        ),
        skills=(
            ("Engineering Leadership", "Technical planning, delivery ownership, code review, mentoring, roadmap execution, technical debt reduction"),
            ("Architecture", "Distributed systems, platform modernization, reliability, performance, API design"),
            ("Stack Fluency", "React, Node.js, Python, TypeScript, AWS, PostgreSQL, Redis, Kafka"),
            ("AI Product Delivery", "RAG, agentic workflows, LLMOps, evals, cost dashboards"),
        ),
    ),
)

# Title substrings that signal a role family when the posting title omits the catalog phrase.
_ROLE_TITLE_MARKERS: dict[str, tuple[str, ...]] = {
    "ai-engineer": (
        "ai engineer",
        "machine learning engineer",
        "ml engineer",
        "llm engineer",
        "applied ai",
        "generative ai",
    ),
    "frontend-developer": (
        "frontend",
        "front end",
        "front-end",
        "react developer",
        "react engineer",
        "ui engineer",
    ),
    "ui-architect": (
        "ui architect",
        "ux architect",
        "design system",
        "design engineer",
        "frontend architect",
        "frontend engineer",
        "web architect",
    ),
    "senior-full-stack-engineer": (
        "full stack",
        "fullstack",
        "full-stack",
    ),
    "backend-engineer": (
        "backend",
        "server engineer",
        "api engineer",
    ),
    "platform-engineer": (
        "platform engineer",
        "platform",
        "infrastructure",
        "devops",
        "site reliability",
        "sre",
        "core infrastructure",
    ),
    "product-engineer": (
        "product engineer",
    ),
    "solutions-architect": (
        "solutions architect",
        "solution architect",
        "customer engineer",
        "sales engineer",
    ),
    "software-architect": (
        "software architect",
        "application architect",
        "technical architect",
        "enterprise architect",
    ),
    "cloud-architect": (
        "cloud architect",
        "cloud solutions architect",
        "aws architect",
        "infrastructure architect",
        "core infrastructure",
        "cloud infrastructure",
        "google cloud",
    ),
    "forward-deployed-engineer": (
        "forward deployed",
        "deployed engineer",
        "field engineer",
        "customer engineer",
    ),
    "founding-engineer": (
        "founding engineer",
        "founding software",
        "early engineer",
    ),
    "staff-engineer": (
        "staff engineer",
        "staff software",
        "senior staff",
    ),
    "principal-engineer": (
        "principal engineer",
        "principal software",
        "distinguished engineer",
    ),
    "tech-lead": (
        "tech lead",
        "technical lead",
        "engineering lead",
        "lead engineer",
    ),
    "engineering-manager": (
        "engineering manager",
        "head of engineering",
        "vp engineering",
        "director of engineering",
    ),
}

_SALARY_USD_SANITY_MAX = 1_500_000


COMPANY_PROBLEM_FACTS = (
    {
        "company": "Happening Today",
        "domain": "event discovery and AI platform",
        "problems": [
            "retrieval quality and latency for event discovery",
            "agentic workflow reliability",
            "streaming inference, token budgets, and hallucination controls",
        ],
        "evidence": [
            "RAG pipeline for event discovery with pgvector and semantic reranking",
            "LangGraph planner/tool/critic orchestration",
            "LLMOps evals, latency/cost dashboards, and hallucination alerts",
        ],
    },
    {
        "company": "MIRA",
        "domain": "consumer-scale generative AI",
        "problems": [
            "serving GenAI to large user bases",
            "personalization and fine-tuning quality",
            "inference cost control and regression evaluation",
        ],
        "evidence": [
            "GenAI features for 50M+ users",
            "LoRA/QLoRA fine-tuning pipeline",
            "35% cost reduction through compression, caching, and model routing",
        ],
    },
    {
        "company": "Delta Exchange",
        "domain": "real-time fintech and trading",
        "problems": [
            "low-latency trading workflows",
            "real-time UI reliability",
            "technical debt and conversion improvements",
        ],
        "evidence": [
            "real-time derivatives platform serving 5M+ users",
            "60% system performance improvement",
            "React component library and 25% conversion lift",
        ],
    },
    {
        "company": "BetterPlace",
        "domain": "enterprise workforce SaaS",
        "problems": [
            "large-scale data ingestion",
            "enterprise workflow scalability",
            "frontend performance and microservice migration",
        ],
        "evidence": [
            "3x ingestion throughput improvement",
            "50% UI render time reduction",
            "monolith-to-microservices migration",
        ],
    },
)


def role_resume_dir() -> Path:
    return Path(config.ROLE_RESUME_DIR)


def manifest_path(output_dir: Path | None = None) -> Path:
    return Path(output_dir or role_resume_dir()) / MANIFEST_NAME


def _norm(text: str | None) -> str:
    return re.sub(r"[^a-z0-9+#.]+", " ", (text or "").lower()).strip()


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "resume"


def _strip_html(text: str | None) -> str:
    if not text:
        return ""
    return BeautifulSoup(text, "html.parser").get_text("\n", strip=True)


def _extract_json(text: str) -> dict[str, Any] | None:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, flags=re.S)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None


def _section(text: str, name: str, stop_names: tuple[str, ...]) -> str:
    start = re.search(rf"(?m)^{re.escape(name)}\s*$", text, flags=re.IGNORECASE)
    if not start:
        return ""
    body_start = start.end()
    stop_pattern = "|".join(re.escape(s) for s in stop_names)
    stop = re.search(rf"(?m)^({stop_pattern})\s*$", text[body_start:], flags=re.IGNORECASE)
    body_end = body_start + stop.start() if stop else len(text)
    return text[body_start:body_end].strip()


def _company_name(line: str) -> str:
    """Normalize a resume company line by removing common location suffixes."""
    company = re.split(r"\s+[·•]\s+|\s+-\s+", line.strip(), maxsplit=1)[0].strip()
    return company or line.strip()


def extract_experience_blocks(master_resume: str) -> list[ExperienceBlock]:
    """Extract source title/company/bullet blocks from the master resume."""
    experience = _section(master_resume, "EXPERIENCE", ("SKILLS", "EDUCATION", "PROJECTS"))
    if not experience:
        experience = _section(master_resume, "WORK EXPERIENCE", ("SKILLS", "EDUCATION", "PROJECTS"))
    lines = [line.strip() for line in experience.splitlines() if line.strip()]
    blocks: list[ExperienceBlock] = []
    idx = 0
    while idx < len(lines) - 1:
        line = lines[idx]
        if line.startswith(("•", "-")):
            idx += 1
            continue
        next_line = lines[idx + 1]
        if next_line.startswith(("•", "-")):
            idx += 1
            continue
        has_date_or_title = (
            "|" in line
            or re.search(r"\b(19|20)\d{2}\b", line)
            or re.search(r"\b(engineer|lead|manager|architect|developer)\b", line, flags=re.I)
        )
        following_is_bullet = idx + 2 < len(lines) and lines[idx + 2].startswith(("•", "-"))
        company = _company_name(next_line)
        if not (has_date_or_title and following_is_bullet):
            idx += 1
            continue
        bullets: list[str] = []
        cursor = idx + 2
        while cursor < len(lines):
            candidate = lines[cursor]
            next_candidate = lines[cursor + 1] if cursor + 1 < len(lines) else ""
            starts_next_block = (
                not candidate.startswith(("•", "-"))
                and next_candidate
                and not next_candidate.startswith(("•", "-"))
                and (
                    "|" in candidate
                    or re.search(r"\b(19|20)\d{2}\b", candidate)
                    or re.search(
                        r"\b(engineer|lead|manager|architect|developer)\b",
                        candidate,
                        flags=re.I,
                    )
                )
            )
            if starts_next_block:
                break
            if candidate.startswith(("•", "-")):
                bullets.append(candidate[1:].strip())
            cursor += 1
        blocks.append(ExperienceBlock(title_line=line, company=company, bullets=tuple(bullets)))
        idx = cursor
    return blocks


def extract_experience_companies(master_resume: str) -> list[str]:
    """Extract company names from the master resume's EXPERIENCE section."""
    companies: list[str] = []
    for block in extract_experience_blocks(master_resume):
        if block.company not in companies:
            companies.append(block.company)
    return companies


def missing_experience_companies(resume_text: str, master_resume: str) -> list[str]:
    """Return master-resume employers that are absent from a generated resume."""
    resume_l = _norm(resume_text)
    missing = []
    for company in extract_experience_companies(master_resume):
        company_l = _norm(company)
        if company_l and company_l not in resume_l:
            missing.append(company)
    return missing


def missing_experience_title_lines(resume_text: str, master_resume: str) -> list[str]:
    """Return original title/date lines that were changed or dropped."""
    resume_l = _norm(resume_text)
    missing = []
    for block in extract_experience_blocks(master_resume):
        variants = _title_line_variants(block.title_line)
        if variants and not any(variant in resume_l for variant in variants):
            missing.append(block.title_line)
    return missing


def _header_lines(master_resume: str, profile: dict[str, Any]) -> tuple[str, str]:
    lines = [line.strip() for line in master_resume.splitlines() if line.strip()]
    name = lines[0] if lines else profile.get("personal", {}).get("full_name", "")
    contact = ""
    summary_idx = next(
        (idx for idx, line in enumerate(lines) if line.upper() == "SUMMARY"),
        min(len(lines), 6),
    )
    contact_lines = [
        line
        for line in lines[1:summary_idx]
        if (
            "@" in line
            or "linkedin" in line.lower()
            or "github" in line.lower()
            or line.startswith("http")
            or re.search(r"\+\d", line)
        )
    ]
    if contact_lines:
        contact = " ".join(contact_lines)
    if not contact:
        personal = profile.get("personal", {})
        parts = [
            personal.get("city"),
            personal.get("country"),
            personal.get("phone"),
            personal.get("email"),
            personal.get("linkedin_url"),
            personal.get("github_url"),
        ]
        contact = " · ".join(str(p) for p in parts if p)
    return name, contact


def _catalog_keys_for_target_phrase(phrase: str) -> list[str]:
    """Map a profile target_roles entry to one or more catalog keys."""
    normalized = _norm(phrase)
    if not normalized:
        return []
    keys: list[str] = []
    for pattern, key in _TARGET_PHRASE_TO_KEY:
        if pattern in normalized:
            keys.append(key)
    if keys:
        return list(dict.fromkeys(keys))
    for spec in ROLE_CATALOG:
        if any(normalized in _norm(alias) or _norm(alias) in normalized for alias in spec.aliases):
            keys.append(spec.key)
    return list(dict.fromkeys(keys))


def _resume_keyword_hit_count(spec: RoleResumeSpec, haystack: str) -> int:
    return sum(1 for keyword in spec.keywords if _norm(keyword) in haystack)


def infer_applicable_roles(profile: dict[str, Any], master_resume: str) -> list[RoleResumeSpec]:
    """Infer role families from profile targets and resume evidence."""
    exp = profile.get("experience", {}) if isinstance(profile, dict) else {}
    targets = exp.get("target_roles") or []
    if not isinstance(targets, list):
        targets = []
    profile_text = " ".join(
        [
            str(exp.get("target_role", "")),
            str(exp.get("current_job_title", "")),
            " ".join(str(t) for t in targets),
        ]
    )
    haystack = _norm(profile_text + "\n" + master_resume)
    profile_haystack = _norm(profile_text)

    selected_keys: set[str] = set()
    for target in targets:
        for key in _catalog_keys_for_target_phrase(str(target)):
            selected_keys.add(key)

    for spec in ROLE_CATALOG:
        alias_hit = any(_norm(alias) in profile_haystack for alias in spec.aliases)
        if alias_hit or _resume_keyword_hit_count(spec, haystack) >= 2:
            selected_keys.add(spec.key)

    stack_markers = (
        "react",
        "typescript",
        "node",
        "python",
        "aws",
        "rag",
        "langchain",
        "kubernetes",
        "postgresql",
        "microservices",
    )
    if sum(1 for marker in stack_markers if marker in haystack) >= 4:
        for spec in ROLE_CATALOG:
            if _resume_keyword_hit_count(spec, haystack) >= 2:
                selected_keys.add(spec.key)

    if not selected_keys:
        selected_keys.add("senior-full-stack-engineer")

    return [spec for spec in ROLE_CATALOG if spec.key in selected_keys]


def discovery_search_query_entries(
    profile: dict[str, Any] | None = None,
) -> list[dict[str, int | str]]:
    """JobSpy/Workday/smart-extract search rows from ROLE_CATALOG and profile targets."""
    seen: set[str] = set()
    entries: list[dict[str, int | str]] = []

    def add(query: str, tier: int) -> None:
        text = query.strip()
        key = _norm(text)
        if not key or key in seen:
            return
        seen.add(key)
        entries.append({"query": text, "tier": tier})

    for spec in ROLE_CATALOG:
        add(spec.title, 1)
        for alias in spec.aliases[:2]:
            add(alias, 2)

    if profile:
        exp = profile.get("experience") or {}
        for target in exp.get("target_roles") or []:
            add(str(target), 1)
        for field in ("target_role", "current_job_title"):
            value = exp.get(field)
            if value:
                add(str(value), 1)

    return entries


def discovery_title_include_keywords() -> list[str]:
    """Title allowlist phrases for discover/score when searches.yaml has no include_titles."""
    seen: set[str] = set()
    phrases: list[str] = []
    for spec in ROLE_CATALOG:
        for phrase in (spec.title, *spec.aliases):
            key = _norm(phrase)
            if len(key) < 3 or key in seen:
                continue
            seen.add(key)
            phrases.append(phrase.lower())
    return phrases


def parse_salary_usd_max(salary_text: str | None, *, salary_min: Any = None, salary_max: Any = None) -> int:
    """Return maximum annual USD compensation inferred from text/API fields."""
    numeric_fields = []
    for value in (salary_min, salary_max):
        try:
            parsed = int(float(value))
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            numeric_fields.append(parsed)
    if numeric_fields:
        return max(numeric_fields)

    text = (salary_text or "").lower()
    text = re.sub(r"(\d),(\d)(?=\s*k\b)", r"\1.\2", text)
    text = text.replace(",", "")
    if not text:
        return 0

    currency = "usd"
    if any(token in text for token in ("₹", "inr", "lpa", "lakhs", "lakh")):
        currency = "inr"
    elif any(token in text for token in ("€", "eur")):
        currency = "eur"

    values: list[float] = []
    for raw, suffix in re.findall(r"(\d+(?:\.\d+)?)\s*(k|m|lpa|lakh|lakhs)?", text):
        value = float(raw)
        if suffix == "m":
            value *= 1_000_000
        elif suffix == "k":
            value *= 1_000
        elif suffix in ("lpa", "lakh", "lakhs"):
            value *= 100_000
            currency = "inr"
        values.append(value)
    if not values:
        return 0

    annual = max(values)
    if annual < 1_000 and "hour" in text:
        annual *= 2080
    if currency == "inr":
        annual /= USD_TO_INR
    elif currency == "eur":
        annual *= 1.08
    if annual > _SALARY_USD_SANITY_MAX:
        return 0
    return int(annual)


def _benchmark_salary_usd_max(job: dict[str, Any]) -> int:
    """Infer max annual USD from salary field and compensation snippets in the JD."""
    from applypilot.apply.salary import _extract_inr_bounds, _extract_usd_bounds

    salary_field = str(job.get("salary") or "").strip()
    description = str(job.get("full_description") or job.get("description") or "")
    location = str(job.get("location") or "")
    head = description[:5000]
    combined = "\n".join(part for part in (salary_field, head, location) if part)

    candidates: list[int] = []
    if salary_field:
        parsed_field = parse_salary_usd_max(salary_field)
        if parsed_field > 0:
            candidates.append(parsed_field)

    _usd_low, usd_high = _extract_usd_bounds(combined)
    if usd_high and 30_000 <= usd_high <= _SALARY_USD_SANITY_MAX:
        candidates.append(usd_high)

    _inr_low, inr_high = _extract_inr_bounds(combined)
    if inr_high and 500_000 <= inr_high <= 50_000_000:
        candidates.append(int(inr_high / USD_TO_INR))

    return max(candidates) if candidates else 0


def _benchmark_has_disclosed_high_pay(job: dict[str, Any], profile: dict[str, Any]) -> bool:
    """True when parsed compensation meets the high-paying benchmark floor."""
    from applypilot.apply.salary import salary_meets_regional_minimum

    salary_usd = _benchmark_salary_usd_max(job)
    if salary_usd >= MIN_BENCHMARK_USD:
        return True
    description = str(job.get("full_description") or job.get("description") or "")
    if salary_usd <= 0:
        return False
    return salary_meets_regional_minimum(
        job.get("salary"),
        description,
        job.get("location"),
        profile=profile,
    ) and salary_usd >= 50_000


def _role_match_score(spec: RoleResumeSpec, title: str, description: str) -> int:
    title_l = _norm(title)
    blob = _norm(f"{title} {description}")
    score = 0
    if any(marker in title_l for marker in _ROLE_TITLE_MARKERS.get(spec.key, ())):
        score += 6
    for alias in spec.aliases:
        alias_l = _norm(alias)
        if alias_l in title_l:
            score += 12
        elif alias_l in blob:
            score += 4
    for keyword in spec.keywords:
        keyword_l = _norm(keyword)
        if keyword_l in title_l:
            score += 3
        elif keyword_l in blob:
            score += 1
    return score


def _title_role_match(spec: RoleResumeSpec, title: str, description: str = "") -> bool:
    title_l = _norm(title)
    desc = description or ""
    for marker in _ROLE_TITLE_MARKERS.get(spec.key, ()):
        if marker in title_l:
            return True
    if any(_norm(alias) in title_l for alias in spec.aliases):
        return True
    if _role_match_score(spec, title, desc) >= 8:
        return True
    if not desc and _role_match_score(spec, title, "") >= 6:
        return True
    return sum(1 for keyword in spec.keywords if _norm(keyword) in title_l) >= 2


def _has_unsupported_core_stack(title: str, description: str, master_resume: str = "") -> bool:
    """Avoid benchmarking against roles whose central stack is absent from the resume."""
    blob = _norm(f"{title} {description}")
    resume_blob = _norm(master_resume)
    unsupported = (
        "ruby",
        "rails",
        "php",
        "laravel",
        "wordpress",
        "ios",
        "android",
        "swift",
        "kotlin",
        "c#",
        ".net",
        "salesforce",
    )
    return any(term in blob and term not in resume_blob for term in unsupported)


def _eligibility_reason(job: dict[str, Any], profile: dict[str, Any]) -> str | None:
    """Shared eligibility gate for benchmark selection (DB + web)."""
    from applypilot.apply.eligibility import description_eligibility_block, location_restriction_block
    from applypilot.discovery._filters import location_passes

    if description_eligibility_block(job, profile):
        return None
    if location_restriction_block(job.get("location"), profile):
        return None
    if not location_passes(job.get("location")):
        return None

    location_text = str(job.get("location") or "").strip().lower()
    blob = _norm(
        " ".join(
            str(job.get(k) or "") for k in ("location", "description", "full_description", "salary", "title")
        )
    )
    require_sponsorship = str(
        (profile.get("work_authorization") or {}).get("require_sponsorship", "")
    ).lower()

    if require_sponsorship in ("yes", "true", "1") and re.search(
        r"\b(no sponsorship|cannot sponsor|do not sponsor|without sponsorship)\b", blob
    ):
        return None
    if re.search(
        r"\b(us only|u s only|must be based in (the )?united states|authorized to work in the united states)\b",
        blob,
    ):
        return None
    if re.search(
        r"\b(remote|worldwide|global|anywhere|india|bengaluru|bangalore|visa sponsorship|sponsor)\b",
        blob,
    ):
        return "eligible: remote/global/India/sponsorship-compatible language found"
    location = _norm(str(job.get("location") or ""))
    if not location:
        return "eligible: no restrictive location found"
    if any(term in location for term in ("san francisco", "new york", "london", "berlin", "toronto")):
        return None
    if location_text and not any(
        token in location_text
        for token in ("worldwide", "global", "anywhere", "india", "asia", "international", "remote")
    ):
        if not re.search(r"\b(visa sponsorship|sponsor|h1b|h-1b|relocation)\b", blob):
            return None
    return "eligible: location not explicitly restrictive"


def _benchmark_tailoring_eligibility_reason(job: dict[str, Any], profile: dict[str, Any]) -> str | None:
    """Looser gate for JD tailoring when no apply-eligible benchmark exists in the DB."""
    from applypilot.apply.eligibility import description_eligibility_block

    if description_eligibility_block(job, profile):
        return None

    blob = _norm(
        " ".join(
            str(job.get(k) or "") for k in ("location", "description", "full_description", "salary", "title")
        )
    )
    require_sponsorship = str(
        (profile.get("work_authorization") or {}).get("require_sponsorship", "")
    ).lower()
    if require_sponsorship in ("yes", "true", "1") and re.search(
        r"\b(no sponsorship|cannot sponsor|do not sponsor|without sponsorship)\b", blob
    ):
        return None
    if len(blob) < 80:
        return None
    return "benchmark_tailoring: apply location filters relaxed for JD rewrite"


def _benchmark_from_row(
    row: Any,
    spec: RoleResumeSpec,
    profile: dict[str, Any],
    *,
    master_resume: str = "",
    tailoring_only: bool = False,
) -> BenchmarkJob | None:
    job = dict(row)
    description = str(job.get("full_description") or job.get("description") or "").strip()
    title = str(job.get("title") or "")
    salary = str(job.get("salary") or "")
    if len(description) < MIN_BENCHMARK_JD_CHARS:
        return None
    if not _title_role_match(spec, title, description):
        return None
    role_score = _role_match_score(spec, title, description)
    if role_score < 4:
        return None
    if _has_unsupported_core_stack(title, description, master_resume):
        return None
    reason = (
        _benchmark_tailoring_eligibility_reason(job, profile)
        if tailoring_only
        else _eligibility_reason(job, profile)
    )
    if not reason:
        return None

    salary_usd = _benchmark_salary_usd_max(job)
    disclosed = _benchmark_has_disclosed_high_pay(job, profile)
    fit_raw = job.get("fit_score")
    fit_score = float(fit_raw) if fit_raw is not None else 0.0
    title_l = _norm(title)
    marker_title = any(marker in title_l for marker in _ROLE_TITLE_MARKERS.get(spec.key, ()))
    if not disclosed:
        strong_title = marker_title and role_score >= 6
        strong_fit = fit_raw is not None and fit_score >= 7.0 and role_score >= 8
        strong_jd = role_score >= 8
        if not (strong_title or strong_fit or strong_jd):
            return None
        salary_usd = max(salary_usd, MIN_BENCHMARK_USD)
        reason = f"{reason}; compensation not disclosed (strong role/fit match)"

    return BenchmarkJob(
        source="db_tailoring" if tailoring_only else "db",
        url=str(job.get("application_url") or job.get("url") or ""),
        title=title or spec.title,
        company=str(job.get("site") or "Unknown"),
        salary=salary,
        salary_usd_max=salary_usd,
        location=str(job.get("location") or ""),
        description=description,
        eligibility_reason=reason,
    )


def _find_db_benchmark(
    spec: RoleResumeSpec,
    profile: dict[str, Any],
    *,
    master_resume: str = "",
    tailoring_only: bool = False,
) -> BenchmarkJob | None:
    try:
        from applypilot.database import get_connection

        rows = get_connection().execute(
            """
            SELECT url, title, site, application_url, salary, description, location,
                   full_description, fit_score, discovered_at
            FROM jobs
            WHERE length(trim(coalesce(full_description, description, ''))) >= ?
            ORDER BY COALESCE(fit_score, 0) DESC, discovered_at DESC
            LIMIT 2000
            """,
            (MIN_BENCHMARK_JD_CHARS,),
        ).fetchall()
    except Exception:
        log.debug("DB benchmark lookup failed", exc_info=True)
        return None

    candidates: list[tuple[tuple[int, int, int, float], BenchmarkJob]] = []
    for row in rows:
        job = _benchmark_from_row(
            row,
            spec,
            profile,
            master_resume=master_resume,
            tailoring_only=tailoring_only,
        )
        if job is None:
            continue
        row_dict = dict(row)
        disclosed_rank = 0 if _benchmark_has_disclosed_high_pay(row_dict, profile) else 1
        sort_key = (
            disclosed_rank,
            -_role_match_score(spec, job.title, job.description),
            -job.salary_usd_max,
            -float(row_dict.get("fit_score") or 0),
        )
        candidates.append((sort_key, job))

    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    return candidates[0][1]


def _append_web_benchmark_candidate(
    candidates: list[BenchmarkJob],
    *,
    spec: RoleResumeSpec,
    profile: dict[str, Any],
    source: str,
    title: str,
    description: str,
    company: str,
    url: str,
    location: str,
    salary: str,
    salary_min: int | float | None = None,
    salary_max: int | float | None = None,
    eligible_only: bool,
    master_resume: str,
) -> None:
    if not _title_role_match(spec, title, description):
        return
    if _has_unsupported_core_stack(title, description, master_resume):
        return
    role_score = _role_match_score(spec, title, description)
    if role_score < 4:
        return
    salary_usd = parse_salary_usd_max(salary, salary_min=salary_min, salary_max=salary_max)
    title_l = _norm(title)
    marker_title = any(marker in title_l for marker in _ROLE_TITLE_MARKERS.get(spec.key, ()))
    if salary_usd < MIN_BENCHMARK_USD:
        if marker_title and role_score >= 6:
            salary_usd = MIN_BENCHMARK_USD
        else:
            return
    job_dict = {
        "title": title,
        "description": description,
        "location": location,
        "salary": salary,
    }
    reason = _candidate_reason(job_dict, profile, eligible_only=eligible_only)
    if not reason:
        return
    candidates.append(
        BenchmarkJob(
            source=_source_label(source, reason),
            url=url,
            title=title,
            company=company,
            salary=salary,
            salary_usd_max=salary_usd,
            location=location,
            description=description,
            eligibility_reason=reason,
        )
    )


def _remoteok_jobs() -> list[dict[str, Any]]:
    global _REMOTEOK_CACHE
    if _REMOTEOK_CACHE is not None:
        return _REMOTEOK_CACHE
    try:
        resp = httpx.get(
            "https://remoteok.com/api",
            timeout=20,
            headers={"User-Agent": "ApplyPilot role resume research"},
        )
        resp.raise_for_status()
        data = resp.json()
        _REMOTEOK_CACHE = [item for item in data if isinstance(item, dict) and item.get("position")]
        return _REMOTEOK_CACHE
    except Exception:
        log.debug("RemoteOK benchmark fetch failed", exc_info=True)
        _REMOTEOK_CACHE = []
        return []


def _remotive_jobs() -> list[dict[str, Any]]:
    global _REMOTIVE_CACHE
    if _REMOTIVE_CACHE is not None:
        return _REMOTIVE_CACHE
    jobs: list[dict[str, Any]] = []
    for category in ("software-dev", "devops", "product", "all-others"):
        try:
            resp = httpx.get(
                f"https://remotive.com/api/remote-jobs?category={category}",
                timeout=20,
                headers={"User-Agent": "ApplyPilot role resume research"},
            )
            resp.raise_for_status()
            data = resp.json()
            jobs.extend(item for item in data.get("jobs", []) if isinstance(item, dict))
        except Exception:
            log.debug("Remotive benchmark fetch failed for %s", category, exc_info=True)
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for job in jobs:
        key = str(job.get("url") or job.get("id") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(job)
    _REMOTIVE_CACHE = deduped
    return _REMOTIVE_CACHE


def _jobicy_jobs() -> list[dict[str, Any]]:
    global _JOBICY_CACHE
    if _JOBICY_CACHE is not None:
        return _JOBICY_CACHE
    jobs: list[dict[str, Any]] = []
    for tag in ("engineering", "dev", "react", "python", "ai", "management"):
        try:
            resp = httpx.get(
                f"https://jobicy.com/api/v2/remote-jobs?count=50&tag={tag}",
                timeout=20,
                headers={"User-Agent": "ApplyPilot role resume research"},
            )
            resp.raise_for_status()
            data = resp.json()
            jobs.extend(item for item in data.get("jobs", []) if isinstance(item, dict))
        except Exception:
            log.debug("Jobicy benchmark fetch failed for %s", tag, exc_info=True)
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for job in jobs:
        key = str(job.get("url") or job.get("id") or job.get("jobSlug") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(job)
    _JOBICY_CACHE = deduped
    return _JOBICY_CACHE


def _candidate_reason(
    job_dict: dict[str, Any],
    profile: dict[str, Any],
    *,
    eligible_only: bool,
) -> str | None:
    reason = _eligibility_reason(job_dict, profile)
    if reason:
        return reason
    if eligible_only:
        return None
    return "research_only: high-paying market JD, not eligible under current location/sponsorship filter"


def _source_label(source: str, reason: str) -> str:
    return source if not reason.startswith("research_only:") else f"{source}_research_only"


def _find_web_benchmark(
    spec: RoleResumeSpec,
    profile: dict[str, Any],
    *,
    eligible_only: bool = True,
    master_resume: str = "",
) -> BenchmarkJob | None:
    candidates: list[BenchmarkJob] = []
    for item in _remoteok_jobs():
        salary_min = item.get("salary_min")
        salary_max = item.get("salary_max")
        salary = f"${salary_min or 0}-${salary_max or 0}" if salary_min or salary_max else ""
        _append_web_benchmark_candidate(
            candidates,
            spec=spec,
            profile=profile,
            source="remoteok",
            title=str(item.get("position") or ""),
            description=_strip_html(str(item.get("description") or "")),
            company=str(item.get("company") or "Unknown"),
            url=str(item.get("apply_url") or item.get("url") or ""),
            location=str(item.get("location") or "Remote"),
            salary=salary,
            salary_min=salary_min,
            salary_max=salary_max,
            eligible_only=eligible_only,
            master_resume=master_resume,
        )

    for item in _remotive_jobs():
        _append_web_benchmark_candidate(
            candidates,
            spec=spec,
            profile=profile,
            source="remotive",
            title=str(item.get("title") or ""),
            description=_strip_html(str(item.get("description") or "")),
            company=str(item.get("company_name") or "Unknown"),
            url=str(item.get("url") or ""),
            location=str(item.get("candidate_required_location") or "Remote"),
            salary=str(item.get("salary") or ""),
            eligible_only=eligible_only,
            master_resume=master_resume,
        )

    for item in _jobicy_jobs():
        salary_currency = str(item.get("salaryCurrency") or "USD").upper()
        salary_min = item.get("salaryMin")
        salary_max = item.get("salaryMax")
        salary = f"{salary_currency} {salary_min or 0}-{salary_max or 0}" if salary_min or salary_max else ""
        _append_web_benchmark_candidate(
            candidates,
            spec=spec,
            profile=profile,
            source="jobicy",
            title=str(item.get("jobTitle") or ""),
            description=_strip_html(str(item.get("jobDescription") or item.get("jobExcerpt") or "")),
            company=str(item.get("companyName") or "Unknown"),
            url=str(item.get("url") or ""),
            location=str(item.get("jobGeo") or "Remote"),
            salary=salary,
            salary_min=salary_min if salary_currency == "USD" else None,
            salary_max=salary_max if salary_currency == "USD" else None,
            eligible_only=eligible_only,
            master_resume=master_resume,
        )

    candidates.sort(
        key=lambda job: (
            _role_match_score(spec, job.title, job.description),
            job.salary_usd_max,
        ),
        reverse=True,
    )
    return candidates[0] if candidates else None


def _fallback_benchmark(spec: RoleResumeSpec) -> BenchmarkJob:
    return BenchmarkJob(
        source="fallback",
        url="",
        title=f"High-paying {spec.title}",
        company="No eligible live benchmark found",
        salary=f"${MIN_BENCHMARK_USD:,}+",
        salary_usd_max=MIN_BENCHMARK_USD,
        location="Remote/global benchmark unavailable",
        description=(
            f"Senior {spec.title} role owning {', '.join(spec.keywords[:12])}. "
            f"Responsibilities: {', '.join(spec.aliases[:4])}, production systems, APIs, "
            "reliability, and cross-functional delivery at scale. "
            "This fallback is used only when the DB and RemoteOK do not expose an "
            "eligible salary-qualified posting aligned to the role family."
        ),
        eligibility_reason="fallback: no live eligible benchmark found",
    )


def _resolve_live_benchmark(
    spec: RoleResumeSpec,
    profile: dict[str, Any],
    master_resume: str = "",
) -> BenchmarkJob | None:
    db_job = _find_db_benchmark(spec, profile, master_resume=master_resume)
    if not db_job:
        db_job = _find_db_benchmark(
            spec,
            profile,
            master_resume=master_resume,
            tailoring_only=True,
        )
    if db_job:
        return db_job
    eligible = _find_web_benchmark(spec, profile, eligible_only=True, master_resume=master_resume)
    if eligible:
        return eligible
    research = _find_web_benchmark(spec, profile, eligible_only=False, master_resume=master_resume)
    if research and _benchmark_is_role_aligned(spec, research):
        return research
    return None


def find_benchmark_job(
    spec: RoleResumeSpec,
    profile: dict[str, Any],
    master_resume: str = "",
) -> BenchmarkJob:
    job = _resolve_live_benchmark(spec, profile, master_resume=master_resume)
    if job:
        return job
    related_key = _RELATED_BENCHMARK_ROLE_KEY.get(spec.key)
    if related_key:
        related_spec = next(s for s in ROLE_CATALOG if s.key == related_key)
        related_job = _resolve_live_benchmark(related_spec, profile, master_resume=master_resume)
        if related_job:
            return BenchmarkJob(
                source=f"{related_job.source}_via_{related_key}",
                url=related_job.url,
                title=related_job.title,
                company=related_job.company,
                salary=related_job.salary,
                salary_usd_max=related_job.salary_usd_max,
                location=related_job.location,
                description=related_job.description,
                eligibility_reason=(
                    f"{related_job.eligibility_reason}; related role benchmark for {spec.key}"
                ),
            )
    return _fallback_benchmark(spec)


def analyze_jd(spec: RoleResumeSpec, benchmark: BenchmarkJob) -> dict[str, Any]:
    """Extract deterministic JD signals used by rewriting and auditing."""
    lines = [
        line.strip(" -•\t")
        for line in re.split(r"[\n\r]+|(?<=[.!?])\s+", benchmark.description)
        if len(line.strip()) > 20
    ]
    hard_markers = ("required", "must", "need", "responsible", "experience", "years", "proficient", "strong")
    nice_markers = ("preferred", "nice", "plus", "bonus", "familiar", "exposure")
    hard = [line for line in lines if any(marker in line.lower() for marker in hard_markers)]
    nice = [line for line in lines if any(marker in line.lower() for marker in nice_markers)]

    blob = _norm(f"{benchmark.title} {benchmark.description}")
    keyword_hits = [keyword for keyword in spec.keywords if _norm(keyword) in blob]
    domain_terms = [
        term for term in (
            "scale", "latency", "performance", "reliability", "security", "customer",
            "platform", "data", "ai", "automation", "integration", "architecture",
            "cost", "experimentation", "observability", "product", "team", "roadmap",
        )
        if term in blob
    ]
    return {
        "hard_requirements": hard[:12],
        "nice_to_haves": nice[:8],
        "keywords": keyword_hits[:20],
        "missing_role_keywords": [k for k in spec.keywords if k not in keyword_hits][:12],
        "domain_problem_signals": domain_terms[:16],
    }


def company_problem_hypothesis(spec: RoleResumeSpec, benchmark: BenchmarkJob, jd_analysis: dict[str, Any]) -> dict[str, Any]:
    jd_terms = jd_analysis.get("domain_problem_signals") or []
    return {
        "benchmark_company_problem": (
            f"{benchmark.company} is hiring a {benchmark.title} to solve problems around "
            f"{', '.join(jd_terms[:6]) or ', '.join(spec.keywords[:5])}."
        ),
        "candidate_company_problem_map": COMPANY_PROBLEM_FACTS,
    }


def _is_ai_engineer_spec(spec: RoleResumeSpec) -> bool:
    return spec.key == "ai-engineer"


def _ai_led_score(line: str) -> int:
    lowered = _norm(line)
    return sum(2 for marker in _AI_LED_MARKERS if marker in lowered)


def _jd_terms_for_role(spec: RoleResumeSpec, jd_analysis: dict[str, Any]) -> tuple[str, ...]:
    raw = [str(term) for term in (jd_analysis.get("keywords") or []) if str(term).strip()]
    if _is_ai_engineer_spec(spec):
        return tuple(raw)
    spec_terms = {_norm(keyword) for keyword in spec.keywords}
    filtered: list[str] = []
    for term in raw:
        normalized = _norm(term)
        if normalized in spec_terms:
            filtered.append(term)
            continue
        if _ai_led_score(term) >= 2:
            continue
        filtered.append(term)
    return tuple(filtered)


def _role_scoring_terms(spec: RoleResumeSpec, jd_analysis: dict[str, Any]) -> tuple[str, ...]:
    return tuple(spec.keywords) + _jd_terms_for_role(spec, jd_analysis)


def _term_in_line(line: str, term: str) -> bool:
    lowered = _norm(line)
    needle = _norm(term)
    if needle in lowered:
        return True
    compact_line = lowered.replace(".", "").replace("-", "")
    compact_term = needle.replace(".", "").replace("-", "")
    return bool(compact_term) and compact_term in compact_line


def _score_line(line: str, spec: RoleResumeSpec, jd_analysis: dict[str, Any]) -> int:
    lowered = _norm(line)
    terms = _role_scoring_terms(spec, jd_analysis)
    score = sum(3 for alias in spec.aliases if _term_in_line(line, alias)) + sum(
        1 for keyword in terms if _term_in_line(line, keyword)
    )
    if not _is_ai_engineer_spec(spec):
        score -= _ai_led_score(line) * 2
        if "cloudwatch" in lowered and "aws" in {_norm(k) for k in spec.keywords}:
            score += 4
        if "kubernetes" in lowered and "kubernetes" in {_norm(k) for k in spec.keywords}:
            score += 3
    return score


def _split_supported_claims(bullet: str) -> list[str]:
    """Split dense source bullets into smaller claims without adding facts."""
    bullet = bullet.strip().rstrip(".")
    if not bullet:
        return []
    parts = [p.strip(" .") for p in re.split(r";\s+", bullet) if p.strip(" .")]
    if len(parts) <= 1:
        return [bullet + "."]

    claims: list[str] = []
    for part in parts:
        subparts = [
            p.strip(" .")
            for p in re.split(r",\s+(?=(?:built|integrated|shipped|designed|reduced|created|migrated)\b)", part, flags=re.I)
            if p.strip(" .")
        ]
        claims.extend(subparts or [part])
    return [claim[0].upper() + claim[1:] + "." for claim in claims if claim]


def _reframe_patterns_for_role(spec: RoleResumeSpec) -> tuple[tuple[re.Pattern[str], str], ...]:
    patterns = _ROLE_LEADING_REFRAMES.get(spec.key, ())
    if not _is_ai_engineer_spec(spec):
        patterns = patterns + _SHARED_NON_AI_BULLET_REFRAMES
    return patterns


_NON_AI_PRODUCT_SCRUBS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bLangGraph\b", re.I), "workflow orchestration"),
    (re.compile(r"\bLangChain\b", re.I), "service orchestration"),
    (re.compile(r"\bPinecone\b", re.I), "vector search"),
    (re.compile(r"\bpgvector\b", re.I), "vector storage"),
    (re.compile(r"\bAnthropic Claude\b", re.I), "managed APIs"),
    (re.compile(r"\bClaude API\b", re.I), "external APIs"),
    (re.compile(r"\bOpenAI\b", re.I), "external APIs"),
    (re.compile(r"\bGPT-4o?\b", re.I), "managed APIs"),
    (re.compile(r"/\s*Claude\b", re.I), ""),
    (re.compile(r"\bLLMOps\b", re.I), "platform operations"),
    (re.compile(r"\bRAG\b", re.I), "search"),
    (re.compile(r"\bLLM\b", re.I), "inference"),
    (re.compile(r"\bgenerative AI\b", re.I), "product"),
    (re.compile(r"\bgenerative product\b", re.I), "high-scale product"),
    (re.compile(r"\bgenerative\b", re.I), "high-scale"),
    (re.compile(r"\bmulti-agent\b", re.I), "multi-service"),
    (re.compile(r"\bagentic\b", re.I), "product"),
    (re.compile(r"tool-use", re.I), "API integration"),
    (re.compile(r"structured prompt versioning", re.I), "structured configuration versioning"),
    (re.compile(r"inference-as-judge", re.I), "automated regression checks"),
    (re.compile(r"golden dataset regression", re.I), "release regression suite"),
    (re.compile(r"golden dataset", re.I), "regression suite"),
    (re.compile(r"human-in-the-loop", re.I), "operator approval"),
    (re.compile(r"vector search as vector store", re.I), "search indexing"),
    (re.compile(r"\bvector search\b", re.I), "search indexing"),
    (re.compile(r"service orchestration for orchestration", re.I), "service orchestration"),
    (re.compile(r"managed APIs\s+for generation", re.I), "managed APIs for responses"),
)


def _scrub_ai_product_names(text: str, spec: RoleResumeSpec) -> str:
    if _is_ai_engineer_spec(spec):
        return text
    out = text
    for pattern, replacement in _NON_AI_PRODUCT_SCRUBS:
        out = pattern.sub(replacement, out)
    return out


def _collapse_duplicate_phrases(text: str) -> str:
    """Fix stacked replacements like 'multi-step multi-step'."""
    out = text
    for _ in range(3):
        collapsed = re.sub(r"\b([\w-]+)\s+\1\b", r"\1", out, flags=re.I)
        if collapsed == out:
            break
        out = collapsed
    return out


def _apply_role_leading_reframes(text: str, spec: RoleResumeSpec) -> str:
    out = text.strip().rstrip(".")
    for pattern, replacement in _reframe_patterns_for_role(spec):
        out = pattern.sub(replacement, out)
    out = _scrub_ai_product_names(out, spec)
    out = _collapse_duplicate_phrases(out)
    if not _is_ai_engineer_spec(spec):
        out = re.sub(r"\b(\w+)\s+as\s+\1\b", r"\1", out, flags=re.I)
        out = re.sub(r"\ban product\b", "a product", out, flags=re.I)
        out = re.sub(r"\s{2,}", " ", out)
    return out.rstrip(".") + "."


def _tailored_claim_still_too_ai_led(text: str, spec: RoleResumeSpec, jd_analysis: dict[str, Any]) -> bool:
    if _is_ai_engineer_spec(spec):
        return False
    return _ai_led_score(text) >= 3 and _score_line(text, spec, jd_analysis) < 2


_NON_AI_HARD_DROP_MARKERS = (
    "gpt-4",
    "gpt-3",
    "rouge",
    "token-budget",
    "context-window",
    "training job",
    "prompt compression",
    "lora",
    "qlora",
    "planner agent",
    "critic agent",
    "few-shot",
    "chain-of-thought",
    "constrained decoding",
    "hallucination",
    "genai",
    "fine-tuning",
    "tool-calling",
    "semantic similarity threshold",
    "model routing",
    "evaluation harness",
    "agentic copilot",
    "inference-as-judge",
    "golden dataset",
    "structured prompt versioning",
    "tool-use capabilities",
    "human-in-the-loop",
    "planning service decomposes",
    "decomposes user intent",
    "groundedness",
    "instruction-following",
    "product copilot",
    "generative product",
)


def _display_experience_title_line(title_line: str, spec: RoleResumeSpec) -> str:
    """Drop AI product labels from recent role titles on non-AI resumes."""
    if _is_ai_engineer_spec(spec):
        return title_line
    out = title_line
    out = re.sub(r"—\s*AI Platform\b", "— Platform Engineering", out, flags=re.I)
    out = re.sub(r"—\s*AI Products\b", "— Product Engineering", out, flags=re.I)
    return out


def _title_line_variants(title_line: str) -> tuple[str, ...]:
    """Original master title plus allowed non-AI display reframes."""
    variants = {_norm(title_line)}
    reframed = title_line
    reframed = re.sub(r"—\s*AI Platform\b", "— Platform Engineering", reframed, flags=re.I)
    reframed = re.sub(r"—\s*AI Products\b", "— Product Engineering", reframed, flags=re.I)
    if _norm(reframed) not in variants:
        variants.add(_norm(reframed))
    return tuple(variants)


def _claim_usable_for_role(
    claim: str,
    spec: RoleResumeSpec,
    jd_analysis: dict[str, Any],
) -> bool:
    if _is_ai_engineer_spec(spec):
        return True
    tailored = _apply_role_leading_reframes(claim.strip().rstrip(".") + ".", spec)
    lowered = _norm(tailored)
    if any(marker in lowered for marker in _NON_AI_HARD_DROP_MARKERS):
        return False
    return not _tailored_claim_still_too_ai_led(tailored, spec, jd_analysis)


def _tailor_claim_for_role(
    claim: str,
    spec: RoleResumeSpec,
    jd_analysis: dict[str, Any] | None = None,
) -> str:
    """Reframe supported facts for the target role without changing employers or metrics."""
    jd_analysis = jd_analysis or {}
    text = claim.strip().rstrip(".") + "."
    if _is_ai_engineer_spec(spec):
        return text

    clauses = _split_supported_claims(text.rstrip("."))
    if len(clauses) > 1:
        clauses.sort(
            key=lambda line: _score_line(line, spec, jd_analysis) - _ai_led_score(line) * 3,
            reverse=True,
        )
        text = " ".join(clauses)

    text = _apply_role_leading_reframes(text, spec)

    segments = [segment.strip(" .") for segment in re.split(r"\s+—\s+", text.rstrip(".")) if segment.strip(" .")]
    if len(segments) > 1:
        kept: list[str] = []
        for segment in segments:
            segment_text = _apply_role_leading_reframes(segment[0].upper() + segment[1:] + ".", spec)
            if _tailored_claim_still_too_ai_led(segment_text, spec, jd_analysis):
                continue
            kept.append(segment_text.rstrip("."))
        if kept:
            text = " — ".join(kept) + "."

    if _tailored_claim_still_too_ai_led(text, spec, jd_analysis):
        return ""
    return text


def _source_phrase_supported(generated: str, source_bullets: tuple[str, ...]) -> bool:
    if ":" in generated:
        generated = generated.split(":", 1)[1]
    source_tokens = set(_norm(" ".join(source_bullets)).split())
    tokens = [token for token in _norm(generated).split() if len(token) > 3]
    if not tokens:
        return False
    overlap = [token for token in tokens if token in source_tokens]
    return len(overlap) / max(1, len(set(tokens))) >= 0.3


_NON_AI_OPENING_PENALTIES = (
    "multi-service orchestration",
    "workflow orchestration",
    "planning service decomposes",
    "architecting an end-to-end search",
    "personalization and training pipeline",
    "evaluation framework for production output",
    "agentic copilot",
    "inference-as-judge",
    "golden dataset",
    "structured prompt versioning",
)


def _bullet_sort_key(
    line: str,
    spec: RoleResumeSpec,
    jd_analysis: dict[str, Any],
) -> tuple[int, int, int]:
    leading = line.lower()[:160]
    opening_penalty = (
        8
        if any(phrase in leading for phrase in _NON_AI_OPENING_PENALTIES)
        else 0
    )
    return (
        opening_penalty,
        _ai_led_score(line),
        -_score_line(line, spec, jd_analysis),
    )


def _prioritize_bullets_for_role(
    bullets: list[str],
    spec: RoleResumeSpec,
    jd_analysis: dict[str, Any],
) -> list[str]:
    """Put the most role-relevant, least AI-led bullets first for non-AI resumes."""
    if _is_ai_engineer_spec(spec):
        return bullets
    return sorted(
        bullets,
        key=lambda line: _bullet_sort_key(line, spec, jd_analysis),
    )


def _target_bullet_count(block: ExperienceBlock, spec: RoleResumeSpec | None = None) -> int:
    source_text = " ".join(block.bullets)
    if len(block.bullets) <= 1 and (
        len(source_text) > 110 or ";" in source_text or " and " in source_text.lower()
    ):
        target = 2
    else:
        target = min(4, max(1, len(block.bullets)))
    if spec is None or not _is_ai_engineer_spec(spec):
        ai_heavy = sum(1 for bullet in block.bullets if _ai_led_score(bullet) >= 6)
        if ai_heavy >= max(1, len(block.bullets) - 1):
            target = min(target, 2)
    return target


def _jd_focused_block_bullets(
    block: ExperienceBlock,
    spec: RoleResumeSpec,
    jd_analysis: dict[str, Any],
    *,
    min_bullets: int = 2,
    max_bullets: int | None = None,
) -> list[str]:
    """Pick JD-aligned bullets for the most recent employers (benchmark-driven)."""
    if max_bullets is None:
        max_bullets = _target_bullet_count(block, spec)
    claims: list[str] = []
    for bullet in block.bullets:
        for claim in _split_supported_claims(bullet):
            if _claim_usable_for_role(claim, spec, jd_analysis):
                claims.append(claim)
    claims.sort(
        key=lambda line: _score_line(line, spec, jd_analysis) - _ai_led_score(line) * 5,
        reverse=True,
    )

    tailored: list[str] = []
    seen: set[str] = set()
    for claim in claims:
        text = _tailor_claim_for_role(claim, spec, jd_analysis)
        if not text:
            continue
        key = _norm(text)
        if key in seen:
            continue
        if not _source_phrase_supported(text, block.bullets):
            continue
        tailored.append(text)
        seen.add(key)
        if len(tailored) >= max_bullets:
            break

    if len(tailored) < min_bullets:
        for bullet in block.bullets:
            for claim in _split_supported_claims(bullet) or [bullet.strip().rstrip(".") + "."]:
                if not _claim_usable_for_role(claim, spec, jd_analysis):
                    continue
                text = _tailor_claim_for_role(claim, spec, jd_analysis)
                if not text:
                    continue
                key = _norm(text)
                if key in seen:
                    continue
                tailored.append(text)
                seen.add(key)
                if len(tailored) >= min_bullets:
                    break
            if len(tailored) >= min_bullets:
                break
    return _prioritize_bullets_for_role(tailored[:max_bullets], spec, jd_analysis)


def _tailored_block_bullets(
    block: ExperienceBlock,
    spec: RoleResumeSpec,
    jd_analysis: dict[str, Any],
) -> list[str]:
    claims: list[str] = []
    for bullet in block.bullets:
        claims.extend(_split_supported_claims(bullet))
    claims.sort(
        key=lambda line: _score_line(line, spec, jd_analysis) - _ai_led_score(line) * 3,
        reverse=True,
    )

    tailored: list[str] = []
    seen: set[str] = set()
    for claim in claims:
        if not _claim_usable_for_role(claim, spec, jd_analysis):
            continue
        text = _tailor_claim_for_role(claim, spec, jd_analysis)
        if not text:
            continue
        key = _norm(text)
        if key in seen:
            continue
        if _source_phrase_supported(text, block.bullets):
            tailored.append(text)
            seen.add(key)

    target = _target_bullet_count(block, spec)
    if len(tailored) < target:
        for bullet in block.bullets:
            fallback = bullet.strip().rstrip(".") + "."
            text = _tailor_claim_for_role(fallback, spec, jd_analysis)
            key = _norm(text)
            if key not in seen:
                tailored.append(text)
                seen.add(key)
            if len(tailored) >= target:
                break
    if len(tailored) < target:
        for bullet in block.bullets:
            for claim in _split_supported_claims(bullet):
                text = _tailor_claim_for_role(claim, spec, jd_analysis)
                key = _norm(text)
                if key in seen:
                    continue
                tailored.append(text)
                seen.add(key)
                if len(tailored) >= target:
                    break
            if len(tailored) >= target:
                break
    trimmed = tailored[: max(target, min(4, len(tailored)))]
    return _prioritize_bullets_for_role(trimmed, spec, jd_analysis)


def _structured_experience_text(
    master_resume: str,
    spec: RoleResumeSpec,
    jd_analysis: dict[str, Any],
) -> str:
    blocks = extract_experience_blocks(master_resume)
    if not blocks:
        experience = _section(master_resume, "EXPERIENCE", ("SKILLS", "EDUCATION", "PROJECTS"))
        if not experience:
            experience = _section(master_resume, "WORK EXPERIENCE", ("SKILLS", "EDUCATION", "PROJECTS"))
        return _prioritize_bullets(experience, spec, jd_analysis)

    lines: list[str] = []
    for index, block in enumerate(blocks):
        if lines:
            lines.append("")
        lines.extend([_display_experience_title_line(block.title_line, spec), block.company])
        if index < 2:
            bullets = _jd_focused_block_bullets(block, spec, jd_analysis)
        else:
            bullets = _tailored_block_bullets(block, spec, jd_analysis)
        for bullet in bullets:
            lines.append(f"• {bullet}")
    return "\n".join(lines).strip()


def thin_experience_sections(
    resume_text: str,
    master_resume: str,
    spec: RoleResumeSpec | None = None,
) -> list[dict[str, Any]]:
    """Find generated company sections with fewer supported bullets than expected."""
    issues: list[dict[str, Any]] = []
    blocks = extract_experience_blocks(master_resume)
    for block in extract_experience_blocks(master_resume):
        company_pattern = rf"^{re.escape(block.company)}(?:[ \t]+[-·•].*)?\s*$"
        company_match = re.search(
            rf"(?mi){company_pattern}",
            resume_text,
        )
        if not company_match:
            continue
        after = resume_text[company_match.end():]
        stop_positions = []
        for other in blocks:
            if other.company == block.company:
                continue
            other_pattern = rf"^{re.escape(other.company)}(?:[ \t]+[-·•].*)?\s*$"
            match = re.search(rf"(?mi){other_pattern}", after)
            if match:
                stop_positions.append(match.start())
        section = after[: min(stop_positions)] if stop_positions else after
        bullet_count = sum(
            1 for line in section.splitlines() if line.strip().startswith(("•", "-"))
        )
        required = _target_bullet_count(block, spec)
        if bullet_count < required:
            issues.append(
                {
                    "company": block.company,
                    "required_bullets": required,
                    "actual_bullets": bullet_count,
                }
            )
    return issues


def experience_role_lens_issues(resume_text: str, spec: RoleResumeSpec) -> list[str]:
    """Flag recent experience sections that still read as AI-first for non-AI roles."""
    if _is_ai_engineer_spec(spec):
        return []
    issues: list[str] = []
    blocks = extract_experience_blocks(resume_text)
    for block in blocks[:2]:
        if not block.bullets:
            continue
        top_bullets = block.bullets[: min(3, len(block.bullets))]
        leading = top_bullets[0].lower()
        if any(
            phrase in leading
            for phrase in (
                "rag pipeline",
                "rag ",
                "multi-agent",
                "langgraph",
                "langchain",
                "llm output",
                "llm inference",
                "llmops",
                "fine-tuning",
                "generative ai",
                "anthropic claude",
                "claude api",
                "prompt engineering",
                "agentic workflow",
                "planner agent",
                "critic agent",
                "token-budget",
                "context-window",
                "gpt-4",
                "training job",
                "prompt compression",
            )
        ):
            issues.append(f"ai_led_opening_bullet:{block.company}")
        elif not any(
            _norm(keyword) in _norm(" ".join(top_bullets))
            for keyword in spec.keywords[:8]
        ) and max(_ai_led_score(bullet) for bullet in top_bullets) >= 6:
            issues.append(f"ai_dominant_top_experience:{block.company}")
    return issues


def resume_role_content_issues(resume_text: str, spec: RoleResumeSpec) -> list[str]:
    """Reject non-AI resumes that still advertise AI-first stack or summary language."""
    issues = list(experience_role_lens_issues(resume_text, spec))
    if _is_ai_engineer_spec(spec):
        return issues
    for section_name in ("SUMMARY", "TECHNICAL SKILLS", "EXPERIENCE"):
        section = _section(
            resume_text,
            section_name,
            ("SUMMARY", "TECHNICAL SKILLS", "EXPERIENCE", "EDUCATION", "PROJECTS"),
        )
        if not section:
            continue
        lowered = section.lower()
        for marker in (
            "rag ",
            " langgraph",
            " langchain",
            "llmops",
            " llm ",
            "anthropic claude",
            "claude api",
            "multi-agent",
            "generative ai",
            "fine-tuning",
            "pgvector",
            "pinecone",
            "tool-calling agent",
            "gpt-4",
            "gpt-3",
            "token-budget",
            "context-window",
            "planner agent",
            "training job",
            "prompt compression",
            "rouge ",
            "agentic",
            "inference-as-judge",
            "golden dataset",
            "tool-use",
            "— ai platform",
            "— ai products",
            " ai platform",
            " ai products",
        ):
            if marker in lowered:
                issues.append(f"ai_marker_in_{section_name.lower()}:{marker.strip()}")
    return sorted(set(issues))


def _benchmark_is_role_aligned(spec: RoleResumeSpec, benchmark: BenchmarkJob) -> bool:
    """Reject research-only postings that barely mention the target role family."""
    if str(benchmark.source).endswith("_research_only"):
        jd = analyze_jd(spec, benchmark)
        keyword_hits = len(jd.get("keywords") or [])
        if keyword_hits < max(2, len(spec.keywords) // 4):
            return False
        title_l = _norm(benchmark.title)
        if not any(_norm(alias) in title_l for alias in spec.aliases) and _role_match_score(
            spec, benchmark.title, benchmark.description
        ) < 8:
            return False
    return True


def public_resume_quality_issues(resume_text: str) -> list[str]:
    """Catch internal pipeline/meta language that must never appear in a resume."""
    lowered = resume_text.lower()
    issues = [
        f"forbidden_public_phrase:{phrase}"
        for phrase in FORBIDDEN_PUBLIC_PHRASES
        if phrase in lowered
    ]
    if re.search(r"(?mi)^technical skills\s*\n\s*jd alignment\s*:", resume_text):
        issues.append("raw_jd_alignment_skill_section")
    if re.search(r"(?mi)^summary\s*\n.*\bbenchmark\b", resume_text, flags=re.S):
        issues.append("benchmark_language_in_summary")
    return sorted(set(issues))


def _structural_audit_flags(audit: dict[str, Any] | None) -> set[str]:
    flags = set(str(flag) for flag in (audit or {}).get("critical_rejection_flags", []))
    if (audit or {}).get("unsupported_claims"):
        flags.add("unsupported_claims_present")
    if (audit or {}).get("public_resume_quality_issues"):
        flags.add("public_resume_quality_failed")
    if (audit or {}).get("experience_role_lens_issues"):
        flags.add("experience_role_lens_failed")
    return flags


def _prioritize_bullets(experience: str, spec: RoleResumeSpec, jd_analysis: dict[str, Any]) -> str:
    out: list[str] = []
    block: list[str] = []

    def flush() -> None:
        if not block:
            return
        headings = [line for line in block if not line.lstrip().startswith(("•", "-"))]
        bullets = [line for line in block if line.lstrip().startswith(("•", "-"))]
        bullets.sort(key=lambda line: _score_line(line, spec, jd_analysis), reverse=True)
        out.extend(headings + bullets)
        block.clear()

    for line in experience.splitlines():
        stripped = line.strip()
        if not stripped:
            flush()
            out.append("")
            continue
        if not stripped.startswith(("•", "-")) and block and any(
            item.lstrip().startswith(("•", "-")) for item in block
        ):
            flush()
        block.append(line)
    flush()
    return "\n".join(out).strip()


def _skill_supported(skill: str, master_resume: str) -> bool:
    master_l = _norm(master_resume)
    skill_l = _norm(skill)
    if any(phrase in skill_l for phrase in _UNSUPPORTED_TRANSITION_PHRASES):
        return skill_l in master_l
    if skill_l in master_l:
        return True
    tokens = [
        token
        for token in skill_l.split()
        if len(token) > 2 and token not in _GENERIC_SKILL_TOKENS
    ]
    if not tokens:
        return False
    return any(token in master_l for token in tokens)


def _skill_value_is_ai_led(value: str) -> bool:
    lowered = _norm(value)
    return any(marker in lowered for marker in _AI_LED_MARKERS) or "llm" in lowered


def _skills_from_source(spec: RoleResumeSpec, master_resume: str) -> str:
    rows: list[str] = []
    for category, values in spec.skills:
        if not _is_ai_engineer_spec(spec) and any(
            hint in category.lower() for hint in _AI_SKILL_CATEGORY_HINTS
        ):
            continue
        kept = [
            value.strip()
            for value in re.split(r",\s*", values)
            if value.strip()
            and _skill_supported(value.strip(), master_resume)
            and (_is_ai_engineer_spec(spec) or not _skill_value_is_ai_led(value))
        ]
        if kept:
            rows.append(f"{category}: {', '.join(dict.fromkeys(kept))}")
    if rows:
        return "\n".join(rows)
    skills = _section(master_resume, "SKILLS", ("EXPERIENCE", "EDUCATION", "PROJECTS"))
    return skills.strip()


def _professional_summary(spec: RoleResumeSpec, master_resume: str) -> str:
    facts = _norm(master_resume)
    raw = master_resume.lower()
    all_impacts: dict[str, str] = {}
    if "50m+" in facts:
        all_impacts["scale"] = "50M+ user-scale systems"
    if "sub 200ms" in facts or "sub-200ms" in raw or "200ms" in facts:
        all_impacts["retrieval"] = "sub-200ms retrieval targets"
    if "35%" in raw or "35 cost" in facts:
        all_impacts["llm_cost"] = "35% LLM cost reduction"
    if "60%" in raw or "60 system performance" in facts:
        all_impacts["performance"] = "60% system performance improvement"
    if "25%" in raw or "25 conversion" in facts:
        all_impacts["conversion"] = "25% conversion lift"
    if "3x" in facts:
        all_impacts["throughput"] = "3x throughput improvement"
    if "50%" in raw or "50 ui render" in facts:
        all_impacts["render"] = "50% UI render-time reduction"
    if "40%" in raw or "40 bug" in facts:
        all_impacts["quality"] = "40% bug-rate reduction"

    impact_priority = {
        "ai-engineer": ("scale", "retrieval", "llm_cost", "throughput"),
        "frontend-developer": ("conversion", "render", "scale", "performance"),
        "ui-architect": ("render", "conversion", "scale", "performance"),
        "senior-full-stack-engineer": ("scale", "performance", "throughput", "llm_cost"),
        "backend-engineer": ("throughput", "performance", "scale", "quality"),
        "platform-engineer": ("performance", "quality", "scale", "throughput"),
        "product-engineer": ("conversion", "scale", "performance", "throughput"),
        "solutions-architect": ("scale", "performance", "throughput", "quality"),
        "software-architect": ("scale", "performance", "throughput", "quality"),
        "cloud-architect": ("scale", "performance", "throughput", "quality"),
        "forward-deployed-engineer": ("scale", "retrieval", "throughput", "conversion"),
        "founding-engineer": ("scale", "llm_cost", "performance", "throughput"),
        "staff-engineer": ("performance", "quality", "scale", "conversion"),
        "principal-engineer": ("performance", "quality", "scale", "throughput"),
        "tech-lead": ("quality", "performance", "conversion", "scale"),
        "engineering-manager": ("quality", "performance", "scale", "conversion"),
    }.get(spec.key, tuple(all_impacts))
    impact = [all_impacts[key] for key in impact_priority if key in all_impacts][:4]

    role_tail = {
        "ai-engineer": "Strengths include production RAG, agentic workflows, LLMOps, streaming inference, evaluation pipelines, and model cost control.",
        "frontend-developer": "Strengths include React/TypeScript delivery, component systems, real-time interfaces, frontend performance, and conversion-focused product engineering.",
        "ui-architect": "Strengths include design systems, UI architecture, React/TypeScript platforms, accessibility-minded patterns, and performance-tuned product interfaces.",
        "senior-full-stack-engineer": "Strengths include React, Node.js, Python, TypeScript, AWS, APIs, microservices, data pipelines, and production platforms.",
        "backend-engineer": "Strengths include Python/Node.js services, API design, data pipelines, distributed systems, and production reliability on AWS.",
        "platform-engineer": "Strengths include Kubernetes, CI/CD, observability, infrastructure automation, and reliable operations for high-scale products.",
        "product-engineer": "Strengths include full-stack product delivery, experimentation, conversion improvements, and end-to-end ownership from UI through APIs.",
        "solutions-architect": "Strengths include customer-facing solution discovery, system design, API and integration architecture, cloud-backed platforms, scalable production systems, and implementation planning.",
        "software-architect": "Strengths include application architecture, integration design, scalability planning, and hands-on delivery across cloud-native stacks.",
        "cloud-architect": "Strengths include AWS architecture, VPC networking, migration planning, reliability and scalability patterns, cost-aware infrastructure, and security-conscious cloud platforms.",
        "forward-deployed-engineer": "Strengths include customer-facing deployments, stakeholder discovery, integration prototypes, workflow automation, full-stack delivery, live API tool use, third-party integrations, and production ownership.",
        "founding-engineer": "Strengths include end-to-end product engineering, architecture, rapid delivery, production ownership, and scaling systems into reliable platforms.",
        "staff-engineer": "Strengths include technical direction, distributed systems design, latency reduction, platform quality, mentorship, and measurable product outcomes.",
        "principal-engineer": "Strengths include cross-team technical strategy, architecture standards, platform evolution, mentorship, and high-impact system design.",
        "tech-lead": "Strengths include team technical leadership, delivery execution, code quality, mentoring, and hands-on architecture across the stack.",
        "engineering-manager": "Strengths include team leadership, roadmap delivery, technical leadership, mentoring engineers, delivery ownership, technical debt reduction, platform quality, and cross-functional product execution.",
    }.get(spec.key, spec.summary)

    sentences = [spec.summary.rstrip(".") + "."]
    if impact:
        sentences.append("Selected impact includes " + ", ".join(impact[:4]) + ".")
    sentences.append(role_tail)
    return _scrub_ai_product_names(" ".join(sentences), spec)


def _deterministic_resume_text(
    spec: RoleResumeSpec,
    *,
    profile: dict[str, Any],
    master_resume: str,
    benchmark: BenchmarkJob,
    jd_analysis: dict[str, Any],
) -> str:
    name, contact = _header_lines(master_resume, profile)
    summary = _professional_summary(spec, master_resume)
    experience = _structured_experience_text(master_resume, spec, jd_analysis)
    education = _section(master_resume, "EDUCATION", ("SKILLS", "PROJECTS", "EXPERIENCE"))

    sections = [
        name,
        spec.title,
        contact,
        "",
        "SUMMARY",
        summary,
        "",
        "TECHNICAL SKILLS",
        _skills_from_source(spec, master_resume),
        "",
        "EXPERIENCE",
        experience,
    ]
    if education:
        sections.extend(["", "EDUCATION", education])
    return "\n".join(sections).strip() + "\n"


def _resume_claim_lines(resume_text: str) -> list[str]:
    claims = []
    for line in resume_text.splitlines():
        stripped = line.strip()
        if stripped.startswith(("•", "-")):
            claims.append(stripped[1:].strip())
    return claims


def validate_fact_support(resume_text: str, master_resume: str) -> dict[str, Any]:
    """Flag resume bullet claims with weak lexical support in the master resume."""
    master_tokens = set(_norm(master_resume).split())
    unsupported: list[str] = []
    support_map: list[dict[str, Any]] = []
    for claim in _resume_claim_lines(resume_text):
        tokens = [t for t in _norm(claim).split() if len(t) > 3]
        if not tokens:
            continue
        overlap = [t for t in tokens if t in master_tokens]
        support_ratio = len(overlap) / max(1, len(set(tokens)))
        if support_ratio < 0.35:
            unsupported.append(claim)
        support_map.append(
            {
                "claim": claim,
                "support_ratio": round(support_ratio, 2),
                "supporting_terms": sorted(set(overlap))[:12],
            }
        )
    return {"unsupported_claims": unsupported, "fact_support_map": support_map}


def _auditable_keywords(
    spec: RoleResumeSpec,
    benchmark: BenchmarkJob,
    jd_analysis: dict[str, Any],
    master_resume: str,
) -> list[str]:
    """Keywords used for deterministic audit scoring (fallback JDs can over-list role terms)."""
    required = list(jd_analysis.get("keywords") or spec.keywords)
    if benchmark.source != "fallback":
        return required
    support_blob = _norm(
        " ".join(
            [
                master_resume,
                spec.summary,
                " ".join(f"{category} {values}" for category, values in spec.skills),
            ]
        )
    )
    return [kw for kw in required if _norm(kw) in support_blob]


def _deterministic_audit(
    spec: RoleResumeSpec,
    resume_text: str,
    master_resume: str,
    jd_analysis: dict[str, Any],
    benchmark: BenchmarkJob,
) -> dict[str, Any]:
    resume_l = _norm(resume_text)
    required_keywords = _auditable_keywords(spec, benchmark, jd_analysis, master_resume)
    covered = [kw for kw in required_keywords if _norm(kw) in resume_l]
    keyword_score = int(100 * len(covered) / max(1, len(required_keywords)))
    support = validate_fact_support(resume_text, master_resume)
    unsupported = support["unsupported_claims"]
    missing_companies = missing_experience_companies(resume_text, master_resume)
    missing_titles = missing_experience_title_lines(resume_text, master_resume)
    thin_sections = thin_experience_sections(resume_text, master_resume, spec)
    public_issues = public_resume_quality_issues(resume_text)
    role_lens_issues = resume_role_content_issues(resume_text, spec)
    evidence_score = max(0, 100 - len(unsupported) * 15)
    benchmark_warnings: list[str] = []
    critical = []
    if benchmark.source == "fallback":
        benchmark_warnings.append("no_live_salary_qualified_benchmark")
    if unsupported:
        critical.append("unsupported_claims_present")
    if missing_companies:
        critical.append("missing_experience_companies")
    if missing_titles:
        critical.append("changed_or_missing_experience_titles")
    if thin_sections and not all(
        issue.get("actual_bullets", 0) >= 2 for issue in thin_sections[:2]
    ):
        critical.append("thin_experience_sections")
    if public_issues:
        critical.append("public_resume_quality_failed")
    if role_lens_issues:
        critical.append("experience_role_lens_failed")
    score = min(95, int(keyword_score * 0.45 + evidence_score * 0.45 + 10))
    return {
        "score": score,
        "pass": score >= AUDIT_PASS_SCORE and not critical,
        "keyword_coverage_score": keyword_score,
        "recruiter_rejection_risk_score": 100 - score,
        "evidence_support_score": evidence_score,
        "role_problem_fit_score": min(95, score + 5),
        "critical_rejection_flags": critical,
        "benchmark_warnings": benchmark_warnings,
        "unsupported_claims": unsupported,
        "missing_experience_companies": missing_companies,
        "missing_experience_title_lines": missing_titles,
        "thin_experience_sections": thin_sections,
        "public_resume_quality_issues": public_issues,
        "tech_mismatches": [],
        "rejection_risks": critical + benchmark_warnings,
        "experience_role_lens_issues": role_lens_issues,
        "improvement_instructions": [] if score >= AUDIT_PASS_SCORE else ["Increase JD keyword coverage using existing facts only."],
        "fact_support_map": support["fact_support_map"],
        "auditor": "deterministic",
    }


def get_direct_gemini_client():
    """Gemini client pinned to GEMINI_API_KEY, bypassing LLM_URL by design."""
    from applypilot.llm import get_gemini_client

    return get_gemini_client()


def _gemini_rewrite_resume(
    *,
    spec: RoleResumeSpec,
    profile: dict[str, Any],
    master_resume: str,
    benchmark: BenchmarkJob,
    jd_analysis: dict[str, Any],
    problem_hypothesis: dict[str, Any],
    previous_audit: dict[str, Any] | None,
) -> tuple[str, list[dict[str, Any]], list[str]]:
    prompt = f"""
You are rewriting a resume for a real job application. Return JSON only.
Current date: 2026-06-03. A 2026-Present role is valid and not future-dated.

STRICT FACT RULES:
- Use only facts in MASTER_RESUME and PROFILE.
- Do not invent metrics, tools, titles, scope, direct customer exposure, management scope, or domain claims.
- You may reorder, compress, emphasize, and map existing facts to JD language.
- You must keep every employer from MASTER_RESUME in EXPERIENCE. Do not drop older companies.
- You must preserve every original EXPERIENCE title/date line exactly. Do not rewrite "Full Stack Engineer" as "Engineering Manager".
- Tailor bullets under each employer to the role/JD using only facts from that employer's original bullets.
- Keep employer order unchanged (most recent first). Do not reorder companies.
- For non-AI roles, bullets must read like {spec.title} work — not a generic AI/ML resume.
- For recent AI-heavy employers, emphasize transferable facts already in MASTER_RESUME: React/TypeScript/UI, APIs, integrations, real-time/web streaming (SSE/WebSockets), performance, cloud ops. Map RAG/agent/LLM wording into product, platform, or integration language without inventing tools or metrics.
- Do not lead non-AI resumes with RAG, LangGraph, LangChain, embeddings, pgvector, Pinecone, LoRA, or fine-tuning unless ROLE is AI Engineer.
- If a company has less role-relevant experience, keep it concise but still include it.
- Keep section headers compatible with this exact plain-text format:
  NAME
  ROLE TITLE
  CONTACT

  SUMMARY
  ...

  TECHNICAL SKILLS
  Category: skills

  EXPERIENCE
  Job title | dates
  Company
  • bullet

  EDUCATION
  ...

ROLE: {spec.title}
BENCHMARK_JOB: {json.dumps(asdict(benchmark), ensure_ascii=False)}
JD_ANALYSIS: {json.dumps(jd_analysis, ensure_ascii=False)}
COMPANY_PROBLEM_HYPOTHESIS: {json.dumps(problem_hypothesis, ensure_ascii=False)}
PROFILE: {json.dumps(profile, ensure_ascii=False)}
REQUIRED_EXPERIENCE_COMPANIES: {json.dumps(extract_experience_companies(master_resume), ensure_ascii=False)}
REQUIRED_EXPERIENCE_TITLE_LINES: {json.dumps([block.title_line for block in extract_experience_blocks(master_resume)], ensure_ascii=False)}
MASTER_RESUME:
{master_resume}

PREVIOUS_AUDIT:
{json.dumps(previous_audit or {}, ensure_ascii=False)}

If the benchmark source ends with "_research_only", use the JD only for market-demand signals.
Do not add unsupported stack terms from that JD and do not optimize for its location restrictions.

Return:
{{
  "resume_text": "full rewritten resume text",
  "fact_support_map": [{{"claim":"resume bullet or summary claim", "evidence":["exact supporting source phrases"]}}],
  "rewrite_notes": ["what changed"]
}}
"""
    try:
        raw = get_direct_gemini_client().ask(
            prompt,
            temperature=0.1,
            max_tokens=6000,
            operation="role_resume_rewrite",
        )
        parsed = _extract_json(raw) or {}
        resume_text = str(parsed.get("resume_text") or "").strip()
        if "SUMMARY" not in resume_text or "EXPERIENCE" not in resume_text:
            raise ValueError("Gemini rewrite did not return structured resume_text")
        missing_companies = missing_experience_companies(resume_text, master_resume)
        if missing_companies:
            raise ValueError(f"Gemini rewrite dropped companies: {', '.join(missing_companies)}")
        missing_titles = missing_experience_title_lines(resume_text, master_resume)
        if missing_titles:
            raise ValueError(f"Gemini rewrite changed title/date lines: {', '.join(missing_titles)}")
        thin_sections = thin_experience_sections(resume_text, master_resume, spec)
        if thin_sections:
            raise ValueError(f"Gemini rewrite left thin experience sections: {thin_sections}")
        public_issues = public_resume_quality_issues(resume_text)
        if public_issues:
            raise ValueError(f"Gemini rewrite leaked public meta language: {public_issues}")
        support = parsed.get("fact_support_map") if isinstance(parsed.get("fact_support_map"), list) else []
        notes = parsed.get("rewrite_notes") if isinstance(parsed.get("rewrite_notes"), list) else []
        return resume_text + "\n", support, [str(n) for n in notes]
    except Exception as exc:
        log.warning("Gemini rewrite failed for %s; using deterministic rewrite: %s", spec.title, exc)
        resume = _deterministic_resume_text(
            spec,
            profile=profile,
            master_resume=master_resume,
            benchmark=benchmark,
            jd_analysis=jd_analysis,
        )
        support = validate_fact_support(resume, master_resume)["fact_support_map"]
        return resume, support, [f"deterministic fallback: {exc}"]


def _gemini_audit_resume(
    *,
    spec: RoleResumeSpec,
    resume_text: str,
    master_resume: str,
    benchmark: BenchmarkJob,
    jd_analysis: dict[str, Any],
    problem_hypothesis: dict[str, Any],
) -> dict[str, Any]:
    deterministic = _deterministic_audit(spec, resume_text, master_resume, jd_analysis, benchmark)
    prompt = f"""
Act as a strict Head of Recruiting and ATS reviewer. Return JSON only.
Current date: 2026-06-03. A 2026-Present role is valid and not future-dated.

Evaluate the resume against the benchmark job. Reject or penalize for:
- unsupported claims or exaggerated metrics
- no proven records
- role/tech mismatch
- not solving the problems this company is hiring for
- weak keyword coverage
- fake leadership, fake domain ownership, or inflated titles
- missing employers or incomplete employment history
- changed source title/date lines or thin company sections
- internal pipeline/meta language in the public resume, such as "Targeted for", "JD Alignment", "benchmark", or "verified resume facts"
- non-AI roles whose two most recent employers still open with AI-first bullets (RAG, LangGraph, multi-agent, LLM evals, fine-tuning) instead of role-relevant delivery

If benchmark_job.source ends with "_research_only", use it for market-demand signals only.
Do not reject for location, work authorization, or sponsorship mismatch against that benchmark.
Still reject unsupported claims, fake stack claims, inflated titles, and proven tech mismatch.

BENCHMARK_JOB: {json.dumps(asdict(benchmark), ensure_ascii=False)}
JD_ANALYSIS: {json.dumps(jd_analysis, ensure_ascii=False)}
COMPANY_PROBLEM_HYPOTHESIS: {json.dumps(problem_hypothesis, ensure_ascii=False)}
MASTER_RESUME_FACTS:
{master_resume}
REQUIRED_EXPERIENCE_COMPANIES: {json.dumps(extract_experience_companies(master_resume), ensure_ascii=False)}
REQUIRED_EXPERIENCE_TITLE_LINES: {json.dumps([block.title_line for block in extract_experience_blocks(master_resume)], ensure_ascii=False)}

ROLE_RESUME:
{resume_text}

Return:
{{
  "score": 0-100,
  "pass": true/false,
  "keyword_coverage_score": 0-100,
  "recruiter_rejection_risk_score": 0-100,
  "evidence_support_score": 0-100,
  "role_problem_fit_score": 0-100,
  "critical_rejection_flags": [],
  "unsupported_claims": [],
  "tech_mismatches": [],
  "rejection_risks": [],
  "improvement_instructions": []
}}
"""
    try:
        raw = get_direct_gemini_client().ask(
            prompt,
            temperature=0.0,
            max_tokens=3000,
            operation="role_resume_audit",
        )
        parsed = _extract_json(raw) or {}
        parsed["score"] = int(parsed.get("score") or 0)
        parsed["pass"] = bool(
            parsed.get("pass")
            and parsed["score"] >= AUDIT_PASS_SCORE
            and not parsed.get("critical_rejection_flags")
            and not parsed.get("unsupported_claims")
        )
        parsed["auditor"] = "gemini"
        fact_support = validate_fact_support(resume_text, master_resume)
        missing_companies = missing_experience_companies(resume_text, master_resume)
        missing_titles = missing_experience_title_lines(resume_text, master_resume)
        thin_sections = thin_experience_sections(resume_text, master_resume, spec)
        public_issues = public_resume_quality_issues(resume_text)
        role_lens_issues = resume_role_content_issues(resume_text, spec)
        if fact_support["unsupported_claims"]:
            parsed["pass"] = False
            parsed.setdefault("critical_rejection_flags", []).append("local_fact_support_failed")
            parsed["unsupported_claims"] = sorted(
                set(list(parsed.get("unsupported_claims") or []) + fact_support["unsupported_claims"])
            )
        if missing_companies:
            parsed["pass"] = False
            parsed.setdefault("critical_rejection_flags", []).append("missing_experience_companies")
            parsed["missing_experience_companies"] = missing_companies
        if missing_titles:
            parsed["pass"] = False
            parsed.setdefault("critical_rejection_flags", []).append("changed_or_missing_experience_titles")
            parsed["missing_experience_title_lines"] = missing_titles
        if thin_sections:
            parsed["pass"] = False
            parsed.setdefault("critical_rejection_flags", []).append("thin_experience_sections")
            parsed["thin_experience_sections"] = thin_sections
        if public_issues:
            parsed["pass"] = False
            parsed.setdefault("critical_rejection_flags", []).append("public_resume_quality_failed")
            parsed["public_resume_quality_issues"] = public_issues
        if role_lens_issues:
            parsed["pass"] = False
            parsed.setdefault("critical_rejection_flags", []).append("experience_role_lens_failed")
            parsed["experience_role_lens_issues"] = role_lens_issues
        if str(benchmark.source).endswith("_research_only"):
            location_terms = ("location", "authorization", "sponsorship", "visa", "country", "timezone")
            parsed["critical_rejection_flags"] = [
                flag for flag in parsed.get("critical_rejection_flags", [])
                if not any(term in str(flag).lower() for term in location_terms)
            ]
            parsed["rejection_risks"] = [
                risk for risk in parsed.get("rejection_risks", [])
                if not any(term in str(risk).lower() for term in location_terms)
            ]
            parsed["pass"] = bool(
                parsed.get("score", 0) >= AUDIT_PASS_SCORE
                and not parsed.get("critical_rejection_flags")
                and not parsed.get("unsupported_claims")
                and not parsed.get("public_resume_quality_issues")
                and not parsed.get("experience_role_lens_issues")
            )
        else:
            parsed["missing_experience_companies"] = missing_companies
            parsed["missing_experience_title_lines"] = missing_titles
            parsed["thin_experience_sections"] = thin_sections
            parsed["public_resume_quality_issues"] = public_issues
        parsed["fact_support_map"] = fact_support["fact_support_map"]
        return {**deterministic, **parsed}
    except Exception as exc:
        log.warning("Gemini audit failed for %s; using deterministic audit: %s", spec.title, exc)
        return {**deterministic, "audit_error": str(exc)}


def build_role_resume_text(
    spec: RoleResumeSpec,
    *,
    profile: dict[str, Any],
    master_resume: str,
    benchmark: BenchmarkJob | None = None,
    jd_analysis: dict[str, Any] | None = None,
) -> str:
    """Back-compatible deterministic resume builder used by tests/fallbacks."""
    benchmark = benchmark or _fallback_benchmark(spec)
    jd_analysis = jd_analysis or analyze_jd(spec, benchmark)
    return _deterministic_resume_text(
        spec,
        profile=profile,
        master_resume=master_resume,
        benchmark=benchmark,
        jd_analysis=jd_analysis,
    )


def generate_one_role_resume(
    spec: RoleResumeSpec,
    *,
    profile: dict[str, Any],
    master_resume: str,
    output: Path,
) -> dict[str, Any]:
    benchmark = find_benchmark_job(spec, profile, master_resume)
    jd_analysis = analyze_jd(spec, benchmark)
    problem_hypothesis = company_problem_hypothesis(spec, benchmark, jd_analysis)
    audit: dict[str, Any] | None = None
    support_map: list[dict[str, Any]] = []
    rewrite_notes: list[str] = [
        f"benchmark: {benchmark.source} — {benchmark.company} ({benchmark.title})",
    ]
    resume_text = ""

    if _is_ai_engineer_spec(spec):
        for _ in range(MAX_GEMINI_ITERATIONS):
            resume_text, support_map, rewrite_notes = _gemini_rewrite_resume(
                spec=spec,
                profile=profile,
                master_resume=master_resume,
                benchmark=benchmark,
                jd_analysis=jd_analysis,
                problem_hypothesis=problem_hypothesis,
                previous_audit=audit,
            )
            audit = _gemini_audit_resume(
                spec=spec,
                resume_text=resume_text,
                master_resume=master_resume,
                benchmark=benchmark,
                jd_analysis=jd_analysis,
                problem_hypothesis=problem_hypothesis,
            )
            if audit.get("pass"):
                break
    else:
        resume_text = _deterministic_resume_text(
            spec,
            profile=profile,
            master_resume=master_resume,
            benchmark=benchmark,
            jd_analysis=jd_analysis,
        )
        support_map = validate_fact_support(resume_text, master_resume)["fact_support_map"]
        rewrite_notes.append(
            "deterministic rewrite: top-two employers tailored to benchmark JD; AI terms reframed or dropped"
        )
        audit = _deterministic_audit(spec, resume_text, master_resume, jd_analysis, benchmark)
        content_issues = resume_role_content_issues(resume_text, spec)
        if content_issues:
            audit["pass"] = False
            audit.setdefault("critical_rejection_flags", []).append("experience_role_lens_failed")
            audit["experience_role_lens_issues"] = content_issues

    structural_flags = _structural_audit_flags(audit)
    if structural_flags & {
        "unsupported_claims_present",
        "local_fact_support_failed",
        "changed_or_missing_experience_titles",
        "thin_experience_sections",
        "missing_experience_companies",
        "public_resume_quality_failed",
        "experience_role_lens_failed",
    }:
        resume_text = _deterministic_resume_text(
            spec,
            profile=profile,
            master_resume=master_resume,
            benchmark=benchmark,
            jd_analysis=jd_analysis,
        )
        support_map = validate_fact_support(resume_text, master_resume)["fact_support_map"]
        rewrite_notes = list(rewrite_notes) + [
            "strict source-preserving fallback after structural audit failure"
        ]
        if _is_ai_engineer_spec(spec):
            audit = _gemini_audit_resume(
                spec=spec,
                resume_text=resume_text,
                master_resume=master_resume,
                benchmark=benchmark,
                jd_analysis=jd_analysis,
                problem_hypothesis=problem_hypothesis,
            )
        else:
            audit = _deterministic_audit(spec, resume_text, master_resume, jd_analysis, benchmark)
            content_issues = resume_role_content_issues(resume_text, spec)
            if content_issues:
                audit["pass"] = False
                audit.setdefault("critical_rejection_flags", []).append("experience_role_lens_failed")
                audit["experience_role_lens_issues"] = content_issues

    stem = _slug(spec.title)
    role_output = output / stem
    role_output.mkdir(parents=True, exist_ok=True)
    txt_path = role_output / "resume.txt"
    pdf_path = role_output / "resume.pdf"
    audit_path = role_output / "audit.json"
    txt_path.write_text(resume_text, encoding="utf-8")

    from applypilot.scoring.pdf import convert_to_pdf

    convert_to_pdf(txt_path, output_path=pdf_path)
    audit_payload = {
        "role": asdict(spec),
        "benchmark_job": asdict(benchmark),
        "jd_analysis": jd_analysis,
        "company_problem_hypothesis": problem_hypothesis,
        "fact_support_map": support_map or (audit or {}).get("fact_support_map", []),
        "rewrite_notes": rewrite_notes,
        "audit": audit or {},
    }
    audit_path.write_text(json.dumps(audit_payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return {
        "key": spec.key,
        "title": spec.title,
        "aliases": list(spec.aliases),
        "keywords": list(spec.keywords),
        "txt_path": str(txt_path.resolve()),
        "pdf_path": str(pdf_path.resolve()),
        "audit_path": str(audit_path.resolve()),
        "benchmark": asdict(benchmark),
        "audit_score": int((audit or {}).get("score") or 0),
        "audit_pass": bool((audit or {}).get("pass")),
    }


def _usable_manifest_items_by_key(
    output_dir: Path | None = None,
) -> dict[str, dict[str, Any]]:
    """Return manifest roles that are ready to use (PDF on disk, audit not failed)."""
    manifest = load_manifest(output_dir)
    if not manifest:
        return {}
    by_key: dict[str, dict[str, Any]] = {}
    for item in manifest.get("roles", []):
        key = str(item.get("key") or "")
        if key and _manifest_item_usable(item):
            by_key[key] = item
    return by_key


def missing_role_specs(
    profile: dict[str, Any],
    master_resume: str,
    output_dir: Path | None = None,
) -> list[RoleResumeSpec]:
    """Role families still needed for the current profile and master resume."""
    required = infer_applicable_roles(profile, master_resume)
    satisfied = set(_usable_manifest_items_by_key(output_dir))
    return [spec for spec in required if spec.key not in satisfied]


def count_missing_role_resumes(output_dir: Path | None = None) -> int:
    profile = config.load_profile()
    master_resume = config.RESUME_PATH.read_text(encoding="utf-8")
    return len(missing_role_specs(profile, master_resume, output_dir))


def role_resumes_complete(output_dir: Path | None = None) -> bool:
    """True when every applicable role has a usable pre-built resume on disk."""
    return count_missing_role_resumes(output_dir) == 0


def _write_manifest(
    output: Path,
    *,
    items: list[dict[str, Any]],
    generated_this_run: int,
    required_role_count: int,
) -> dict[str, Any]:
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_resume": str(config.RESUME_PATH),
        "min_benchmark_usd": MIN_BENCHMARK_USD,
        "audit_pass_score": AUDIT_PASS_SCORE,
        "role_count": len(items),
        "required_role_count": required_role_count,
        "generated_this_run": generated_this_run,
        "status": "complete" if generated_this_run == 0 else "generated",
        "roles": items,
    }
    manifest_path(output).write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return manifest


def generate_role_resumes(
    output_dir: Path | None = None,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """Generate repo-local role TXT/PDF files plus recruiter audit bundles.

    By default only builds roles that are missing or failed audit. When ``force`` is
    true, regenerates every applicable role family.
    """
    output = Path(output_dir or role_resume_dir())
    output.mkdir(parents=True, exist_ok=True)
    profile = config.load_profile()
    master_resume = config.RESUME_PATH.read_text(encoding="utf-8")
    required_specs = infer_applicable_roles(profile, master_resume)
    if force:
        to_generate = list(required_specs)
        existing_by_key: dict[str, dict[str, Any]] = {}
    else:
        existing_by_key = _usable_manifest_items_by_key(output)
        to_generate = [spec for spec in required_specs if spec.key not in existing_by_key]

    if not to_generate:
        items = [existing_by_key[spec.key] for spec in required_specs if spec.key in existing_by_key]
        return _write_manifest(
            output,
            items=items,
            generated_this_run=0,
            required_role_count=len(required_specs),
        )

    new_items = [
        generate_one_role_resume(
            spec,
            profile=profile,
            master_resume=master_resume,
            output=output,
        )
        for spec in to_generate
    ]
    merged = dict(existing_by_key)
    for item in new_items:
        merged[item["key"]] = item
    items = [merged[spec.key] for spec in required_specs if spec.key in merged]
    return _write_manifest(
        output,
        items=items,
        generated_this_run=len(new_items),
        required_role_count=len(required_specs),
    )


def ensure_role_resumes(output_dir: Path | None = None) -> dict[str, Any]:
    """One-time prep: generate only missing role resumes; no-op when already complete."""
    return generate_role_resumes(output_dir, force=False)


def load_manifest(output_dir: Path | None = None) -> dict[str, Any] | None:
    path = manifest_path(output_dir)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        log.warning("Ignoring invalid role resume manifest: %s", path)
        return None


def role_resumes_available(output_dir: Path | None = None) -> bool:
    """True when at least one usable role resume exists for apply-time matching."""
    return bool(_usable_manifest_items_by_key(output_dir))


def _manifest_item_usable(item: dict[str, Any]) -> bool:
    # Older manifests did not have audit_pass; keep them usable for compatibility.
    return Path(item.get("pdf_path", "")).exists() and item.get("audit_pass", True) is not False


def role_resume_jd_min_score() -> int:
    """Minimum 1–10 JD alignment score to apply with a role resume instead of per-job tailor."""
    return max(1, min(10, int(config.DEFAULTS.get("role_resume_jd_min_score", 8))))


def _role_resume_text(item: dict[str, Any]) -> str:
    for key in ("txt_path", "resume_txt_path"):
        raw = item.get(key)
        if raw:
            path = Path(str(raw))
            if path.is_file():
                return path.read_text(encoding="utf-8")
    pdf = Path(str(item.get("pdf_path") or ""))
    if pdf.suffix.lower() == ".pdf":
        txt = pdf.with_suffix(".txt")
        if txt.is_file():
            return txt.read_text(encoding="utf-8")
    return ""


def score_role_resume_jd_fit(
    role_item: dict[str, Any],
    job: dict[str, Any],
) -> int:
    """Deterministic 1–10 alignment of a role resume against this job's JD."""
    resume_text = _role_resume_text(role_item)
    jd = " ".join(
        str(job.get(key) or "")
        for key in ("title", "full_description", "description", "site")
    ).strip()
    if not resume_text.strip() or not jd:
        return 0
    ratio = keyword_overlap_ratio(resume_text, jd, top_n=20)
    overlap_score = max(1, min(10, round(ratio * 9 + 1)))

    jd_blob = _norm(jd)
    resume_blob = _norm(resume_text)
    keywords = [str(k) for k in (role_item.get("keywords") or []) if k]
    if keywords:
        in_jd = [_norm(k) for k in keywords if _norm(k) in jd_blob]
        if in_jd:
            in_both = sum(1 for k in in_jd if k in resume_blob)
            keyword_score = max(1, min(10, round((in_both / len(in_jd)) * 9 + 1)))
            return max(overlap_score, keyword_score)
    return overlap_score


@dataclass(frozen=True)
class ResumeResolution:
    path: str | None
    source: str  # role_resume | tailored | base | needs_tailor | none
    jd_score: int | None = None
    role_key: str | None = None


def _role_item_for_apply(
    job: dict[str, Any],
    output_dir: Path | None = None,
) -> dict[str, Any] | None:
    """Manifest role for apply: title/JD match wins when it disagrees with score_role_key."""
    live_match = match_role_resume(job, output_dir)
    score_role_key = job.get("score_role_key")
    if not score_role_key:
        return live_match
    scored_item = _usable_manifest_items_by_key(output_dir).get(str(score_role_key))
    if not scored_item:
        return live_match
    if not live_match:
        return scored_item
    live_key = str(live_match.get("key") or "")
    scored_key = str(scored_item.get("key") or "")
    if live_key and scored_key and live_key != scored_key:
        return live_match
    return scored_item


def _jd_score_for_role_apply(job: dict[str, Any], role_item: dict[str, Any]) -> int:
    """JD fit at apply time; reuse score_jd_fit when it matches the chosen role."""
    role_key = str(role_item.get("key") or "")
    scorer_key = job.get("score_role_key")
    if scorer_key and str(scorer_key) == role_key:
        raw = job.get("score_jd_fit")
        if raw is not None:
            try:
                return max(1, min(10, int(raw)))
            except (TypeError, ValueError):
                pass
    return score_role_resume_jd_fit(role_item, job)


def _role_text_by_key(role_key: str, output_dir: Path | None = None) -> str:
    item = _usable_manifest_items_by_key(output_dir).get(role_key)
    if not item:
        return ""
    text = _role_resume_text(item)
    return text if text.strip() else ""


def resolve_job_resume(
    job: dict[str, Any],
    *,
    allow_base: bool = False,
    jd_min_score: int | None = None,
    output_dir: Path | None = None,
) -> ResumeResolution:
    """Pick resume for apply: role resume if JD score is high enough, else tailored, else base."""
    jd_min = role_resume_jd_min_score() if jd_min_score is None else max(1, min(10, jd_min_score))

    matched = _role_item_for_apply(job, output_dir)
    if matched:
        jd_score = _jd_score_for_role_apply(job, matched)
        role_key = str(matched.get("key") or "")
        if jd_score >= jd_min:
            return ResumeResolution(
                path=str(matched["pdf_path"]),
                source="role_resume",
                jd_score=jd_score,
                role_key=role_key,
            )
        tailored = job.get("tailored_resume_path")
        if tailored:
            return ResumeResolution(
                path=str(tailored),
                source="tailored",
                jd_score=jd_score,
                role_key=role_key,
            )
        if allow_base:
            return ResumeResolution(
                path=str(config.RESUME_PDF_PATH),
                source="base",
                jd_score=jd_score,
                role_key=role_key,
            )
        return ResumeResolution(
            path=None,
            source="needs_tailor",
            jd_score=jd_score,
            role_key=role_key,
        )

    tailored = job.get("tailored_resume_path")
    if tailored:
        return ResumeResolution(
            path=str(tailored),
            source="tailored",
        )
    if allow_base:
        return ResumeResolution(
            path=str(config.RESUME_PDF_PATH),
            source="base",
        )
    return ResumeResolution(path=None, source="none")


def role_resume_min_match_score() -> int:
    """Minimum title/JD match score before a manifest role is selected (no default role)."""
    return max(1, int(config.DEFAULTS.get("role_resume_min_match_score", 3)))


def _role_manifest_match_score(item: dict[str, Any], text: str) -> int:
    score = 0
    for alias in item.get("aliases", []):
        if _norm(alias) in text:
            score += 8
    for keyword in item.get("keywords", []):
        if _norm(keyword) in text:
            score += 1
    return score


def _match_role_resume_from_manifest(
    manifest: dict[str, Any],
    job: dict[str, Any],
) -> dict[str, Any] | None:
    if not manifest:
        return None
    text = _norm(
        " ".join(
            str(job.get(key) or "")
            for key in ("title", "site", "full_description", "description", "strategy")
        )
    )
    min_score = role_resume_min_match_score()
    best: tuple[int, dict[str, Any]] | None = None
    for item in manifest.get("roles", []):
        if not _manifest_item_usable(item):
            continue
        score = _role_manifest_match_score(item, text)
        if score >= min_score and (best is None or score > best[0]):
            best = (score, item)
    if not best:
        return None
    chosen = dict(best[1])
    chosen["_match_score"] = best[0]
    return chosen


def match_role_resume(job: dict[str, Any], output_dir: Path | None = None) -> dict[str, Any] | None:
    """Return the best manifest role for a job title/description."""
    manifest = load_manifest(output_dir)
    return _match_role_resume_from_manifest(manifest, job)


ROLE_AWARE_RESCORE_MARKER = config.APP_DIR / ".role_aware_scoring_v1.rescored"


@dataclass(frozen=True)
class RoleMatch:
    item: dict[str, Any] | None
    match_score: int


def _job_match_text(job: dict[str, Any]) -> str:
    return _norm(
        " ".join(
            str(job.get(key) or "")
            for key in ("title", "site", "full_description", "description", "strategy")
        )
    )


def _match_manifest_scored(
    manifest: dict[str, Any],
    job: dict[str, Any],
) -> RoleMatch:
    if not manifest:
        return RoleMatch(None, 0)
    text = _job_match_text(job)
    best: tuple[int, dict[str, Any]] | None = None
    for item in manifest.get("roles", []):
        if not _manifest_item_usable(item):
            continue
        score = _role_manifest_match_score(item, text)
        if score > 0 and (best is None or score > best[0]):
            best = (score, item)
    if best:
        return RoleMatch(best[1], best[0])
    return RoleMatch(None, 0)


def match_role_resume_scored(
    job: dict[str, Any],
    output_dir: Path | None = None,
) -> RoleMatch:
    """Scoring match: alias/keyword hits only (no default-role fallback)."""
    manifest = load_manifest(output_dir)
    if not manifest:
        return RoleMatch(None, 0)
    return _match_manifest_scored(manifest, job)


def role_aware_scoring_enabled(output_dir: Path | None = None) -> bool:
    """True when all applicable role resumes exist and scoring.role_aware is not disabled."""
    profile = config.load_profile()
    if profile.get("scoring", {}).get("role_aware") is False:
        return False
    return role_resumes_complete(output_dir)


def should_one_time_rescore(output_dir: Path | None = None) -> bool:
    if not role_aware_scoring_enabled(output_dir):
        return False
    return not ROLE_AWARE_RESCORE_MARKER.is_file()


def resolve_job_resume_for_scoring(
    job: dict[str, Any],
    output_dir: Path | None = None,
) -> ResumeResolution:
    """Pick resume text source for LLM scoring (role resume only on real title/JD match)."""
    if not role_aware_scoring_enabled(output_dir):
        base = str(config.RESUME_PATH) if config.RESUME_PATH.is_file() else None
        return ResumeResolution(path=base, source="base", jd_score=None, role_key=None)

    matched = match_role_resume_scored(job, output_dir)
    if matched.match_score > 0 and matched.item:
        role_key = str(matched.item.get("key") or "")
        jd_score = score_role_resume_jd_fit(matched.item, job)
        pdf = matched.item.get("pdf_path")
        return ResumeResolution(
            path=str(pdf) if pdf else None,
            source="role_resume",
            jd_score=jd_score,
            role_key=role_key or None,
        )

    base = str(config.RESUME_PATH) if config.RESUME_PATH.is_file() else None
    return ResumeResolution(path=base, source="base", jd_score=None, role_key=None)


def resume_text_for_scoring(
    resolution: ResumeResolution,
    job: dict[str, Any],
    output_dir: Path | None = None,
) -> str:
    """Plain-text resume body used by the score stage for this resolution."""
    if resolution.source == "role_resume" and resolution.role_key:
        manifest = load_manifest(output_dir)
        if manifest:
            for item in manifest.get("roles", []):
                if item.get("key") == resolution.role_key:
                    text = _role_resume_text(item)
                    if text.strip():
                        return text
    if config.RESUME_PATH.is_file():
        return config.RESUME_PATH.read_text(encoding="utf-8")
    return ""


def scoring_resume_cache_key(resolution: ResumeResolution) -> str:
    return f"{resolution.source}:{resolution.role_key or 'base'}"


def resolve_job_resume_path(
    job: dict[str, Any],
    *,
    allow_base: bool = False,
    output_dir: Path | None = None,
) -> str | None:
    """Return the PDF path chosen by :func:`resolve_job_resume`."""
    return resolve_job_resume(
        job,
        allow_base=allow_base,
        output_dir=output_dir,
    ).path


def resolve_job_resume_text(
    job: dict[str, Any],
    *,
    allow_base: bool = False,
    output_dir: Path | None = None,
) -> str:
    """Plain-text resume for apply prompts: role resume, tailored file, or base."""
    resolution = resolve_job_resume(
        job,
        allow_base=allow_base,
        output_dir=output_dir,
    )
    if resolution.source == "role_resume" and resolution.role_key:
        text = _role_text_by_key(str(resolution.role_key), output_dir)
        if text.strip():
            return text
    tailored = job.get("tailored_resume_path")
    if tailored:
        txt = Path(str(tailored)).with_suffix(".txt")
        if txt.is_file():
            return txt.read_text(encoding="utf-8")
    if resolution.path:
        pdf = Path(resolution.path)
        txt = pdf.with_suffix(".txt")
        if txt.is_file():
            return txt.read_text(encoding="utf-8")
    if allow_base and config.RESUME_PATH.is_file():
        return config.RESUME_PATH.read_text(encoding="utf-8")
    return ""


def _max_tailor_attempts() -> int:
    return max(1, int(config.DEFAULTS.get("max_tailor_attempts", 5)))


def job_needs_per_job_tailor(
    job: dict[str, Any],
    *,
    jd_min_score: int | None = None,
    output_dir: Path | None = None,
) -> bool:
    """True when per-job LLM tailoring is still required (role resume is not enough)."""
    if job.get("tailored_resume_path"):
        return False
    if int(job.get("tailor_attempts") or 0) >= _max_tailor_attempts():
        return False
    resolution = resolve_job_resume(
        job,
        allow_base=False,
        jd_min_score=jd_min_score,
        output_dir=output_dir,
    )
    return resolution.source in ("needs_tailor", "none")


_TAILOR_CANDIDATE_COLUMNS = (
    "title",
    "site",
    "full_description",
    "description",
    "strategy",
    "tailored_resume_path",
    "tailor_attempts",
    "fit_score",
    "score_role_key",
)


def _iter_tailor_candidates(
    conn: Any,
    *,
    min_score: int,
    batch_size: int = 500,
) -> Any:
    """Yield high-score jobs that might still need per-job tailoring."""
    offset = 0
    max_att = _max_tailor_attempts()
    cols = ", ".join(_TAILOR_CANDIDATE_COLUMNS)
    while True:
        rows = conn.execute(
            f"""
            SELECT {cols} FROM jobs
            WHERE fit_score >= ?
              AND full_description IS NOT NULL
              AND tailored_resume_path IS NULL
              AND COALESCE(tailor_attempts, 0) < ?
            ORDER BY fit_score DESC, discovered_at DESC
            LIMIT ? OFFSET ?
            """,
            (min_score, max_att, batch_size, offset),
        ).fetchall()
        if not rows:
            return
        columns = rows[0].keys()
        for row in rows:
            yield dict(zip(columns, row))
        if len(rows) < batch_size:
            return
        offset += batch_size


def bind_role_resume_paths(
    conn: Any | None = None,
    *,
    min_score: int = 7,
    batch_size: int = 500,
) -> dict[str, int]:
    """Set ``tailored_resume_path`` to a matched role-resume PDF for high-score jobs.

    Downstream pipeline stages (cover, PDF, dashboard counts, apply queue) key off
    ``tailored_resume_path``. Role-resume-ready jobs skip per-job LLM tailor but still
    need this column populated so they are not stuck at scored-only.
    """
    if conn is None:
        from applypilot.database import get_connection

        conn = get_connection()

    if not role_resumes_available():
        return {"bound": 0, "skipped": 0}

    now = datetime.now(timezone.utc).isoformat()
    bound = 0
    skipped = 0
    offset = 0
    cols = ", ".join((*_TAILOR_CANDIDATE_COLUMNS, "url"))
    while True:
        rows = conn.execute(
            f"""
            SELECT {cols} FROM jobs
            WHERE fit_score >= ?
              AND full_description IS NOT NULL
              AND (tailored_resume_path IS NULL OR tailored_resume_path = '')
            ORDER BY fit_score DESC, discovered_at DESC
            LIMIT ? OFFSET ?
            """,
            (min_score, batch_size, offset),
        ).fetchall()
        if not rows:
            break
        columns = rows[0].keys()
        for row in rows:
            job = dict(zip(columns, row))
            score_role_key = job.get("score_role_key")
            matched = None
            if score_role_key:
                by_key = _usable_manifest_items_by_key()
                matched = by_key.get(str(score_role_key))
            if not matched:
                matched = match_role_resume(job)
            if not matched:
                skipped += 1
                continue
            pdf_raw = matched.get("pdf_path")
            if not pdf_raw:
                skipped += 1
                continue
            pdf = Path(str(pdf_raw))
            if not pdf.is_file():
                skipped += 1
                continue
            cur = conn.execute(
                """
                UPDATE jobs
                SET tailored_resume_path = ?, tailored_at = ?
                WHERE url = ?
                  AND (tailored_resume_path IS NULL OR tailored_resume_path = '')
                """,
                (str(pdf.resolve()), now, job["url"]),
            )
            if cur.rowcount:
                bound += 1
        if len(rows) < batch_size:
            break
        offset += batch_size

    if bound:
        conn.commit()
        invalidate_tailor_count_cache()
        from applypilot.database import invalidate_stats_cache

        invalidate_stats_cache()
        log.info(
            "Bound %d high-score jobs to role resumes (score >= %d; %d had no match).",
            bound,
            min_score,
            skipped,
        )
    return {"bound": bound, "skipped": skipped}


def fetch_jobs_needing_tailor(
    conn: Any | None = None,
    *,
    min_score: int = 7,
    limit: int = 0,
) -> list[dict[str, Any]]:
    """Jobs that still need per-job tailoring (skips role-resume-ready rows)."""
    if conn is None:
        from applypilot.database import get_connection

        conn = get_connection()
    needed: list[dict[str, Any]] = []
    for job in _iter_tailor_candidates(conn, min_score=min_score):
        if not job_needs_per_job_tailor(job):
            continue
        needed.append(job)
        if limit > 0 and len(needed) >= limit:
            break
    return needed


_TAILOR_NEED_COUNT_CACHE_TTL_S = 3.0
_tailor_need_count_cache: dict[int, tuple[float, int]] = {}
_tailor_need_count_cache_lock = threading.Lock()


def invalidate_tailor_count_cache() -> None:
    with _tailor_need_count_cache_lock:
        _tailor_need_count_cache.clear()


def count_jobs_needing_tailor(
    conn: Any | None = None,
    *,
    min_score: int = 7,
    use_cache: bool = True,
) -> int:
    """Count jobs that still need per-job tailoring."""
    if use_cache and conn is None:
        now = time.monotonic()
        with _tailor_need_count_cache_lock:
            cached = _tailor_need_count_cache.get(min_score)
            if cached is not None and now - cached[0] < _TAILOR_NEED_COUNT_CACHE_TTL_S:
                return cached[1]

    if conn is None:
        from applypilot.database import get_connection

        conn = get_connection()
    manifest = load_manifest()
    total = sum(
        1
        for job in _iter_tailor_candidates(conn, min_score=min_score)
        if _job_needs_tailor_with_manifest(job, manifest, min_score=min_score)
    )

    if use_cache and conn is None:
        with _tailor_need_count_cache_lock:
            _tailor_need_count_cache[min_score] = (time.monotonic(), total)

    return total


def _job_needs_tailor_with_manifest(
    job: dict[str, Any],
    manifest: dict[str, Any],
    *,
    min_score: int | None = None,
) -> bool:
    if job.get("tailored_resume_path"):
        return False
    if int(job.get("tailor_attempts") or 0) >= _max_tailor_attempts():
        return False
    jd_min = role_resume_jd_min_score() if min_score is None else max(1, min(10, min_score))
    matched = _match_role_resume_from_manifest(manifest, job)
    if matched:
        jd_score = score_role_resume_jd_fit(matched, job)
        if jd_score >= jd_min:
            return False
        return True
    return True


def apply_queue_min_ready() -> int:
    return max(0, int(config.DEFAULTS.get("apply_queue_min_ready", 300)))
