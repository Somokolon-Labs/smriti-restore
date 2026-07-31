"""Image primitives the restoration stages are built from.

Everything here is classical, deterministic and cheap. The diffusion models do
the generative work; these functions decide *where* to apply them and how to put
the pieces back together without visible seams.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image

log = logging.getLogger("smriti.worker.imaging")


# --------------------------------------------------------------------------- #
# conversions
# --------------------------------------------------------------------------- #
def to_array(image: Image.Image) -> np.ndarray:
    return np.asarray(image.convert("RGB"), dtype=np.uint8)


def to_image(array: np.ndarray) -> Image.Image:
    return Image.fromarray(np.clip(array, 0, 255).astype(np.uint8), mode="RGB")


def snap_to_multiple(value: int, multiple: int = 8, minimum: int = 64) -> int:
    return max(minimum, int(round(value / multiple)) * multiple)


# --------------------------------------------------------------------------- #
# damage detection
# --------------------------------------------------------------------------- #
@dataclass
class DamageReport:
    mask: np.ndarray  # uint8, 255 where damaged
    ratio: float  # fraction of the frame flagged
    overlay: Image.Image  # human-readable visualisation


def detect_damage(
    image: Image.Image,
    *,
    sensitivity: float = 0.5,
    max_ratio: float = 0.35,
) -> DamageReport:
    """Find scratches, creases, dust and tears without a trained detector.

    Scratches and dust share a signature: thin, high-contrast structures that
    differ sharply from a median-filtered version of their surroundings. A median
    blur destroys thin features while preserving real edges, so the residual
    between the image and its median isolates exactly the defects. Morphology then
    keeps only components whose shape is plausible for damage.

    `max_ratio` is a safety valve: if the "damage" covers a third of the frame the
    detector has almost certainly latched onto texture, and inpainting that much
    would repaint the photograph rather than repair it.
    """
    grey = cv2.cvtColor(to_array(image), cv2.COLOR_RGB2GRAY)

    # Top-hat isolates features brighter than their surroundings and smaller than
    # the structuring element; black-hat does the same for darker ones. Together
    # they catch bright emulsion loss and dust as well as dark ink and deep
    # scratches, while leaving broad tonal variation alone. This is the classical
    # scratch detector and it is far more sensitive than a median residual.
    element = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    tophat = cv2.morphologyEx(grey, cv2.MORPH_TOPHAT, element)
    blackhat = cv2.morphologyEx(grey, cv2.MORPH_BLACKHAT, element)
    response = cv2.max(tophat, blackhat)

    # Threshold relative to the response distribution, since photographs vary
    # enormously in contrast. The 99th percentile tracks the strongest defects,
    # and a fraction of it admits their softer, anti-aliased edges too.
    peak = float(np.percentile(response, 99.0))
    cutoff = max(6.0, peak * (0.55 - sensitivity * 0.35))
    _, raw = cv2.threshold(response, cutoff, 255, cv2.THRESH_BINARY)

    # Bridge one-pixel gaps so a broken scratch reads as one component, using a
    # deliberately small kernel. Aggressive directional closing was tried and
    # rejected: it welds scattered dust into frame-spanning blobs, which the size
    # filter below then discards as subject matter, destroying recall. Grouping
    # nearby damage is `mask_regions`' job, not this one's.
    joined = cv2.morphologyEx(
        raw, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    )
    # No opening pass: a 3x3 open erases single-pixel dust, which is exactly what
    # needs detecting.

    # Keep components that look like damage: either elongated (scratch, crease) or
    # small and compact (dust, spot). Reject large blobs, which are subject matter.
    count, labels, stats, _ = cv2.connectedComponentsWithStats(joined, connectivity=8)
    frame_area = grey.shape[0] * grey.shape[1]
    mask = np.zeros_like(joined)
    for index in range(1, count):
        x, y, w, h, area = stats[index]
        # Single stray pixels are sensor noise, not damage worth inpainting.
        if area < 2:
            continue
        # Anything occupying a sizeable share of the frame is subject matter.
        if area > frame_area * 0.02:
            continue
        # Fill ratio, not bounding-box elongation. A diagonal scratch has a
        # near-square bounding box, so elongation reads ~1.0 and would reject it;
        # the fraction of its box that is actually filled stays low whatever the
        # orientation. Thin sparse structures are damage, solid blobs are subject.
        fill = area / float(max(1, w * h))
        if fill <= 0.30 or area <= 400:
            mask[labels == index] = 255

    # Dilate so inpainting has clean context either side of a scratch.
    mask = cv2.dilate(mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)), iterations=1)

    ratio = float(np.count_nonzero(mask)) / float(frame_area)
    if ratio > max_ratio:
        log.warning(
            "damage detector flagged %.1f%% of the frame, above the %.0f%% ceiling; "
            "treating it as texture and skipping repair",
            ratio * 100,
            max_ratio * 100,
        )
        mask = np.zeros_like(mask)
        ratio = 0.0

    return DamageReport(mask=mask, ratio=ratio, overlay=_damage_overlay(image, mask))


def _damage_overlay(image: Image.Image, mask: np.ndarray) -> Image.Image:
    """Tint detected damage so a user can see what the repair will touch."""
    array = to_array(image).copy()
    highlight = mask > 0
    array[highlight] = (0.35 * array[highlight] + np.array([0.65 * 220, 0, 0.65 * 60])).astype(
        np.uint8
    )
    return to_image(array)


def merge_masks(*masks: np.ndarray | None) -> np.ndarray | None:
    present = [m for m in masks if m is not None and m.size]
    if not present:
        return None
    combined = present[0].copy()
    for extra in present[1:]:
        if extra.shape != combined.shape:
            extra = cv2.resize(extra, (combined.shape[1], combined.shape[0]), cv2.INTER_NEAREST)
        combined = cv2.bitwise_or(combined, extra)
    return combined


def mask_regions(
    mask: np.ndarray, *, tile: int, padding: int = 24
) -> list[tuple[int, int, int, int]]:
    """Bounding boxes covering the mask, so inpainting only visits damaged areas.

    A photograph with three scratches should cost three small inpaints, not a
    full-frame pass. Boxes are snapped up to the model's working size.
    """
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    height, width = mask.shape[:2]
    boxes: list[tuple[int, int, int, int]] = []

    for index in range(1, count):
        x, y, w, h, _area = stats[index]
        cx, cy = x + w / 2, y + h / 2
        size = max(tile, snap_to_multiple(max(w, h) + padding * 2, 64, tile))
        size = min(size, min(width, height)) if min(width, height) >= tile else min(width, height)
        left = int(np.clip(cx - size / 2, 0, max(0, width - size)))
        top = int(np.clip(cy - size / 2, 0, max(0, height - size)))
        boxes.append((left, top, min(size, width), min(size, height)))

    return _merge_overlapping(boxes)


def _merge_overlapping(
    boxes: list[tuple[int, int, int, int]], threshold: float = 0.35
) -> list[tuple[int, int, int, int]]:
    """Collapse boxes that substantially overlap, to avoid inpainting twice."""
    merged: list[tuple[int, int, int, int]] = []
    for box in sorted(boxes, key=lambda b: b[2] * b[3], reverse=True):
        x1, y1, w1, h1 = box
        absorbed = False
        for existing in merged:
            x2, y2, w2, h2 = existing
            inter_w = max(0, min(x1 + w1, x2 + w2) - max(x1, x2))
            inter_h = max(0, min(y1 + h1, y2 + h2) - max(y1, y2))
            overlap = inter_w * inter_h
            if overlap and overlap / float(w1 * h1) >= threshold:
                absorbed = True
                break
        if not absorbed:
            merged.append(box)
    return merged


# --------------------------------------------------------------------------- #
# seamless composition
# --------------------------------------------------------------------------- #
def feather_mask(shape: tuple[int, int], radius: int) -> np.ndarray:
    """Float mask in [0,1], 1 in the centre, falling to 0 at the border."""
    height, width = shape
    ramp_y = np.ones(height, dtype=np.float32)
    ramp_x = np.ones(width, dtype=np.float32)
    radius = max(1, min(radius, height // 2, width // 2))
    edge = np.linspace(0.0, 1.0, radius, dtype=np.float32)
    ramp_y[:radius] = edge
    ramp_y[-radius:] = edge[::-1]
    ramp_x[:radius] = edge
    ramp_x[-radius:] = edge[::-1]
    return np.outer(ramp_y, ramp_x)


def paste_feathered(
    base: np.ndarray,
    patch: np.ndarray,
    box: tuple[int, int, int, int],
    *,
    feather: int = 24,
    restrict: np.ndarray | None = None,
) -> np.ndarray:
    """Blend a patch into the base with a feathered border.

    `restrict` limits the blend to a region of interest, so an inpainted tile
    replaces the scratch but leaves untouched pixels bit-identical. That matters:
    a restoration that silently rewrites clean areas is not a restoration.
    """
    x, y, w, h = box
    patch = patch[:h, :w]
    weight = feather_mask((h, w), feather)

    if restrict is not None:
        local = restrict[y : y + h, x : x + w].astype(np.float32) / 255.0
        # Grow the mask smoothly so the seam sits in damaged territory.
        local = cv2.GaussianBlur(local, (0, 0), sigmaX=max(1.0, feather / 3))
        weight = weight * np.clip(local * 1.6, 0.0, 1.0)

    weight = weight[..., None]
    region = base[y : y + h, x : x + w].astype(np.float32)
    base[y : y + h, x : x + w] = (region * (1 - weight) + patch.astype(np.float32) * weight).astype(
        np.uint8
    )
    return base


def tiles_for(width: int, height: int, tile: int, overlap: int) -> list[tuple[int, int, int, int]]:
    """Cover the frame in overlapping tiles, clamped to the edges."""
    step = max(32, tile - overlap)
    boxes: list[tuple[int, int, int, int]] = []
    ys = list(range(0, max(1, height - overlap), step)) or [0]
    xs = list(range(0, max(1, width - overlap), step)) or [0]
    for y in ys:
        for x in xs:
            w = min(tile, width - x)
            h = min(tile, height - y)
            if w <= 0 or h <= 0:
                continue
            # Pull the final tile back so it stays full-size where possible.
            if w < tile and width >= tile:
                x = width - tile
                w = tile
            if h < tile and height >= tile:
                y = height - tile
                h = tile
            if (x, y, w, h) not in boxes:
                boxes.append((x, y, w, h))
    return boxes


# --------------------------------------------------------------------------- #
# colour handling
# --------------------------------------------------------------------------- #
def transfer_chroma(luminance_source: Image.Image, colour_source: Image.Image) -> Image.Image:
    """Keep the original detail, borrow only the colour.

    Naive img2img colourisation returns an image that is both recoloured and
    subtly redrawn, which loses real photographic detail. Working in LAB and
    taking only the a/b channels from the generated version means every bit of
    original luminance survives, and the model contributes nothing but hue.
    """
    # float32 throughout: a uint8 LAB round trip quantises L and visibly shifts
    # brightness, which defeats the whole point of preserving luminance.
    original_rgb = to_array(luminance_source).astype(np.float32) / 255.0
    generated_rgb = to_array(colour_source).astype(np.float32) / 255.0

    original = cv2.cvtColor(original_rgb, cv2.COLOR_RGB2LAB)
    generated = cv2.cvtColor(generated_rgb, cv2.COLOR_RGB2LAB)

    if generated.shape[:2] != original.shape[:2]:
        generated = cv2.resize(
            generated, (original.shape[1], original.shape[0]), interpolation=cv2.INTER_CUBIC
        )

    merged = original.copy()
    # Smooth the borrowed chroma to hide blotchy colour. Chroma is low-frequency,
    # so this costs nothing real and removes most colour bleeding.
    merged[..., 1] = cv2.GaussianBlur(generated[..., 1], (0, 0), sigmaX=2.0)
    merged[..., 2] = cv2.GaussianBlur(generated[..., 2], (0, 0), sigmaX=2.0)

    restored = cv2.cvtColor(merged, cv2.COLOR_LAB2RGB)
    return to_image(np.clip(restored, 0.0, 1.0) * 255.0)


def blend_detail(original: Image.Image, processed: Image.Image, strength: float) -> Image.Image:
    """Interpolate towards a processed result, preserving some original texture.

    Denoisers remove film grain along with noise. Blending back a fraction of the
    original keeps the photograph looking like a photograph.
    """
    strength = float(np.clip(strength, 0.0, 1.0))
    base = to_array(original).astype(np.float32)
    other = to_array(processed)
    if other.shape != base.shape:
        other = cv2.resize(other, (base.shape[1], base.shape[0]), interpolation=cv2.INTER_CUBIC)
    return to_image(base * (1 - strength) + other.astype(np.float32) * strength)


def denoise_classical(image: Image.Image, strength: float) -> Image.Image:
    """Edge-preserving denoise, used on its own or before a diffusion pass.

    Non-local means is slow but keeps texture that a Gaussian would erase, and on
    scanned prints it removes most of the sensor and film noise on its own.
    """
    if strength <= 0.01:
        return image
    array = to_array(image)
    h = float(np.clip(strength * 12.0, 1.0, 15.0))
    denoised = cv2.fastNlMeansDenoisingColored(array, None, h, h, 7, 21)
    return blend_detail(image, to_image(denoised), min(1.0, strength * 1.2))


# --------------------------------------------------------------------------- #
# faces
# --------------------------------------------------------------------------- #
def detect_faces(
    image: Image.Image, *, min_size: int = 48, padding: float = 0.35, limit: int = 12
) -> list[tuple[int, int, int, int]]:
    """Locate faces with OpenCV's bundled cascade.

    A Haar cascade is crude next to a learned detector, but it ships with OpenCV,
    needs no weights download, runs on CPU in milliseconds, and only has to be
    good enough to pick regions for the diffusion model to refine. False negatives
    cost detail; false positives cost a wasted refine pass. Neither is fatal.
    """
    # The default frontal cascade alone misses roughly a third of real portraits,
    # mostly non-frontal poses. Running alt2 (generally the strongest of the
    # bundled frontal models) and the profile cascade as well, then merging,
    # recovers most of those for a few milliseconds of extra CPU.
    names = (
        "haarcascade_frontalface_alt2.xml",
        "haarcascade_frontalface_default.xml",
        "haarcascade_profileface.xml",
    )
    grey = cv2.equalizeHist(cv2.cvtColor(to_array(image), cv2.COLOR_RGB2GRAY))

    found: list[tuple[int, int, int, int]] = []
    loaded = 0
    for name in names:
        cascade = cv2.CascadeClassifier(cv2.data.haarcascades + name)
        if cascade.empty():
            continue
        loaded += 1
        found.extend(
            tuple(int(v) for v in box)
            for box in cascade.detectMultiScale(
                grey, scaleFactor=1.08, minNeighbors=4, minSize=(min_size, min_size)
            )
        )
        # Profile faces only look one way, so mirror the frame to catch the other.
        if "profile" in name:
            flipped = cv2.flip(grey, 1)
            for x, y, w, h in cascade.detectMultiScale(
                flipped, scaleFactor=1.08, minNeighbors=4, minSize=(min_size, min_size)
            ):
                found.append((int(grey.shape[1] - x - w), int(y), int(w), int(h)))

    if not loaded:
        log.warning("no face cascades available; skipping face detection")
        return []

    found = _merge_overlapping(found, threshold=0.30)

    height, width = grey.shape[:2]
    boxes: list[tuple[int, int, int, int]] = []
    for x, y, w, h in sorted(found, key=lambda b: b[2] * b[3], reverse=True)[:limit]:
        pad_x, pad_y = int(w * padding), int(h * padding)
        left = max(0, x - pad_x)
        top = max(0, y - pad_y)
        right = min(width, x + w + pad_x)
        bottom = min(height, y + h + pad_y)
        boxes.append((left, top, right - left, bottom - top))
    return boxes
