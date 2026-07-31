"""Pluggable image storage.

`postgres` keeps bytes in the images table (zero extra credentials, ideal for a
free-tier demo), `local` writes to disk (fast dev loop), `s3` targets any
S3-compatible bucket (R2/B2/MinIO) for when the demo outgrows the database.
Swapping backends never changes calling code.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import logging
from abc import ABC, abstractmethod
from pathlib import Path

from PIL import Image as PILImage
from PIL import ImageOps

from .config import settings

log = logging.getLogger(__name__)

EXT_BY_MIME = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
}


class StoredBlob:
    """Result of a write: how to find the bytes again."""

    __slots__ = ("backend", "inline", "ref")

    def __init__(self, backend: str, ref: str = "", inline: bytes | None = None) -> None:
        self.backend = backend
        self.ref = ref
        self.inline = inline


class StorageBackend(ABC):
    name: str

    @abstractmethod
    async def put(self, image_id: str, data: bytes, mime: str) -> StoredBlob: ...

    @abstractmethod
    async def get(self, ref: str, inline: bytes | None) -> bytes: ...

    @abstractmethod
    async def delete(self, ref: str) -> None: ...

    def public_url(self, ref: str) -> str | None:
        """Direct CDN URL when the backend has one, else None (serve via API)."""
        return None


class PostgresStorage(StorageBackend):
    name = "postgres"

    async def put(self, image_id: str, data: bytes, mime: str) -> StoredBlob:
        return StoredBlob(self.name, ref="", inline=data)

    async def get(self, ref: str, inline: bytes | None) -> bytes:
        if inline is None:
            raise FileNotFoundError("image row has no inline bytes")
        return bytes(inline)

    async def delete(self, ref: str) -> None:
        return None  # row deletion removes the bytes


class LocalStorage(StorageBackend):
    name = "local"

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, ref: str) -> Path:
        # ref is always "<shard>/<id><ext>" produced by put(); reject traversal.
        candidate = (self.root / ref).resolve()
        if not str(candidate).startswith(str(self.root)):
            raise ValueError("refusing path outside storage root")
        return candidate

    async def put(self, image_id: str, data: bytes, mime: str) -> StoredBlob:
        ext = EXT_BY_MIME.get(mime, ".bin")
        ref = f"{image_id[:2]}/{image_id}{ext}"
        path = self._path(ref)

        def _write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)

        await asyncio.to_thread(_write)
        return StoredBlob(self.name, ref=ref)

    async def get(self, ref: str, inline: bytes | None) -> bytes:
        if inline is not None:
            return bytes(inline)
        return await asyncio.to_thread(self._path(ref).read_bytes)

    async def delete(self, ref: str) -> None:
        def _rm() -> None:
            try:
                self._path(ref).unlink(missing_ok=True)
            except (OSError, ValueError) as exc:
                log.warning("could not delete %s: %s", ref, exc)

        await asyncio.to_thread(_rm)


class S3Storage(StorageBackend):
    name = "s3"

    def __init__(self) -> None:
        import boto3  # imported lazily: only needed for this backend

        self.bucket = settings.s3_bucket
        self.public_base = settings.s3_public_base_url.rstrip("/")
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url or None,
            region_name=settings.s3_region,
            aws_access_key_id=settings.s3_access_key_id or None,
            aws_secret_access_key=settings.s3_secret_access_key or None,
        )

    async def put(self, image_id: str, data: bytes, mime: str) -> StoredBlob:
        ext = EXT_BY_MIME.get(mime, ".bin")
        key = f"images/{image_id[:2]}/{image_id}{ext}"
        await asyncio.to_thread(
            self._client.put_object,
            Bucket=self.bucket,
            Key=key,
            Body=data,
            ContentType=mime,
            CacheControl="public, max-age=31536000, immutable",
        )
        return StoredBlob(self.name, ref=key)

    async def get(self, ref: str, inline: bytes | None) -> bytes:
        if inline is not None:
            return bytes(inline)
        obj = await asyncio.to_thread(self._client.get_object, Bucket=self.bucket, Key=ref)
        return obj["Body"].read()

    async def delete(self, ref: str) -> None:
        await asyncio.to_thread(self._client.delete_object, Bucket=self.bucket, Key=ref)

    def public_url(self, ref: str) -> str | None:
        return f"{self.public_base}/{ref}" if self.public_base else None


_backend: StorageBackend | None = None


def get_storage() -> StorageBackend:
    global _backend
    if _backend is None:
        if settings.storage_backend == "postgres":
            _backend = PostgresStorage()
        elif settings.storage_backend == "s3":
            _backend = S3Storage()
        else:
            _backend = LocalStorage(settings.storage_local_dir)
        log.info("storage backend: %s", _backend.name)
    return _backend


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def normalise_upload(data: bytes, *, max_pixels: int) -> tuple[bytes, int, int, str, bool, bool]:
    """Validate, orient, bound and inspect an uploaded photograph.

    Returns (data, width, height, mime, downscaled, is_grayscale).

    Three things happen here rather than in the worker. EXIF orientation is
    applied, because a phone photo of a print is usually rotated and every later
    stage would otherwise work on a sideways image. Oversized scans are
    downscaled, which bounds storage and worker VRAM at the edge instead of
    discovering the problem mid-pipeline. And the image is checked for being
    effectively monochrome, so the UI can offer colourisation only when it makes
    sense.
    """
    try:
        with PILImage.open(io.BytesIO(data)) as probe:
            probe.verify()
        with PILImage.open(io.BytesIO(data)) as image:
            fmt = (image.format or "").upper()
            image = ImageOps.exif_transpose(image)
            had_exif_rotation = image.size != PILImage.open(io.BytesIO(data)).size
            image = image.convert("RGB")

            pixels = image.width * image.height
            downscaled = False
            if pixels > max_pixels:
                ratio = (max_pixels / pixels) ** 0.5
                image = image.resize(
                    (max(1, int(image.width * ratio)), max(1, int(image.height * ratio))),
                    PILImage.LANCZOS,
                )
                downscaled = True

            is_grayscale = _looks_monochrome(image)

            if downscaled or had_exif_rotation or fmt not in {"PNG", "JPEG", "WEBP"}:
                buffer = io.BytesIO()
                image.save(buffer, format="PNG", optimize=True)
                data = buffer.getvalue()
                mime = "image/png"
            else:
                mime = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}[fmt]

            return data, image.width, image.height, mime, downscaled, is_grayscale
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"not a decodable image: {exc}") from exc


def _looks_monochrome(image: PILImage.Image, tolerance: int = 12) -> bool:
    """True when channel differences are small enough to call it black and white.

    Sepia and faded prints are technically colour but carry no real chroma
    information, so they are treated as monochrome for colourisation purposes.
    """
    sample = image.resize((64, 64), PILImage.BILINEAR)
    pixels = list(sample.getdata())
    if not pixels:
        return False
    spread = sum(max(p) - min(p) for p in pixels) / len(pixels)
    return spread <= tolerance


def probe_image(data: bytes) -> tuple[int, int, str]:
    """Return (width, height, mime). Raises ValueError on non-images."""
    try:
        with PILImage.open(io.BytesIO(data)) as im:
            im.verify()
        with PILImage.open(io.BytesIO(data)) as im:
            fmt = (im.format or "").upper()
            width, height = im.size
    except Exception as exc:
        raise ValueError(f"not a decodable image: {exc}") from exc

    mime = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}.get(fmt)
    if mime is None:
        raise ValueError(f"unsupported image format: {fmt or 'unknown'}")
    return width, height, mime
