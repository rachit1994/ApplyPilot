"""Optional local embedding pre-filter for scoring.

This module is intentionally import-safe when sentence-transformers is not
installed. T0/T1 pre-filters and normal LLM scoring continue to work without
the optional embedding extra.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from applypilot import config

log = logging.getLogger(__name__)

MODEL_NAME = "BAAI/bge-small-en-v1.5"
DEFAULT_THRESHOLD = 0.25

try:  # pragma: no cover - depends on optional environment.
    from sentence_transformers import SentenceTransformer as _SentenceTransformer

    _IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - depends on optional environment.
    _SentenceTransformer = None  # type: ignore[assignment]
    _IMPORT_ERROR = exc
    log.info(
        "T2 embedding filter disabled - install with: pip install applypilot[embedding]"
    )

_model: Any | None = None
_model_load_attempted = False
_cached_resume_text: str | None = None
_cached_resume_embedding: Sequence[float] | None = None


@dataclass(frozen=True)
class EmbeddingFilterVerdict:
    passes: bool
    similarity: float | None
    reason: str | None = None


def reset_cache() -> None:
    """Clear in-process embedding cache. Intended for tests."""
    global _model, _model_load_attempted, _cached_resume_text, _cached_resume_embedding
    _model = None
    _model_load_attempted = False
    _cached_resume_text = None
    _cached_resume_embedding = None


def enabled() -> bool:
    """Return True when the optional embedding dependency is importable."""
    return _SentenceTransformer is not None


def threshold_from_profile(profile: dict | None) -> float:
    """Read the embedding pre-filter threshold from profile.json."""
    raw = (profile or {}).get("embedding_threshold", DEFAULT_THRESHOLD)
    try:
        return float(raw)
    except (TypeError, ValueError):
        return DEFAULT_THRESHOLD


def _load_model() -> Any | None:
    global _model, _model_load_attempted

    if _model is not None:
        return _model
    if _SentenceTransformer is None:
        return None
    if not _model_load_attempted:
        model_dir = config.APP_DIR / "models"
        model_dir.mkdir(parents=True, exist_ok=True)
        log.info(
            "Loading T2 embedding model %s from %s; first run may download weights.",
            MODEL_NAME,
            model_dir,
        )
        _model_load_attempted = True
        try:
            _model = _SentenceTransformer(MODEL_NAME, cache_folder=str(model_dir))
        except Exception as exc:
            log.info("T2 embedding filter disabled after model load failed: %s", exc)
            _model = None
    return _model


def encode_resume(resume_text: str) -> Sequence[float] | None:
    """Encode and cache the resume embedding for this Python process."""
    global _cached_resume_text, _cached_resume_embedding

    if _cached_resume_embedding is not None and _cached_resume_text == resume_text:
        return _cached_resume_embedding

    model = _load_model()
    if model is None:
        return None

    _cached_resume_embedding = _to_vector(model.encode(resume_text))
    _cached_resume_text = resume_text
    return _cached_resume_embedding


def pre_filter_job(
    job: dict,
    resume_embedding: Sequence[float] | None,
    *,
    threshold: float = DEFAULT_THRESHOLD,
) -> EmbeddingFilterVerdict:
    """Return a T2 verdict for a job."""
    if resume_embedding is None:
        return EmbeddingFilterVerdict(True, None)

    model = _load_model()
    if model is None:
        return EmbeddingFilterVerdict(True, None)

    job_embedding = _to_vector(model.encode(_job_text(job)))
    similarity = cosine_similarity(resume_embedding, job_embedding)
    if similarity < threshold:
        return EmbeddingFilterVerdict(False, similarity, "embedding_low")
    return EmbeddingFilterVerdict(True, similarity)


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """Compute cosine similarity for two embedding vectors."""
    if not a or not b:
        return 0.0
    dot = sum(float(x) * float(y) for x, y in zip(a, b))
    norm_a = math.sqrt(sum(float(x) * float(x) for x in a))
    norm_b = math.sqrt(sum(float(y) * float(y) for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def _to_vector(value: Any) -> Sequence[float]:
    if hasattr(value, "tolist"):
        value = value.tolist()
    if value and isinstance(value[0], list):
        value = value[0]
    return [float(x) for x in value]


def _job_text(job: dict) -> str:
    return (
        f"TITLE: {job.get('title') or ''}\n"
        f"COMPANY: {job.get('site') or ''}\n"
        f"LOCATION: {job.get('location') or ''}\n"
        f"DESCRIPTION:\n{(job.get('full_description') or job.get('description') or '')[:4000]}"
    )
