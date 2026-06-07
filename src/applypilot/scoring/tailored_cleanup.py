"""Remove per-job tailored resume artifacts after apply consumes them."""

from __future__ import annotations

import logging
from pathlib import Path

from applypilot import config
from applypilot.database import get_connection
from applypilot.db.dialect import scalar

log = logging.getLogger(__name__)


def _tailored_dir() -> Path:
    return config.TAILORED_DIR


def _artifact_stem(path: Path) -> Path:
    """Normalize any tailored artifact path to its base stem (no suffix)."""
    name = path.name
    if name.endswith("_JOB.txt"):
        return path.parent / name[: -len("_JOB.txt")]
    if name.endswith("_REPORT.json"):
        return path.parent / name[: -len("_REPORT.json")]
    return path.with_suffix("")


def tailored_artifact_paths(resume_path: str | Path) -> list[Path]:
    """Return the four standard artifact paths for a tailored resume prefix."""
    stem = _artifact_stem(Path(resume_path))
    base = stem.name
    parent = stem.parent
    return [
        parent / f"{base}.txt",
        parent / f"{base}.pdf",
        parent / f"{base}_JOB.txt",
        parent / f"{base}_REPORT.json",
    ]


def _under_tailored_dir(path: Path) -> bool:
    try:
        path.resolve().relative_to(_tailored_dir().resolve())
    except ValueError:
        return False
    return True


def _other_jobs_still_need_resume(
    conn,
    resume_path: str,
    url: str,
) -> bool:
    row = conn.execute(
        """
        SELECT COUNT(*) FROM jobs
        WHERE tailored_resume_path = ?
          AND url != ?
          AND applied_at IS NULL
          AND COALESCE(apply_status, '') NOT IN ('applied', 'submitted_unverified')
        """,
        (resume_path, url),
    ).fetchone()
    return bool(row and int(scalar(row) or 0) > 0)


def cleanup_tailored_resume_after_use(
    url: str,
    *,
    resume_path: str | None = None,
    conn=None,
) -> int:
    """Delete tailored resume artifacts once apply has used them.

    Only removes files under ``~/.applypilot/tailored_resumes``. Skips deletion when another job
    row still references the same ``tailored_resume_path`` and has not applied.
    """
    owns_conn = conn is None
    if owns_conn:
        conn = get_connection()

    path_value = (resume_path or "").strip()
    if not path_value:
        row = conn.execute(
            "SELECT tailored_resume_path FROM jobs WHERE url = ?",
            (url,),
        ).fetchone()
        path_value = str(row["tailored_resume_path"] or "").strip() if row else ""

    if not path_value:
        return 0

    candidate = Path(path_value)
    if not _under_tailored_dir(candidate):
        return 0

    stored_path = path_value
    if _other_jobs_still_need_resume(conn, stored_path, url):
        log.debug(
            "Skipping tailored cleanup for %s; other jobs still reference %s",
            url[:80],
            stored_path,
        )
        return 0

    removed = 0
    for artifact in tailored_artifact_paths(candidate):
        if not artifact.is_file():
            continue
        if not _under_tailored_dir(artifact):
            continue
        try:
            artifact.unlink()
            removed += 1
        except OSError:
            log.debug("Failed to remove tailored artifact %s", artifact, exc_info=True)

    if removed:
        log.info(
            "Removed %d tailored artifact(s) for %s under %s",
            removed,
            url[:80],
            _tailored_dir(),
        )
    return removed
