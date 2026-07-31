"""Prometheus instrumentation. Scrape at GET /metrics."""

from __future__ import annotations

import os
import time

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, multiprocess

REGISTRY = CollectorRegistry()
if os.getenv("PROMETHEUS_MULTIPROC_DIR"):  # pragma: no cover - multi-worker uvicorn
    multiprocess.MultiProcessCollector(REGISTRY)

jobs_created = Counter(
    "smriti_jobs_created_total",
    "Restoration jobs enqueued",
    ["profile", "tier"],
    registry=REGISTRY,
)
jobs_finished = Counter(
    "smriti_jobs_finished_total",
    "Jobs that reached a terminal state",
    ["profile", "tier", "status"],
    registry=REGISTRY,
)
jobs_requeued = Counter(
    "smriti_jobs_requeued_total",
    "Jobs returned to the queue after a lost lease or retryable failure",
    ["reason"],
    registry=REGISTRY,
)
stage_requested = Counter(
    "smriti_stage_requested_total",
    "Pipeline stages requested across all jobs",
    ["stage"],
    registry=REGISTRY,
)
stage_completed = Counter(
    "smriti_stage_completed_total",
    "Pipeline stages that finished successfully",
    ["stage"],
    registry=REGISTRY,
)
stage_duration = Histogram(
    "smriti_stage_duration_seconds",
    "Wall-clock GPU time per pipeline stage",
    ["stage"],
    buckets=(0.5, 1, 2, 4, 8, 15, 30, 60, 120, 300),
    registry=REGISTRY,
)
job_duration = Histogram(
    "smriti_job_duration_seconds",
    "Wall-clock time for a complete restoration",
    ["profile", "tier"],
    buckets=(1, 2, 5, 10, 20, 40, 80, 150, 300, 600),
    registry=REGISTRY,
)
job_queue_wait = Histogram(
    "smriti_job_queue_wait_seconds",
    "Time from enqueue to claim",
    buckets=(0.5, 1, 2, 5, 10, 30, 60, 300, 900),
    registry=REGISTRY,
)
megapixels_restored = Counter(
    "smriti_megapixels_restored_total",
    "Output megapixels produced, the honest unit of work done",
    registry=REGISTRY,
)
http_requests = Counter(
    "smriti_http_requests_total",
    "HTTP requests",
    ["method", "path", "status"],
    registry=REGISTRY,
)
http_latency = Histogram(
    "smriti_http_request_seconds",
    "HTTP request latency",
    ["method", "path"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 5),
    registry=REGISTRY,
)
queue_depth = Gauge("smriti_queue_depth", "Jobs waiting", registry=REGISTRY)
jobs_running = Gauge("smriti_jobs_running", "Jobs in flight", registry=REGISTRY)
workers_online = Gauge("smriti_workers_online", "Workers seen recently", registry=REGISTRY)
images_stored = Gauge("smriti_images_stored", "Rows in the images table", registry=REGISTRY)
images_pruned = Counter(
    "smriti_images_pruned_total", "Images removed by retention", ["reason"], registry=REGISTRY
)


class Timer:
    """`with Timer() as t: ...` then read `t.elapsed`."""

    def __init__(self) -> None:
        self.elapsed = 0.0
        self._start = 0.0

    def __enter__(self) -> Timer:
        self._start = time.perf_counter()
        return self

    def __exit__(self, *_exc) -> None:
        self.elapsed = time.perf_counter() - self._start
