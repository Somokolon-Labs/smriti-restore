"""Image passthrough.

Content is immutable and addressed by id, so it is safe to cache hard. When the
storage backend has its own CDN URL the API hands out a redirect instead of
proxying the bytes.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..models import Image
from ..storage import get_storage

router = APIRouter(prefix="/v1", tags=["images"])

IMMUTABLE = "public, max-age=31536000, immutable"


@router.get("/images/{image_id}")
async def get_image(
    image_id: str,
    session: AsyncSession = Depends(get_session),
) -> Response:
    image = await session.get(Image, image_id)
    if image is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "image not found")

    storage = get_storage()
    if image.ref:
        direct = storage.public_url(image.ref)
        if direct:
            return RedirectResponse(direct, status_code=status.HTTP_307_TEMPORARY_REDIRECT)

    try:
        data = await storage.get(image.ref, image.data)
    except FileNotFoundError as exc:
        raise HTTPException(status.HTTP_410_GONE, "image bytes were pruned") from exc

    return Response(
        content=data,
        media_type=image.mime,
        headers={
            "Cache-Control": IMMUTABLE,
            "ETag": f'"{image.sha256[:32]}"',
            "Content-Disposition": f'inline; filename="smriti-{image_id[:8]}"',
            "X-Image-Width": str(image.width),
            "X-Image-Height": str(image.height),
        },
    )
