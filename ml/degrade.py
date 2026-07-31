"""Synthesise known degradations so restoration can be measured against truth.

Restoration is one of the few generative tasks where ground truth is obtainable:
take a clean photograph, damage it in a controlled way, restore it, and compare
against the original. That makes PSNR, SSIM and LPIPS meaningful, unlike the
reference-free scores generative work usually has to settle for.

Each degradation models a real failure mode of physical photographs, and each is
applied deterministically from a seed so a benchmark is reproducible.
"""

from __future__ import annotations

import cv2
import numpy as np
from PIL import Image


def _array(image: Image.Image) -> np.ndarray:
    return np.asarray(image.convert("RGB"), dtype=np.uint8)


def _image(array: np.ndarray) -> Image.Image:
    return Image.fromarray(np.clip(array, 0, 255).astype(np.uint8), mode="RGB")


def scratches(image: Image.Image, seed: int, *, count: int = 14) -> Image.Image:
    """Emulsion scratches: thin, bright or dark, roughly straight."""
    rng = np.random.default_rng(seed)
    array = _array(image).copy()
    h, w = array.shape[:2]
    for _ in range(count):
        x1, y1 = int(rng.integers(0, w)), int(rng.integers(0, h))
        length = int(rng.integers(min(h, w) // 8, min(h, w) // 2))
        angle = rng.uniform(0, np.pi)
        x2 = int(np.clip(x1 + np.cos(angle) * length, 0, w - 1))
        y2 = int(np.clip(y1 + np.sin(angle) * length, 0, h - 1))
        bright = rng.random() < 0.7
        value = int(rng.integers(215, 255)) if bright else int(rng.integers(0, 40))
        cv2.line(array, (x1, y1), (x2, y2), (value, value, value), int(rng.integers(1, 3)))
    return _image(array)


def dust(image: Image.Image, seed: int, *, count: int = 260) -> Image.Image:
    """Dust and emulsion specks from a dirty scanner bed or aged print."""
    rng = np.random.default_rng(seed + 1)
    array = _array(image).copy()
    h, w = array.shape[:2]
    for _ in range(count):
        cx, cy = int(rng.integers(0, w)), int(rng.integers(0, h))
        radius = int(rng.integers(1, 4))
        value = int(rng.integers(200, 255)) if rng.random() < 0.75 else int(rng.integers(0, 50))
        cv2.circle(array, (cx, cy), radius, (value, value, value), -1)
    return _image(array)


def creases(image: Image.Image, seed: int, *, count: int = 3) -> Image.Image:
    """Fold lines: long, soft-edged, slightly brighter than the surface."""
    rng = np.random.default_rng(seed + 2)
    array = _array(image).astype(np.float32)
    h, w = array.shape[:2]
    overlay = np.zeros((h, w), dtype=np.float32)
    for _ in range(count):
        horizontal = rng.random() < 0.5
        position = int(
            rng.integers(int(0.15 * (h if horizontal else w)), int(0.85 * (h if horizontal else w)))
        )
        thickness = int(rng.integers(3, 9))
        if horizontal:
            cv2.line(overlay, (0, position), (w - 1, position), 1.0, thickness)
        else:
            cv2.line(overlay, (position, 0), (position, h - 1), 1.0, thickness)
    overlay = cv2.GaussianBlur(overlay, (0, 0), sigmaX=2.5)[..., None]
    return _image(array * (1 - overlay * 0.5) + 235.0 * overlay * 0.5)


def film_grain(image: Image.Image, seed: int, *, sigma: float = 16.0) -> Image.Image:
    """Sensor or film noise, correlated across channels like real grain."""
    rng = np.random.default_rng(seed + 3)
    array = _array(image).astype(np.float32)
    mono = rng.normal(0, sigma, array.shape[:2])[..., None]
    chroma = rng.normal(0, sigma * 0.35, array.shape)
    return _image(array + mono + chroma)


def fade(image: Image.Image, seed: int) -> Image.Image:
    """Sun-bleached print: compressed contrast with a warm cast."""
    rng = np.random.default_rng(seed + 4)
    array = _array(image).astype(np.float32) / 255.0
    strength = rng.uniform(0.35, 0.6)
    array = array * (1 - strength) + strength * 0.72
    tint = np.array([1.06, 1.0, 0.9], dtype=np.float32)
    return _image(np.clip(array * tint, 0, 1) * 255.0)


def blur(image: Image.Image, seed: int) -> Image.Image:
    """Soft focus or camera shake."""
    rng = np.random.default_rng(seed + 5)
    array = _array(image)
    if rng.random() < 0.5:
        return _image(cv2.GaussianBlur(array, (0, 0), sigmaX=rng.uniform(1.0, 2.2)))
    size = int(rng.integers(5, 11))
    kernel = np.zeros((size, size), dtype=np.float32)
    kernel[size // 2, :] = 1.0 / size
    rotation = cv2.getRotationMatrix2D((size / 2 - 0.5, size / 2 - 0.5), rng.uniform(0, 180), 1.0)
    kernel = cv2.warpAffine(kernel, rotation, (size, size))
    kernel /= max(kernel.sum(), 1e-6)
    return _image(cv2.filter2D(array, -1, kernel))


def jpeg_artifacts(image: Image.Image, seed: int) -> Image.Image:
    """Generational loss from being re-saved and re-shared many times."""
    rng = np.random.default_rng(seed + 6)
    array = _array(image)
    for _ in range(int(rng.integers(2, 4))):
        quality = int(rng.integers(18, 40))
        ok, buffer = cv2.imencode(".jpg", array, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
        if ok:
            array = cv2.imdecode(buffer, cv2.IMREAD_COLOR)
    return _image(array)


def downscale(image: Image.Image, seed: int, *, factor: int = 2) -> Image.Image:
    """Lost resolution: a small scan enlarged back to the original size."""
    small = image.resize(
        (max(1, image.width // factor), max(1, image.height // factor)), Image.BICUBIC
    )
    return small.resize(image.size, Image.BICUBIC)


def monochrome(image: Image.Image, seed: int) -> Image.Image:
    """Black and white, for evaluating colourisation."""
    return image.convert("L").convert("RGB")


# Named recipes. Each maps to the pipeline stages that should address it, which is
# what lets the harness report per-degradation results against the right profile.
DEGRADATIONS: dict[str, dict] = {
    "scratches": {"apply": [scratches, dust], "stages": ["descratch"]},
    "creases": {"apply": [creases, dust], "stages": ["descratch"]},
    "grain": {"apply": [film_grain], "stages": ["denoise"]},
    "faded": {"apply": [fade, film_grain], "stages": ["denoise"]},
    "blurred": {"apply": [blur], "stages": ["upscale"]},
    "jpeg": {"apply": [jpeg_artifacts], "stages": ["denoise"]},
    "low_res": {"apply": [downscale, film_grain], "stages": ["upscale"]},
    "heavy": {
        "apply": [scratches, dust, creases, film_grain, fade],
        "stages": ["descratch", "denoise"],
    },
}


def degrade(image: Image.Image, kind: str, seed: int) -> Image.Image:
    """Apply a named degradation recipe deterministically."""
    recipe = DEGRADATIONS.get(kind)
    if recipe is None:
        raise ValueError(f"unknown degradation {kind!r}; expected one of {sorted(DEGRADATIONS)}")
    result = image.convert("RGB")
    for step in recipe["apply"]:
        result = step(result, seed)
    return result
