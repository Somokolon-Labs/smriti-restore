"""Worker configuration, env-driven so the same file runs on a laptop or a rented pod."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

ALL_STAGES = ["descratch", "denoise", "colorize", "upscale", "face_enhance"]


def load_dotenv() -> None:
    """Minimal .env loader; real environment variables always win."""
    for candidate in (ROOT / ".env", Path.cwd() / ".env"):
        if not candidate.exists():
            continue
        for line in candidate.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())
        return


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    return default if raw is None else raw.strip().lower() in {"1", "true", "yes", "on"}


def _list(name: str, default: list[str]) -> list[str]:
    parsed = [part.strip() for part in os.getenv(name, "").split(",") if part.strip()]
    return parsed or default


@dataclass
class WorkerConfig:
    api_url: str = ""
    api_key: str = ""
    name: str = "local-worker"

    inpaint_model_id: str = "stable-diffusion-v1-5/stable-diffusion-inpainting"
    upscale_model_id: str = "stabilityai/stable-diffusion-x4-upscaler"
    refine_model_id: str = "stable-diffusion-v1-5/stable-diffusion-v1-5"

    dtype: str = "float16"
    attention_slicing: bool = True
    vae_slicing: bool = True
    vae_tiling: bool = True
    cpu_offload: bool = False

    stages: list[str] = field(default_factory=lambda: list(ALL_STAGES))
    tiers: list[str] = field(default_factory=lambda: ["fast", "balanced"])
    poll_wait_seconds: int = 25
    progress_every: float = 2.0

    # Tiling bounds peak VRAM independently of how large the photograph is.
    # 512 in -> 2048 out per tile is what a 4GB card can hold with slicing on.
    upscale_tile: int = 384
    upscale_overlap: int = 48
    inpaint_tile: int = 512

    # Largest output this worker will accept, in pixels. Advertised at
    # registration so the control plane never hands it a job it cannot finish.
    max_pixels: int = 12_000_000

    face_min_size: int = 48
    face_padding: float = 0.35
    max_faces: int = 12

    @classmethod
    def from_env(cls) -> WorkerConfig:
        load_dotenv()
        return cls(
            api_url=os.getenv("SMRITI_API_URL", "http://127.0.0.1:8000").rstrip("/"),
            api_key=os.getenv("SMRITI_WORKER_KEY", ""),
            name=os.getenv("WORKER_NAME", "local-worker"),
            inpaint_model_id=os.getenv(
                "INPAINT_MODEL_ID", "stable-diffusion-v1-5/stable-diffusion-inpainting"
            ),
            upscale_model_id=os.getenv(
                "UPSCALE_MODEL_ID", "stabilityai/stable-diffusion-x4-upscaler"
            ),
            refine_model_id=os.getenv(
                "REFINE_MODEL_ID", "stable-diffusion-v1-5/stable-diffusion-v1-5"
            ),
            dtype=os.getenv("TORCH_DTYPE", "float16"),
            attention_slicing=_bool("ATTENTION_SLICING", True),
            vae_slicing=_bool("VAE_SLICING", True),
            vae_tiling=_bool("VAE_TILING", True),
            cpu_offload=_bool("CPU_OFFLOAD", False),
            stages=_list("WORKER_STAGES", list(ALL_STAGES)),
            tiers=_list("WORKER_TIERS", ["fast", "balanced"]),
            poll_wait_seconds=int(os.getenv("WORKER_POLL_SECONDS", "25")),
            progress_every=float(os.getenv("WORKER_PROGRESS_EVERY", "2")),
            upscale_tile=int(os.getenv("UPSCALE_TILE", "384")),
            upscale_overlap=int(os.getenv("UPSCALE_OVERLAP", "48")),
            inpaint_tile=int(os.getenv("INPAINT_TILE", "512")),
            max_pixels=int(os.getenv("WORKER_MAX_PIXELS", "12000000")),
            face_min_size=int(os.getenv("FACE_MIN_SIZE", "48")),
            face_padding=float(os.getenv("FACE_PADDING", "0.35")),
            max_faces=int(os.getenv("MAX_FACES", "12")),
        )

    def validated_stages(self) -> list[str]:
        """Keep the canonical order and drop anything unrecognised."""
        offered = set(self.stages)
        return [stage for stage in ALL_STAGES if stage in offered]
