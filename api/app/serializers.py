"""ORM -> response mapping, kept out of the routers."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .models import Image, Job, Worker, utcnow
from .queue import queue_position
from .schemas import JobOut, ShowcaseItem, WorkerOut
from .storage import get_storage


def image_url(image: Image | None) -> str | None:
    """CDN URL when the backend exposes one, otherwise the API passthrough."""
    if image is None:
        return None
    if image.ref:
        direct = get_storage().public_url(image.ref)
        if direct:
            return direct
    return f"/v1/images/{image.id}"


def image_url_by_id(image_id: str | None) -> str | None:
    return f"/v1/images/{image_id}" if image_id else None


async def job_out(session: AsyncSession, job: Job, *, with_position: bool = True) -> JobOut:
    payload = JobOut.model_validate(job)
    payload.source_url = image_url_by_id(job.source_image_id)
    payload.result_url = image_url_by_id(job.result_image_id)
    payload.damage_map_url = image_url_by_id(job.damage_map_id)
    if with_position:
        payload.queue_position = await queue_position(session, job)
    return payload


def worker_out(worker: Worker) -> WorkerOut:
    payload = WorkerOut.model_validate(worker)
    cutoff = utcnow() - timedelta(seconds=settings.worker_offline_after_seconds)
    payload.online = bool(worker.last_seen_at and worker.last_seen_at >= cutoff)
    return payload


def showcase_item(job: Job) -> ShowcaseItem:
    """A before/after pair. Both images must exist or this is not showable."""
    return ShowcaseItem(
        job_id=job.id,
        before_url=image_url_by_id(job.source_image_id) or "",
        after_url=image_url_by_id(job.result_image_id) or "",
        profile=job.profile,
        stages=list(job.stages or []),
        source_width=job.source_width,
        source_height=job.source_height,
        result_width=job.result_width,
        result_height=job.result_height,
        damage_ratio=job.damage_ratio,
        faces_found=job.faces_found,
        duration_ms=job.duration_ms,
        notes=job.notes,
        featured=True,
        created_at=job.created_at,
    )
