"""SQLAlchemy models for restoration jobs, images, workers and eval runs."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

try:  # pragma: no cover - Python >= 3.11
    from enum import StrEnum
except ImportError:  # pragma: no cover - Python 3.10
    from enum import Enum

    class StrEnum(str, Enum):  # type: ignore[no-redef]
        """Minimal 3.11 StrEnum shim so members render as their value."""

        def __str__(self) -> str:
            return str(self.value)


from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return uuid.uuid4().hex


class UTCDateTime(TypeDecorator):
    """Timezone-aware in and out on every dialect.

    SQLite has no native tz support and returns naive datetimes, which would make
    arithmetic against utcnow() fail in dev but not in production.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def process_result_value(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class Base(DeclarativeBase):
    pass


# --------------------------------------------------------------------------- #
# enums (plain strings in the column, for painless migrations)
# --------------------------------------------------------------------------- #
class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"


class Tier(StrEnum):
    """How much compute the caller is willing to spend."""

    FAST = "fast"
    BALANCED = "balanced"
    MAX = "max"


class ImageRole(StrEnum):
    SOURCE = "source"  # what the user uploaded
    MASK = "mask"  # user-painted or auto-detected damage
    DAMAGE_MAP = "damage"  # visualisation of what the detector found
    RESULT = "result"


# --------------------------------------------------------------------------- #
# tables
# --------------------------------------------------------------------------- #
class Worker(Base):
    __tablename__ = "workers"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120), index=True)
    gpu_name: Mapped[str] = mapped_column(String(160), default="")
    vram_mb: Mapped[int] = mapped_column(Integer, default=0)
    version: Mapped[str] = mapped_column(String(40), default="")
    # Which pipeline stages this worker can actually run, e.g. ["descratch","upscale"].
    stages: Mapped[list] = mapped_column(JSON, default=list)
    tiers: Mapped[list] = mapped_column(JSON, default=list)
    max_pixels: Mapped[int] = mapped_column(Integer, default=0)
    jobs_completed: Mapped[int] = mapped_column(Integer, default=0)
    jobs_failed: Mapped[int] = mapped_column(Integer, default=0)
    registered_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)

    jobs: Mapped[list[Job]] = relationship(back_populates="worker")


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    status: Mapped[str] = mapped_column(String(16), default=JobStatus.QUEUED, index=True)
    profile: Mapped[str] = mapped_column(String(48), default="full_restore")
    tier: Mapped[str] = mapped_column(String(16), default=Tier.BALANCED)

    # Ordered pipeline for this job, resolved from the profile plus overrides.
    stages: Mapped[list] = mapped_column(JSON, default=list)
    stages_completed: Mapped[list] = mapped_column(JSON, default=list)

    # restoration parameters
    scale: Mapped[int] = mapped_column(Integer, default=2)
    fidelity: Mapped[float] = mapped_column(Float, default=0.75)
    denoise_strength: Mapped[float] = mapped_column(Float, default=0.35)
    auto_mask: Mapped[bool] = mapped_column(Boolean, default=True)
    seed: Mapped[int] = mapped_column(Integer, default=0)
    params: Mapped[dict] = mapped_column(JSON, default=dict)

    # images
    source_image_id: Mapped[str] = mapped_column(String(32), default="", index=True)
    mask_image_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    damage_map_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    result_image_id: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # measured outcome, per job
    source_width: Mapped[int] = mapped_column(Integer, default=0)
    source_height: Mapped[int] = mapped_column(Integer, default=0)
    result_width: Mapped[int] = mapped_column(Integer, default=0)
    result_height: Mapped[int] = mapped_column(Integer, default=0)
    damage_ratio: Mapped[float] = mapped_column(Float, default=0.0)
    faces_found: Mapped[int] = mapped_column(Integer, default=0)

    # scheduling / fault tolerance
    priority: Mapped[int] = mapped_column(Integer, default=0)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime, nullable=True, index=True
    )
    worker_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("workers.id", ondelete="SET NULL"), nullable=True
    )

    # progress
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    stage: Mapped[str] = mapped_column(String(40), default="")
    stage_index: Mapped[int] = mapped_column(Integer, default=0)
    progress_step: Mapped[int] = mapped_column(Integer, default=0)
    progress_total: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    stage_timings: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(Text, default="")

    # provenance
    session_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    ip_hash: Mapped[str] = mapped_column(String(64), default="", index=True)
    share_public: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    worker: Mapped[Worker | None] = relationship(back_populates="jobs")

    __table_args__ = (
        Index("ix_jobs_queue_pick", "status", "priority", "created_at"),
        Index("ix_jobs_session_created", "session_id", "created_at"),
    )


class Image(Base):
    __tablename__ = "images"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    job_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    role: Mapped[str] = mapped_column(String(12), default=ImageRole.RESULT)

    mime: Mapped[str] = mapped_column(String(40), default="image/png")
    width: Mapped[int] = mapped_column(Integer, default=0)
    height: Mapped[int] = mapped_column(Integer, default=0)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    sha256: Mapped[str] = mapped_column(String(64), default="", index=True)

    backend: Mapped[str] = mapped_column(String(12), default="local")
    ref: Mapped[str] = mapped_column(String(400), default="")
    data: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)

    # Restoration inputs are personal photographs. Nothing is public unless the
    # uploader explicitly opts in, and the showcase is curated by hand.
    is_public: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    featured: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    nsfw: Mapped[bool] = mapped_column(Boolean, default=False)

    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)

    __table_args__ = (Index("ix_images_showcase", "is_public", "featured", "created_at"),)


class EvalRun(Base):
    """A published restoration benchmark, rendered by the model card page."""

    __tablename__ = "eval_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120), default="")
    commit_sha: Mapped[str] = mapped_column(String(40), default="")
    is_current: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    results: Mapped[dict] = mapped_column(JSON, default=dict)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class RateEvent(Base):
    """Append-only quota ledger for anonymous public users."""

    __tablename__ = "rate_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bucket: Mapped[str] = mapped_column(String(80), index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
