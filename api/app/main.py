"""FastAPI application factory, background loops and middleware."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, ORJSONResponse

from . import metrics, queue
from .activity import activity
from .config import settings
from .db import SessionLocal, dispose_db, init_db
from .routers import admin, evals, health, images, jobs, profiles, showcase, workers
from .security import prune_rate_events
from .version import VERSION

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
log = logging.getLogger("smriti.api")

DESCRIPTION = """
Control plane for **Smriti** - diffusion-based restoration of damaged and ageing
photographs.

Upload a photograph, pick a profile, and a pipeline runs in a fixed order: damage
repair, denoise, optional colourisation, super-resolution, then face restoration.
Each stage is independently reported, timed and retried.

GPU workers **pull** work from `/v1/worker/claim`, so inference runs wherever a
CUDA device happens to be while this API stays on a small always-on CPU box.
Leases, heartbeats and bounded retries mean a worker dying mid-pipeline costs a
retry, not the photograph.

**Privacy:** these are personal photographs. Sources and results are private by
default, deleted on a short clock, and a caller can erase their own job
immediately with `DELETE /v1/jobs/{id}`. Nothing reaches the public showcase
without both an uploader opt-in and an explicit admin action.
"""


MAX_IDLE_REAP_INTERVAL = 300.0


async def _reaper_loop() -> None:
    """Recover jobs whose worker vanished.

    Tight interval while there is activity, backing off to a few minutes once the
    queue and the worker pool are both empty. An idle deployment should not wake
    a serverless database every fifteen seconds to learn nothing.
    """
    while True:
        await asyncio.sleep(
            activity.next_interval(settings.reaper_interval_seconds, MAX_IDLE_REAP_INTERVAL)
        )
        try:
            async with SessionLocal() as session:
                requeued, failed = await queue.reap_expired_leases(session)
                counts = await queue.refresh_gauges(session)
                activity.note_sweep(
                    bool(
                        requeued
                        or failed
                        or counts["queued"]
                        or counts["running"]
                        or counts["workers_online"]
                    )
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("reaper iteration failed")


async def _retention_loop() -> None:
    """Keep the free-tier database inside its storage budget."""
    while True:
        await asyncio.sleep(settings.retention_interval_seconds)
        try:
            async with SessionLocal() as session:
                await queue.prune_images(session)
                await prune_rate_events(session)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("retention iteration failed")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    await init_db()
    tasks = [
        asyncio.create_task(_reaper_loop(), name="lease-reaper"),
        asyncio.create_task(_retention_loop(), name="retention"),
    ]
    log.info("%s %s up (%s)", settings.app_name, VERSION, settings.environment)
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await dispose_db()
        log.info("shutdown complete")


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version=VERSION,
        description=DESCRIPTION,
        default_response_class=ORJSONResponse,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url=None,
        openapi_url="/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins or ["*"],
        allow_origin_regex=r"https://.*\.vercel\.app",
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["X-Image-Width", "X-Image-Height", "Retry-After"],
        max_age=3600,
    )

    @app.middleware("http")
    async def observe(request: Request, call_next):
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            metrics.http_requests.labels(
                method=request.method, path=_route_label(request), status="500"
            ).inc()
            raise
        elapsed = time.perf_counter() - started
        label = _route_label(request)
        metrics.http_requests.labels(
            method=request.method, path=label, status=str(response.status_code)
        ).inc()
        metrics.http_latency.labels(method=request.method, path=label).observe(elapsed)
        response.headers["X-Response-Time-Ms"] = f"{elapsed * 1000:.1f}"
        return response

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={"detail": "internal error", "request_path": request.url.path},
        )

    for module in (health, profiles, jobs, images, showcase, workers, evals, admin):
        app.include_router(module.router)

    @app.get("/", include_in_schema=False)
    async def root() -> dict[str, str]:
        return {
            "name": settings.app_name,
            "version": VERSION,
            "docs": "/docs",
            "health": "/health",
            "status": "/v1/status",
        }

    return app


def _route_label(request: Request) -> str:
    """Collapse path params so metrics cardinality stays bounded."""
    route = request.scope.get("route")
    return getattr(route, "path", request.url.path)


app = create_app()
