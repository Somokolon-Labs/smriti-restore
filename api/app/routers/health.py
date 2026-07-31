"""Liveness, readiness and the public queue status the UI polls."""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import queue
from ..config import settings
from ..db import get_session, ping
from ..metrics import REGISTRY
from ..models import Worker, utcnow
from ..schemas import HealthOut, LivenessOut, QueueStatus
from ..serializers import worker_out
from ..version import VERSION

router = APIRouter(tags=["system"])


@router.get("/health", response_model=LivenessOut)
async def health() -> LivenessOut:
    """Liveness only: is this process able to serve?

    Deliberately does no I/O. Tying a platform liveness probe to the database means
    a serverless Postgres waking from auto-suspend looks like an unhealthy
    container, and the platform restarts a perfectly good instance. Readiness is a
    separate question, below.
    """
    return LivenessOut(
        status="ok",
        version=VERSION,
        environment=settings.environment,
        storage_backend=settings.storage_backend,
    )


@router.get(
    "/health/ready",
    response_model=HealthOut,
    responses={503: {"description": "a dependency is unavailable"}},
)
async def readiness(response: Response) -> HealthOut:
    """Readiness: are dependencies reachable? Safe to poll, not to probe."""
    database = await ping()
    if not database:
        response.status_code = 503
    return HealthOut(
        status="ok" if database else "degraded",
        version=VERSION,
        environment=settings.environment,
        database=database,
        storage_backend=settings.storage_backend,
    )


@router.get("/v1/status", response_model=QueueStatus)
async def queue_status(session: AsyncSession = Depends(get_session)) -> QueueStatus:
    """Drives the worker pill, the queue estimate, and which stages the UI offers."""
    counts = await queue.refresh_gauges(session)
    cutoff = utcnow() - timedelta(seconds=settings.worker_offline_after_seconds * 4)
    workers = (
        await session.scalars(
            select(Worker).where(Worker.last_seen_at >= cutoff).order_by(Worker.last_seen_at.desc())
        )
    ).all()

    avg_ms = await queue.average_duration_ms(session)
    online = counts["workers_online"]
    est = None
    if avg_ms and online:
        pending = counts["queued"] + counts["running"]
        est = int((pending * avg_ms / 1000) / max(online, 1))

    return QueueStatus(
        queued=counts["queued"],
        running=counts["running"],
        workers_online=online,
        workers=[worker_out(w) for w in workers],
        accepting_jobs=counts["queued"] < settings.max_queue_depth,
        available_stages=await queue.available_stages(session),
        est_wait_seconds=est,
        avg_duration_ms=avg_ms,
    )


@router.get("/metrics", include_in_schema=False)
async def metrics_endpoint(session: AsyncSession = Depends(get_session)) -> Response:
    await queue.refresh_gauges(session)
    return Response(generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)
