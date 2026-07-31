"""GPU worker entry point.

Pulls restoration jobs from the control plane, runs the pipeline, posts the result
back. Runs anywhere with a CUDA device and outbound HTTPS; nothing needs to reach
it.

    python -m worker.main
    python -m worker.main --once                    # drain one job then exit
    python -m worker.main --self-test path/to.jpg   # restore locally, post nothing
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import threading
import time
from pathlib import Path

import httpx
from PIL import Image

from .client import ClaimedJob, ControlPlaneClient
from .config import ROOT, WorkerConfig
from .pipeline import JobCanceled, RestorationPipeline, RestoreRequest

VERSION = "0.1.0"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("smriti.worker")

_shutdown = threading.Event()


def _handle_signal(signum, _frame) -> None:
    log.info("signal %s received; finishing the current job then exiting", signum)
    _shutdown.set()


class Worker:
    def __init__(self, config: WorkerConfig) -> None:
        self.config = config
        self.pipeline = RestorationPipeline(config)
        self.client = ControlPlaneClient(config.api_url, config.api_key)
        self.stages = config.validated_stages()
        self.completed = 0
        self.failed = 0

    def start(self, once: bool = False) -> None:
        log.info(
            "worker %s | %s (%d MB) | stages=%s | tiers=%s | max %.1f MP",
            self.config.name,
            self.pipeline.gpu_name(),
            self.pipeline.vram_mb(),
            ",".join(self.stages),
            ",".join(self.config.tiers),
            self.config.max_pixels / 1e6,
        )
        self._register_with_retry()

        heartbeat = threading.Thread(target=self._heartbeat_loop, daemon=True)
        heartbeat.start()

        while not _shutdown.is_set():
            try:
                job = self.client.claim(
                    stages=self.stages,
                    tiers=self.config.tiers,
                    max_pixels=self.config.max_pixels,
                    wait_seconds=self.config.poll_wait_seconds,
                )
            except httpx.HTTPStatusError as exc:
                code = exc.response.status_code
                if code in (401, 403):
                    log.error("worker key rejected; check SMRITI_WORKER_KEY")
                    return
                if code == 404:
                    log.warning("control plane forgot this worker; re-registering")
                    self._register_with_retry()
                    continue
                log.warning("claim failed (%s); retrying", code)
                time.sleep(5)
                continue
            except httpx.HTTPError as exc:
                log.warning("cannot reach the control plane (%s); retrying in 5s", exc)
                time.sleep(5)
                continue

            if job is None:
                continue

            self._run_job(job)
            if once:
                break

        log.info("stopped after %d completed / %d failed", self.completed, self.failed)
        self.client.close()

    def _register_with_retry(self) -> None:
        delay = 2
        while not _shutdown.is_set():
            try:
                worker_id = self.client.register(
                    name=self.config.name,
                    gpu_name=self.pipeline.gpu_name(),
                    vram_mb=self.pipeline.vram_mb(),
                    version=VERSION,
                    stages=self.stages,
                    tiers=self.config.tiers,
                    max_pixels=self.config.max_pixels,
                    meta={
                        "dtype": self.config.dtype,
                        "upscale_tile": self.config.upscale_tile,
                        "cpu_offload": self.config.cpu_offload,
                    },
                )
                log.info("registered as %s", worker_id)
                return
            except httpx.HTTPError as exc:
                log.warning("registration failed (%s); retrying in %ds", exc, delay)
                time.sleep(delay)
                delay = min(delay * 2, 60)

    def _heartbeat_loop(self) -> None:
        while not _shutdown.is_set():
            _shutdown.wait(20)
            if not _shutdown.is_set():
                self.client.heartbeat()

    def _run_job(self, job: ClaimedJob) -> None:
        log.info(
            "job %s | %s | %dx%d -> %dx | stages=%s | attempt %d",
            job.id[:8],
            job.profile,
            job.source_width,
            job.source_height,
            job.scale,
            ",".join(job.stages),
            job.attempt,
        )
        started = time.perf_counter()
        last_report = 0.0
        current_stage = ""

        def on_progress(stage: str, index: int, step: int, total: int, overall: float) -> None:
            nonlocal last_report, current_stage
            now = time.perf_counter()
            # Always report a stage transition; throttle within a stage.
            if stage == current_stage and now - last_report < self.config.progress_every:
                return
            current_stage = stage
            last_report = now
            if not self.client.report_progress(
                job.id, stage=stage, stage_index=index, step=step, total=total, overall=overall
            ):
                raise JobCanceled(f"job {job.id} canceled or reassigned")

        try:
            source = self.client.fetch_image(job.source_image_url)
            mask = self.client.fetch_image(job.mask_image_url) if job.mask_image_url else None

            result = self.pipeline.run(
                RestoreRequest(
                    stages=job.stages,
                    scale=job.scale,
                    fidelity=job.fidelity,
                    denoise_strength=job.denoise_strength,
                    auto_mask=job.auto_mask,
                    seed=job.seed,
                    image=source,
                    mask=mask,
                    grayscale_source=bool(job.params.get("grayscale_source")),
                    tier=job.tier,
                ),
                on_progress=on_progress,
            )
        except JobCanceled:
            log.info("job %s abandoned mid-pipeline", job.id[:8])
            return
        except Exception as exc:
            self.failed += 1
            message = f"{type(exc).__name__}: {exc}"
            lowered = str(exc).lower()
            retryable = "out of memory" in lowered or isinstance(exc, httpx.HTTPError)
            log.exception("job %s failed", job.id[:8])
            self.client.report_failure(job.id, message, retryable=retryable, stage=current_stage)
            return

        duration_ms = int((time.perf_counter() - started) * 1000)
        try:
            self.client.submit_result(
                job.id,
                result.image,
                duration_ms=duration_ms,
                damage_ratio=result.damage_ratio,
                faces_found=result.faces_found,
                stage_timings=result.stage_timings,
                damage_overlay=result.damage_overlay,
            )
        except httpx.HTTPError as exc:
            self.failed += 1
            log.error("could not upload result for %s: %s", job.id[:8], exc)
            self.client.report_failure(job.id, f"result upload failed: {exc}", retryable=True)
            return

        self.completed += 1
        log.info(
            "job %s done in %.1fs | %dx%d | damage %.2f%% | faces %d | %s",
            job.id[:8],
            duration_ms / 1000,
            result.image.width,
            result.image.height,
            result.damage_ratio * 100,
            result.faces_found,
            result.stage_timings,
        )


def self_test(config: WorkerConfig, source_path: Path, stages: list[str], scale: int) -> None:
    """Restore one local file and write the result. No control plane involved."""
    pipeline = RestorationPipeline(config)
    log.info("device=%s dtype=%s", pipeline.device, pipeline.dtype)

    image = Image.open(source_path)
    started = time.perf_counter()
    result = pipeline.run(
        RestoreRequest(
            stages=stages,
            scale=scale,
            fidelity=0.75,
            denoise_strength=0.35,
            auto_mask=True,
            seed=1234,
            image=image,
        ),
        on_progress=lambda stage, i, step, total, overall: log.info(
            "  %s %d/%d (%.0f%% overall)", stage, step, total, overall * 100
        ),
    )
    elapsed = time.perf_counter() - started

    out_dir = ROOT / "outputs"
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{source_path.stem}-restored.png"
    result.image.save(target)
    if result.damage_overlay is not None:
        result.damage_overlay.save(out_dir / f"{source_path.stem}-damage.png")

    log.info("wrote %s in %.1fs", target, elapsed)
    log.info("timings: %s", result.stage_timings)
    log.info("damage %.2f%% | faces %d", result.damage_ratio * 100, result.faces_found)
    for note in result.notes:
        log.info("note: %s", note)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="process a single job then exit")
    parser.add_argument("--self-test", metavar="IMAGE", help="restore a local file, post nothing")
    parser.add_argument("--stages", default=None, help="comma-separated stages for --self-test")
    parser.add_argument("--scale", type=int, default=2)
    parser.add_argument("--name", default=None, help="override the worker name")
    args = parser.parse_args()

    config = WorkerConfig.from_env()
    if args.name:
        config.name = args.name

    signal.signal(signal.SIGINT, _handle_signal)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _handle_signal)

    if args.self_test:
        stages = (
            [s.strip() for s in args.stages.split(",") if s.strip()]
            if args.stages
            else ["descratch", "denoise", "upscale", "face_enhance"]
        )
        self_test(config, Path(args.self_test), stages, args.scale)
        return

    if not config.api_key:
        sys.exit("SMRITI_WORKER_KEY is not set; copy .env.example to .env and fill it in")

    Worker(config).start(once=args.once)


if __name__ == "__main__":
    main()
