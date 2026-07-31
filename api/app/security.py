"""Auth for GPU workers and admins, plus anonymous identity and DB-backed quotas.

Quotas live in Postgres rather than process memory so they still hold when
Render runs more than one API replica.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from datetime import timedelta

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .db import get_session
from .models import RateEvent, utcnow

SESSION_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


def _constant_time_in(candidate: str, allowed: list[str]) -> bool:
    return any(hmac.compare_digest(candidate, item) for item in allowed if item)


async def require_worker(x_api_key: str | None = Header(default=None)) -> str:
    """Authenticate a GPU worker. Returns the presented key."""
    if not settings.worker_api_keys:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "WORKER_API_KEYS is not configured on the server",
        )
    if not x_api_key or not _constant_time_in(x_api_key, settings.worker_api_keys):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid worker key")
    return x_api_key


async def require_admin(x_api_key: str | None = Header(default=None)) -> str:
    if not settings.admin_api_key:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "ADMIN_API_KEY is not configured")
    if not x_api_key or not hmac.compare_digest(x_api_key, settings.admin_api_key):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid admin key")
    return x_api_key


def hash_ip(request: Request) -> str:
    """Salted, truncated IP hash: enough to rate-limit, not enough to identify."""
    forwarded = request.headers.get("x-forwarded-for", "")
    ip = (
        forwarded.split(",")[0].strip()
        if forwarded
        else (request.client.host if request.client else "unknown")
    )
    salt = settings.admin_api_key or settings.app_name
    return hashlib.sha256(f"{salt}:{ip}".encode()).hexdigest()[:32]


class Identity:
    __slots__ = ("ip_hash", "session_id")

    def __init__(self, session_id: str, ip_hash: str) -> None:
        self.session_id = session_id
        self.ip_hash = ip_hash


async def client_identity(
    request: Request,
    x_session_id: str | None = Header(default=None),
) -> Identity:
    """Anonymous but stable identity for public callers."""
    session_id = x_session_id or ""
    if not SESSION_RE.match(session_id):
        session_id = "anon_" + secrets.token_urlsafe(12)
    return Identity(session_id=session_id, ip_hash=hash_ip(request))


class QuotaExceeded(HTTPException):
    def __init__(self, window: str, limit: int, retry_after: int) -> None:
        super().__init__(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"quota reached: {limit} generations per {window}",
            headers={"Retry-After": str(retry_after)},
        )


async def enforce_job_quota(
    identity: Identity = Depends(client_identity),
    session: AsyncSession = Depends(get_session),
) -> Identity:
    """Allow the burst, block the abuse. Charged on successful enqueue."""
    now = utcnow()
    for window, seconds, limit in (
        ("hour", 3600, settings.public_jobs_per_hour),
        ("day", 86400, settings.public_jobs_per_day),
    ):
        if limit <= 0:
            continue
        since = now - timedelta(seconds=seconds)
        for bucket in (f"job:s:{identity.session_id}", f"job:i:{identity.ip_hash}"):
            used = await session.scalar(
                select(func.count())
                .select_from(RateEvent)
                .where(RateEvent.bucket == bucket, RateEvent.created_at >= since)
            )
            if (used or 0) >= limit:
                raise QuotaExceeded(window, limit, retry_after=min(seconds, 900))
    return identity


async def charge_job_quota(session: AsyncSession, identity: Identity) -> None:
    session.add(RateEvent(bucket=f"job:s:{identity.session_id}"))
    session.add(RateEvent(bucket=f"job:i:{identity.ip_hash}"))


async def prune_rate_events(session: AsyncSession) -> int:
    cutoff = utcnow() - timedelta(days=2)
    result = await session.execute(delete(RateEvent).where(RateEvent.created_at < cutoff))
    await session.commit()
    return result.rowcount or 0
