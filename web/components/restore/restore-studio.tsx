"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { MaskCanvas } from "@/components/restore/mask-canvas";
import { ResultPanel } from "@/components/restore/result-panel";
import { useJob } from "@/components/restore/use-job";
import { Callout, Segmented, Slider, Spinner } from "@/components/ui";
import { useQueueStatus } from "@/components/worker-status";
import { ApiError, absoluteUrl, api } from "@/lib/api";
import type { Job, Profile, Stage, StageInfo, UploadResult } from "@/lib/types";
import { cn, formatWait } from "@/lib/utils";

const SCALES = [
  { value: "1" as const, label: "1×" },
  { value: "2" as const, label: "2×" },
  { value: "4" as const, label: "4×" },
];

export function RestoreStudio() {
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [stageInfo, setStageInfo] = useState<StageInfo[]>([]);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [overrides, setOverrides] = useState<Partial<Record<Stage, boolean>>>({});

  const [source, setSource] = useState<UploadResult | null>(null);
  const [uploading, setUploading] = useState(false);
  const [maskBlob, setMaskBlob] = useState<Blob | null>(null);
  const [showBrush, setShowBrush] = useState(false);

  const [scale, setScale] = useState<"1" | "2" | "4">("2");
  const [fidelity, setFidelity] = useState(0.75);
  const [denoise, setDenoise] = useState(0.35);
  const [autoMask, setAutoMask] = useState(true);
  const [sharePublic, setSharePublic] = useState(false);
  const [advanced, setAdvanced] = useState(false);

  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [initialJob, setInitialJob] = useState<Job | null>(null);
  const { job } = useJob(initialJob);
  const { status } = useQueueStatus();
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    Promise.all([api.getProfiles(), api.getStages()])
      .then(([list, stages]) => {
        setProfiles(list);
        setStageInfo(stages);
        const preferred = list.find((p) => p.id === "full_restore") ?? list[0];
        if (preferred) applyProfile(preferred);
      })
      .catch(() => setError("Could not load profiles. Is the API running?"));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function applyProfile(next: Profile) {
    setProfile(next);
    setOverrides({});
    setScale(String(next.defaults.scale) as "1" | "2" | "4");
    setFidelity(next.defaults.fidelity);
    setDenoise(next.defaults.denoise_strength);
    setAutoMask(next.defaults.auto_mask);
    setShowBrush(next.requires_mask);
  }

  const activeStages = useMemo<Stage[]>(() => {
    if (!profile) return [];
    const enabled = new Set<Stage>(profile.stages);
    for (const [stage, wanted] of Object.entries(overrides)) {
      if (wanted) enabled.add(stage as Stage);
      else enabled.delete(stage as Stage);
    }
    return (stageInfo.map((s) => s.id) as Stage[]).filter((s) => enabled.has(s));
  }, [profile, overrides, stageInfo]);

  const workersOnline = (status?.workers_online ?? 0) > 0;
  const unavailable = useMemo(() => {
    const offered = new Set(status?.available_stages ?? []);
    return workersOnline ? activeStages.filter((s) => !offered.has(s)) : [];
  }, [activeStages, status, workersOnline]);

  const handleUpload = useCallback(async (file: File) => {
    setUploading(true);
    setError(null);
    try {
      const result = await api.uploadImage(file, "source");
      setSource(result);
      setMaskBlob(null);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "upload failed");
    } finally {
      setUploading(false);
    }
  }, []);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (!source) {
      setError("Upload a photograph first.");
      return;
    }
    if (profile?.requires_mask && !maskBlob) {
      setError("This profile repairs only what you paint, so paint something first.");
      return;
    }

    setSubmitting(true);
    setError(null);
    try {
      let maskId: string | null = null;
      if (maskBlob) {
        const maskFile = new File([maskBlob], "mask.png", { type: "image/png" });
        maskId = (await api.uploadImage(maskFile, "mask")).image_id;
      }

      const created = await api.createJob({
        source_image_id: source.image_id,
        profile: profile?.id ?? "full_restore",
        stages: Object.keys(overrides).length ? overrides : null,
        scale: Number(scale) as 1 | 2 | 4,
        fidelity,
        denoise_strength: denoise,
        auto_mask: autoMask,
        mask_image_id: maskId,
        share_public: sharePublic,
      });
      setInitialJob(created);
    } catch (cause) {
      setError(
        cause instanceof ApiError
          ? cause.retryAfter
            ? `${cause.message}. Try again in ${Math.ceil(cause.retryAfter / 60)} min.`
            : cause.message
          : "could not queue the job",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,23rem)_minmax(0,1fr)]">
      <form onSubmit={handleSubmit} className="surface space-y-5 p-5">
        <div className="space-y-2">
          <p className="label">Photograph</p>
          <input
            ref={fileRef}
            type="file"
            accept="image/png,image/jpeg,image/webp"
            className="hidden"
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) void handleUpload(file);
            }}
          />
          <button
            type="button"
            onClick={() => fileRef.current?.click()}
            className={cn(
              "flex w-full items-center justify-center gap-2 rounded-lg border border-dashed px-3 py-7 text-sm transition-colors",
              source
                ? "border-leaf/50 text-cotton-dim"
                : "border-ink-line text-cotton-faint hover:border-cotton-faint",
            )}
          >
            {uploading ? (
              <>
                <Spinner /> uploading…
              </>
            ) : source ? (
              `${source.width}×${source.height} — click to replace`
            ) : (
              `Choose a photograph (up to ${status?.max_upload_mb ?? 25} MB)`
            )}
          </button>

          {source?.downscaled && (
            <Callout tone="info">
              This scan was large, so it was reduced to {source.width}×{source.height} before
              processing. That bounds both storage and the memory the worker needs.
            </Callout>
          )}
          {source?.is_grayscale && !activeStages.includes("colorize") && (
            <Callout tone="info">
              This looks black and white. Enable colourisation under Advanced if you want colour
              added — the colours will be invented, not recovered.
            </Callout>
          )}
        </div>

        {profiles.length > 0 && (
          <div>
            <p className="label mb-2">Profile</p>
            <div className="space-y-1.5">
              {profiles.map((item) => {
                const active = item.id === profile?.id;
                return (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => applyProfile(item)}
                    aria-pressed={active}
                    className={cn(
                      "w-full rounded-lg border p-3 text-left transition-colors",
                      active
                        ? "border-turmeric/70 bg-turmeric/10"
                        : "border-ink-line bg-ink/50 hover:border-cotton-faint/60",
                    )}
                  >
                    <span className="flex items-baseline justify-between gap-2">
                      <span className="text-sm font-medium text-cotton">{item.label}</span>
                      <span className="font-mono text-[10px] uppercase tracking-wider text-cotton-faint">
                        {item.tier}
                      </span>
                    </span>
                    <span className="mt-1 block text-xs leading-snug text-cotton-faint">
                      {item.description}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>
        )}

        {profile && (
          <p className="text-xs leading-relaxed text-cotton-faint">
            <span className="text-cotton-dim">Best for:</span> {profile.best_for}
          </p>
        )}

        {source && (
          <div>
            <button
              type="button"
              onClick={() => setShowBrush((value) => !value)}
              className="label flex w-full items-center justify-between hover:text-cotton"
              aria-expanded={showBrush}
            >
              Paint damage manually
              <span aria-hidden>{showBrush ? "−" : "+"}</span>
            </button>
            {showBrush && (
              <MaskCanvas
                className="mt-3"
                imageUrl={absoluteUrl(source.url)}
                width={source.width}
                height={source.height}
                onChange={setMaskBlob}
              />
            )}
            {maskBlob && !showBrush && (
              <p className="mt-2 text-xs text-leaf">A painted mask is attached.</p>
            )}
          </div>
        )}

        <button
          type="submit"
          className="btn-primary w-full"
          disabled={submitting || uploading || !source}
        >
          {submitting ? (
            <>
              <Spinner /> queueing…
            </>
          ) : (
            "Restore"
          )}
        </button>

        {status && (
          <p className="text-center text-xs text-cotton-faint">
            {workersOnline
              ? `${status.workers_online} worker online · ${formatWait(status.est_wait_seconds)}`
              : "No GPU worker attached — jobs will queue until one connects."}
          </p>
        )}

        {unavailable.length > 0 && (
          <Callout tone="warn">
            No attached worker can run: {unavailable.join(", ").replace(/_/g, " ")}. The job will
            wait rather than silently skipping those stages.
          </Callout>
        )}

        {error && <Callout tone="error">{error}</Callout>}

        <div className="stitch-rule" />

        <button
          type="button"
          onClick={() => setAdvanced((value) => !value)}
          className="label flex w-full items-center justify-between hover:text-cotton"
          aria-expanded={advanced}
        >
          Advanced
          <span aria-hidden>{advanced ? "−" : "+"}</span>
        </button>

        {advanced && (
          <div className="space-y-5 animate-fade-up">
            <div>
              <p className="label mb-2">Pipeline stages</p>
              <div className="space-y-1.5">
                {stageInfo.map((stage) => {
                  const on = activeStages.includes(stage.id);
                  return (
                    <label
                      key={stage.id}
                      className="flex cursor-pointer items-start gap-2.5 rounded-lg border border-ink-line/70 p-2.5"
                    >
                      <input
                        type="checkbox"
                        checked={on}
                        onChange={(event) =>
                          setOverrides((prev) => ({ ...prev, [stage.id]: event.target.checked }))
                        }
                        className="mt-0.5 accent-turmeric"
                      />
                      <span>
                        <span className="block text-sm text-cotton">{stage.label}</span>
                        <span className="block text-xs leading-snug text-cotton-faint">
                          {stage.note}
                        </span>
                      </span>
                    </label>
                  );
                })}
              </div>
            </div>

            {activeStages.includes("upscale") && (
              <Segmented label="Output size" options={SCALES} value={scale} onChange={setScale} />
            )}

            <Slider
              label="Fidelity to the original"
              value={fidelity}
              min={0}
              max={1}
              step={0.05}
              onChange={setFidelity}
              format={(v) => `${Math.round(v * 100)}%`}
              hint="High keeps the photograph as it is and repairs conservatively. Low lets the model reconstruct more."
            />

            {activeStages.includes("denoise") && (
              <Slider
                label="Noise reduction"
                value={denoise}
                min={0}
                max={1}
                step={0.05}
                onChange={setDenoise}
                format={(v) => `${Math.round(v * 100)}%`}
                hint="Too much removes real film grain along with the noise."
              />
            )}

            {activeStages.includes("descratch") && (
              <label className="flex items-start gap-2.5 text-sm text-cotton-dim">
                <input
                  type="checkbox"
                  checked={autoMask}
                  onChange={(event) => setAutoMask(event.target.checked)}
                  className="mt-0.5 accent-turmeric"
                />
                Detect damage automatically
              </label>
            )}

            <label className="flex items-start gap-2.5 text-sm text-cotton-dim">
              <input
                type="checkbox"
                checked={sharePublic}
                onChange={(event) => setSharePublic(event.target.checked)}
                className="mt-0.5 accent-turmeric"
              />
              <span>
                Allow this before/after pair to be considered for the public showcase.
                <span className="mt-0.5 block text-xs text-cotton-faint">
                  Off by default. Even with this on, nothing appears publicly until it is featured
                  by hand.
                </span>
              </span>
            </label>
          </div>
        )}
      </form>

      <div>
        <ResultPanel
          job={job}
          stageInfo={stageInfo}
          workersOnline={workersOnline}
          onDeleted={() => setInitialJob(null)}
        />
      </div>
    </div>
  );
}
