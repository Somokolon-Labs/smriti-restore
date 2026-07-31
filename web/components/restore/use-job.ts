"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "@/lib/api";
import type { Job } from "@/lib/types";

const ACTIVE_POLL_MS = 900;
const QUEUED_POLL_MS = 2200;
const TERMINAL = new Set(["succeeded", "failed", "canceled"]);

/**
 * Polls one job until it settles. Backs off while merely queued so a job waiting
 * on an offline worker does not hammer the API for hours.
 */
export function useJob(initial: Job | null) {
  const [job, setJob] = useState<Job | null>(initial);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const stop = useCallback(() => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
  }, []);

  useEffect(() => {
    setJob(initial);
  }, [initial]);

  useEffect(() => {
    if (!job || TERMINAL.has(job.status)) {
      stop();
      return;
    }

    let cancelled = false;
    const delay = job.status === "queued" ? QUEUED_POLL_MS : ACTIVE_POLL_MS;

    timer.current = setTimeout(async () => {
      try {
        const next = await api.getJob(job.id);
        if (!cancelled) setJob(next);
      } catch {
        // transient network blip: keep the last known state and retry
        if (!cancelled) setJob({ ...job });
      }
    }, delay);

    return () => {
      cancelled = true;
      stop();
    };
  }, [job, stop]);

  return { job, setJob };
}
