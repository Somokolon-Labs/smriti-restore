/** Typed client for the control plane. */

import { getSessionId } from "./session";
import type {
  CreateJobInput,
  EvalRun,
  Job,
  JobList,
  Profile,
  QueueStatus,
  ShowcaseItem,
  ShowcasePage,
  StageInfo,
  UploadResult,
} from "./types";

export const API_BASE = (process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000").replace(
  /\/$/,
  "",
);

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly retryAfter?: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** Resolve a relative `/v1/images/...` path against the API origin. */
export function absoluteUrl(path: string | null | undefined): string {
  if (!path) return "";
  if (/^(https?:|data:|blob:)/.test(path)) return path;
  return `${API_BASE}${path}`;
}

interface RequestOptions extends Omit<RequestInit, "body"> {
  body?: unknown;
  timeoutMs?: number;
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { body, timeoutMs = 30_000, headers, ...rest } = options;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  const requestHeaders: Record<string, string> = {
    Accept: "application/json",
    ...((headers as Record<string, string>) ?? {}),
  };
  const sessionId = getSessionId();
  if (sessionId) requestHeaders["X-Session-Id"] = sessionId;

  let payload: BodyInit | undefined;
  if (body instanceof FormData) {
    payload = body;
  } else if (body !== undefined) {
    requestHeaders["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }

  try {
    const response = await fetch(`${API_BASE}${path}`, {
      ...rest,
      headers: requestHeaders,
      body: payload,
      signal: controller.signal,
      cache: "no-store",
    });

    if (response.status === 204) return undefined as T;

    if (!response.ok) {
      let detail = `request failed with ${response.status}`;
      try {
        const parsed = await response.json();
        if (typeof parsed?.detail === "string") detail = parsed.detail;
        else if (Array.isArray(parsed?.detail)) detail = parsed.detail[0]?.msg ?? detail;
      } catch {
        /* non-JSON error body */
      }
      const retryAfter = Number(response.headers.get("Retry-After") ?? "") || undefined;
      throw new ApiError(detail, response.status, retryAfter);
    }

    return (await response.json()) as T;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new ApiError("the request timed out", 408);
    }
    throw new ApiError("cannot reach the API — is the control plane running?", 0);
  } finally {
    clearTimeout(timer);
  }
}

export const api = {
  getProfiles: () => request<Profile[]>("/v1/profiles"),
  getStages: () => request<StageInfo[]>("/v1/stages"),
  getStatus: () => request<QueueStatus>("/v1/status", { timeoutMs: 12_000 }),

  uploadImage: (file: File, role: "source" | "mask" = "source") => {
    const form = new FormData();
    form.append("file", file);
    return request<UploadResult>(`/v1/uploads?role=${role}`, {
      method: "POST",
      body: form,
      timeoutMs: 120_000,
    });
  },

  createJob: (input: CreateJobInput) => request<Job>("/v1/jobs", { method: "POST", body: input }),
  getJob: (id: string) => request<Job>(`/v1/jobs/${id}`, { timeoutMs: 12_000 }),
  listJobs: (limit = 24) => request<JobList>(`/v1/jobs?limit=${limit}`),
  cancelJob: (id: string) => request<Job>(`/v1/jobs/${id}/cancel`, { method: "POST" }),
  deleteJob: (id: string) => request<void>(`/v1/jobs/${id}`, { method: "DELETE" }),

  getShowcase: (params: { limit?: number; cursor?: string; profile?: string } = {}) => {
    const query = new URLSearchParams();
    query.set("limit", String(params.limit ?? 12));
    if (params.cursor) query.set("cursor", params.cursor);
    if (params.profile) query.set("profile", params.profile);
    return request<ShowcasePage>(`/v1/showcase?${query.toString()}`);
  },
  getShowcaseItem: (id: string) => request<ShowcaseItem>(`/v1/showcase/${id}`),

  getCurrentEval: () => request<EvalRun>("/v1/model/current"),
};

export type Api = typeof api;
