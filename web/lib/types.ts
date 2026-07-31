/** Mirrors api/app/schemas.py. Keep the two in step. */

export type Tier = "fast" | "balanced" | "max";
export type Stage = "descratch" | "denoise" | "colorize" | "upscale" | "face_enhance";
export type JobStatus = "queued" | "running" | "succeeded" | "failed" | "canceled";

export const STAGE_ORDER: Stage[] = [
  "descratch",
  "denoise",
  "colorize",
  "upscale",
  "face_enhance",
];

export interface StageInfo {
  id: Stage;
  label: string;
  note: string;
}

export interface Profile {
  id: string;
  label: string;
  description: string;
  best_for: string;
  stages: Stage[];
  tier: Tier;
  requires_mask: boolean;
  defaults: {
    scale: number;
    fidelity: number;
    denoise_strength: number;
    auto_mask: boolean;
  };
}

export interface Job {
  id: string;
  status: JobStatus;
  profile: string;
  tier: string;
  stages: Stage[];
  stages_completed: Stage[];
  scale: number;
  fidelity: number;
  denoise_strength: number;
  auto_mask: boolean;
  seed: number;
  progress: number;
  stage: string;
  stage_index: number;
  progress_step: number;
  progress_total: number;
  attempts: number;
  max_attempts: number;
  queue_position: number | null;
  duration_ms: number;
  stage_timings: Record<string, number>;
  error: string;
  notes: string;
  source_image_id: string;
  mask_image_id: string | null;
  damage_map_id: string | null;
  result_image_id: string | null;
  source_url: string | null;
  result_url: string | null;
  damage_map_url: string | null;
  source_width: number;
  source_height: number;
  result_width: number;
  result_height: number;
  damage_ratio: number;
  faces_found: number;
  worker_id: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface JobList {
  items: Job[];
  total: number;
}

export interface UploadResult {
  image_id: string;
  url: string;
  width: number;
  height: number;
  mime: string;
  size_bytes: number;
  is_grayscale: boolean;
  downscaled: boolean;
}

export interface WorkerInfo {
  id: string;
  name: string;
  gpu_name: string;
  vram_mb: number;
  version: string;
  stages: Stage[];
  tiers: Tier[];
  max_pixels: number;
  jobs_completed: number;
  jobs_failed: number;
  last_seen_at: string;
  online: boolean;
}

export interface QueueStatus {
  queued: number;
  running: number;
  workers_online: number;
  workers: WorkerInfo[];
  accepting_jobs: boolean;
  available_stages: Stage[];
  est_wait_seconds: number | null;
  avg_duration_ms: number | null;
  max_upload_mb: number;
  max_source_pixels: number;
}

export interface ShowcaseItem {
  job_id: string;
  before_url: string;
  after_url: string;
  profile: string;
  stages: Stage[];
  source_width: number;
  source_height: number;
  result_width: number;
  result_height: number;
  damage_ratio: number;
  faces_found: number;
  duration_ms: number;
  notes: string;
  featured: boolean;
  created_at: string;
}

export interface ShowcasePage {
  items: ShowcaseItem[];
  next_cursor: string | null;
}

/** Shape written by ml/evaluate.py and published to /v1/model/runs. */
export interface EvalResults {
  summary?: {
    images_evaluated?: number;
    psnr_degraded?: number;
    psnr_restored?: number;
    psnr_gain_db?: number;
    ssim_degraded?: number;
    ssim_restored?: number;
    ssim_gain?: number;
    lpips_degraded?: number;
    lpips_restored?: number;
    lpips_improvement_pct?: number;
    seconds_per_megapixel?: number;
  };
  per_degradation?: Array<{
    degradation: string;
    psnr_degraded: number;
    psnr_restored: number;
    ssim_degraded: number;
    ssim_restored: number;
  }>;
  per_stage_timing?: Record<string, number>;
  protocol?: Record<string, string | number>;
  hardware?: Record<string, string | number>;
  [key: string]: unknown;
}

export interface EvalRun {
  id: string;
  name: string;
  commit_sha: string;
  results: EvalResults;
  notes: string;
  created_at: string;
}

export interface CreateJobInput {
  source_image_id: string;
  profile: string;
  tier?: Tier | null;
  stages?: Partial<Record<Stage, boolean>> | null;
  scale?: 1 | 2 | 4 | null;
  fidelity?: number | null;
  denoise_strength?: number | null;
  auto_mask?: boolean | null;
  mask_image_id?: string | null;
  seed?: number;
  share_public?: boolean;
  notes?: string;
}
