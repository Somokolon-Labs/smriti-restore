"use client";

import { useEffect, useState } from "react";

import { Callout, Spinner, Stat } from "@/components/ui";
import { api } from "@/lib/api";
import type { EvalRun } from "@/lib/types";
import { cn } from "@/lib/utils";

function num(value: number | undefined, digits = 3): string {
  return value === undefined || Number.isNaN(value) ? "—" : value.toFixed(digits);
}

/** Paired bars: degraded input against restored output. */
function PairedBars({
  rows,
  higherIsBetter,
  unit = "",
}: {
  rows: Array<{ label: string; before: number; after: number }>;
  higherIsBetter: boolean;
  unit?: string;
}) {
  const max = Math.max(...rows.flatMap((row) => [row.before, row.after]), 0.0001);

  return (
    <div className="space-y-4">
      {rows.map((row) => {
        const improved = higherIsBetter ? row.after > row.before : row.after < row.before;
        return (
          <div key={row.label}>
            <div className="mb-1.5 flex items-baseline justify-between gap-3">
              <span className="text-sm text-cotton-dim">{row.label.replace(/_/g, " ")}</span>
              <span className="font-mono text-xs text-cotton-faint">
                {num(row.before)} → <span className="text-cotton">{num(row.after)}</span>
                {unit}
              </span>
            </div>
            <div className="space-y-1">
              <div className="h-2 overflow-hidden rounded-full bg-ink-line">
                <div
                  className="h-full rounded-full bg-cotton-faint/60"
                  style={{ width: `${(row.before / max) * 100}%` }}
                />
              </div>
              <div className="h-2 overflow-hidden rounded-full bg-ink-line">
                <div
                  className={cn("h-full rounded-full", improved ? "bg-turmeric" : "bg-madder")}
                  style={{ width: `${(row.after / max) * 100}%` }}
                />
              </div>
            </div>
          </div>
        );
      })}
      <p className="label pt-1">
        <span className="mr-3 inline-flex items-center gap-1.5">
          <span className="h-2 w-4 rounded-full bg-cotton-faint/60" /> degraded input
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="h-2 w-4 rounded-full bg-turmeric" /> restored
        </span>
      </p>
    </div>
  );
}

export function EvalReport() {
  const [run, setRun] = useState<EvalRun | null>(null);
  const [missing, setMissing] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    api
      .getCurrentEval()
      .then((result) => {
        if (!cancelled) setRun(result);
      })
      .catch(() => {
        if (!cancelled) setMissing(true);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (loading) {
    return (
      <p className="flex items-center gap-2 text-sm text-cotton-faint">
        <Spinner /> loading evaluation
      </p>
    );
  }

  if (missing || !run) {
    return (
      <Callout tone="warn" title="No evaluation published yet">
        The benchmark has not been run against this deployment. Run{" "}
        <code className="font-mono text-turmeric">python -m ml.evaluate --publish</code> on a
        machine with a GPU to fill this page with measured numbers. Nothing here is hard-coded,
        which is why it is empty rather than optimistic.
      </Callout>
    );
  }

  const summary = run.results.summary ?? {};
  const perDegradation = run.results.per_degradation ?? [];
  const timings = run.results.per_stage_timing ?? {};
  const protocol = run.results.protocol ?? {};

  return (
    <div className="space-y-10">
      <section>
        <h2 className="label mb-3">Headline results</h2>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Stat
            label="PSNR"
            value={summary.psnr_restored !== undefined ? `${num(summary.psnr_restored, 2)} dB` : "—"}
            sub={
              summary.psnr_gain_db !== undefined
                ? `${summary.psnr_gain_db > 0 ? "+" : ""}${summary.psnr_gain_db.toFixed(2)} dB vs degraded ${num(summary.psnr_degraded, 2)}`
                : undefined
            }
            accent
          />
          <Stat
            label="SSIM"
            value={num(summary.ssim_restored)}
            sub={
              summary.ssim_degraded !== undefined
                ? `from ${num(summary.ssim_degraded)} degraded (higher is better)`
                : undefined
            }
            accent
          />
          <Stat
            label="LPIPS"
            value={num(summary.lpips_restored)}
            sub={
              summary.lpips_improvement_pct !== undefined
                ? `${summary.lpips_improvement_pct.toFixed(0)}% closer perceptually (lower is better)`
                : undefined
            }
          />
          <Stat
            label="Seconds per megapixel"
            value={
              summary.seconds_per_megapixel !== undefined
                ? `${summary.seconds_per_megapixel.toFixed(1)}s`
                : "—"
            }
            sub={
              summary.images_evaluated !== undefined
                ? `over ${summary.images_evaluated} image pairs`
                : undefined
            }
          />
        </div>
        <p className="mt-3 text-xs leading-relaxed text-cotton-faint">
          Reference-based: clean photographs are degraded with known, synthesised damage, restored,
          then compared against the originals. Because ground truth exists, these are measurements
          rather than preferences.
        </p>
      </section>

      {perDegradation.length > 0 && (
        <>
          <section className="surface p-5">
            <h2 className="label mb-4">PSNR by degradation type</h2>
            <PairedBars
              higherIsBetter
              unit=" dB"
              rows={perDegradation.map((row) => ({
                label: row.degradation,
                before: row.psnr_degraded,
                after: row.psnr_restored,
              }))}
            />
          </section>

          <section className="surface p-5">
            <h2 className="label mb-4">SSIM by degradation type</h2>
            <PairedBars
              higherIsBetter
              rows={perDegradation.map((row) => ({
                label: row.degradation,
                before: row.ssim_degraded,
                after: row.ssim_restored,
              }))}
            />
          </section>
        </>
      )}

      {Object.keys(timings).length > 0 && (
        <section>
          <h2 className="label mb-3">Where the time goes</h2>
          <dl className="surface grid gap-x-8 gap-y-3 p-5 sm:grid-cols-2">
            {Object.entries(timings).map(([stage, seconds]) => (
              <div key={stage} className="flex items-baseline justify-between gap-4">
                <dt className="label">{stage.replace(/_/g, " ")}</dt>
                <dd className="font-mono text-xs text-cotton">{Number(seconds).toFixed(2)}s</dd>
              </div>
            ))}
          </dl>
        </section>
      )}

      {Object.keys(protocol).length > 0 && (
        <section>
          <h2 className="label mb-3">Protocol</h2>
          <dl className="surface grid gap-x-8 gap-y-3 p-5 sm:grid-cols-2">
            {Object.entries(protocol).map(([key, value]) => (
              <div key={key} className="flex items-baseline justify-between gap-4">
                <dt className="label">{key.replace(/_/g, " ")}</dt>
                <dd className="font-mono text-xs text-cotton">{String(value)}</dd>
              </div>
            ))}
          </dl>
        </section>
      )}

      <p className="text-xs text-cotton-faint">
        Run “{run.name}”
        {run.commit_sha && ` · commit ${run.commit_sha.slice(0, 8)}`} · published{" "}
        {new Date(run.created_at).toLocaleString()}
      </p>
    </div>
  );
}
