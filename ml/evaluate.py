"""Measure restoration quality against ground truth, then publish the numbers.

Protocol: collect clean photographs, apply a named synthetic degradation, run the
restoration pipeline, and score the result against the untouched original. Because
the clean image is known, PSNR, SSIM and perceptual distance are all measurable
rather than merely arguable.

    python -m ml.evaluate --per-degradation 4
    python -m ml.evaluate --per-degradation 4 --publish
    python -m ml.evaluate --quick            # smoke test the harness

Writes eval/results.json plus triptychs (clean | degraded | restored) in
eval/samples/.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx
from PIL import Image
from tqdm import tqdm

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ml.degrade import DEGRADATIONS, degrade  # noqa: E402
from ml.metrics import Lpips, psnr, safe_mean, ssim  # noqa: E402

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S"
)
log = logging.getLogger("smriti.ml.eval")

EVAL_DIR = ROOT / "eval"
SAMPLE_DIR = EVAL_DIR / "samples"
CLEAN_DIR = ROOT / "data" / "clean"


def load_env() -> None:
    for candidate in (ROOT / ".env", ROOT.parent / "nakshi-studio" / ".env"):
        if not candidate.exists():
            continue
        for line in candidate.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())
        return


def git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, stderr=subprocess.DEVNULL, text=True
        ).strip()
    except Exception:
        return ""


def fetch_clean_set(count: int) -> list[Path]:
    """Download openly licensed photographs to serve as ground truth."""
    CLEAN_DIR.mkdir(parents=True, exist_ok=True)
    existing = sorted(CLEAN_DIR.glob("*.jpg"))
    if len(existing) >= count:
        return existing[:count]

    key = os.getenv("PEXELS_ACCESS_KEY", "")
    if not key:
        if existing:
            log.warning("PEXELS_ACCESS_KEY unset; using the %d cached images", len(existing))
            return existing
        sys.exit("no clean images cached and PEXELS_ACCESS_KEY is unset")

    # Portraits and groups, because face restoration is part of what is measured.
    queries = [
        "family portrait vintage",
        "portrait person face",
        "group of people",
        "old photograph",
    ]
    # Pexels rejects a default urllib User-Agent, and httpx sends a real one.
    with httpx.Client(
        headers={"Authorization": key, "User-Agent": "smriti-restore/0.1"}, timeout=60.0
    ) as client:
        for query in queries:
            if len(list(CLEAN_DIR.glob("*.jpg"))) >= count:
                break
            try:
                response = client.get(
                    "https://api.pexels.com/v1/search",
                    params={"query": query, "per_page": max(4, count // 2)},
                )
                response.raise_for_status()
                photos = response.json().get("photos", [])
            except (httpx.HTTPError, ValueError) as exc:
                log.warning("pexels '%s' failed: %s", query, exc)
                continue

            for photo in photos:
                target = CLEAN_DIR / f"pexels-{photo['id']}.jpg"
                if target.exists():
                    continue
                try:
                    image_bytes = client.get(photo["src"]["large"]).content
                    target.write_bytes(image_bytes)
                except httpx.HTTPError:
                    continue
                if len(list(CLEAN_DIR.glob("*.jpg"))) >= count:
                    break

    return sorted(CLEAN_DIR.glob("*.jpg"))[:count]


def triptych(clean: Image.Image, degraded: Image.Image, restored: Image.Image, path: Path) -> None:
    """clean | degraded | restored, side by side at matched height."""
    height = 320
    panels = []
    for picture in (clean, degraded, restored):
        ratio = height / picture.height
        panels.append(picture.resize((max(1, int(picture.width * ratio)), height), Image.LANCZOS))
    sheet = Image.new("RGB", (sum(p.width for p in panels), height), (18, 16, 14))
    offset = 0
    for panel in panels:
        sheet.paste(panel, (offset, 0))
        offset += panel.width
    sheet.save(path, quality=90)


def publish(results: dict, name: str, notes: str) -> None:
    api_url = os.getenv("SMRITI_API_URL", "http://127.0.0.1:8000").rstrip("/")
    admin_key = os.getenv("ADMIN_API_KEY", "")
    if not admin_key:
        log.error("ADMIN_API_KEY not set; cannot publish")
        return
    try:
        response = httpx.post(
            f"{api_url}/v1/model/runs",
            headers={"X-API-Key": admin_key},
            json={
                "name": name,
                "commit_sha": git_sha(),
                "results": results,
                "notes": notes,
                "make_current": True,
            },
            timeout=60.0,
        )
        response.raise_for_status()
        log.info("published run %s to %s", response.json()["id"][:8], api_url)
    except httpx.HTTPError as exc:
        log.error("publish failed: %s", exc)


def main() -> None:
    load_env()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--per-degradation", type=int, default=3, help="images per degradation")
    parser.add_argument("--max-side", type=int, default=768, help="downscale clean images to this")
    parser.add_argument("--scale", type=int, default=2, help="upscale factor to evaluate")
    parser.add_argument("--quick", action="store_true", help="two degradations, one image each")
    parser.add_argument("--skip-lpips", action="store_true")
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--name", default=None)
    args = parser.parse_args()

    import torch

    if not torch.cuda.is_available():
        raise SystemExit(
            "evaluation needs a CUDA device: it runs the full restoration pipeline. "
            "Use a GPU host, or see infra/runpod/."
        )

    from worker.config import WorkerConfig
    from worker.pipeline import RestorationPipeline, RestoreRequest

    kinds = ["scratches", "grain"] if args.quick else list(DEGRADATIONS)
    per_kind = 1 if args.quick else args.per_degradation

    clean_paths = fetch_clean_set(max(per_kind, 4))
    if not clean_paths:
        raise SystemExit("no clean images available to degrade")
    log.info(
        "%d clean image(s), %d degradation(s), %d each", len(clean_paths), len(kinds), per_kind
    )

    config = WorkerConfig.from_env()
    pipeline = RestorationPipeline(config)
    lpips = None if args.skip_lpips else Lpips()

    SAMPLE_DIR.mkdir(parents=True, exist_ok=True)
    per_degradation: list[dict] = []
    stage_totals: dict[str, list[float]] = {}
    all_rows: list[dict] = []
    total_megapixels = 0.0
    total_seconds = 0.0

    for kind in kinds:
        stages = DEGRADATIONS[kind]["stages"]
        # Only ask for upscaling where the degradation actually lost resolution;
        # scoring an enlargement against a same-size reference measures nothing.
        active = list(stages)
        scale = 1
        if "upscale" in DEGRADATIONS[kind]["stages"]:
            active = [s for s in stages if s != "upscale"] + ["upscale"]
            scale = args.scale

        rows = []
        for index, path in enumerate(tqdm(clean_paths[:per_kind], desc=f"{kind:11}", unit="img")):
            clean = Image.open(path).convert("RGB")
            clean.thumbnail((args.max_side, args.max_side), Image.LANCZOS)
            degraded = degrade(clean, kind, seed=1000 + index)

            started = time.perf_counter()
            result = pipeline.run(
                RestoreRequest(
                    stages=active,
                    scale=scale,
                    fidelity=0.75,
                    denoise_strength=0.4,
                    auto_mask=True,
                    seed=4242 + index,
                    image=degraded,
                    tier="balanced",
                )
            )
            elapsed = time.perf_counter() - started
            restored = result.image
            # Compare at the reference resolution whatever the pipeline produced.
            if restored.size != clean.size:
                restored = restored.resize(clean.size, Image.LANCZOS)

            total_seconds += elapsed
            total_megapixels += (clean.width * clean.height) / 1e6
            for stage, seconds in result.stage_timings.items():
                stage_totals.setdefault(stage, []).append(seconds)

            row = {
                "image": path.name,
                "psnr_degraded": psnr(clean, degraded),
                "psnr_restored": psnr(clean, restored),
                "ssim_degraded": ssim(clean, degraded),
                "ssim_restored": ssim(clean, restored),
            }
            if lpips is not None:
                row["lpips_degraded"] = lpips.distance(clean, degraded)
                row["lpips_restored"] = lpips.distance(clean, restored)
            rows.append(row)
            all_rows.append(row)

            triptych(clean, degraded, restored, SAMPLE_DIR / f"{kind}-{index}.jpg")

        per_degradation.append(
            {
                "degradation": kind,
                "images": len(rows),
                "stages": active,
                "psnr_degraded": round(safe_mean([r["psnr_degraded"] for r in rows]), 3),
                "psnr_restored": round(safe_mean([r["psnr_restored"] for r in rows]), 3),
                "ssim_degraded": round(safe_mean([r["ssim_degraded"] for r in rows]), 4),
                "ssim_restored": round(safe_mean([r["ssim_restored"] for r in rows]), 4),
            }
        )
        latest = per_degradation[-1]
        log.info(
            "  %-11s PSNR %.2f -> %.2f dB | SSIM %.4f -> %.4f",
            kind,
            latest["psnr_degraded"],
            latest["psnr_restored"],
            latest["ssim_degraded"],
            latest["ssim_restored"],
        )

    if lpips is not None:
        lpips.unload()

    psnr_before = safe_mean([r["psnr_degraded"] for r in all_rows])
    psnr_after = safe_mean([r["psnr_restored"] for r in all_rows])
    ssim_before = safe_mean([r["ssim_degraded"] for r in all_rows])
    ssim_after = safe_mean([r["ssim_restored"] for r in all_rows])
    lpips_before = safe_mean([r.get("lpips_degraded", float("nan")) for r in all_rows])
    lpips_after = safe_mean([r.get("lpips_restored", float("nan")) for r in all_rows])

    summary = {
        "images_evaluated": len(all_rows),
        "psnr_degraded": round(psnr_before, 3),
        "psnr_restored": round(psnr_after, 3),
        "psnr_gain_db": round(psnr_after - psnr_before, 3),
        "ssim_degraded": round(ssim_before, 4),
        "ssim_restored": round(ssim_after, 4),
        "ssim_gain": round(ssim_after - ssim_before, 4),
        "seconds_per_megapixel": round(total_seconds / max(total_megapixels, 1e-6), 2),
    }
    if lpips is not None and lpips_before == lpips_before:
        summary["lpips_degraded"] = round(lpips_before, 4)
        summary["lpips_restored"] = round(lpips_after, 4)
        summary["lpips_improvement_pct"] = round(
            (lpips_before - lpips_after) / max(lpips_before, 1e-9) * 100, 2
        )

    results = {
        "summary": summary,
        "per_degradation": per_degradation,
        "per_stage_timing": {
            stage: round(safe_mean(values), 2) for stage, values in sorted(stage_totals.items())
        },
        "protocol": {
            "method": "synthetic degradation of clean photographs, restored, scored against the original",
            "degradations": ", ".join(kinds),
            "images_per_degradation": per_kind,
            "reference_max_side": args.max_side,
            "upscale_factor_evaluated": args.scale,
            "lpips_note": "VGG16 normalised deep feature distance, not the calibrated LPIPS metric",
            "ssim_window": "11x11 Gaussian, sigma 1.5",
        },
        "hardware": {"gpu": torch.cuda.get_device_name(0), "torch": torch.__version__},
    }

    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    (EVAL_DIR / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")

    log.info("---------------------------------------------")
    log.info("PSNR  %.2f -> %.2f dB (%+.2f)", psnr_before, psnr_after, psnr_after - psnr_before)
    log.info("SSIM  %.4f -> %.4f (%+.4f)", ssim_before, ssim_after, ssim_after - ssim_before)
    if "lpips_restored" in summary:
        log.info("LPIPS %.4f -> %.4f", lpips_before, lpips_after)
    log.info("%.1f s per megapixel", summary["seconds_per_megapixel"])
    log.info("results -> %s", EVAL_DIR / "results.json")

    if args.publish:
        publish(
            results,
            args.name
            or f"smriti restoration, {len(all_rows)} pairs across {len(kinds)} degradations",
            notes=(
                f"{len(all_rows)} image pairs. Clean photographs were degraded with known "
                f"synthetic damage ({', '.join(kinds)}), restored by the pipeline, and scored "
                "against the untouched originals."
            ),
        )


if __name__ == "__main__":
    main()
