"""FastAPI application factory."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from applypilot.config import APP_DIR, load_env, ensure_dirs
from applypilot.dashboard_settings import bootstrap_dashboard_settings, save_agent_settings
from applypilot.database import init_db
from applypilot.server import activity as activity_module
from applypilot.server import events as events_routes
from applypilot.server import jobs as jobs_module
from applypilot.server import runs as runs_routes
from applypilot.server import workers as workers_module
from applypilot.server import applications as applications_module
from applypilot.server import referrals as referrals_module
from applypilot.server import inbox as inbox_module
from applypilot.server import login as login_module
from applypilot.server import learning as learning_module
from applypilot.server import llm_usage_api
from applypilot.server.schemas import (
    ApplicationDetailResponse,
    ApplicationRow,
    ApplicationsResponse,
    AttentionApplicationsResponse,
    ApplyErrorSummaryResponse,
    ApplyErrorSummaryRow,
    JobRow,
    JobsResponse,
    TriageCountsResponse,
    LlmUsageResponse,
    OverviewResponse,
    ReferralActionRequest,
    ReferralActionResponse,
    ReferralActionResult,
    ReferralRow,
    ReferralsResponse,
    SourceStatsResponse,
    SourceStatsRow,
    StatsResponse,
    AgentSettingsPayload,
    AgentSettingsResponse,
    AgentSettingsPatch,
    BulkStageRequest,
)
from applypilot.orchestration.run_controller import reconcile_orphaned_runs
from applypilot.server.overview import build_overview
from applypilot.server.stats import fetch_source_stats, fetch_stats

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DASHBOARD_DIST = _REPO_ROOT / "dashboard" / "web" / "dist"


def create_app() -> FastAPI:
    load_env()
    ensure_dirs()
    bootstrap_dashboard_settings()
    init_db()

    app = FastAPI(title="ApplyPilot Dashboard", version="0.1.0")

    @app.on_event("startup")
    def _on_startup() -> None:
        n = reconcile_orphaned_runs()
        if n:
            import logging

            logging.getLogger(__name__).info(
                "Reconciled %d orphaned dashboard run(s) after startup", n
            )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://127.0.0.1:5173",
            "http://localhost:5173",
            "http://127.0.0.1:9477",
            "http://127.0.0.1:5174",
            "http://localhost:5174",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    api = FastAPI()
    api.include_router(runs_routes.router)
    api.include_router(events_routes.router)
    api.include_router(inbox_module.router)
    api.include_router(activity_module.router)
    api.include_router(workers_module.router)
    api.include_router(login_module.router)
    api.include_router(learning_module.router)

    @api.get("/overview", response_model=OverviewResponse)
    def api_overview() -> OverviewResponse:
        return OverviewResponse.model_validate(build_overview())

    @api.get("/llm-usage", response_model=LlmUsageResponse)
    def api_llm_usage(month: str | None = None) -> LlmUsageResponse:
        payload = llm_usage_api.build_llm_usage_detail(month=month)
        return LlmUsageResponse.model_validate(payload)

    @api.get("/stats", response_model=StatsResponse)
    def api_stats() -> StatsResponse:
        return StatsResponse(stats=fetch_stats())

    @api.get("/source-stats", response_model=SourceStatsResponse)
    def api_source_stats(days: int = 7) -> SourceStatsResponse:
        rows = fetch_source_stats(days=max(1, min(days, 90)))
        return SourceStatsResponse(sources=[SourceStatsRow(**r) for r in rows])

    @api.get("/jobs", response_model=JobsResponse)
    def api_jobs(
        min_score: int | None = None,
        site: str | None = None,
        search: str | None = None,
        pipeline_stage: str | None = None,
        stage: str | None = None,
        apply_status: str | None = None,
        low_score_reason: str | None = None,
        sort: str = "activity_desc",
        limit: int = 50,
        offset: int = 0,
        page: int | None = None,
    ) -> JobsResponse:
        limit, query_offset, current_page, _ = jobs_module.resolve_jobs_pagination(
            limit=limit,
            offset=offset,
            page=page,
            total=0,
        )
        rows, total = jobs_module.query_jobs(
            min_score=min_score,
            site=site,
            search=search,
            pipeline_stage=pipeline_stage,
            stage=stage,
            apply_status=apply_status,
            low_score_reason=low_score_reason,
            sort=sort,
            limit=limit,
            offset=query_offset,
        )
        limit, offset, current_page, pages = jobs_module.resolve_jobs_pagination(
            limit=limit,
            offset=query_offset,
            page=page if page is not None else current_page,
            total=total,
        )
        if offset != query_offset:
            rows, total = jobs_module.query_jobs(
                min_score=min_score,
                site=site,
                search=search,
                pipeline_stage=pipeline_stage,
                stage=stage,
                apply_status=apply_status,
                low_score_reason=low_score_reason,
                sort=sort,
                limit=limit,
                offset=offset,
            )
        return JobsResponse(
            jobs=[JobRow(**r) for r in rows],
            total=total,
            limit=limit,
            offset=offset,
            page=current_page,
            pages=pages,
        )

    @api.get("/jobs/triage-counts", response_model=TriageCountsResponse)
    def api_jobs_triage_counts(
        min_score: int | None = None,
        site: str | None = None,
        search: str | None = None,
        apply_status: str | None = None,
        low_score_reason: str | None = None,
    ) -> TriageCountsResponse:
        counts = jobs_module.fetch_triage_counts_filtered(
            min_score=min_score,
            site=site,
            search=search,
            apply_status=apply_status,
            low_score_reason=low_score_reason,
        )
        return TriageCountsResponse(counts=counts)

    @api.get("/jobs/recent", response_model=JobsResponse)
    def api_jobs_recent(minutes: int = 60, limit: int = 50) -> JobsResponse:
        rows = jobs_module.query_recent_jobs(minutes=minutes, limit=min(limit, 200))
        return JobsResponse(jobs=[JobRow(**r) for r in rows], total=len(rows))

    @api.get("/applications", response_model=ApplicationsResponse)
    def api_applications(
        limit: int = 100,
        offset: int = 0,
        include_failed: bool = False,
        status: str | None = None,
        site: str | None = None,
        search: str | None = None,
        claude_escalated: bool = False,
        needs_attention: bool = False,
    ) -> ApplicationsResponse:
        rows, total = applications_module.query_applied_jobs(
            limit=min(limit, 500),
            offset=offset,
            include_failed=include_failed,
            status=status,
            site=site,
            search=search,
            claude_escalated=claude_escalated,
            needs_attention=needs_attention,
        )
        return ApplicationsResponse(
            applications=[ApplicationRow(**r) for r in rows],
            total=total,
        )

    @api.get("/applications/errors", response_model=ApplyErrorSummaryResponse)
    def api_application_errors() -> ApplyErrorSummaryResponse:
        rows = applications_module.query_apply_error_summary()
        return ApplyErrorSummaryResponse(
            groups=[ApplyErrorSummaryRow(**r) for r in rows],
        )

    @api.get("/applications/attention", response_model=AttentionApplicationsResponse)
    def api_applications_attention(limit: int = 200, offset: int = 0) -> AttentionApplicationsResponse:
        rows, total = applications_module.query_attention_jobs(
            limit=min(limit, 500),
            offset=offset,
        )
        return AttentionApplicationsResponse(
            applications=[ApplicationRow(**r) for r in rows],
            total=total,
        )

    @api.get("/applications/detail", response_model=ApplicationDetailResponse)
    def api_application_detail(url: str) -> ApplicationDetailResponse:
        row = applications_module.get_application_detail(url)
        if not row:
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail="Application not found")
        return ApplicationDetailResponse(application=row)

    @api.get("/artifacts/file")
    def api_artifact_file(path: str):
        from fastapi import HTTPException
        from fastapi.responses import RedirectResponse

        from applypilot.server import artifacts as artifacts_module

        try:
            target = artifacts_module.resolve_artifact_path(path)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return RedirectResponse(url=target.as_uri(), status_code=302)

    @api.get("/field-overrides")
    def api_list_field_overrides() -> dict[str, object]:
        from applypilot.database import list_field_overrides

        return {"overrides": list_field_overrides()}

    @api.post("/field-overrides")
    def api_set_field_override(label: str, value: str) -> dict[str, object]:
        """Save a correction applied to this field on every future form."""
        from fastapi import HTTPException

        from applypilot.database import set_field_override

        if not (label or "").strip():
            raise HTTPException(status_code=400, detail="label is required")
        set_field_override(label, value)
        return {"ok": True, "label": label, "value": value}

    @api.delete("/field-overrides")
    def api_delete_field_override(label: str) -> dict[str, object]:
        from applypilot.database import delete_field_override

        return {"ok": delete_field_override(label), "label": label}

    @api.post("/applications/confirm")
    def api_confirm_application(url: str) -> dict[str, object]:
        from fastapi import HTTPException

        if not applications_module.confirm_application(url):
            raise HTTPException(status_code=404, detail="Application not found")
        return {"ok": True, "url": url}

    @api.post("/applications/retry")
    def api_retry_application(url: str) -> dict[str, object]:
        from fastapi import HTTPException

        if not applications_module.retry_application(url):
            raise HTTPException(status_code=404, detail="Application not found")
        return {"ok": True, "url": url}

    @api.post("/applications/mark-applied")
    def api_mark_applied(url: str) -> dict[str, object]:
        from fastapi import HTTPException

        if not applications_module.mark_application_applied(url):
            raise HTTPException(status_code=404, detail="Application not found")
        return {"ok": True, "url": url}

    @api.post("/applications/requeue")
    def api_requeue_application(url: str) -> dict[str, object]:
        from fastapi import HTTPException

        if not applications_module.requeue_application(url):
            raise HTTPException(status_code=404, detail="Application not found")
        return {"ok": True, "url": url}

    @api.post("/applications/stage")
    def api_stage_application(url: str) -> dict[str, object]:
        from fastapi import HTTPException

        if not applications_module.stage_application(url):
            raise HTTPException(status_code=404, detail="Job not in prepare review")
        return {"ok": True, "url": url}

    @api.post("/applications/unstage")
    def api_unstage_application(url: str) -> dict[str, object]:
        from fastapi import HTTPException

        if not applications_module.unstage_application(url):
            raise HTTPException(status_code=404, detail="Job not staged")
        return {"ok": True, "url": url}

    @api.post("/applications/bulk-stage")
    def api_bulk_stage(body: BulkStageRequest) -> dict[str, object]:
        from fastapi import HTTPException

        try:
            result = applications_module.bulk_stage_applications(body.urls, body.action)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return result

    @api.get("/referrals", response_model=ReferralsResponse)
    def api_referrals(
        filter: str = "all",
        search: str | None = None,
        min_score: int | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> ReferralsResponse:
        rows, total, meta = referrals_module.query_referrals(
            filter_name=filter,
            search=search,
            min_score=min_score,
            limit=min(limit, 500),
            offset=offset,
        )
        return ReferralsResponse(
            referrals=[ReferralRow(**r) for r in rows],
            total=total,
            meta=meta,
        )

    @api.post("/referrals/actions", response_model=ReferralActionResponse)
    def api_referral_actions(body: ReferralActionRequest) -> ReferralActionResponse:
        from fastapi import HTTPException

        if not body.urls:
            raise HTTPException(status_code=400, detail="urls required")
        try:
            payload = referrals_module.run_referral_actions(body.action, body.urls)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return ReferralActionResponse(
            action=payload["action"],
            results=[ReferralActionResult(**r) for r in payload["results"]],
            summary=payload.get("summary") or {},
        )

    @api.get("/settings/agent", response_model=AgentSettingsResponse)
    def api_get_agent_settings() -> AgentSettingsResponse:
        from applypilot.dashboard_settings import load_dashboard_settings

        payload = load_dashboard_settings()
        return AgentSettingsResponse(
            agent=AgentSettingsPayload.model_validate(payload["agent"]),
            updated_at=payload.get("updated_at"),
        )

    @api.patch("/settings/agent", response_model=AgentSettingsResponse)
    def api_patch_agent_settings(body: AgentSettingsPatch) -> AgentSettingsResponse:
        patch = body.model_dump(exclude_unset=True)
        if not patch:
            from fastapi import HTTPException

            raise HTTPException(status_code=400, detail="No settings fields provided")
        saved = save_agent_settings(patch)
        return AgentSettingsResponse(
            agent=AgentSettingsPayload.model_validate(saved["agent"]),
            updated_at=saved.get("updated_at"),
        )

    @api.get("/meta/stages")
    def api_stages() -> dict:
        from applypilot.pipeline import STAGE_META, STAGE_ORDER

        return {
            "order": list(STAGE_ORDER),
            "meta": STAGE_META,
        }

    app.mount("/api", api)

    @app.get("/health")
    def health():
        from applypilot.config import DATABASE_URL
        from applypilot.db.status import database_status, redact_database_url

        payload = {"status": "ok", "app_dir": str(APP_DIR), "database": redact_database_url(DATABASE_URL)}
        try:
            info = database_status()
            payload["jobs"] = info.get("table_counts", {}).get("jobs", 0)
            payload["total_rows"] = info.get("total_rows", 0)
        except ConnectionError as exc:
            payload["status"] = "degraded"
            payload["database_error"] = str(exc)
        return payload

    if _DASHBOARD_DIST.is_dir():
        assets = _DASHBOARD_DIST / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/")
        def spa_index():
            return FileResponse(_DASHBOARD_DIST / "index.html")

        @app.get("/{full_path:path}")
        def spa_fallback(full_path: str):
            if full_path.startswith("api"):
                return {"detail": "Not Found"}
            target = _DASHBOARD_DIST / full_path
            if target.is_file():
                return FileResponse(target)
            return FileResponse(_DASHBOARD_DIST / "index.html")

    return app
