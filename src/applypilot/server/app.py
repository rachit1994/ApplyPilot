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
from applypilot.server.schemas import (
    ApplicationDetailResponse,
    ApplicationRow,
    ApplicationsResponse,
    JobRow,
    JobsResponse,
    StatsResponse,
)
from applypilot.server.stats import fetch_stats

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DASHBOARD_DIST = _REPO_ROOT / "dashboard" / "web" / "dist"


def create_app() -> FastAPI:
    load_env()
    ensure_dirs()
    init_db()

    app = FastAPI(title="ApplyPilot Dashboard", version="0.1.0")
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

    @api.get("/stats", response_model=StatsResponse)
    def api_stats() -> StatsResponse:
        return StatsResponse(stats=fetch_stats())


    @api.get("/jobs", response_model=JobsResponse)
    def api_jobs(
        min_score: int | None = None,
        site: str | None = None,
        search: str | None = None,
        sort: str = "activity_desc",
        limit: int = 100,
        offset: int = 0,
    ) -> JobsResponse:
        rows, total = jobs_module.query_jobs(
            min_score=min_score,
            site=site,
            search=search,
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
    ) -> ApplicationsResponse:
        rows, total = applications_module.query_applied_jobs(
            limit=min(limit, 500),
            offset=offset,
            include_failed=include_failed,
        )
        return ApplicationsResponse(
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
