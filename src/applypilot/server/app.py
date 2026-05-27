"""FastAPI application factory."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from applypilot.config import APP_DIR, load_env, ensure_dirs
from applypilot.database import init_db
from applypilot.server import events as events_routes
from applypilot.server import jobs as jobs_module
from applypilot.server import runs as runs_routes
from applypilot.server import applications as applications_module
from applypilot.server import referrals as referrals_module
from applypilot.server import inbox as inbox_module
from applypilot.server.schemas import (
    ApplicationDetailResponse,
    ApplicationRow,
    ApplicationsResponse,
    AttentionApplicationsResponse,
    ApplyErrorSummaryResponse,
    ApplyErrorSummaryRow,
    JobRow,
    JobsResponse,
    ReferralActionRequest,
    ReferralActionResponse,
    ReferralActionResult,
    ReferralRow,
    ReferralsResponse,
    SourceStatsResponse,
    SourceStatsRow,
    StatsResponse,
)
from applypilot.orchestration.run_controller import reconcile_orphaned_runs
from applypilot.server.stats import fetch_source_stats, fetch_stats

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DASHBOARD_DIST = _REPO_ROOT / "dashboard" / "web" / "dist"


def create_app() -> FastAPI:
    load_env()
    ensure_dirs()
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
            "http://localhost:9477",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    api = FastAPI()
    api.include_router(runs_routes.router)
    api.include_router(events_routes.router)
    api.include_router(inbox_module.router)

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
        sort: str = "activity_desc",
        limit: int = 100,
        offset: int = 0,
    ) -> JobsResponse:
        rows, total = jobs_module.query_jobs(
            min_score=min_score,
            site=site,
            search=search,
            pipeline_stage=pipeline_stage,
            stage=stage,
            apply_status=apply_status,
            sort=sort,
            limit=min(limit, 500),
            offset=offset,
        )
        return JobsResponse(jobs=[JobRow(**r) for r in rows], total=total)

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
    ) -> ApplicationsResponse:
        rows, total = applications_module.query_applied_jobs(
            limit=min(limit, 500),
            offset=offset,
            include_failed=include_failed,
            status=status,
            site=site,
            search=search,
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
        return {"status": "ok", "app_dir": str(APP_DIR)}

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
