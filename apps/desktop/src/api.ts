export type Project = { id: string; name: string; workspace_path: string; target_duration_seconds: string; frame_rate: string; assets?: number; shots?: number; latest_music?: boolean; music_paths?: string[]; style_reference_count?: number; stale_analysis?: { shots: boolean; music: boolean } };
export type CreateProject = Pick<Project, "name" | "workspace_path" | "target_duration_seconds" | "frame_rate">;
export type JobStatus = "queued" | "running" | "cancel_requested" | "cancelled" | "completed" | "failed";
export type Job = {
  id: string;
  kind: string;
  status: JobStatus;
  progress: number;
  error?: string | null;
  stalled?: boolean;
  // P2 job observability contract — additive, all optional so a response from before this
  // existed (or a job kind this UI does not special-case) still renders correctly.
  stage?: string | null;
  processed?: number | null;
  total?: number | null;
  stage_progress?: number | null;
  overall_progress?: number | null;
  current_asset_id?: string | null;
  current_asset_display?: string | null;
  current_shot_id?: string | null;
  current_shot_index?: number | null;
  last_progress_at?: string | null;
  last_heartbeat_at?: string | null;
};
export type TimelineItem = { clip_name: string; source_path: string; score: number; category: string; shot_scale: string; selection_reason: string; source_in: { start_seconds: string; duration_seconds: string }; timeline_in: { start_seconds: string; duration_seconds: string } };
export type Timeline = { id: string; name: string; created_at?: string | null; actual_duration_seconds: string; frame_rate: string; music_path?: string | null; warnings: string[]; items: TimelineItem[] };

/**
 * FastAPI answers a rejected body with `detail` as a list of objects, not a string, and
 * `new Error(list)` reads as "[object Object]" — which is what the status panel showed when a
 * request was refused, telling the user nothing at all about what was wrong.
 */
function describe(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const lines = detail.map((item) => {
      if (typeof item === "string") return item;
      const where = Array.isArray(item?.loc) ? item.loc.filter((part: unknown) => part !== "body").join(".") : "";
      const message = item?.msg ?? JSON.stringify(item);
      return where ? `${where}: ${message}` : String(message);
    });
    if (lines.length) return lines.join("; ");
  }
  if (detail && typeof detail === "object") return JSON.stringify(detail);
  return "İstek tamamlanamadı.";
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { headers: { "Content-Type": "application/json" }, ...init });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(describe(body.detail));
  return body as T;
}
export type Rejections = { clips: string[]; added?: string[]; unknown?: string[] };

export const api = {
  projects: () => call<Project[]>("/api/projects"),
  project: (payload: CreateProject) => call<Project>("/api/projects", { method: "POST", body: JSON.stringify(payload) }),
  getProject: (id: string) => call<Project>(`/api/projects/${id}`),
  latestTimeline: (projectId: string) => call<Timeline>(`/api/projects/${projectId}/timelines/latest`),
  startJob: (projectId: string, endpoint: string, payload?: object) => call<{ job_id: string }>(`/api/projects/${projectId}/${endpoint}`, { method: "POST", body: payload ? JSON.stringify(payload) : undefined }),
  job: (id: string) => call<Job>(`/api/jobs/${id}`),
  latestJob: (projectId: string) => call<Job>(`/api/projects/${projectId}/jobs/latest`),
  cancel: (jobId: string) => call<Job>(`/api/jobs/${jobId}/cancel`, { method: "POST" }),
  timeline: (projectId: string, payload: object) => call<Timeline>(`/api/projects/${projectId}/timelines`, { method: "POST", body: JSON.stringify(payload) }),
  export: (timelineId: string) => call<Record<string, string>>(`/api/timelines/${timelineId}/export`, { method: "POST" }),
  rejections: (projectId: string) => call<Rejections>(`/api/projects/${projectId}/rejections`),
  reject: (projectId: string, clips: string[], reason = "") =>
    call<Rejections>(`/api/projects/${projectId}/rejections`, { method: "POST", body: JSON.stringify({ clips, reason }) }),
  restore: (projectId: string, clips: string[]) =>
    call<Rejections>(`/api/projects/${projectId}/rejections`, { method: "DELETE", body: JSON.stringify({ clips }) }),
};
