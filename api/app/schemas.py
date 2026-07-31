"""Pydantic request/response contracts. These also generate the OpenAPI docs."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .config import settings
from .profiles import DEFAULT_PROFILE, STAGE_ORDER

TierT = Literal["fast", "balanced", "max"]
StageT = Literal["descratch", "denoise", "colorize", "upscale", "face_enhance"]


# --------------------------------------------------------------------------- #
# public: creating and reading jobs
# --------------------------------------------------------------------------- #
class JobCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_image_id: str = Field(max_length=32)
    profile: str = DEFAULT_PROFILE
    tier: TierT | None = None

    # Explicit per-stage overrides on top of the profile, e.g. {"colorize": true}.
    stages: dict[StageT, bool] | None = None

    scale: Literal[1, 2, 4] | None = None
    fidelity: float | None = Field(default=None, ge=0.0, le=1.0)
    denoise_strength: float | None = Field(default=None, ge=0.0, le=1.0)
    auto_mask: bool | None = None
    mask_image_id: str | None = Field(default=None, max_length=32)
    seed: int = Field(default=-1, ge=-1, le=2**31 - 1)

    # Off by default: these are people's family photographs.
    share_public: bool = False
    notes: str = Field(default="", max_length=500)

    @field_validator("profile")
    @classmethod
    def _known_profile(cls, value: str) -> str:
        from .profiles import PROFILES_BY_ID

        if value not in PROFILES_BY_ID:
            raise ValueError(f"unknown profile; expected one of {sorted(PROFILES_BY_ID)}")
        return value


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    status: str
    profile: str
    tier: str
    stages: list[str]
    stages_completed: list[str]

    scale: int
    fidelity: float
    denoise_strength: float
    auto_mask: bool
    seed: int

    progress: float
    stage: str
    stage_index: int
    progress_step: int
    progress_total: int
    attempts: int
    max_attempts: int
    queue_position: int | None = None
    duration_ms: int
    stage_timings: dict[str, Any]
    error: str
    notes: str

    source_image_id: str
    mask_image_id: str | None = None
    damage_map_id: str | None = None
    result_image_id: str | None = None
    source_url: str | None = None
    result_url: str | None = None
    damage_map_url: str | None = None

    source_width: int
    source_height: int
    result_width: int
    result_height: int
    damage_ratio: float
    faces_found: int

    worker_id: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class JobListOut(BaseModel):
    items: list[JobOut]
    total: int


class UploadResult(BaseModel):
    image_id: str
    url: str
    width: int
    height: int
    mime: str
    size_bytes: int
    is_grayscale: bool
    downscaled: bool = False


# --------------------------------------------------------------------------- #
# worker protocol
# --------------------------------------------------------------------------- #
class WorkerRegister(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = Field(max_length=120)
    gpu_name: str = Field(default="", max_length=160)
    vram_mb: int = 0
    version: str = Field(default="", max_length=40)
    stages: list[StageT] = Field(default_factory=list)
    tiers: list[TierT] = Field(default_factory=lambda: ["fast"])
    max_pixels: int = 0
    meta: dict[str, Any] = Field(default_factory=dict)


class WorkerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    gpu_name: str
    vram_mb: int
    version: str
    stages: list[str]
    tiers: list[str]
    max_pixels: int
    jobs_completed: int
    jobs_failed: int
    last_seen_at: datetime
    online: bool = True


class ClaimRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    worker_id: str = Field(max_length=32)
    stages: list[StageT] = Field(default_factory=list)
    tiers: list[TierT] = Field(default_factory=lambda: ["fast"])
    max_pixels: int = 0
    wait_seconds: int = Field(default=25, ge=0, le=60)


class ClaimedJob(BaseModel):
    """Everything a worker needs for one job, with no extra round trips."""

    id: str
    profile: str
    tier: str
    stages: list[str]
    scale: int
    fidelity: float
    denoise_strength: float
    auto_mask: bool
    seed: int
    params: dict[str, Any] = Field(default_factory=dict)
    source_image_url: str
    mask_image_url: str | None = None
    source_width: int
    source_height: int
    lease_expires_at: datetime
    attempt: int


class ProgressUpdate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    stage: str = Field(default="", max_length=40)
    stage_index: int = Field(default=0, ge=0)
    step: int = Field(default=0, ge=0)
    total: int = Field(default=0, ge=0)
    # Overall completion across the whole pipeline, computed by the worker which
    # is the only party that knows how expensive each remaining stage is.
    overall: float | None = Field(default=None, ge=0.0, le=1.0)


class FailReport(BaseModel):
    model_config = ConfigDict(extra="ignore")

    error: str = Field(default="", max_length=2000)
    retryable: bool = True
    stage: str = Field(default="", max_length=40)


class LeaseAck(BaseModel):
    ok: bool = True
    lease_expires_at: datetime | None = None
    canceled: bool = False


# --------------------------------------------------------------------------- #
# profiles, showcase, model card, status
# --------------------------------------------------------------------------- #
class StageInfo(BaseModel):
    id: str
    label: str
    note: str


class ProfileOut(BaseModel):
    id: str
    label: str
    description: str
    best_for: str
    stages: list[str]
    tier: str
    requires_mask: bool = False
    defaults: dict[str, Any]


class ShowcaseItem(BaseModel):
    job_id: str
    before_url: str
    after_url: str
    profile: str
    stages: list[str]
    source_width: int
    source_height: int
    result_width: int
    result_height: int
    damage_ratio: float
    faces_found: int
    duration_ms: int
    notes: str
    featured: bool
    created_at: datetime


class ShowcasePage(BaseModel):
    items: list[ShowcaseItem]
    next_cursor: str | None = None


class EvalRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    commit_sha: str
    results: dict[str, Any]
    notes: str
    created_at: datetime


class EvalRunCreate(BaseModel):
    name: str = Field(max_length=120)
    commit_sha: str = Field(default="", max_length=40)
    results: dict[str, Any]
    notes: str = ""
    make_current: bool = True


class QueueStatus(BaseModel):
    queued: int
    running: int
    workers_online: int
    workers: list[WorkerOut]
    accepting_jobs: bool
    available_stages: list[str]
    est_wait_seconds: int | None = None
    avg_duration_ms: int | None = None
    max_upload_mb: int = settings.max_upload_bytes // (1024 * 1024)
    max_source_pixels: int = settings.max_source_pixels


class LivenessOut(BaseModel):
    """Process liveness. No dependency checks, so platform probes cannot flap."""

    status: str
    version: str
    environment: str
    storage_backend: str


class HealthOut(BaseModel):
    status: str
    version: str
    environment: str
    database: bool
    storage_backend: str


ALL_STAGES: list[StageInfo] = []  # populated by the profiles router at import time
STAGE_SEQUENCE = STAGE_ORDER
