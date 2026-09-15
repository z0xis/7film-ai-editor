import { Job } from "./api";

/**
 * Backend lifecycle is authoritative; `stalled` is a health signal beside it, never a status of
 * its own. Nothing here invents a terminal state the backend did not report — see P0's
 * cross-project contamination fix and P1's job state machine for why that boundary matters.
 */
export const TERMINAL_STATUSES = new Set(["completed", "failed", "cancelled"]);

export function isTerminal(status: Job["status"]): boolean {
  return TERMINAL_STATUSES.has(status);
}

/** A job is "busy" — blocking a new one of the same kind — for as long as the backend still
 * owns it, `cancel_requested` included: the worker has not stopped yet, it has only been asked
 * to. `stalled` never enters this: a job reading unhealthy is still the job the backend is
 * tracking, and treating a stale heartbeat as "not busy any more" is exactly what would let the
 * UI start a second job on top of one that is, in fact, still running (P1's duplicate-active-job
 * guard exists on the backend for this, but the UI should not need to lean on a 409 to avoid it). */
export function isBusy(job: Job | null): boolean {
  return job !== null && !isTerminal(job.status);
}

/** Cancel is only ever offered for a job the backend can still act on. */
export function canCancel(job: Job | null): boolean {
  return job !== null && (job.status === "queued" || job.status === "running");
}

export const STATUS_LABELS: Record<Job["status"], string> = {
  queued: "sırada",
  running: "çalışıyor",
  cancel_requested: "iptal ediliyor",
  cancelled: "iptal edildi",
  completed: "tamamlandı",
  failed: "başarısız",
};

export function statusLabel(status: Job["status"]): string {
  return STATUS_LABELS[status] ?? status;
}

/** Shot analysis's own stages, worded for someone watching the status line, not the log. Every
 * other job kind runs a single, unnamed stage — its kind already says what it is doing. */
const SHOT_STAGE_LABELS: Record<string, string> = {
  encode: "Görüntüler analiz ediliyor",
  label: "Shot'lar sınıflandırılıyor",
  windows: "Shot anları ölçülüyor",
  finalize: "Tamamlanıyor",
};

export function stageLabel(job: Job): string | null {
  if (job.kind !== "shots" || !job.stage) return null;
  return SHOT_STAGE_LABELS[job.stage] ?? null;
}

/**
 * The one number the status line shows as a percentage. `overall_progress` (P2) is preferred;
 * `progress` (still present, and now equal to it) is the fallback for a response this field
 * came from before either existed. Never 100 unless the job is actually `completed` — a
 * malformed 1.0 from a `running` job is clamped down to 99, not trusted, exactly because a
 * mismatch here (backend hits 100% hours before it is actually done) is the production bug this
 * whole package traces back to.
 */
export function visiblePercent(job: Job): number {
  if (job.status === "completed") return 100;
  const raw = job.overall_progress ?? job.progress;
  if (typeof raw !== "number" || Number.isNaN(raw)) return 0;
  return Math.max(0, Math.min(99, Math.round(raw * 100)));
}

/** `processed`/`total`, only when the backend actually sent a real count -- never invented. */
export function progressCount(job: Job): string | null {
  if (typeof job.processed !== "number" || typeof job.total !== "number" || job.total <= 0) {
    return null;
  }
  return `${job.processed}/${job.total}`;
}

/** The single line describing a job in progress: kind, stage if there is one worth naming,
 * percentage, and a count when the backend gave one. Health (`stalled`) is reported separately
 * — see `healthWarning` — so this line never has to say a job is both "running" and "not
 * responding" in the same breath. */
export function statusLine(job: Job): string {
  const parts = [`${job.kind}: ${statusLabel(job.status)}`];
  const stage = stageLabel(job);
  if (stage) parts.push(stage);
  parts.push(`%${visiblePercent(job)}`);
  const count = progressCount(job);
  if (count) parts.push(count);
  return parts.join(" · ");
}

/**
 * A stale heartbeat is a warning beside a still-live job, not a reason to stop polling or to
 * show an error — the backend is the one that decides when this job is actually done, and it
 * may still finish healthily. Never claims a "resume" capability that does not exist: the
 * earlier wording here ("Yeniden başlatabilirsiniz; tamamlanan kısım korunur") promised a
 * feature — resuming a partially-measured `windows` pass — that P2's own checkpoint contract
 * explicitly does not provide (it records where a pass got to; nothing replays it automatically).
 */
export function healthWarning(job: Job): string | null {
  if (isTerminal(job.status) || !job.stalled) return null;
  return `${job.kind}: birkaç dakikadır yanıt vermiyor. İş arka planda hâlâ sürüyor olabilir; ` +
    "beklemeye devam edin veya iptal edin.";
}

/** What a terminal job should leave behind as the visible message, if anything. `completed`
 * clears whatever transient warning or error was showing for this same job; `failed` surfaces
 * the backend's own reason; `cancelled` needs no error at all -- the status line already says
 * it. This is what makes an authoritative `completed` response win over a stale local error for
 * the same job, rather than the two fighting over the same string. */
export function terminalMessage(job: Job): string {
  if (job.status === "failed") return job.error || "İş tamamlanamadı.";
  return "";
}
