"""Tracks whether anything is actually happening.

The background loops exist to recover abandoned jobs and prune storage. On an
idle demo there is nothing to recover, but polling every 15 seconds would keep a
serverless Postgres awake around the clock and burn through free-tier compute
hours for no benefit.

So the loops back off when idle and snap back to a tight interval the moment a
job is created or a worker appears. Recovery latency only matters when there is
work in flight, and work in flight is exactly what resets the timer.
"""

from __future__ import annotations

import time


class ActivityTracker:
    def __init__(self, idle_after_seconds: float = 180.0) -> None:
        self.idle_after_seconds = idle_after_seconds
        self._last_activity = time.monotonic()
        self._consecutive_quiet_sweeps = 0

    def touch(self) -> None:
        """Signal real activity: a job queued, claimed, or a worker checking in."""
        self._last_activity = time.monotonic()
        self._consecutive_quiet_sweeps = 0

    @property
    def seconds_since_activity(self) -> float:
        return time.monotonic() - self._last_activity

    @property
    def is_idle(self) -> bool:
        return self.seconds_since_activity > self.idle_after_seconds

    def note_sweep(self, found_work: bool) -> None:
        if found_work:
            self.touch()
        else:
            self._consecutive_quiet_sweeps = min(self._consecutive_quiet_sweeps + 1, 16)

    def next_interval(self, base_seconds: float, max_seconds: float) -> float:
        """Exponential backoff while nothing is happening, capped."""
        if not self.is_idle:
            return base_seconds
        return min(base_seconds * (2**self._consecutive_quiet_sweeps), max_seconds)


activity = ActivityTracker()
