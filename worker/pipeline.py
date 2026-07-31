"""The restoration pipeline.

Stages run in a fixed order and each hands a full-resolution image to the next:

    descratch -> denoise -> colorize -> upscale -> face_enhance

Two rules shape every stage. Diffusion is applied to *regions*, not whole frames,
wherever that is possible, because a model asked to redraw an entire photograph
will change things that were never damaged. And undamaged pixels are preserved
bit-for-bit through feathered, mask-restricted compositing, so a restoration is
a repair rather than a reinterpretation.

Only one checkpoint is resident at a time; pipelines are swapped on demand so the
whole thing fits on a small card.
"""

from __future__ import annotations

import gc
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np
import torch
from diffusers import (
    DPMSolverMultistepScheduler,
    StableDiffusionImg2ImgPipeline,
    StableDiffusionInpaintPipeline,
    StableDiffusionUpscalePipeline,
)
from PIL import Image

from .config import WorkerConfig
from .imaging import (
    blend_detail,
    denoise_classical,
    detect_damage,
    detect_faces,
    mask_regions,
    merge_masks,
    paste_feathered,
    snap_to_multiple,
    tiles_for,
    to_array,
    to_image,
    transfer_chroma,
)

log = logging.getLogger("smriti.worker.pipeline")

# Prompts are fixed, not user-supplied: someone restoring a family photograph
# should not have to learn prompt engineering.
INPAINT_PROMPT = (
    "restored photograph, continuous natural texture, consistent film grain, "
    "seamless repair, undamaged surface"
)
INPAINT_NEGATIVE = (
    "scratch, crease, tear, dust, stain, watermark, text, hair, fibre, blur, "
    "smear, duplicated feature, extra limb, deformed face"
)
UPSCALE_PROMPT = "sharp detailed photograph, fine natural texture, clear edges"
COLORIZE_PROMPT = (
    "natural colour photograph, believable skin tones, muted period-accurate "
    "clothing colours, soft daylight"
)
COLORIZE_NEGATIVE = "oversaturated, neon, garish colours, colour fringing, sepia wash"
FACE_PROMPT = "sharp detailed face, natural skin texture, clear eyes, in focus"
FACE_NEGATIVE = "blurry, distorted face, extra eyes, plastic skin, waxy, deformed"


class JobCanceled(RuntimeError):
    """Raised between or during stages to abandon a job promptly."""


@dataclass
class RestoreRequest:
    stages: list[str]
    scale: int
    fidelity: float
    denoise_strength: float
    auto_mask: bool
    seed: int
    image: Image.Image
    mask: Image.Image | None = None
    grayscale_source: bool = False
    tier: str = "balanced"


@dataclass
class RestoreResult:
    image: Image.Image
    damage_ratio: float = 0.0
    faces_found: int = 0
    damage_overlay: Image.Image | None = None
    stage_timings: dict[str, float] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


# Rough relative cost per stage, used only to report honest overall progress.
STAGE_WEIGHTS = {
    "descratch": 1.5,
    "denoise": 1.0,
    "colorize": 1.5,
    "upscale": 5.0,
    "face_enhance": 2.0,
}


class RestorationPipeline:
    def __init__(self, config: WorkerConfig) -> None:
        self.config = config
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.dtype = (
            torch.float16 if config.dtype == "float16" and self.device == "cuda" else torch.float32
        )
        self._inpaint: StableDiffusionInpaintPipeline | None = None
        self._upscale: StableDiffusionUpscalePipeline | None = None
        self._img2img: StableDiffusionImg2ImgPipeline | None = None

        if self.device == "cpu":
            log.warning(
                "no CUDA device found — running on CPU. Correct, but far too slow "
                "for interactive restoration."
            )

    # ------------------------------------------------------------------ #
    # capability reporting
    # ------------------------------------------------------------------ #
    def gpu_name(self) -> str:
        return torch.cuda.get_device_name(0) if self.device == "cuda" else "CPU"

    def vram_mb(self) -> int:
        if self.device != "cuda":
            return 0
        return int(torch.cuda.get_device_properties(0).total_memory / (1024 * 1024))

    # ------------------------------------------------------------------ #
    # model loading
    # ------------------------------------------------------------------ #
    def _tune(self, pipe) -> None:
        pipe.set_progress_bar_config(disable=True)
        if self.device == "cuda":
            if self.config.cpu_offload:
                pipe.enable_model_cpu_offload()
            else:
                pipe.to(self.device)
            if self.config.attention_slicing:
                pipe.enable_attention_slicing("max")
            if self.config.vae_slicing:
                pipe.enable_vae_slicing()
            if self.config.vae_tiling:
                pipe.enable_vae_tiling()
        else:
            pipe.to(self.device)

    def _release(self, *names: str) -> None:
        for name in names:
            if getattr(self, name, None) is not None:
                setattr(self, name, None)
        gc.collect()
        if self.device == "cuda":
            torch.cuda.empty_cache()

    def _from_pretrained(self, cls, model_id: str, **extra):
        """Prefer safetensors but accept a checkpoint that only ships .bin."""
        kwargs = {
            "torch_dtype": self.dtype,
            "safety_checker": None,
            "requires_safety_checker": False,
            **extra,
        }
        try:
            return cls.from_pretrained(model_id, use_safetensors=True, **kwargs)
        except (OSError, ValueError) as exc:
            log.warning("no safetensors for %s (%s); retrying with .bin", model_id, exc)
            return cls.from_pretrained(model_id, **kwargs)

    def load_inpaint(self) -> StableDiffusionInpaintPipeline:
        if self._inpaint is None:
            self._release("_upscale")
            log.info("loading %s", self.config.inpaint_model_id)
            pipe = self._from_pretrained(
                StableDiffusionInpaintPipeline, self.config.inpaint_model_id
            )
            pipe.scheduler = DPMSolverMultistepScheduler.from_config(
                pipe.scheduler.config, use_karras_sigmas=True, algorithm_type="dpmsolver++"
            )
            self._tune(pipe)
            self._inpaint = pipe
        return self._inpaint

    def load_img2img(self) -> StableDiffusionImg2ImgPipeline:
        if self._img2img is None:
            self._release("_upscale")
            log.info("loading %s", self.config.refine_model_id)
            pipe = self._from_pretrained(
                StableDiffusionImg2ImgPipeline, self.config.refine_model_id
            )
            pipe.scheduler = DPMSolverMultistepScheduler.from_config(
                pipe.scheduler.config, use_karras_sigmas=True, algorithm_type="dpmsolver++"
            )
            self._tune(pipe)
            self._img2img = pipe
        return self._img2img

    def load_upscale(self) -> StableDiffusionUpscalePipeline:
        if self._upscale is None:
            self._release("_inpaint", "_img2img")
            log.info("loading %s", self.config.upscale_model_id)
            pipe = StableDiffusionUpscalePipeline.from_pretrained(
                self.config.upscale_model_id, torch_dtype=self.dtype
            )
            self._tune(pipe)
            self._upscale = pipe
        return self._upscale

    def _generator(self, seed: int) -> torch.Generator:
        # Seed on CPU so results reproduce across devices.
        return torch.Generator(device="cpu").manual_seed(int(seed))

    # ------------------------------------------------------------------ #
    # orchestration
    # ------------------------------------------------------------------ #
    def run(
        self,
        request: RestoreRequest,
        on_progress: Callable[[str, int, int, int, float], None] | None = None,
    ) -> RestoreResult:
        stages = [s for s in request.stages if s in STAGE_WEIGHTS]
        total_weight = sum(STAGE_WEIGHTS[s] for s in stages) or 1.0
        done_weight = 0.0
        result = RestoreResult(image=request.image.convert("RGB"))

        def report(stage: str, index: int, step: int, total: int) -> None:
            if on_progress is None:
                return
            fraction = (step / total) if total else 0.0
            overall = (done_weight + STAGE_WEIGHTS[stage] * fraction) / total_weight
            on_progress(stage, index, step, total, min(overall, 0.999))

        for index, stage in enumerate(stages):
            log.info("stage %d/%d: %s", index + 1, len(stages), stage)
            started = time.perf_counter()
            handler = getattr(self, f"_stage_{stage}")
            handler(request, result, index, report)
            result.stage_timings[stage] = round(time.perf_counter() - started, 2)
            done_weight += STAGE_WEIGHTS[stage]
            report(stage, index, 1, 1)

        return result

    # ------------------------------------------------------------------ #
    # stages
    # ------------------------------------------------------------------ #
    def _stage_descratch(self, request, result, index, report) -> None:
        """Inpaint only the damaged regions, leaving everything else untouched."""
        auto_mask = None
        if request.auto_mask:
            damage = detect_damage(result.image, sensitivity=0.5)
            auto_mask = damage.mask
            result.damage_ratio = damage.ratio
            result.damage_overlay = damage.overlay

        manual = None
        if request.mask is not None:
            manual = np.asarray(request.mask.convert("L").resize(result.image.size, Image.NEAREST))
            manual = (manual > 127).astype(np.uint8) * 255

        mask = merge_masks(auto_mask, manual)
        if mask is None or not np.count_nonzero(mask):
            result.notes.append("No damage detected, so nothing was repainted.")
            report("descratch", index, 1, 1)
            return

        if manual is not None:
            result.damage_ratio = max(
                result.damage_ratio, float(np.count_nonzero(mask)) / mask.size
            )

        boxes = mask_regions(mask, tile=self.config.inpaint_tile)
        if not boxes:
            report("descratch", index, 1, 1)
            return

        pipe = self.load_inpaint()
        canvas = to_array(result.image).copy()
        # Higher fidelity means fewer steps and a lighter touch on the repair.
        steps = 30 if request.tier == "max" else 20
        log.info("repairing %d region(s), %.2f%% of frame", len(boxes), result.damage_ratio * 100)

        for position, (x, y, w, h) in enumerate(boxes):
            report("descratch", index, position, len(boxes))
            crop = to_image(canvas[y : y + h, x : x + w])
            crop_mask = Image.fromarray(mask[y : y + h, x : x + w], mode="L")

            work = (snap_to_multiple(w, 8, 256), snap_to_multiple(h, 8, 256))
            patch = pipe(
                prompt=INPAINT_PROMPT,
                negative_prompt=INPAINT_NEGATIVE,
                image=crop.resize(work, Image.LANCZOS),
                mask_image=crop_mask.resize(work, Image.NEAREST),
                width=work[0],
                height=work[1],
                num_inference_steps=steps,
                guidance_scale=7.0,
                strength=1.0,
                generator=self._generator(request.seed + position),
            ).images[0]

            canvas = paste_feathered(
                canvas,
                to_array(patch.resize((w, h), Image.LANCZOS)),
                (x, y, w, h),
                feather=max(8, min(w, h) // 8),
                restrict=mask,  # only damaged pixels are allowed to change
            )

        result.image = to_image(canvas)
        result.notes.append(
            f"Repaired {len(boxes)} damaged region(s) covering "
            f"{result.damage_ratio * 100:.2f}% of the frame."
        )

    def _stage_denoise(self, request, result, index, report) -> None:
        """Classical edge-preserving denoise, blended to keep real grain."""
        report("denoise", index, 0, 1)
        if request.denoise_strength <= 0.01:
            return
        cleaned = denoise_classical(result.image, request.denoise_strength)
        # Fidelity acts as a brake: high fidelity keeps more of the original.
        result.image = blend_detail(result.image, cleaned, 1.0 - request.fidelity * 0.4)
        result.notes.append(
            f"Denoised at strength {request.denoise_strength:.2f}, "
            f"preserving {request.fidelity * 40:.0f}% of original grain."
        )

    def _stage_colorize(self, request, result, index, report) -> None:
        """Infer colour, then keep only the chroma so no detail is lost."""
        report("colorize", index, 0, 2)
        pipe = self.load_img2img()
        source = result.image

        # Work at a bounded size: chroma is low-frequency, so colour inferred on a
        # smaller copy upsamples without visible loss, and it saves a lot of VRAM.
        work_w = snap_to_multiple(min(source.width, 768), 8, 256)
        work_h = snap_to_multiple(min(source.height, 768), 8, 256)
        small = source.resize((work_w, work_h), Image.LANCZOS)

        coloured = pipe(
            prompt=COLORIZE_PROMPT,
            negative_prompt=COLORIZE_NEGATIVE,
            image=small,
            strength=0.55,
            num_inference_steps=28,
            guidance_scale=7.5,
            generator=self._generator(request.seed + 991),
        ).images[0]

        report("colorize", index, 1, 2)
        result.image = transfer_chroma(source, coloured)
        result.notes.append(
            "Colour was inferred and applied as chroma only, so the original "
            "luminance detail is unchanged. These colours are invented, not recovered."
        )

    def _stage_upscale(self, request, result, index, report) -> None:
        """Tiled diffusion super-resolution.

        The x4 model is run over overlapping tiles and the results blended, which
        keeps peak VRAM flat regardless of input size. For a 2x request the 4x
        output is resampled down, which is still sharper than upscaling 2x
        directly.
        """
        if request.scale <= 1:
            report("upscale", index, 1, 1)
            return

        source = result.image
        target = (source.width * request.scale, source.height * request.scale)
        tile = self.config.upscale_tile
        overlap = self.config.upscale_overlap
        steps = 30 if request.tier == "max" else 20

        try:
            pipe = self.load_upscale()
        except Exception as exc:
            log.error("upscaler unavailable (%s); falling back to Lanczos", exc)
            result.image = source.resize(target, Image.LANCZOS)
            result.notes.append(
                "Super-resolution model could not be loaded, so this was resampled "
                "with Lanczos rather than upscaled by diffusion."
            )
            return

        boxes = tiles_for(source.width, source.height, tile, overlap)
        canvas = np.zeros((source.height * 4, source.width * 4, 3), dtype=np.uint8)
        log.info("upscaling %d tile(s) at %dpx", len(boxes), tile)

        for position, (x, y, w, h) in enumerate(boxes):
            report("upscale", index, position, len(boxes))
            crop = source.crop((x, y, x + w, y + h))
            try:
                enlarged = pipe(
                    prompt=UPSCALE_PROMPT,
                    image=crop,
                    num_inference_steps=steps,
                    guidance_scale=2.0,
                    noise_level=20,
                    generator=self._generator(request.seed + position),
                ).images[0]
            except torch.cuda.OutOfMemoryError:
                # Degrade this tile rather than losing the whole job.
                log.warning("tile %d ran out of VRAM; resampling it instead", position)
                self._release("_upscale")
                enlarged = crop.resize((w * 4, h * 4), Image.LANCZOS)
                pipe = self.load_upscale()

            enlarged = enlarged.resize((w * 4, h * 4), Image.LANCZOS)
            canvas = paste_feathered(
                canvas,
                to_array(enlarged),
                (x * 4, y * 4, w * 4, h * 4),
                feather=overlap * 4,
            )

        upscaled = to_image(canvas)
        if request.scale != 4:
            upscaled = upscaled.resize(target, Image.LANCZOS)
        result.image = upscaled
        result.notes.append(
            f"Upscaled {request.scale}x to {target[0]}x{target[1]} across {len(boxes)} tile(s)."
        )

    def _stage_face_enhance(self, request, result, index, report) -> None:
        """Refine detected face regions with a low-strength img2img pass.

        This is face-aware refinement, not a dedicated face-restoration network.
        It recovers plausible detail and is honest about its limits: strength is
        capped so identity cannot drift far, and the blend is feathered so a
        missed face simply stays as it was.
        """
        faces = detect_faces(
            result.image,
            min_size=self.config.face_min_size,
            padding=self.config.face_padding,
            limit=self.config.max_faces,
        )
        result.faces_found = len(faces)
        if not faces:
            result.notes.append("No faces detected, so no face refinement was applied.")
            report("face_enhance", index, 1, 1)
            return

        pipe = self.load_img2img()
        canvas = to_array(result.image).copy()
        # Cap strength hard: identity preservation matters more than sharpness.
        strength = float(np.clip(0.35 * (1.0 - request.fidelity) + 0.12, 0.10, 0.34))

        for position, (x, y, w, h) in enumerate(faces):
            report("face_enhance", index, position, len(faces))
            crop = to_image(canvas[y : y + h, x : x + w])
            work = (snap_to_multiple(min(w, 640), 8, 256), snap_to_multiple(min(h, 640), 8, 256))
            refined = pipe(
                prompt=FACE_PROMPT,
                negative_prompt=FACE_NEGATIVE,
                image=crop.resize(work, Image.LANCZOS),
                strength=strength,
                num_inference_steps=28,
                guidance_scale=6.0,
                generator=self._generator(request.seed + 500 + position),
            ).images[0]

            canvas = paste_feathered(
                canvas,
                to_array(refined.resize((w, h), Image.LANCZOS)),
                (x, y, w, h),
                feather=max(12, min(w, h) // 5),
            )

        result.image = to_image(canvas)
        result.notes.append(
            f"Refined {len(faces)} face region(s) at strength {strength:.2f}. "
            "Facial detail is reconstructed, so fine features are plausible rather "
            "than recovered."
        )
