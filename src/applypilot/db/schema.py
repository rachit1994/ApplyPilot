"""Postgres DDL for all ApplyPilot tables."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from applypilot.db.connection import Connection

# Forward migrations: column name -> Postgres type (jobs table)
JOBS_EXTRA_COLUMNS: dict[str, str] = {
    "content_hash": "TEXT",
    "sources": "TEXT",
    "pre_fit_score": "INTEGER",
    "pre_filter_reason": "TEXT",
    "pre_filter_rejected_at": "TEXT",
    "referral_connect_at": "TEXT",
    "referral_message_at": "TEXT",
    "referral_status": "TEXT",
    "referral_error": "TEXT",
    "referral_attempts": "INTEGER DEFAULT 0",
    "apply_not_before": "TEXT",
    "role_archetype": "TEXT",
    "role_resume_path": "TEXT",
    "triage_status": "TEXT",
    "triage_reason": "TEXT",
    "triage_at": "TEXT",
    "pdf_path": "TEXT",
    "pdf_at": "TEXT",
    "pdf_attempts": "INTEGER DEFAULT 0",
}

INBOX_OPPORTUNITY_COLUMNS: dict[str, str] = {
    "intent": "TEXT",
    "intent_confidence": "REAL",
    "apply_url": "TEXT",
    "ats_vendor": "TEXT",
}

INBOX_REPLY_COLUMNS: dict[str, str] = {
    "approved_at": "TEXT",
    "approved_by": "TEXT",
}


TABLES_WITH_SERIAL_ID: tuple[str, ...] = (
    "llm_usage_events",
    "dashboard_activity_events",
    "apply_outcomes",
    "review_log",
    "run_events",
    "inbox_audit_events",
)


def sync_serial_sequences(conn: Connection) -> None:
    """Align BIGSERIAL sequences after bulk imports that set explicit ids."""
    from applypilot.db.dialect import table_exists

    for table in TABLES_WITH_SERIAL_ID:
        if not table_exists(conn, table):
            continue
        row = conn.execute(
            "SELECT pg_get_serial_sequence(%s, 'id') AS seq",
            (table,),
        ).fetchone()
        if not row or not row["seq"]:
            continue
        conn.execute(
            f"""
            SELECT setval(
                %s,
                (SELECT COALESCE(MAX(id), 0) FROM {table}) + 1,
                false
            )
            """,
            (row["seq"],),
        )


def init_schema(conn: Connection) -> None:
    """Create all tables and indexes (idempotent)."""
    _create_jobs(conn)
    _create_discover_source_stats(conn)
    _create_llm_usage_events(conn)
    _create_dashboard_activity_events(conn)
    _create_qa_bank(conn)
    _create_apply_outcomes(conn)
    _create_field_overrides(conn)
    _create_playbook(conn)
    _create_review_log(conn)
    _create_runs(conn)
    _create_inbox(conn)
    ensure_jobs_columns(conn)
    ensure_apply_outcomes_columns(conn)
    ensure_inbox_columns(conn)
    sync_serial_sequences(conn)
    conn.commit()


def ensure_jobs_columns(conn: Connection) -> list[str]:
    from applypilot.db.dialect import table_columns

    existing = table_columns(conn, "jobs")
    added: list[str] = []
    for col, dtype in JOBS_EXTRA_COLUMNS.items():
        if col not in existing:
            if "PRIMARY KEY" in dtype:
                continue
            conn.execute(f"ALTER TABLE jobs ADD COLUMN IF NOT EXISTS {col} {dtype}")
            added.append(col)
    return added


def ensure_apply_outcomes_columns(conn: Connection) -> None:
    from applypilot.db.dialect import table_columns

    cols = table_columns(conn, "apply_outcomes")
    if "canonical_url" not in cols:
        conn.execute("ALTER TABLE apply_outcomes ADD COLUMN IF NOT EXISTS canonical_url TEXT")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_apply_outcomes_canonical_created "
        "ON apply_outcomes(canonical_url, created_at)"
    )


def ensure_inbox_columns(conn: Connection) -> list[str]:
    from applypilot.db.dialect import table_columns

    added: list[str] = []
    opp_cols = table_columns(conn, "inbox_opportunities")
    for col, dtype in INBOX_OPPORTUNITY_COLUMNS.items():
        if col not in opp_cols:
            conn.execute(
                f"ALTER TABLE inbox_opportunities ADD COLUMN IF NOT EXISTS {col} {dtype}"
            )
            added.append(f"inbox_opportunities.{col}")

    reply_cols = table_columns(conn, "inbox_replies")
    for col, dtype in INBOX_REPLY_COLUMNS.items():
        if col not in reply_cols:
            conn.execute(f"ALTER TABLE inbox_replies ADD COLUMN IF NOT EXISTS {col} {dtype}")
            added.append(f"inbox_replies.{col}")
    return added


def _create_jobs(conn: Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS jobs (
            url                   TEXT PRIMARY KEY,
            title                 TEXT,
            salary                TEXT,
            description           TEXT,
            location              TEXT,
            site                  TEXT,
            content_hash          TEXT,
            sources               TEXT,
            strategy              TEXT,
            discovered_at         TEXT,
            full_description      TEXT,
            application_url       TEXT,
            detail_scraped_at     TEXT,
            detail_error          TEXT,
            pre_fit_score         INTEGER,
            pre_filter_reason     TEXT,
            pre_filter_rejected_at TEXT,
            fit_score             INTEGER,
            score_reasoning       TEXT,
            scored_at             TEXT,
            tailored_resume_path  TEXT,
            tailored_at           TEXT,
            tailor_attempts       INTEGER DEFAULT 0,
            cover_letter_path     TEXT,
            cover_letter_at       TEXT,
            cover_attempts        INTEGER DEFAULT 0,
            applied_at            TEXT,
            apply_status          TEXT,
            apply_error           TEXT,
            apply_attempts        INTEGER DEFAULT 0,
            agent_id              TEXT,
            last_attempted_at     TEXT,
            apply_duration_ms     INTEGER,
            apply_task_id         TEXT,
            verification_confidence TEXT
        )
        """
    )


def _create_discover_source_stats(conn: Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS discover_source_stats (
            source TEXT NOT NULL,
            run_id TEXT NOT NULL,
            discovered INTEGER DEFAULT 0,
            passed_filter INTEGER DEFAULT 0,
            scored_ge7 INTEGER DEFAULT 0,
            tailored INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        )
        """
    )


def _create_llm_usage_events(conn: Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS llm_usage_events (
            id BIGSERIAL PRIMARY KEY,
            provider TEXT NOT NULL,
            model TEXT NOT NULL,
            operation TEXT NOT NULL,
            input_tokens INTEGER DEFAULT 0,
            output_tokens INTEGER DEFAULT 0,
            cache_read_tokens INTEGER DEFAULT 0,
            cache_create_tokens INTEGER DEFAULT 0,
            estimated INTEGER DEFAULT 1,
            cost_usd DOUBLE PRECISION DEFAULT 0,
            created_at TEXT NOT NULL,
            metadata_json TEXT
        )
        """
    )


def _create_dashboard_activity_events(conn: Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS dashboard_activity_events (
            id BIGSERIAL PRIMARY KEY,
            ts TEXT NOT NULL,
            level TEXT NOT NULL DEFAULT 'info',
            stage TEXT,
            message TEXT NOT NULL,
            run_id TEXT,
            job_url TEXT,
            meta_json TEXT
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_dashboard_activity_id "
        "ON dashboard_activity_events(id)"
    )


def _create_qa_bank(conn: Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS qa_bank (
            question_key   TEXT PRIMARY KEY,
            question_text  TEXT,
            answer         TEXT,
            answer_type    TEXT,
            section_header TEXT,
            name_attr      TEXT,
            scope          TEXT DEFAULT 'generic',
            source         TEXT DEFAULT 'gemini',
            hit_count      INTEGER DEFAULT 0,
            created_at     TEXT,
            updated_at     TEXT
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_qa_bank_hit_count ON qa_bank(hit_count)"
    )


def _create_apply_outcomes(conn: Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS apply_outcomes (
            id              BIGSERIAL PRIMARY KEY,
            url             TEXT NOT NULL,
            canonical_url   TEXT,
            ats_family      TEXT,
            fingerprint     TEXT,
            result          TEXT,
            tier_resolved   INTEGER,
            escalated       INTEGER DEFAULT 0,
            escalate_reason TEXT,
            fields_total    INTEGER DEFAULT 0,
            fields_llm      INTEGER DEFAULT 0,
            elapsed_ms      INTEGER,
            created_at      TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_apply_outcomes_created "
        "ON apply_outcomes(created_at)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_apply_outcomes_fingerprint "
        "ON apply_outcomes(fingerprint)"
    )


def _create_field_overrides(conn: Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS field_overrides (
            label_key  TEXT PRIMARY KEY,
            label      TEXT,
            value      TEXT,
            created_at TEXT,
            updated_at TEXT
        )
        """
    )


def _create_playbook(conn: Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS nav_playbook (
            state_sig        TEXT NOT NULL,
            sig_version      INTEGER NOT NULL DEFAULT 1,
            scope            TEXT NOT NULL DEFAULT 'host',
            ats_family       TEXT,
            apex_host        TEXT,
            step_name        TEXT,
            preconditions    TEXT,
            action_type      TEXT,
            action_args      TEXT,
            side_effecting   INTEGER NOT NULL DEFAULT 0,
            goto_allowlist   TEXT,
            status           TEXT NOT NULL DEFAULT 'trial',
            promote_score    DOUBLE PRECISION NOT NULL DEFAULT 0.0,
            success_weak     INTEGER NOT NULL DEFAULT 0,
            success_receipt  INTEGER NOT NULL DEFAULT 0,
            distinct_hosts   INTEGER NOT NULL DEFAULT 0,
            fail_count       INTEGER NOT NULL DEFAULT 0,
            source           TEXT,
            created_at       TEXT,
            last_used_at     TEXT,
            last_verified_at TEXT,
            PRIMARY KEY (state_sig, scope)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS field_strategy (
            field_sig      TEXT NOT NULL,
            ats_family     TEXT NOT NULL,
            fill_method    TEXT NOT NULL,
            match_rule     TEXT,
            status         TEXT NOT NULL DEFAULT 'trial',
            success_count  INTEGER NOT NULL DEFAULT 0,
            fail_count     INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (field_sig, ats_family)
        )
        """
    )


def _create_review_log(conn: Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS review_log (
            id BIGSERIAL PRIMARY KEY,
            ts TEXT,
            job_url TEXT,
            ats_family TEXT,
            apex_host TEXT,
            state_sig TEXT,
            scope TEXT,
            step_index INTEGER,
            url_before TEXT,
            url_after TEXT,
            frame_info TEXT,
            tier TEXT,
            action_type TEXT,
            action_args TEXT,
            locator TEXT,
            llm_suggestion TEXT,
            outcome TEXT,
            postcondition_met INTEGER,
            receipt_status TEXT,
            screenshot_path TEXT,
            failure_reason TEXT,
            cost_usd DOUBLE PRECISION
        )
        """
    )


def _create_runs(conn: Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS runs (
            id              TEXT PRIMARY KEY,
            run_type        TEXT NOT NULL DEFAULT 'pipeline',
            status          TEXT NOT NULL DEFAULT 'starting',
            stages_json     TEXT,
            stream          INTEGER NOT NULL DEFAULT 0,
            dry_run         INTEGER NOT NULL DEFAULT 0,
            current_stage   TEXT,
            exit_code       INTEGER,
            error_message   TEXT,
            started_at      TEXT NOT NULL,
            finished_at     TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS run_events (
            id              BIGSERIAL PRIMARY KEY,
            run_id          TEXT NOT NULL REFERENCES runs(id),
            event_type      TEXT NOT NULL,
            stage           TEXT,
            level           TEXT,
            message         TEXT,
            payload_json    TEXT,
            created_at      TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_run_events_run_id ON run_events(run_id, id)"
    )


def _create_inbox(conn: Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS inbox_threads (
            conversation_urn TEXT PRIMARY KEY,
            participant_public_id TEXT NOT NULL,
            folder TEXT NOT NULL DEFAULT 'other',
            last_message_at TEXT,
            last_inbound_at TEXT,
            last_outbound_at TEXT,
            last_scanned_at TEXT,
            latest_inbound_text TEXT
        );

        CREATE TABLE IF NOT EXISTS inbox_messages (
            linkedin_message_urn TEXT PRIMARY KEY,
            conversation_urn TEXT NOT NULL REFERENCES inbox_threads(conversation_urn),
            is_outgoing INTEGER NOT NULL DEFAULT 0,
            body TEXT,
            sent_at TEXT
        );

        CREATE TABLE IF NOT EXISTS inbox_opportunities (
            conversation_urn TEXT PRIMARY KEY REFERENCES inbox_threads(conversation_urn),
            is_job_related INTEGER NOT NULL DEFAULT 0,
            confidence DOUBLE PRECISION,
            extracted_title TEXT,
            extracted_company TEXT,
            reasoning TEXT,
            classified_at TEXT
        );

        CREATE TABLE IF NOT EXISTS inbox_replies (
            conversation_urn TEXT PRIMARY KEY REFERENCES inbox_threads(conversation_urn),
            reply_status TEXT NOT NULL DEFAULT 'pending',
            reply_message TEXT,
            reply_mode TEXT,
            drafted_at TEXT,
            sent_at TEXT,
            skip_reason TEXT,
            error TEXT
        );

        CREATE TABLE IF NOT EXISTS inbox_audit_events (
            id BIGSERIAL PRIMARY KEY,
            conversation_urn TEXT,
            event_type TEXT NOT NULL,
            payload_json TEXT,
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_inbox_threads_public_id
            ON inbox_threads(participant_public_id);
        CREATE INDEX IF NOT EXISTS idx_inbox_replies_status
            ON inbox_replies(reply_status);
        CREATE INDEX IF NOT EXISTS idx_inbox_audit_urn
            ON inbox_audit_events(conversation_urn);
        CREATE INDEX IF NOT EXISTS idx_inbox_audit_created
            ON inbox_audit_events(created_at);

        CREATE TABLE IF NOT EXISTS inbox_gmail_messages (
            message_id TEXT PRIMARY KEY,
            thread_id TEXT,
            from_address TEXT,
            subject TEXT,
            snippet TEXT,
            received_at TEXT,
            intent TEXT,
            intent_confidence DOUBLE PRECISION,
            extracted_title TEXT,
            extracted_company TEXT,
            reasoning TEXT,
            classified_at TEXT,
            matched_job_url TEXT,
            matched_at TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_inbox_gmail_classified
            ON inbox_gmail_messages(classified_at);
        CREATE INDEX IF NOT EXISTS idx_inbox_gmail_matched
            ON inbox_gmail_messages(matched_job_url)
        """
    )


TABLES_MIGRATION_ORDER: list[str] = [
    "jobs",
    "discover_source_stats",
    "llm_usage_events",
    "dashboard_activity_events",
    "qa_bank",
    "apply_outcomes",
    "field_overrides",
    "nav_playbook",
    "field_strategy",
    "review_log",
    "runs",
    "run_events",
    "inbox_threads",
    "inbox_messages",
    "inbox_opportunities",
    "inbox_replies",
    "inbox_audit_events",
    "inbox_gmail_messages",
]
