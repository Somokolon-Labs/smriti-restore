"""Public showcase: curated before/after pairs.

Deliberately narrow. Restoration inputs are personal photographs, so nothing
appears here unless the uploader opted in *and* an admin featured it. There is no
"recent uploads" feed, because that would be a privacy hazard dressed up as a
gallery.
"""

from __future__ import annotations

import base64
import binascii
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..models import Image, Job, JobStatus
from ..schemas import ShowcaseItem, ShowcasePage
from ..serializers import showcase_item

router = APIRouter(prefix="/v1", tags=["showcase"])


def _encode_cursor(created_at: datetime, job_id: str) -> str:
    raw = f"{created_at.isoformat()}|{job_id}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        created_raw, job_id = base64.urlsafe_b64decode(padded).decode().split("|", 1)
        return datetime.fromisoformat(created_raw), job_id
    except (ValueError, binascii.Error) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "malformed cursor") from exc


@router.get("/showcase", response_model=ShowcasePage)
async def list_showcase(
    limit: int = Query(default=12, ge=1, le=40),
    cursor: str | None = None,
    profile: str | None = Query(default=None, max_length=48),
    session: AsyncSession = Depends(get_session),
) -> ShowcasePage:
    # A result image marked featured is the single source of truth for what is
    # public; the job is only joined to read its settings.
    featured = (
        select(Image.job_id)
        .where(Image.featured.is_(True), Image.is_public.is_(True), Image.job_id.is_not(None))
        .scalar_subquery()
    )

    stmt = (
        select(Job)
        .where(
            Job.id.in_(featured),
            Job.status == JobStatus.SUCCEEDED.value,
            Job.result_image_id.is_not(None),
        )
        .order_by(Job.created_at.desc(), Job.id.desc())
        .limit(limit + 1)
    )
    if profile:
        stmt = stmt.where(Job.profile == profile)
    if cursor:
        created_at, job_id = _decode_cursor(cursor)
        stmt = stmt.where(
            (Job.created_at < created_at) | ((Job.created_at == created_at) & (Job.id < job_id))
        )

    rows = (await session.scalars(stmt)).all()
    has_more = len(rows) > limit
    rows = list(rows)[:limit]

    items: list[ShowcaseItem] = [showcase_item(job) for job in rows]
    next_cursor = _encode_cursor(rows[-1].created_at, rows[-1].id) if has_more and rows else None
    return ShowcasePage(items=items, next_cursor=next_cursor)


@router.get("/showcase/{job_id}", response_model=ShowcaseItem)
async def get_showcase_item(
    job_id: str, session: AsyncSession = Depends(get_session)
) -> ShowcaseItem:
    job = await session.get(Job, job_id)
    if job is None or not job.result_image_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not found")

    result = await session.get(Image, job.result_image_id)
    if result is None or not (result.featured and result.is_public):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not found")
    return showcase_item(job)
