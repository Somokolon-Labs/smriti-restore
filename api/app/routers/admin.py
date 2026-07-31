"""Admin operations: curate the showcase, run retention, force the lease reaper."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from .. import queue
from ..db import get_session
from ..models import Image, Job
from ..security import require_admin

router = APIRouter(prefix="/v1/admin", tags=["admin"], dependencies=[Depends(require_admin)])


@router.post("/jobs/{job_id}/feature")
async def feature_job(
    job_id: str,
    featured: bool = Query(default=True),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    """Publish a before/after pair to the showcase.

    Two gates, both required: the uploader must have opted in, and an admin must
    feature it here. Featuring also exempts both images from retention, otherwise
    the showcase would quietly empty itself.
    """
    job = await session.get(Job, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "job not found")
    if not job.result_image_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "job has no result to show")
    if featured and not job.share_public:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "the uploader did not consent to sharing this photograph publicly",
        )

    touched = []
    for image_id in (job.source_image_id, job.result_image_id):
        if not image_id:
            continue
        image = await session.get(Image, image_id)
        if image is None:
            continue
        image.featured = featured
        image.is_public = featured
        touched.append(image_id)

    await session.commit()
    return {"job_id": job.id, "featured": featured, "images": touched}


@router.delete("/jobs/{job_id}")
async def delete_job(
    job_id: str, session: AsyncSession = Depends(get_session)
) -> dict[str, object]:
    job = await session.get(Job, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "job not found")
    removed = await queue.delete_job_images(session, job)
    await session.delete(job)
    await session.commit()
    return {"deleted": job_id, "images_removed": removed}


@router.post("/prune")
async def prune(session: AsyncSession = Depends(get_session)) -> dict[str, int]:
    from ..security import prune_rate_events

    images = await queue.prune_images(session)
    events = await prune_rate_events(session)
    return {"images_pruned": images, "rate_events_pruned": events}


@router.post("/reap")
async def reap(session: AsyncSession = Depends(get_session)) -> dict[str, int]:
    """Manually trigger lease recovery. Handy when demonstrating fault tolerance."""
    requeued, failed = await queue.reap_expired_leases(session)
    return {"requeued": requeued, "failed": failed}
