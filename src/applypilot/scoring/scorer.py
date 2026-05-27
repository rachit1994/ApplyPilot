"""Job fit scoring: LLM-powered evaluation of candidate-job match quality.

Scores jobs on a 1-10 scale by comparing the user's resume against each
job description. All personal data is loaded at runtime from the user's
profile and resume file.
"""

import json
import logging
import os
import re
import time
from datetime import datetime, timezone

from applypilot.config import RESUME_PATH, get_target_roles, load_profile, load_search_config
from applypilot.database import get_connection, get_jobs_by_stage, refresh_source_stats_scores
from applypilot.llm import get_client
from applypilot.scoring import embedding_filter
from applypilot.scoring.pre_filter import pre_score_filter

log = logging.getLogger(__name__)


# ── Scoring Prompt ────────────────────────────────────────────────────────

SCORE_PROMPT = """You are a job fit evaluator. Given a candidate's resume and a job description, score how well the candidate fits the role.

SCORING CRITERIA:
- 9-10: Perfect match. Candidate has direct experience in nearly all required skills and qualifications.
- 7-8: Strong match. Candidate has most required skills, minor gaps easily bridged.
- 5-6: Moderate match. Candidate has some relevant skills but missing key requirements.
- 3-4: Weak match. Significant skill gaps, would need substantial ramp-up.
- 1-2: Poor match. Completely different field or experience level.

IMPORTANT FACTORS:
- Weight technical skills heavily (programming languages, frameworks, tools)
- Consider transferable experience (automation, scripting, API work)
- Factor in the candidate's project experience
- Be realistic about experience level vs. job requirements (years of experience, seniority)
- Visa / work authorization: if the posting requires a specific work authorization the candidate likely lacks, cap at 4 unless resume clearly states eligibility
- Remote vs on-site: penalize only when location is clearly incompatible with candidate preferences in the resume or target roles
- Seniority: staff/principal/CTO/founding-engineer targets should score lower on clearly junior-only roles

RECOMMENDATION (derive from score and blockers):
- apply: score >= 7 and no hard blockers (visa, wrong seniority band)
- maybe: score 5-6 or minor gaps worth a human look
- skip: score <= 4 or hard blocker

RESPOND IN EXACTLY THIS FORMAT (no other text):
SCORE: [1-10]
RECOMMENDATION: [apply|maybe|skip]
KEYWORDS: [comma-separated ATS keywords from the job description that match or could match the candidate]
REASONING: [2-3 sentences explaining the score]"""


BATCH_SCORE_PROMPT = """You are scoring job-resume fit. Return a JSON array of exactly {count} objects, one per job, in the same order as input.

Each object must use this exact shape:
{{"url":"...","score":1-10,"recommendation":"apply|maybe|skip","keywords":"...","reasoning":"2-3 sentences"}}

Use the same scoring criteria and recommendation rules as the single-job evaluator:
- 9-10: Perfect match.
- 7-8: Strong match.
- 5-6: Moderate match.
- 3-4: Weak match.
- 1-2: Poor match.
- apply: score >= 7 and no hard blockers.
- maybe: score 5-6 or minor gaps worth a human look.
- skip: score <= 4 or hard blockers.

Respond with only the JSON array."""


def _parse_score_response(response: str) -> dict:
    """Parse the LLM's score response into structured data.

    Args:
        response: Raw LLM response text.

    Returns:
        {"score": int, "recommendation": str, "keywords": str, "reasoning": str}
    """
    score = 0
    recommendation = ""
    keywords = ""
    reasoning = response

    for line in response.split("\n"):
        line = line.strip()
        if line.startswith("SCORE:"):
            try:
                score = int(re.search(r"\d+", line).group())
                score = max(1, min(10, score))
            except (AttributeError, ValueError):
                score = 0
        elif line.startswith("RECOMMENDATION:"):
            raw = line.replace("RECOMMENDATION:", "").strip().lower()
            if raw in ("apply", "maybe", "skip"):
                recommendation = raw
        elif line.startswith("KEYWORDS:"):
            keywords = line.replace("KEYWORDS:", "").strip()
        elif line.startswith("REASONING:"):
            reasoning = line.replace("REASONING:", "").strip()

    if not recommendation:
        if score >= 7:
            recommendation = "apply"
        elif score >= 5:
            recommendation = "maybe"
        else:
            recommendation = "skip"

    return {
        "score": score,
        "recommendation": recommendation,
        "keywords": keywords,
        "reasoning": reasoning,
    }


def _recommendation_from_score(score: int) -> str:
    if score >= 7:
        return "apply"
    if score >= 5:
        return "maybe"
    return "skip"


def _coerce_score_result(item: dict) -> dict:
    score = 0
    try:
        score = int(item.get("score", 0))
        score = max(1, min(10, score))
    except (TypeError, ValueError):
        score = 0

    recommendation = str(item.get("recommendation", "")).strip().lower()
    if recommendation not in ("apply", "maybe", "skip"):
        recommendation = _recommendation_from_score(score)

    return {
        "score": score,
        "recommendation": recommendation,
        "keywords": str(item.get("keywords", "") or "").strip(),
        "reasoning": str(item.get("reasoning", "") or "").strip(),
    }


def _extract_json_array(response: str) -> list:
    try:
        parsed = json.loads(response)
    except json.JSONDecodeError:
        match = re.search(r"\[[\s\S]*\]", response)
        if not match:
            raise
        parsed = json.loads(match.group(0))
    if not isinstance(parsed, list):
        raise ValueError("response was not a JSON array")
    return parsed


def _parse_batch_score_response(response: str, expected_count: int) -> list[dict]:
    parsed = _extract_json_array(response)
    if len(parsed) != expected_count:
        raise ValueError(f"expected {expected_count} results, got {len(parsed)}")
    if not all(isinstance(item, dict) for item in parsed):
        raise ValueError("all batch results must be objects")
    return [_coerce_score_result(item) for item in parsed]


def _format_batch_job(job: dict, index: int) -> str:
    description = (job.get("full_description") or "")[:2000]
    return (
        f"{index}. URL:{job['url']}\n"
        f"TITLE:{job.get('title', '')}\n"
        f"COMPANY:{job.get('site', '')}\n"
        f"LOCATION:{job.get('location', 'N/A')}\n"
        f"DESCRIPTION:{description}"
    )


def score_jobs_batch(
    resume_text: str,
    jobs: list[dict],
    *,
    batch_id: str,
) -> list[dict]:
    """Score a batch of jobs with one LLM call.

    Raises on malformed batch responses so the caller can fall back to
    the existing single-job path for the whole batch.
    """
    jobs_block = "\n\n".join(
        _format_batch_job(job, idx) for idx, job in enumerate(jobs, 1)
    )
    messages = [
        {
            "role": "system",
            "content": BATCH_SCORE_PROMPT.format(count=len(jobs)),
        },
        {
            "role": "user",
            "content": f"<RESUME>\n{resume_text}\n</RESUME>\n\nJOBS:\n{jobs_block}",
        },
    ]
    client = get_client()
    response = client.chat(
        messages,
        max_tokens=2048,
        temperature=0.2,
        operation="score_batch",
    )
    results = _parse_batch_score_response(response, len(jobs))
    for result, job in zip(results, jobs, strict=True):
        result["url"] = job["url"]
    log.info("Batch %s scored %d jobs", batch_id, len(jobs))
    return results


def _scoring_batch_size(profile: dict) -> int:
    try:
        configured = int(profile.get("scoring_batch_size", 5))
    except (TypeError, ValueError):
        configured = 5
    return max(1, configured)


def score_job(resume_text: str, job: dict, profile: dict | None = None) -> dict:
    """Score a single job against the resume.

    Args:
        resume_text: The candidate's full resume text.
        job: Job dict with keys: title, site, location, full_description.

    Returns:
        {"score": int, "keywords": str, "reasoning": str}
    """
    profile = profile or load_profile()
    roles = get_target_roles(profile)
    roles_block = (
        f"TARGET ROLES (strong fit counts as 7+): {', '.join(roles)}\n\n"
        if roles
        else ""
    )
    job_text = (
        f"TITLE: {job['title']}\n"
        f"COMPANY: {job['site']}\n"
        f"LOCATION: {job.get('location', 'N/A')}\n\n"
        f"DESCRIPTION:\n{(job.get('full_description') or '')[:6000]}"
    )

    messages = [
        {"role": "system", "content": SCORE_PROMPT},
        {
            "role": "user",
            "content": f"{roles_block}RESUME:\n{resume_text}\n\n---\n\nJOB POSTING:\n{job_text}",
        },
    ]

    try:
        client = get_client()
        response = client.chat(
            messages,
            max_tokens=512,
            temperature=0.2,
            operation="score_single",
        )
        return _parse_score_response(response)
    except Exception as e:
        log.error("LLM error scoring job '%s': %s", job.get("title", "?"), e)
        return {
            "score": 0,
            "recommendation": "skip",
            "keywords": "",
            "reasoning": f"LLM error: {e}",
        }


def run_scoring(limit: int = 0, rescore: bool = False) -> dict:
    """Score unscored jobs that have full descriptions.

    Args:
        limit: Maximum number of jobs to score in this run.
        rescore: If True, re-score all jobs (not just unscored ones).

    Returns:
        {"scored": int, "errors": int, "elapsed": float, "distribution": list}
    """
    resume_text = RESUME_PATH.read_text(encoding="utf-8")
    profile = load_profile()
    search_cfg = load_search_config()
    conn = get_connection()

    if rescore:
        query = "SELECT * FROM jobs WHERE full_description IS NOT NULL"
        if limit > 0:
            query += f" LIMIT {limit}"
        jobs = conn.execute(query).fetchall()
    else:
        jobs = get_jobs_by_stage(conn=conn, stage="pending_score", limit=limit)

    if not jobs:
        log.info("No unscored jobs with descriptions found.")
        return {
            "scored": 0,
            "skipped_pre": 0,
            "errors": 0,
            "elapsed": 0.0,
            "distribution": [],
        }

    # Convert sqlite3.Row to dicts if needed
    if jobs and not isinstance(jobs[0], dict):
        columns = jobs[0].keys()
        jobs = [dict(zip(columns, row)) for row in jobs]

    now = datetime.now(timezone.utc).isoformat()
    skipped_pre = 0
    survivors: list[dict] = []
    for job in jobs:
        verdict = pre_score_filter(job, profile, search_cfg)
        if not verdict.passes:
            conn.execute(
                "UPDATE jobs SET fit_score = 0, score_reasoning = ?, scored_at = ? WHERE url = ?",
                (f"pre_filter:{verdict.reason}", now, job["url"]),
            )
            skipped_pre += 1
            continue
        survivors.append(job)
    if skipped_pre:
        conn.commit()
        log.info("Pre-filter skipped %d jobs before Gemini", skipped_pre)

    if survivors:
        resume_embedding = embedding_filter.encode_resume(resume_text)
        embedding_threshold = embedding_filter.threshold_from_profile(profile)
        embedding_skipped = 0
        embedding_survivors: list[dict] = []
        for job in survivors:
            verdict = embedding_filter.pre_filter_job(
                job,
                resume_embedding,
                threshold=embedding_threshold,
            )
            if not verdict.passes:
                conn.execute(
                    "UPDATE jobs SET fit_score = 0, score_reasoning = ?, scored_at = ? WHERE url = ?",
                    ("pre_filter:embedding_low", now, job["url"]),
                )
                embedding_skipped += 1
                continue
            embedding_survivors.append(job)
        if embedding_skipped:
            conn.commit()
            skipped_pre += embedding_skipped
            log.info(
                "Embedding pre-filter skipped %d jobs below %.2f similarity",
                embedding_skipped,
                embedding_threshold,
            )
        survivors = embedding_survivors

    if not survivors:
        log.info("No jobs left after pre-filter.")
        return {
            "scored": 0,
            "skipped_pre": skipped_pre,
            "errors": 0,
            "elapsed": 0.0,
            "distribution": [],
        }

    batch_size = _scoring_batch_size(profile)
    if batch_size > 1:
        log.info("Scoring %d jobs in batches of %d...", len(survivors), batch_size)
    else:
        log.info("Scoring %d jobs sequentially...", len(survivors))
    t0 = time.time()
    completed = 0
    errors = 0
    results: list[dict] = []

    for batch_start in range(0, len(survivors), batch_size):
        batch = survivors[batch_start : batch_start + batch_size]
        batch_id = f"score-batch-{(batch_start // batch_size) + 1}"
        if batch_size > 1:
            try:
                batch_results = score_jobs_batch(resume_text, batch, batch_id=batch_id)
            except Exception as e:
                log.warning(
                    "Batch scoring failed; falling back to single-job scoring batch_id=%s reason=%s",
                    batch_id,
                    e,
                )
                batch_results = []
                for job in batch:
                    result = score_job(resume_text, job, profile=profile)
                    result["url"] = job["url"]
                    batch_results.append(result)
        else:
            batch_results = []
            for job in batch:
                result = score_job(resume_text, job, profile=profile)
                result["url"] = job["url"]
                batch_results.append(result)

        for result, job in zip(batch_results, batch, strict=True):
            completed += 1

            if result["score"] == 0:
                errors += 1

            results.append(result)
            log.info(
                "[%d/%d] score=%d  %s",
                completed,
                len(survivors),
                result["score"],
                job.get("title", "?")[:60],
            )

    # Write scores to DB
    for r in results:
        conn.execute(
            "UPDATE jobs SET fit_score = ?, score_reasoning = ?, scored_at = ? WHERE url = ?",
            (
                r["score"],
                f"{r.get('recommendation', '')}\n{r['keywords']}\n{r['reasoning']}".strip(),
                now,
                r["url"],
            ),
        )
    conn.commit()
    refresh_source_stats_scores(conn, run_id=os.environ.get("APPLYPILOT_RUN_ID", "").strip())

    elapsed = time.time() - t0
    log.info("Done: %d scored in %.1fs (%.1f jobs/sec)", len(results), elapsed, len(results) / elapsed if elapsed > 0 else 0)

    # Score distribution
    dist = conn.execute("""
        SELECT fit_score, COUNT(*) FROM jobs
        WHERE fit_score IS NOT NULL
        GROUP BY fit_score ORDER BY fit_score DESC
    """).fetchall()
    distribution = [(row[0], row[1]) for row in dist]

    return {
        "scored": len(results),
        "skipped_pre": skipped_pre,
        "errors": errors,
        "elapsed": elapsed,
        "distribution": distribution,
    }
