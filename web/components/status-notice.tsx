"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { api } from "@/lib/api";

/**
 * Honest state of the deployment, derived rather than hardcoded.
 *
 * Smriti uses pretrained diffusion models, so there is nothing to train — what
 * can be missing is a GPU worker to run them and a published benchmark. Both are
 * checked live, and the notice removes itself once they exist. No flag to flip.
 */
export function AdapterStatusNotice({ className = "" }: { className?: string }) {
  const [state, setState] = useState<
    { workers: number; published: boolean; stages: number } | null
  >(null);

  useEffect(() => {
    let cancelled = false;

    (async () => {
      const [evalResult, statusResult] = await Promise.allSettled([
        api.getCurrentEval(),
        api.getStatus(),
      ]);
      if (cancelled) return;
      setState({
        published: evalResult.status === "fulfilled",
        workers:
          statusResult.status === "fulfilled" ? statusResult.value.workers_online : 0,
        stages:
          statusResult.status === "fulfilled"
            ? statusResult.value.available_stages.length
            : 0,
      });
    })();

    return () => {
      cancelled = true;
    };
  }, []);

  if (!state) return null;
  if (state.workers > 0 && state.published) return null;

  return (
    <aside
      className={`rounded-card border border-turmeric/35 bg-turmeric/[0.07] px-4 py-3.5 ${className}`}
      role="status"
    >
      <p className="text-sm font-medium text-cotton">
        {state.workers > 0
          ? "Running, but no benchmark has been published yet."
          : "No GPU worker is attached right now."}
      </p>
      <p className="mt-1.5 text-sm leading-relaxed text-cotton-dim">
        {state.workers > 0 ? (
          <>
            Restoration works — {state.stages} pipeline stage
            {state.stages === 1 ? "" : "s"} available. The{" "}
            <Link href="/model" className="text-turmeric underline">
              model card
            </Link>{" "}
            stays empty until the evaluation harness has actually measured something.
          </>
        ) : (
          <>
            The control plane, job queue, fault-tolerant worker protocol, damage detection and
            evaluation harness are complete and running here. What is missing is a GPU to attach.
            You can still submit a photograph and it will wait in the queue, and the{" "}
            <Link href="/showcase" className="text-turmeric underline">
              showcase
            </Link>{" "}
            works regardless. Nothing here pretends to have restored something it has not.
          </>
        )}
      </p>
    </aside>
  );
}
