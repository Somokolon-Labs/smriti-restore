"""Public job API: upload a photograph, queue a restoration, poll it, cancel it."""

from __future__ import annotations

import logging
import secrets

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import metrics, queue
from ..activity import activity
from ..config import settings
from ..db import get_session
from ..models import Image, ImageRole, Job, JobStatus, new_id, utcnow
from ..profiles import PROFILES_BY_ID, profile_defaults, requires_mask, resolve_stages
from ..schemas import JobCreate, JobListOut, JobOut, UploadResult
from ..security import Identity, charge_job_quota, client_identity, enforce_job_quota
from ..serializers import job_out
from ..storage import normalise_upload

log = logging.getLogger(__name__)
router = APIRouter(prefix="/v1", tags=["jobs"])


@router.post("/uploads", response_model=UploadResult, status_code=status.HTTP_201_CREATED)
async def upload_source(
    file: UploadFile = File(...),
    role: str = Query(default=ImageRole.SOURCE.value, pattern="^(source|mask)$"),
    identity: Identity = Depends(client_identity),
    session: AsyncSession = Depends(get_session),
) -> UploadResult:
    """Stage a photograph, or a hand-painted damage mask, for restoration."""
    data = await file.read()
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "empty upload")
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"image exceeds {settings.max_upload_bytes // (1024 * 1024)} MB",
        )

    try:
        # Oversized scans are downscaled here rather than in the worker: it bounds
        # storage, bounds worker VRAM, and gives the user immediate feedback.
        data, width, height, mime, downscaled, is_grayscale = normalise_upload(
            data, max_pixels=settings.max_source_pixels
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, str(exc)) from exc

    image = await queue.save_image_bytes(
        session,
        data,
        role=role,
        width=width,
        height=height,
        mime=mime,
        is_public=False,  # uploads are private; the showcase is curated by hand
        meta={
            "session_id": identity.session_id,
            "original_name": file.filename or "",
            "grayscale": is_grayscale,
            "downscaled": downscaled,
        },
    )
    await session.commit()

    return UploadResult(
        image_id=image.id,
        url=f"/v1/images/{image.id}",
        width=width,
        height=height,
        mime=mime,
        size_bytes=len(data),
        is_grayscale=is_grayscale,
        downscaled=downscaled,
    )


@router.post("/jobs", response_model=JobOut, status_code=status.HTTP_202_ACCEPTED)
async def create_job(
    payload: JobCreate,
    identity: Identity = Depends(enforce_job_quota),
    session: AsyncSession = Depends(get_session),
) -> JobOut:
    depth = await session.scalar(
        select(func.count()).select_from(Job).where(Job.status == JobStatus.QUEUED.value)
    )
    if (depth or 0) >= settings.max_queue_depth:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "the queue is full right now, try again shortly",
            headers={"Retry-After": "60"},
        )

    source = await session.get(Image, payload.source_image_id)
    if source is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "source image not found")
    if source.role != ImageRole.SOURCE.value:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "that image is not a source upload")

    if payload.mask_image_id:
        mask = await session.get(Image, payload.mask_image_id)
        if mask is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "mask image not found")

    if requires_mask(payload.profile) and not payload.mask_image_id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"the {payload.profile} profile needs a painted mask; send mask_image_id",
        )

    stages = resolve_stages(payload.profile, payload.stages)
    if not stages:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "no pipeline stages selected")

    defaults = profile_defaults(payload.profile)
    profile = PROFILES_BY_ID[payload.profile]
    scale = payload.scale if payload.scale is not None else int(defaults["scale"])
    if "upscale" not in stages:
        scale = 1  # no upscale stage means no enlargement, whatever was asked for

    result_pixels = source.width * source.height * scale * scale
    if result_pixels > settings.max_result_pixels:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"{scale}x on a {source.width}x{source.height} source would exceed the output "
            "size limit; choose a smaller scale",
        )

    job = Job(
        id=new_id(),
        status=JobStatus.QUEUED.value,
        profile=payload.profile,
        tier=payload.tier or profile["tier"],
        stages=stages,
        stages_completed=[],
        scale=scale,
        fidelity=(
            payload.fidelity if payload.fidelity is not None else float(defaults["fidelity"])
        ),
        denoise_strength=(
            payload.denoise_strength
            if payload.denoise_strength is not None
            else float(defaults["denoise_strength"])
        ),
        auto_mask=(
            payload.auto_mask if payload.auto_mask is not None else bool(defaults["auto_mask"])
        ),
        seed=payload.seed if payload.seed >= 0 else secrets.randbelow(2**31 - 1),
        source_image_id=source.id,
        mask_image_id=payload.mask_image_id,
        source_width=source.width,
        source_height=source.height,
        progress_total=len(stages),
        max_attempts=settings.job_max_attempts,
        session_id=identity.session_id,
        ip_hash=identity.ip_hash,
        share_public=payload.share_public,
        notes=payload.notes,
        params={"grayscale_source": bool((source.meta or {}).get("grayscale"))},
    )
    session.add(job)
    await charge_job_quota(session, identity)
    await session.commit()

    metrics.jobs_created.labels(profile=job.profile, tier=job.tier).inc()
    for stage in stages:
        metrics.stage_requested.labels(stage=stage).inc()
    activity.touch()
    log.info("job %s queued (%s, stages=%s)", job.id, job.profile, ",".join(stages))
    return await job_out(session, job)


@router.get("/jobs/{job_id}", response_model=JobOut)
async def get_job(job_id: str, session: AsyncSession = Depends(get_session)) -> JobOut:
    job = await session.get(Job, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "job not found")
    return await job_out(session, job)


@router.get("/jobs", response_model=JobListOut)
async def list_jobs(
    limit: int = Query(default=24, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    identity: Identity = Depends(client_identity),
    session: AsyncSession = Depends(get_session),
) -> JobListOut:
    """This caller's own restorations, newest first."""
    where = Job.session_id == identity.session_id
    total = await session.scalar(select(func.count()).select_from(Job).where(where))
    rows = (
        await session.scalars(
            select(Job).where(where).order_by(Job.created_at.desc()).offset(offset).limit(limit)
        )
    ).all()
    return JobListOut(
        items=[await job_out(session, j, with_position=False) for j in rows],
        total=total or 0,
    )


@router.post("/jobs/{job_id}/cancel", response_model=JobOut)
async def cancel_job(
    job_id: str,
    identity: Identity = Depends(client_identity),
    session: AsyncSession = Depends(get_session),
) -> JobOut:
    job = await session.get(Job, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "job not found")
    if job.session_id and job.session_id != identity.session_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not your job")
    if job.status in {JobStatus.SUCCEEDED.value, JobStatus.FAILED.value}:
        return await job_out(session, job)

    # A running job is flagged; the worker notices on its next heartbeat and stops
    # between stages rather than finishing an unwanted pipeline.
    job.status = JobStatus.CANCELED.value
    job.finished_at = utcnow()
    job.stage = "canceled"
    await session.commit()
    metrics.jobs_finished.labels(profile=job.profile, tier=job.tier, status="canceled").inc()
    return await job_out(session, job)


@router.delete(
    "/jobs/{job_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    # A `-> None` annotation becomes a truthy NoneType response model, which
    # FastAPI refuses to pair with 204. Returning Response directly avoids it.
    response_class=Response,
    response_model=None,
)
async def delete_job(
    job_id: str,
    identity: Identity = Depends(client_identity),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Let a user erase their own photograph and result immediately.

    Retention would remove these anyway, but someone who has just uploaded a
    family photograph should not have to wait for a cron sweep to take it back.
    """
    job = await session.get(Job, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "job not found")
    if job.session_id != identity.session_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not your job")

    await queue.delete_job_images(session, job)
    await session.delete(job)
    await session.commit()
    log.info("job %s deleted by owner", job_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
