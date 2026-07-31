"""Job queue mechanics: atomic claim, lease renewal, requeue, retention.

The claim is a single round trip. On Postgres it uses `FOR UPDATE SKIP LOCKED` so
N workers never collide; on SQLite (dev) writes are already serialised, so a
guarded conditional update gives the same guarantee.

Matching is stricter than a generation queue needs. A restoration worker must be
able to run *every* stage a job asks for, and must be able to hold the output in
VRAM, so the claim filters on both.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import delete, func, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from . import metrics
from .config import settings
from .models import Image, ImageRole, Job, JobStatus, Worker, utcnow
from .storage import get_storage

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# claiming
# --------------------------------------------------------------------------- #
# `stages <@ :stages` is containment: every stage the job needs is offered by the
# worker. Postgres evaluates it on the jsonb column directly.
_PG_CLAIM = text(
    """
    WITH picked AS (
        SELECT id FROM jobs
        WHERE status = 'queued'
          AND tier = ANY(:tiers)
          AND (source_width * source_height * scale * scale) <= :max_pixels
          AND NOT EXISTS (
              SELECT 1
              FROM jsonb_array_elements_text(jobs.stages::jsonb) AS needed(stage)
              WHERE needed.stage <> ALL(:stages)
          )
        ORDER BY priority DESC, created_at ASC
        LIMIT 1
        FOR UPDATE SKIP LOCKED
    )
    UPDATE jobs AS j
       SET status = 'running',
           worker_id = :worker_id,
           started_at = COALESCE(j.started_at, :now),
           lease_expires_at = :lease,
           attempts = j.attempts + 1,
           progress = 0,
           stage_index = 0,
           progress_step = 0,
           stage = 'claimed',
           stages_completed = '[]',
           error = ''
      FROM picked
     WHERE j.id = picked.id
    RETURNING j.id
    """
)


async def claim_one(
    session: AsyncSession,
    *,
    worker_id: str,
    stages: list[str],
    tiers: list[str],
    max_pixels: int,
) -> Job | None:
    """Atomically move one eligible queued job to running."""
    if not tiers:
        return None

    now = utcnow()
    lease = now + timedelta(seconds=settings.job_lease_seconds)
    ceiling = max_pixels or settings.max_result_pixels

    if settings.is_postgres:
        row = (
            await session.execute(
                _PG_CLAIM,
                {
                    "stages": stages,
                    "tiers": tiers,
                    "max_pixels": ceiling,
                    "worker_id": worker_id,
                    "now": now,
                    "lease": lease,
                },
            )
        ).first()
        if row is None:
            await session.rollback()
            return None
        job_id = row[0]
    else:
        # SQLite has no jsonb containment, so filter capability in Python over a
        # small candidate set. Writes are serialised, so this stays race-free.
        candidates = (
            await session.scalars(
                select(Job)
                .where(Job.status == JobStatus.QUEUED.value, Job.tier.in_(tiers))
                .order_by(Job.priority.desc(), Job.created_at.asc())
                .limit(25)
            )
        ).all()

        offered = set(stages)
        job_id = None
        for candidate in candidates:
            needed = set(candidate.stages or [])
            output_pixels = (
                candidate.source_width * candidate.source_height * candidate.scale * candidate.scale
            )
            if needed <= offered and output_pixels <= ceiling:
                job_id = candidate.id
                break
        if job_id is None:
            return None

        result = await session.execute(
            update(Job)
            .where(Job.id == job_id, Job.status == JobStatus.QUEUED.value)
            .values(
                status=JobStatus.RUNNING.value,
                worker_id=worker_id,
                started_at=now,
                lease_expires_at=lease,
                attempts=Job.attempts + 1,
                progress=0.0,
                stage_index=0,
                progress_step=0,
                stage="claimed",
                stages_completed=[],
                error="",
            )
        )
        if not result.rowcount:
            await session.rollback()
            return None

    await session.commit()
    job = await session.get(Job, job_id)
    if job is not None:
        wait = (now - job.created_at).total_seconds() if job.created_at else 0.0
        metrics.job_queue_wait.observe(max(wait, 0.0))
    return job


async def renew_lease(session: AsyncSession, job: Job) -> None:
    job.lease_expires_at = utcnow() + timedelta(seconds=settings.job_lease_seconds)
    await session.commit()


# --------------------------------------------------------------------------- #
# reaper: recover work abandoned by a dead worker
# --------------------------------------------------------------------------- #
async def reap_expired_leases(session: AsyncSession) -> tuple[int, int]:
    """Requeue jobs whose worker went silent; fail the ones out of attempts."""
    now = utcnow()
    stale = (
        await session.scalars(
            select(Job).where(
                Job.status == JobStatus.RUNNING.value,
                Job.lease_expires_at.is_not(None),
                Job.lease_expires_at < now,
            )
        )
    ).all()

    requeued = failed = 0
    for job in stale:
        if job.attempts < job.max_attempts:
            job.status = JobStatus.QUEUED.value
            job.worker_id = None
            job.lease_expires_at = None
            job.progress = 0.0
            job.stage = "requeued"
            job.stage_index = 0
            job.progress_step = 0
            job.stages_completed = []
            job.started_at = None
            requeued += 1
            metrics.jobs_requeued.labels(reason="lease_expired").inc()
        else:
            job.status = JobStatus.FAILED.value
            job.error = (
                f"worker stopped responding after {job.attempts} attempt(s); "
                "lease expired with no result"
            )
            job.finished_at = now
            job.lease_expires_at = None
            failed += 1
            metrics.jobs_finished.labels(profile=job.profile, tier=job.tier, status="failed").inc()

    if stale:
        await session.commit()
        log.warning("lease reaper: requeued=%d failed=%d", requeued, failed)
    return requeued, failed


# --------------------------------------------------------------------------- #
# gauges
# --------------------------------------------------------------------------- #
async def refresh_gauges(session: AsyncSession) -> dict[str, int]:
    queued = await session.scalar(
        select(func.count()).select_from(Job).where(Job.status == JobStatus.QUEUED.value)
    )
    running = await session.scalar(
        select(func.count()).select_from(Job).where(Job.status == JobStatus.RUNNING.value)
    )
    cutoff = utcnow() - timedelta(seconds=settings.worker_offline_after_seconds)
    online = await session.scalar(
        select(func.count()).select_from(Worker).where(Worker.last_seen_at >= cutoff)
    )
    stored = await session.scalar(select(func.count()).select_from(Image))

    metrics.queue_depth.set(queued or 0)
    metrics.jobs_running.set(running or 0)
    metrics.workers_online.set(online or 0)
    metrics.images_stored.set(stored or 0)
    return {
        "queued": queued or 0,
        "running": running or 0,
        "workers_online": online or 0,
        "images": stored or 0,
    }


async def available_stages(session: AsyncSession) -> list[str]:
    """Union of stages currently served by online workers."""
    cutoff = utcnow() - timedelta(seconds=settings.worker_offline_after_seconds)
    rows = (await session.scalars(select(Worker.stages).where(Worker.last_seen_at >= cutoff))).all()
    offered: set[str] = set()
    for entry in rows:
        offered.update(entry or [])
    from .profiles import STAGE_ORDER

    return [stage for stage in STAGE_ORDER if stage in offered]


async def average_duration_ms(session: AsyncSession, sample: int = 20) -> int | None:
    recent = (
        await session.scalars(
            select(Job.duration_ms)
            .where(Job.status == JobStatus.SUCCEEDED.value, Job.duration_ms > 0)
            .order_by(Job.finished_at.desc())
            .limit(sample)
        )
    ).all()
    if not recent:
        return None
    return int(sum(recent) / len(recent))


async def queue_position(session: AsyncSession, job: Job) -> int | None:
    """1-based position among queued jobs; None once the job has been claimed."""
    if job.status != JobStatus.QUEUED.value:
        return None
    ahead = await session.scalar(
        select(func.count())
        .select_from(Job)
        .where(
            Job.status == JobStatus.QUEUED.value,
            or_(
                Job.priority > job.priority,
                (Job.priority == job.priority) & (Job.created_at < job.created_at),
            ),
        )
    )
    return (ahead or 0) + 1


# --------------------------------------------------------------------------- #
# retention
# --------------------------------------------------------------------------- #
async def _drop_images(session: AsyncSession, images: list[Image], reason: str) -> int:
    storage = get_storage()
    seen: set[str] = set()
    for image in images:
        if image.id in seen:
            continue
        seen.add(image.id)
        if image.ref:
            try:
                await storage.delete(image.ref)
            except Exception as exc:
                log.warning("storage delete failed for %s: %s", image.id, exc)
    if seen:
        await session.execute(delete(Image).where(Image.id.in_(seen)))
        metrics.images_pruned.labels(reason=reason).inc(len(seen))
    return len(seen)


async def delete_job_images(session: AsyncSession, job: Job) -> int:
    """Remove every image belonging to one job, for owner-initiated deletion."""
    images = (await session.scalars(select(Image).where(Image.job_id == job.id))).all()
    extra_ids = [i for i in (job.source_image_id, job.mask_image_id) if i]
    if extra_ids:
        images = list(images) + list(
            (await session.scalars(select(Image).where(Image.id.in_(extra_ids)))).all()
        )
    return await _drop_images(session, list(images), reason="owner_request")


async def prune_images(session: AsyncSession) -> int:
    """Two-speed retention.

    Private uploads and their results are personal photographs, so they go on a
    short clock measured in hours. The hand-curated showcase is exempt entirely.
    """
    removed = 0

    if settings.private_retention_hours > 0:
        cutoff = utcnow() - timedelta(hours=settings.private_retention_hours)
        private = (
            await session.scalars(
                select(Image).where(
                    Image.featured.is_(False),
                    Image.is_public.is_(False),
                    Image.created_at < cutoff,
                )
            )
        ).all()
        removed += await _drop_images(session, list(private), reason="private_expiry")

    if settings.image_retention_days > 0:
        cutoff = utcnow() - timedelta(days=settings.image_retention_days)
        aged = (
            await session.scalars(
                select(Image).where(Image.featured.is_(False), Image.created_at < cutoff)
            )
        ).all()
        removed += await _drop_images(session, list(aged), reason="age")

    if settings.image_max_count > 0:
        total = await session.scalar(select(func.count()).select_from(Image)) or 0
        overflow = total - settings.image_max_count
        if overflow > 0:
            oldest = (
                await session.scalars(
                    select(Image)
                    .where(Image.featured.is_(False))
                    .order_by(Image.created_at.asc())
                    .limit(overflow)
                )
            ).all()
            removed += await _drop_images(session, list(oldest), reason="overflow")

    if removed:
        await session.commit()
        log.info("retention: pruned %d images", removed)
    return removed


# --------------------------------------------------------------------------- #
# shared helper
# --------------------------------------------------------------------------- #
async def save_image_bytes(
    session: AsyncSession,
    data: bytes,
    *,
    role: str = ImageRole.RESULT.value,
    job_id: str | None = None,
    width: int = 0,
    height: int = 0,
    mime: str = "image/png",
    is_public: bool = False,
    nsfw: bool = False,
    meta: dict | None = None,
) -> Image:
    from .models import new_id
    from .storage import sha256_hex

    storage = get_storage()
    image = Image(
        id=new_id(),  # needed before flush: the storage ref derives from it
        job_id=job_id,
        role=role,
        mime=mime,
        width=width,
        height=height,
        size_bytes=len(data),
        sha256=sha256_hex(data),
        is_public=is_public,
        nsfw=nsfw,
        meta=meta or {},
    )
    blob = await storage.put(image.id, data, mime)
    image.backend = blob.backend
    image.ref = blob.ref
    image.data = blob.inline
    session.add(image)
    return image
