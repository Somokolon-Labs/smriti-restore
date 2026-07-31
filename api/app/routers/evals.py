"""Published benchmark runs.

`ml/evaluate.py` posts its results here, and the model-card page renders whatever
is current. The numbers on the live site are therefore the numbers the harness
actually produced, not copy in a template.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..models import EvalRun, new_id
from ..schemas import EvalRunCreate, EvalRunOut
from ..security import require_admin

router = APIRouter(prefix="/v1/model", tags=["model"])


@router.get("/current", response_model=EvalRunOut)
async def current_run(session: AsyncSession = Depends(get_session)) -> EvalRunOut:
    run = await session.scalar(
        select(EvalRun).where(EvalRun.is_current.is_(True)).order_by(EvalRun.created_at.desc())
    )
    if run is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "no evaluation has been published yet; run ml/evaluate.py --publish",
        )
    return EvalRunOut.model_validate(run)


@router.get("/runs", response_model=list[EvalRunOut])
async def list_runs(
    limit: int = Query(default=20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
) -> list[EvalRunOut]:
    rows = (
        await session.scalars(select(EvalRun).order_by(EvalRun.created_at.desc()).limit(limit))
    ).all()
    return [EvalRunOut.model_validate(r) for r in rows]


@router.post(
    "/runs",
    response_model=EvalRunOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
)
async def publish_run(
    payload: EvalRunCreate,
    session: AsyncSession = Depends(get_session),
) -> EvalRunOut:
    if payload.make_current:
        await session.execute(update(EvalRun).values(is_current=False))

    run = EvalRun(
        id=new_id(),
        name=payload.name,
        commit_sha=payload.commit_sha,
        results=payload.results,
        notes=payload.notes,
        is_current=payload.make_current,
    )
    session.add(run)
    await session.commit()
    return EvalRunOut.model_validate(run)
