"""HTTP client for the control-plane worker protocol."""

from __future__ import annotations

import io
import json
import logging
from dataclasses import dataclass

import httpx
from PIL import Image

log = logging.getLogger("smriti.worker.client")


@dataclass
class ClaimedJob:
    id: str
    profile: str
    tier: str
    stages: list[str]
    scale: int
    fidelity: float
    denoise_strength: float
    auto_mask: bool
    seed: int
    params: dict
    source_image_url: str
    mask_image_url: str | None
    source_width: int
    source_height: int
    attempt: int

    @classmethod
    def from_json(cls, data: dict) -> ClaimedJob:
        return cls(
            id=data["id"],
            profile=data.get("profile", ""),
            tier=data.get("tier", "balanced"),
            stages=list(data.get("stages") or []),
            scale=int(data.get("scale", 1)),
            fidelity=float(data.get("fidelity", 0.75)),
            denoise_strength=float(data.get("denoise_strength", 0.35)),
            auto_mask=bool(data.get("auto_mask", True)),
            seed=int(data.get("seed", 0)),
            params=data.get("params") or {},
            source_image_url=data["source_image_url"],
            mask_image_url=data.get("mask_image_url"),
            source_width=int(data.get("source_width", 0)),
            source_height=int(data.get("source_height", 0)),
            attempt=int(data.get("attempt", 1)),
        )


class ControlPlaneClient:
    def __init__(self, api_url: str, api_key: str, timeout: float = 120.0) -> None:
        self.api_url = api_url.rstrip("/")
        self._client = httpx.Client(
            base_url=self.api_url,
            headers={"X-API-Key": api_key},
            timeout=httpx.Timeout(timeout, connect=15.0),
            follow_redirects=True,
        )
        self.worker_id = ""

    # ------------------------------------------------------------------ #
    def register(
        self,
        *,
        name: str,
        gpu_name: str,
        vram_mb: int,
        version: str,
        stages: list[str],
        tiers: list[str],
        max_pixels: int,
        meta: dict | None = None,
    ) -> str:
        response = self._client.post(
            "/v1/worker/register",
            json={
                "name": name,
                "gpu_name": gpu_name,
                "vram_mb": vram_mb,
                "version": version,
                "stages": stages,
                "tiers": tiers,
                "max_pixels": max_pixels,
                "meta": meta or {},
            },
        )
        response.raise_for_status()
        self.worker_id = response.json()["id"]
        return self.worker_id

    def heartbeat(self) -> None:
        try:
            self._client.post("/v1/worker/heartbeat", params={"worker_id": self.worker_id})
        except httpx.HTTPError as exc:
            log.debug("heartbeat failed: %s", exc)

    def claim(
        self, *, stages: list[str], tiers: list[str], max_pixels: int, wait_seconds: int
    ) -> ClaimedJob | None:
        response = self._client.post(
            "/v1/worker/claim",
            json={
                "worker_id": self.worker_id,
                "stages": stages,
                "tiers": tiers,
                "max_pixels": max_pixels,
                "wait_seconds": wait_seconds,
            },
            timeout=httpx.Timeout(wait_seconds + 30, connect=15.0),
        )
        if response.status_code == 204:
            return None
        response.raise_for_status()
        return ClaimedJob.from_json(response.json())

    def report_progress(
        self, job_id: str, *, stage: str, stage_index: int, step: int, total: int, overall: float
    ) -> bool:
        """Returns True to keep going, False if the job was canceled or reassigned."""
        try:
            response = self._client.post(
                f"/v1/worker/jobs/{job_id}/progress",
                params={"worker_id": self.worker_id},
                json={
                    "stage": stage,
                    "stage_index": stage_index,
                    "step": step,
                    "total": total,
                    "overall": overall,
                },
                timeout=httpx.Timeout(20.0, connect=10.0),
            )
        except httpx.HTTPError as exc:
            # A dropped progress ping is not a reason to abandon work; the lease
            # reaper is the backstop if the connection is genuinely gone.
            log.debug("progress update failed (continuing): %s", exc)
            return True

        if response.status_code == 409:
            log.warning("lease for %s was reassigned; abandoning", job_id)
            return False
        if response.status_code != 200:
            return True
        return not response.json().get("canceled", False)

    def submit_result(
        self,
        job_id: str,
        image: Image.Image,
        *,
        duration_ms: int,
        damage_ratio: float,
        faces_found: int,
        stage_timings: dict[str, float],
        damage_overlay: Image.Image | None = None,
    ) -> None:
        def encode(picture: Image.Image) -> bytes:
            buffer = io.BytesIO()
            picture.convert("RGB").save(buffer, format="PNG", optimize=True)
            return buffer.getvalue()

        files = {"file": (f"{job_id}.png", encode(image), "image/png")}
        if damage_overlay is not None:
            files["damage_map"] = (f"{job_id}-damage.png", encode(damage_overlay), "image/png")

        response = self._client.post(
            f"/v1/worker/jobs/{job_id}/result",
            files=files,
            data={
                "worker_id": self.worker_id,
                "duration_ms": str(duration_ms),
                "damage_ratio": str(damage_ratio),
                "faces_found": str(faces_found),
                "stage_timings": json.dumps(stage_timings),
            },
            timeout=httpx.Timeout(300.0, connect=15.0),
        )
        response.raise_for_status()

    def report_failure(
        self, job_id: str, error: str, *, retryable: bool = True, stage: str = ""
    ) -> None:
        try:
            self._client.post(
                f"/v1/worker/jobs/{job_id}/fail",
                params={"worker_id": self.worker_id},
                json={"error": error[:2000], "retryable": retryable, "stage": stage},
            )
        except httpx.HTTPError as exc:
            log.error("could not report failure for %s: %s", job_id, exc)

    def fetch_image(self, url: str) -> Image.Image:
        response = self._client.get(url)
        response.raise_for_status()
        return Image.open(io.BytesIO(response.content))

    def close(self) -> None:
        self._client.close()
