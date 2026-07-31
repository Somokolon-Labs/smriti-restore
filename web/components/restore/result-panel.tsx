"use client";

import { useState } from "react";

import { CompareSlider } from "@/components/compare-slider";
import { Callout, Spinner } from "@/components/ui";
import { absoluteUrl, api } from "@/lib/api";
import type { Job, StageInfo } from "@/lib/types";
import { STATUS_LABEL, downloadUrl, formatDuration } from "@/lib/utils";
import { cn } from "@/lib/utils";

function StageTrail({ job, stageInfo }: { job: Job; stageInfo: StageInfo[] }) {
  const labelFor = (id: string) =>
    stageInfo.find((s) => s.id === id)?.label ?? id.replace(/_/g, " ");

  return (
    <ol className="space-y-1.5">
      {job.stages.map((stage, index) => {
        const done = job.stages_completed.includes(stage) || job.status === "succeeded";
        const active = !done && job.stage === stage;
        const seconds = job.stage_timings?.[stage];
        return (
          <li key={stage} className="flex items-center gap-2.5 text-sm">
            <span
              className={cn(
                "grid h-5 w-5 shrink-0 place-items-center rounded-full border text-[10px]",
                done
                  ? "border-leaf bg-leaf/20 text-leaf"
                  : active
                    ? "border-turmeric bg-turmeric/20 text-turmeric"
                    : "border-ink-line text-cotton-faint",
              )}
            >
              {done ? "✓" : index + 1}
            </span>
            <span className={done || active ? "text-cotton" : "text-cotton-faint"}>
              {labelFor(stage)}
            </span>
            {seconds !== undefined && (
              <span className="ml-auto font-mono text-xs text-cotton-faint">
                {seconds.toFixed(1)}s
              </span>
            )}
            {active && <Spinner className="ml-auto h-3.5 w-3.5 text-turmeric" />}
          </li>
        );
      })}
    </ol>
  );
}

export function ResultPanel({
  job,
  stageInfo,
  workersOnline,
  onDeleted,
}: {
  job: Job | null;
  stageInfo: StageInfo[];
  workersOnline: boolean;
  onDeleted?: () => void;
}) {
  const [showDamage, setShowDamage] = useState(false);
  const [deleting, setDeleting] = useState(false);

  if (!job) {
    return (
      <div className="surface flex min-h-[26rem] flex-col items-center justify-center gap-3 p-8 text-center">
        <div className="h-16 w-16 rounded-lg border border-dashed border-ink-line" aria-hidden />
        <p className="font-display text-lg text-cotton">Nothing restored yet</p>
        <p className="max-w-xs text-sm text-cotton-faint">
          Upload a photograph and pick a profile. Damage is detected automatically; you can also
          paint over anything it misses.
        </p>
        {!workersOnline && (
          <div className="mt-2 max-w-sm">
            <Callout tone="warn">
              No GPU worker is attached right now, so a job will wait in the queue until one
              connects.
            </Callout>
          </div>
        )}
      </div>
    );
  }

  const before = absoluteUrl(job.source_url);
  const after = absoluteUrl(job.result_url);
  const damageMap = absoluteUrl(job.damage_map_url);

  return (
    <div className="surface overflow-hidden">
      <div className="flex items-center justify-between gap-3 border-b border-ink-line px-4 py-2.5">
        <span className="label">{STATUS_LABEL[job.status] ?? job.status}</span>
        <span className="font-mono text-[11px] text-cotton-faint">{job.id.slice(0, 12)}</span>
      </div>

      <div className="flex min-h-[22rem] items-center justify-center p-4">
        {job.status === "succeeded" && after ? (
          showDamage && damageMap ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={damageMap} alt="Detected damage" className="max-h-[32rem] w-auto rounded-lg" />
          ) : (
            <CompareSlider
              beforeUrl={before}
              afterUrl={after}
              beforeLabel="Original"
              afterLabel="Restored"
              className="w-full"
            />
          )
        ) : job.status === "failed" ? (
          <div className="max-w-sm">
            <Callout tone="error" title="Restoration failed">
              {job.error || "The worker reported an error."}
            </Callout>
          </div>
        ) : job.status === "canceled" ? (
          <p className="text-sm text-cotton-faint">Canceled.</p>
        ) : (
          <div className="w-full max-w-sm space-y-4">
            <div>
              <div className="mb-2 flex items-baseline justify-between text-xs">
                <span className="text-cotton-dim">
                  {job.status === "queued"
                    ? job.queue_position
                      ? `Queued · position ${job.queue_position}`
                      : "Queued"
                    : job.stage.replace(/_/g, " ") || "working"}
                </span>
                <span className="font-mono text-cotton">
                  {Math.round((job.progress || 0) * 100)}%
                </span>
              </div>
              <div className="h-1.5 overflow-hidden rounded-full bg-ink-line">
                <div
                  className={
                    job.status === "queued"
                      ? "skeleton h-full w-1/3 rounded-full bg-turmeric/50"
                      : "h-full rounded-full bg-turmeric transition-[width] duration-500"
                  }
                  style={
                    job.status === "queued"
                      ? undefined
                      : { width: `${Math.round((job.progress || 0) * 100)}%` }
                  }
                />
              </div>
            </div>
            <StageTrail job={job} stageInfo={stageInfo} />
            {job.attempts > 1 && (
              <p className="text-xs text-turmeric">
                Retry {job.attempts} of {job.max_attempts} — the previous worker dropped this job
                and it was requeued automatically.
              </p>
            )}
          </div>
        )}
      </div>

      {job.status === "succeeded" && (
        <div className="space-y-3 border-t border-ink-line px-4 py-4">
          <div className="flex flex-wrap gap-1.5">
            <span className="chip">
              {job.source_width}×{job.source_height} → {job.result_width}×{job.result_height}
            </span>
            {job.scale > 1 && <span className="chip">{job.scale}× upscale</span>}
            <span className="chip">{(job.damage_ratio * 100).toFixed(2)}% repaired</span>
            {job.faces_found > 0 && (
              <span className="chip">
                {job.faces_found} face{job.faces_found === 1 ? "" : "s"}
              </span>
            )}
            <span className="chip">{formatDuration(job.duration_ms)}</span>
          </div>

          <StageTrail job={job} stageInfo={stageInfo} />

          {job.notes && <p className="text-xs leading-relaxed text-cotton-faint">{job.notes}</p>}

          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              className="btn-primary text-xs"
              onClick={() => downloadUrl(after, `restored-${job.id.slice(0, 8)}.png`)}
            >
              Download
            </button>
            {damageMap && (
              <button
                type="button"
                className="btn-ghost text-xs"
                onClick={() => setShowDamage((value) => !value)}
              >
                {showDamage ? "Show comparison" : "Show detected damage"}
              </button>
            )}
            <button
              type="button"
              className="btn-ghost text-xs"
              disabled={deleting}
              onClick={async () => {
                setDeleting(true);
                try {
                  await api.deleteJob(job.id);
                  onDeleted?.();
                } finally {
                  setDeleting(false);
                }
              }}
              title="Erase this photograph and its result from the server now"
            >
              {deleting ? "Deleting…" : "Delete my photo"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
