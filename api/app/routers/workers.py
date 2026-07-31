"""GPU worker protocol.

Workers pull: they long-poll for a claim, heartbeat between and during stages, then
post the restored image. Nothing connects inbound, so a worker can sit behind NAT
on a laptop or in a rented GPU pod and still serve the deployed site.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import metrics, queue
from ..activity import activity
from ..config import settings
from ..db import get_session
from ..models import ImageRole, Job, JobStatus, Worker, new_id, utcnow
from ..schemas import (
    ClaimedJob,
    ClaimRequest,
    FailReport,
    JobOut,
    LeaseAck,
    ProgressUpdate,
    WorkerOut,
    WorkerRegister,
)
from ..security import require_worker
from ..serializers import job_out, worker_out
from ..storage import probe_image

log = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/worker", tags=["worker"], dependencies=[Depends(require_worker)])

TERMINAL = {JobStatus.SUCCEEDED.value, JobStatus.FAILED.value, JobStatus.CANCELED.value}


async def _get_worker(session: AsyncSession, worker_id: str) -> Worker:
    worker = await session.get(Worker, worker_id)
    if worker is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown worker; register first")
    return worker


async def _get_owned_job(session: AsyncSession, job_id: str, worker_id: str | None) -> Job:
    job = await session.get(Job, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "job not found")
    if worker_id and job.worker_id and job.worker_id != worker_id:
        # The lease was reaped and handed on. Tell the loser to stop working.
        raise HTTPException(status.HTTP_409_CONFLICT, "job is leased to another worker")
    return job


# --------------------------------------------------------------------------- #
# registration / heartbeat
# --------------------------------------------------------------------------- #
@router.post("/register", response_model=WorkerOut)
async def register(
    payload: WorkerRegister,
    session: AsyncSession = Depends(get_session),
) -> WorkerOut:
    """Idempotent by name, so restarting a worker keeps its identity and counters."""
    existing = await session.scalar(select(Worker).where(Worker.name == payload.name))
    worker = existing or Worker(id=new_id(), name=payload.name)
    worker.gpu_name = payload.gpu_name
    worker.vram_mb = payload.vram_mb
    worker.version = payload.version
    worker.stages = list(payload.stages)
    worker.tiers = list(payload.tiers)
    worker.max_pixels = payload.max_pixels
    worker.meta = payload.meta
    worker.last_seen_at = utcnow()
    if existing is None:
        session.add(worker)
    await session.commit()
    log.info(
        "worker %s (%s) online: stages=%s tiers=%s",
        worker.name,
        worker.gpu_name,
        ",".join(worker.stages),
        ",".join(worker.tiers),
    )
    return worker_out(worker)


@router.post("/heartbeat", response_model=WorkerOut)
async def heartbeat(
    worker_id: str,
    session: AsyncSession = Depends(get_session),
) -> WorkerOut:
    worker = await _get_worker(session, worker_id)
    worker.last_seen_at = utcnow()
    await session.commit()
    return worker_out(worker)


# --------------------------------------------------------------------------- #
# claim (long poll)
# --------------------------------------------------------------------------- #
@router.post(
    "/claim",
    response_model=ClaimedJob,
    responses={204: {"description": "no eligible work before the poll expired"}},
)
async def claim(
    payload: ClaimRequest,
    session: AsyncSession = Depends(get_session),
):
    worker = await _get_worker(session, payload.worker_id)
    worker.last_seen_at = utcnow()
    await session.commit()
    activity.touch()

    deadline = min(payload.wait_seconds, settings.claim_long_poll_seconds)
    waited = 0.0
    while True:
        job = await queue.claim_one(
            session,
            worker_id=worker.id,
            stages=list(payload.stages),
            tiers=list(payload.tiers),
            max_pixels=payload.max_pixels,
        )
        if job is not None:
            return await _claimed_payload(session, job)
        if waited >= deadline:
            return Response(status_code=status.HTTP_204_NO_CONTENT)
        await asyncio.sleep(1.0)
        waited += 1.0
        worker.last_seen_at = utcnow()
        await session.commit()


async def _claimed_payload(session: AsyncSession, job: Job) -> ClaimedJob:
    mask_url = f"/v1/images/{job.mask_image_id}" if job.mask_image_id else None
    return ClaimedJob(
        id=job.id,
        profile=job.profile,
        tier=job.tier,
        stages=list(job.stages or []),
        scale=job.scale,
        fidelity=job.fidelity,
        denoise_strength=job.denoise_strength,
        auto_mask=job.auto_mask,
        seed=job.seed,
        params=job.params or {},
        source_image_url=f"/v1/images/{job.source_image_id}",
        mask_image_url=mask_url,
        source_width=job.source_width,
        source_height=job.source_height,
        lease_expires_at=job.lease_expires_at or utcnow(),
        attempt=job.attempts,
    )


# --------------------------------------------------------------------------- #
# progress / result / failure
# --------------------------------------------------------------------------- #
@router.post("/jobs/{job_id}/progress", response_model=LeaseAck)
async def report_progress(
    job_id: str,
    payload: ProgressUpdate,
    worker_id: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> LeaseAck:
    """Heartbeat plus progress in one call; the response tells the worker to abort."""
    job = await _get_owned_job(session, job_id, worker_id)
    if job.status == JobStatus.CANCELED.value:
        return LeaseAck(ok=False, canceled=True)

    previous_stage = job.stage
    job.stage = payload.stage or job.stage
    job.stage_index = payload.stage_index
    job.progress_step = payload.step
    job.progress_total = payload.total or job.progress_total

    if payload.overall is not None:
        job.progress = payload.overall
    elif job.stages:
        # Fall back to stage-granular progress when the worker does not estimate.
        job.progress = min(1.0, payload.stage_index / max(len(job.stages), 1))

    if previous_stage and previous_stage != job.stage and previous_stage in (job.stages or []):
        done = list(job.stages_completed or [])
        if previous_stage not in done:
            done.append(previous_stage)
            job.stages_completed = done
            metrics.stage_completed.labels(stage=previous_stage).inc()

    await queue.renew_lease(session, job)

    if job.worker_id:
        worker = await session.get(Worker, job.worker_id)
        if worker is not None:
            worker.last_seen_at = utcnow()
            await session.commit()

    return LeaseAck(ok=True, lease_expires_at=job.lease_expires_at)


@router.post("/jobs/{job_id}/result", response_model=JobOut)
async def submit_result(
    job_id: str,
    file: UploadFile = File(...),
    worker_id: str = Form(...),
    duration_ms: int = Form(default=0),
    damage_ratio: float = Form(default=0.0),
    faces_found: int = Form(default=0),
    stage_timings: str = Form(default="{}"),
    damage_map: UploadFile | None = File(default=None),
    session: AsyncSession = Depends(get_session),
) -> JobOut:
    job = await _get_owned_job(session, job_id, worker_id)
    if job.status in TERMINAL:
        # Canceled mid-flight, or a duplicate delivery. Accept without mutating.
        return await job_out(session, job, with_position=False)

    data = await file.read()
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "empty result upload")
    try:
        width, height, mime = probe_image(data)
    except ValueError as exc:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, str(exc)) from exc

    import json

    try:
        timings = json.loads(stage_timings) or {}
    except ValueError:
        timings = {}

    image = await queue.save_image_bytes(
        session,
        data,
        role=ImageRole.RESULT.value,
        job_id=job.id,
        width=width,
        height=height,
        mime=mime,
        # Opting in only makes a result *eligible* for the showcase; an admin
        # still has to feature it before anything is publicly visible.
        is_public=job.share_public,
        meta={"profile": job.profile, "stages": list(job.stages or [])},
    )

    if damage_map is not None:
        map_bytes = await damage_map.read()
        if map_bytes:
            try:
                map_w, map_h, map_mime = probe_image(map_bytes)
                overlay = await queue.save_image_bytes(
                    session,
                    map_bytes,
                    role=ImageRole.DAMAGE_MAP.value,
                    job_id=job.id,
                    width=map_w,
                    height=map_h,
                    mime=map_mime,
                    is_public=False,
                )
                job.damage_map_id = overlay.id
            except ValueError:
                log.warning("job %s sent an undecodable damage map; ignoring", job.id[:8])

    job.result_image_id = image.id
    job.status = JobStatus.SUCCEEDED.value
    job.progress = 1.0
    job.stage = "done"
    job.stage_index = len(job.stages or [])
    job.stages_completed = list(job.stages or [])
    job.result_width = width
    job.result_height = height
    job.damage_ratio = damage_ratio
    job.faces_found = faces_found
    job.stage_timings = timings
    job.duration_ms = duration_ms
    job.error = ""
    job.finished_at = utcnow()
    job.lease_expires_at = None

    worker = await session.get(Worker, worker_id)
    if worker is not None:
        worker.jobs_completed += 1
        worker.last_seen_at = utcnow()

    await session.commit()

    metrics.jobs_finished.labels(profile=job.profile, tier=job.tier, status="succeeded").inc()
    if duration_ms:
        metrics.job_duration.labels(profile=job.profile, tier=job.tier).observe(duration_ms / 1000)
    for stage, seconds in timings.items():
        try:
            metrics.stage_duration.labels(stage=stage).observe(float(seconds))
        except (TypeError, ValueError):
            continue
    metrics.megapixels_restored.inc((width * height) / 1_000_000)

    log.info(
        "job %s done in %dms (%dx%d, damage %.1f%%, faces %d)",
        job.id[:8],
        duration_ms,
        width,
        height,
        damage_ratio * 100,
        faces_found,
    )
    return await job_out(session, job, with_position=False)


@router.post("/jobs/{job_id}/fail", response_model=JobOut)
async def report_failure(
    job_id: str,
    payload: FailReport,
    worker_id: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> JobOut:
    """Retry if attempts remain and the worker says the error is transient."""
    job = await _get_owned_job(session, job_id, worker_id)
    if job.status in TERMINAL:
        return await job_out(session, job, with_position=False)

    can_retry = payload.retryable and job.attempts < job.max_attempts
    prefix = f"[{payload.stage}] " if payload.stage else ""
    job.error = (prefix + payload.error)[:2000]
    job.lease_expires_at = None
    job.worker_id = None

    if can_retry:
        job.status = JobStatus.QUEUED.value
        job.stage = "retrying"
        job.progress = 0.0
        job.stage_index = 0
        job.progress_step = 0
        job.stages_completed = []
        job.started_at = None
        metrics.jobs_requeued.labels(reason="worker_error").inc()
        log.warning("job %s failed (attempt %d), requeued: %s", job.id, job.attempts, job.error)
    else:
        job.status = JobStatus.FAILED.value
        job.stage = "failed"
        job.finished_at = utcnow()
        metrics.jobs_finished.labels(profile=job.profile, tier=job.tier, status="failed").inc()
        log.error("job %s failed permanently: %s", job.id, job.error)

    if worker_id:
        worker = await session.get(Worker, worker_id)
        if worker is not None:
            worker.jobs_failed += 1
            worker.last_seen_at = utcnow()

    await session.commit()
    return await job_out(session, job, with_position=False)
