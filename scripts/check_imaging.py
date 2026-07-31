"""Exercise the classical imaging stages on a synthetic damaged photo.

No diffusion involved, so this validates damage detection, region selection,
feathered compositing, chroma transfer and face detection on CPU in seconds.
"""

import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from worker.imaging import (  # noqa: E402
    denoise_classical,
    detect_damage,
    detect_faces,
    mask_regions,
    paste_feathered,
    tiles_for,
    to_array,
    to_image,
    transfer_chroma,
)

out = ROOT / "outputs" / "imaging-check"
out.mkdir(parents=True, exist_ok=True)
lines = []

# --- build a synthetic photograph with known damage -------------------------
rng = np.random.default_rng(7)
h, w = 512, 640
base = np.zeros((h, w, 3), dtype=np.uint8)
for y in range(h):
    base[y, :] = (90 + y * 0.12, 105 + y * 0.10, 120 + y * 0.08)
for _ in range(40):  # some texture so "flat" detection is not trivially true
    cx, cy = rng.integers(0, w), rng.integers(0, h)
    cv2.circle(base, (int(cx), int(cy)), int(rng.integers(10, 45)), (140, 130, 115), -1)
base = cv2.GaussianBlur(base, (0, 0), 3)
clean = to_image(base)

damaged = base.copy()
truth = np.zeros((h, w), dtype=np.uint8)
for _ in range(6):  # long thin scratches
    x1, y1 = rng.integers(0, w), rng.integers(0, h)
    x2, y2 = x1 + rng.integers(-160, 160), y1 + rng.integers(-160, 160)
    cv2.line(damaged, (int(x1), int(y1)), (int(x2), int(y2)), (245, 245, 245), 2)
    cv2.line(truth, (int(x1), int(y1)), (int(x2), int(y2)), 255, 2)
for _ in range(60):  # dust specks
    cx, cy = int(rng.integers(0, w)), int(rng.integers(0, h))
    # Draw the radius ONCE: sampling separately for image and truth produced a
    # misaligned ground truth and made the detector look far worse than it is.
    radius = int(rng.integers(1, 3))
    cv2.circle(damaged, (cx, cy), radius, (250, 250, 250), -1)
    cv2.circle(truth, (cx, cy), radius, 255, -1)

damaged_img = to_image(damaged)
clean.save(out / "01-clean.png")
damaged_img.save(out / "02-damaged.png")

# --- damage detection -------------------------------------------------------
report = detect_damage(damaged_img)
report.overlay.save(out / "03-damage-overlay.png")

detected = report.mask > 0
actual = truth > 0
recall = float((detected & actual).sum()) / max(1, actual.sum())
# The mask is deliberately dilated to give inpainting clean context, so raw
# precision against an undilated ground truth is not the useful number. What
# matters is that recall is high while the flagged share of the frame stays low.
overreach = report.ratio / max(1e-9, float(actual.mean()))
lines.append(
    f"damage detect : recall={recall:.2f}  flagged={report.ratio * 100:.2f}% of frame  "
    f"({overreach:.1f}x the true damage area)"
)

# false-positive check: a clean image should flag almost nothing
clean_report = detect_damage(clean)
lines.append(f"clean image   : flagged {clean_report.ratio * 100:.3f}% (want near 0)")

# --- region selection -------------------------------------------------------
boxes = mask_regions(report.mask, tile=256)
covered = np.zeros_like(report.mask)
for x, y, bw, bh in boxes:
    covered[y : y + bh, x : x + bw] = 255
coverage = float((detected & (covered > 0)).sum()) / max(1, detected.sum())
lines.append(f"regions       : {len(boxes)} box(es) covering {coverage * 100:.1f}% of damage")

# --- feathered compositing preserves unmasked pixels ------------------------
canvas = to_array(damaged_img).copy()
patch = np.full((256, 256, 3), (255, 0, 0), dtype=np.uint8)
before = canvas.copy()
canvas = paste_feathered(canvas, patch, (100, 100, 256, 256), feather=32, restrict=report.mask)
outside = report.mask[100:356, 100:356] == 0
region_before = before[100:356, 100:356]
region_after = canvas[100:356, 100:356]
drift = np.abs(region_after[outside].astype(int) - region_before[outside].astype(int)).mean()
lines.append(f"composite     : mean drift on undamaged pixels = {drift:.2f} (want small)")
to_image(canvas).save(out / "04-composite.png")

# --- tiling covers the frame ------------------------------------------------
tiles = tiles_for(w, h, 384, 48)
cover = np.zeros((h, w), dtype=np.uint8)
for x, y, tw, th in tiles:
    cover[y : y + th, x : x + tw] = 1
lines.append(f"tiling        : {len(tiles)} tile(s), frame coverage {cover.mean() * 100:.1f}%")

# --- chroma transfer keeps luminance identical ------------------------------
grey = damaged_img.convert("L").convert("RGB")
tint = np.array([40, -10, -25])
fake_colour = to_image(np.clip(to_array(damaged_img).astype(int) + tint, 0, 255))
recoloured = transfer_chroma(grey, fake_colour)
lum_before = cv2.cvtColor(to_array(grey), cv2.COLOR_RGB2LAB)[..., 0].astype(int)
lum_after = cv2.cvtColor(to_array(recoloured), cv2.COLOR_RGB2LAB)[..., 0].astype(int)
delta = np.abs(lum_after - lum_before)
# Mean is the meaningful figure: a handful of out-of-gamut pixels must clip when
# chroma changes while luminance is held, so max can never be exactly zero.
lines.append(f"chroma xfer   : luminance change mean={delta.mean():.3f} max={delta.max()} of 255")
recoloured.save(out / "05-chroma.png")

# --- denoise ---------------------------------------------------------------
noisy = to_image(np.clip(to_array(clean).astype(int) + rng.normal(0, 14, (h, w, 3)), 0, 255))
cleaned = denoise_classical(noisy, 0.5)
before_err = np.abs(to_array(noisy).astype(int) - to_array(clean).astype(int)).mean()
after_err = np.abs(to_array(cleaned).astype(int) - to_array(clean).astype(int)).mean()
lines.append(f"denoise       : mean abs error {before_err:.2f} -> {after_err:.2f}")
cleaned.save(out / "06-denoised.png")

# --- face detection on a drawn face ---------------------------------------
portrait = Image.new("RGB", (400, 400), (205, 185, 165))
d = ImageDraw.Draw(portrait)
d.ellipse([120, 90, 280, 300], fill=(225, 195, 170))
d.ellipse([160, 160, 185, 180], fill=(40, 30, 25))
d.ellipse([215, 160, 240, 180], fill=(40, 30, 25))
d.arc([170, 210, 230, 260], 200, 340, fill=(120, 70, 60), width=5)
faces = detect_faces(portrait, min_size=32)
lines.append(f"face detect   : {len(faces)} region(s) on a synthetic portrait")

(out / "report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
print("\n".join(lines))
print(f"\nartefacts in {out}")
