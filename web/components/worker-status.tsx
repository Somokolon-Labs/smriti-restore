"use client";

import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import type { QueueStatus } from "@/lib/types";
import { cn, formatDuration } from "@/lib/utils";

const POLL_MS = 8000;

export function useQueueStatus(pollMs = POLL_MS) {
  const [status, setStatus] = useState<QueueStatus | null>(null);
  const [reachable, setReachable] = useState(true);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;

    const tick = async () => {
      try {
        const next = await api.getStatus();
        if (!cancelled) {
          setStatus(next);
          setReachable(true);
        }
      } catch {
        if (!cancelled) setReachable(false);
      } finally {
        if (!cancelled) timer = setTimeout(tick, pollMs);
      }
    };

    void tick();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [pollMs]);

  return { status, reachable };
}

/**
 * Honest availability signal. When no GPU worker is attached the site says so
 * instead of pretending a queued job is about to run.
 */
export function WorkerStatusPill({ className }: { className?: string }) {
  const { status, reachable } = useQueueStatus();

  const state = !reachable
    ? { tone: "bg-madder", text: "API offline" }
    : !status
      ? { tone: "bg-cotton-faint", text: "checking…" }
      : status.workers_online > 0
        ? {
            tone: "bg-leaf",
            text:
              status.queued > 0
                ? `GPU online · ${status.queued} queued`
                : `GPU online · ${status.workers_online} worker${status.workers_online > 1 ? "s" : ""}`,
          }
        : { tone: "bg-turmeric", text: "GPU offline · browsing gallery" };

  return (
    <span
      className={cn("chip", className)}
      title={
        status?.avg_duration_ms
          ? `average generation ${formatDuration(status.avg_duration_ms)}`
          : "worker availability"
      }
    >
      <span className={cn("h-1.5 w-1.5 rounded-full", state.tone)} aria-hidden />
      {state.text}
    </span>
  );
}
