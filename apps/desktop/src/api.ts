export type Project = { id: string; name: string; workspace_path: string; target_duration_seconds: string; frame_rate: string; assets?: number; shots?: number; latest_music?: boolean; music_paths?: string[]; style_reference_count?: number; stale_analysis?: { shots: boolean; music: boolean } };
export type CreateProject = Pick<Project, "name" | "workspace_path" | "target_duration_seconds" | "frame_rate">;
export type Job = { id: string; kind: string; status: "queued" | "running" | "completed" | "failed"; progress: number; error?: string | null ; stalled?: boolean };
export type TimelineItem = { clip_name: string; source_path: string; score: number; category: string; shot_scale: string; selection_reason: string; source_in: { start_seconds: string; duration_seconds: string }; timeline_in: { start_seconds: string; duration_seconds: string } };
export type Timeline = { id: string; name: string; actual_duration_seconds: string; frame_rate: string; music_path?: string | null; warnings: string[]; items: TimelineItem[] };

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { headers: { "Content-Type": "application/json" }, ...init });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail ?? "İstek tamamlanamadı.");
  return body as T;
}
export const api = {
  projects: () => call<Project[]>("/api/projects"),
  project: (payload: CreateProject) => call<Project>("/api/projects", { method: "POST", body: JSON.stringify(payload) }),
  getProject: (id: string) => call<Project>(`/api/projects/${id}`),
  latestTimeline: (projectId: string) => call<Timeline>(`/api/projects/${projectId}/timelines/latest`),
  startJob: (projectId: string, endpoint: string, payload?: object) => call<{ job_id: string }>(`/api/projects/${projectId}/${endpoint}`, { method: "POST", body: payload ? JSON.stringify(payload) : undefined }),
  job: (id: string) => call<Job>(`/api/jobs/${id}`),
  latestJob: (projectId: string) => call<Job>(`/api/projects/${projectId}/jobs/latest`),
  timeline: (projectId: string, payload: object) => call<Timeline>(`/api/projects/${projectId}/timelines`, { method: "POST", body: JSON.stringify(payload) }),
  export: (timelineId: string) => call<Record<string, string>>(`/api/timelines/${timelineId}/export`, { method: "POST" }),
};
