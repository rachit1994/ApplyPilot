from __future__ import annotations

from pathlib import Path

import pytest

from applypilot import config
from applypilot import database
from applypilot.scoring import tailored_cleanup


@pytest.fixture
def cleanup_env(tmp_path: Path, monkeypatch):
    tailored_dir = tmp_path / "tailored_resumes"
    tailored_dir.mkdir()
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "TAILORED_DIR", tailored_dir)
    database.close_connection()
    conn = database.init_db()
    yield conn, tailored_dir
    database.close_connection()


def _write_tailored_set(tailored_dir: Path, prefix: str) -> Path:
    txt = tailored_dir / f"{prefix}.txt"
    txt.write_text("resume body", encoding="utf-8")
    (tailored_dir / f"{prefix}.pdf").write_bytes(b"%PDF-1.4\n")
    (tailored_dir / f"{prefix}_JOB.txt").write_text("job desc", encoding="utf-8")
    (tailored_dir / f"{prefix}_REPORT.json").write_text("{}", encoding="utf-8")
    return txt


def test_cleanup_removes_all_artifacts(cleanup_env):
    conn, tailored_dir = cleanup_env
    txt = _write_tailored_set(tailored_dir, "Acme_Engineer")
    conn.execute(
        """
        INSERT INTO jobs (url, title, site, tailored_resume_path, apply_status)
        VALUES ('https://a.test/1', 'Engineer', 'Acme', ?, 'applied')
        """,
        (str(txt),),
    )
    conn.commit()

    removed = tailored_cleanup.cleanup_tailored_resume_after_use(
        "https://a.test/1",
        conn=conn,
    )

    assert removed == 4
    assert not any(p.exists() for p in tailored_cleanup.tailored_artifact_paths(txt))


def test_cleanup_skips_outside_tailored_dir(cleanup_env, tmp_path: Path):
    conn, _tailored_dir = cleanup_env
    outside = tmp_path / "role_resumes" / "resume.pdf"
    outside.parent.mkdir(parents=True)
    outside.write_bytes(b"%PDF-1.4\n")
    conn.execute(
        """
        INSERT INTO jobs (url, title, site, tailored_resume_path, apply_status)
        VALUES ('https://a.test/2', 'Engineer', 'Acme', ?, 'applied')
        """,
        (str(outside),),
    )
    conn.commit()

    removed = tailored_cleanup.cleanup_tailored_resume_after_use(
        "https://a.test/2",
        conn=conn,
    )

    assert removed == 0
    assert outside.is_file()


def test_cleanup_skips_when_other_job_still_needs_path(cleanup_env):
    conn, tailored_dir = cleanup_env
    txt = _write_tailored_set(tailored_dir, "Shared_Role")
    path = str(txt)
    conn.executemany(
        """
        INSERT INTO jobs (url, title, site, tailored_resume_path, apply_status)
        VALUES (?, 'Engineer', 'Acme', ?, ?)
        """,
        [
            ("https://a.test/applied", path, "applied"),
            ("https://a.test/queued", path, None),
        ],
    )
    conn.commit()

    removed = tailored_cleanup.cleanup_tailored_resume_after_use(
        "https://a.test/applied",
        conn=conn,
    )

    assert removed == 0
    assert txt.is_file()


def test_mark_result_triggers_cleanup(cleanup_env, monkeypatch):
    conn, tailored_dir = cleanup_env
    txt = _write_tailored_set(tailored_dir, "Via_Mark")
    conn.execute(
        """
        INSERT INTO jobs (url, title, site, tailored_resume_path)
        VALUES ('https://a.test/3', 'Engineer', 'Via', ?)
        """,
        (str(txt),),
    )
    conn.commit()

    from applypilot.apply import launcher

    monkeypatch.setattr(database, "get_connection", lambda: conn)
    launcher.mark_result("https://a.test/3", "applied")

    assert not txt.is_file()
    assert not (tailored_dir / "Via_Mark.pdf").is_file()
