"""Restoration profiles and pipeline stages, served so the UI hard-codes nothing."""

from __future__ import annotations

from fastapi import APIRouter

from ..profiles import PROFILES, STAGE_LABELS, STAGE_NOTES, STAGE_ORDER
from ..schemas import ProfileOut, StageInfo

router = APIRouter(prefix="/v1", tags=["profiles"])


@router.get("/profiles", response_model=list[ProfileOut])
async def list_profiles() -> list[ProfileOut]:
    return [
        ProfileOut(
            id=profile["id"],
            label=profile["label"],
            description=profile["description"],
            best_for=profile["best_for"],
            stages=profile["stages"],
            tier=profile["tier"],
            requires_mask=bool(profile.get("requires_mask")),
            defaults=profile["defaults"],
        )
        for profile in PROFILES
    ]


@router.get("/stages", response_model=list[StageInfo])
async def list_stages() -> list[StageInfo]:
    """Pipeline stages in the order they are applied."""
    return [
        StageInfo(id=stage, label=STAGE_LABELS[stage], note=STAGE_NOTES[stage])
        for stage in STAGE_ORDER
    ]
