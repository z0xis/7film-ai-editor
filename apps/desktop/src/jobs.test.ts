import { describe, expect, it } from "vitest";
import { Job } from "./api";
import {
  canCancel,
  healthWarning,
  isBusy,
  isTerminal,
  progressCount,
  stageLabel,
  statusLabel,
  statusLine,
  terminalMessage,
  visiblePercent,
} from "./jobs";

function job(overrides: Partial<Job> = {}): Job {
  return {
    id: "j1",
    kind: "shots",
    status: "running",
    progress: 0,
    ...overrides,
  };
}

describe("visiblePercent", () => {
  // Items 7, 8, 9 from the P3 acceptance list.
  it("renders 100 only for a completed job", () => {
    expect(visiblePercent(job({ status: "completed", progress: 1, overall_progress: 1 }))).toBe(100);
  });

  it("running 0.99 renders 99, never 100", () => {
    expect(visiblePercent(job({ status: "running", overall_progress: 0.99 }))).toBe(99);
  });

  it("a malformed running job reporting 1.0 is clamped to 99", () => {
    expect(visiblePercent(job({ status: "running", overall_progress: 1.0 }))).toBe(99);
  });

  it("0 renders as 0", () => {
    expect(visiblePercent(job({ status: "running", overall_progress: 0 }))).toBe(0);
  });

  it("a representative fraction renders as its rounded percentage", () => {
    expect(visiblePercent(job({ status: "running", overall_progress: 0.123 }))).toBe(12);
  });

  it("falls back to the legacy progress field when overall_progress is absent", () => {
    expect(visiblePercent(job({ status: "running", progress: 0.4, overall_progress: undefined }))).toBe(40);
  });

  it("never invents a percentage for NaN or missing data", () => {
    expect(visiblePercent(job({ status: "running", progress: NaN, overall_progress: undefined }))).toBe(0);
  });

  it("clamps a negative value to 0", () => {
    expect(visiblePercent(job({ status: "running", overall_progress: -0.2 }))).toBe(0);
  });
});

describe("isBusy / isTerminal", () => {
  it("queued is busy", () => expect(isBusy(job({ status: "queued" }))).toBe(true));
  it("running is busy", () => expect(isBusy(job({ status: "running" }))).toBe(true));
  it("cancel_requested is busy", () => expect(isBusy(job({ status: "cancel_requested" }))).toBe(true));
  it("completed is not busy", () => expect(isBusy(job({ status: "completed" }))).toBe(false));
  it("failed is not busy", () => expect(isBusy(job({ status: "failed" }))).toBe(false));
  it("cancelled is not busy", () => expect(isBusy(job({ status: "cancelled" }))).toBe(false));
  it("no job is not busy", () => expect(isBusy(null)).toBe(false));

  // The bug this guards against: a stale heartbeat used to flip `busy` to false on its own,
  // which would have re-enabled the start buttons on top of a job the backend still owned.
  it("a stalled but still-running job remains busy", () =>
    expect(isBusy(job({ status: "running", stalled: true }))).toBe(true));

  it("terminal statuses are exactly completed/failed/cancelled", () => {
    expect(isTerminal("completed")).toBe(true);
    expect(isTerminal("failed")).toBe(true);
    expect(isTerminal("cancelled")).toBe(true);
    expect(isTerminal("queued")).toBe(false);
    expect(isTerminal("running")).toBe(false);
    expect(isTerminal("cancel_requested")).toBe(false);
  });
});

describe("canCancel", () => {
  it("queued can be cancelled", () => expect(canCancel(job({ status: "queued" }))).toBe(true));
  it("running can be cancelled", () => expect(canCancel(job({ status: "running" }))).toBe(true));
  it("cancel_requested cannot be cancelled again", () =>
    expect(canCancel(job({ status: "cancel_requested" }))).toBe(false));
  it("completed cannot be cancelled", () => expect(canCancel(job({ status: "completed" }))).toBe(false));
  it("failed cannot be cancelled", () => expect(canCancel(job({ status: "failed" }))).toBe(false));
  it("cancelled cannot be cancelled", () => expect(canCancel(job({ status: "cancelled" }))).toBe(false));
  it("no job cannot be cancelled", () => expect(canCancel(null)).toBe(false));
});

describe("statusLabel / stageLabel / statusLine", () => {
  it("renders a Turkish label for every backend status", () => {
    expect(statusLabel("queued")).toBe("sırada");
    expect(statusLabel("running")).toBe("çalışıyor");
    expect(statusLabel("cancel_requested")).toBe("iptal ediliyor");
    expect(statusLabel("cancelled")).toBe("iptal edildi");
    expect(statusLabel("completed")).toBe("tamamlandı");
    expect(statusLabel("failed")).toBe("başarısız");
  });

  it("maps a shots stage to a human sentence", () => {
    expect(stageLabel(job({ kind: "shots", stage: "windows" }))).toBe("Shot anları ölçülüyor");
    expect(stageLabel(job({ kind: "shots", stage: "encode" }))).toBe("Görüntüler analiz ediliyor");
  });

  it("has no stage label for a non-shots job", () => {
    expect(stageLabel(job({ kind: "index", stage: "index" }))).toBeNull();
  });

  it("renders processed/total only when the backend sent a real count", () => {
    expect(progressCount(job({ processed: 813, total: 2638 }))).toBe("813/2638");
    expect(progressCount(job({ processed: null, total: null }))).toBeNull();
    expect(progressCount(job({ processed: 3, total: 0 }))).toBeNull();
  });

  it("composes kind, stage, percent and count into one line", () => {
    const line = statusLine(job({
      kind: "shots", status: "running", stage: "windows", overall_progress: 0.42,
      processed: 1100, total: 2638,
    }));
    expect(line).toContain("shots: çalışıyor");
    expect(line).toContain("Shot anları ölçülüyor");
    expect(line).toContain("%42");
    expect(line).toContain("1100/2638");
  });
});

describe("healthWarning", () => {
  // Items 10, 11 (in spirit — the render-level half of the stalled/health split).
  it("a healthy running job has no warning", () => {
    expect(healthWarning(job({ status: "running", stalled: false }))).toBeNull();
  });

  it("a stalled running job carries a warning, not an error", () => {
    const warning = healthWarning(job({ status: "running", stalled: true }));
    expect(warning).not.toBeNull();
    expect(warning).not.toMatch(/yeniden başlatabilirsiniz/i);
    expect(warning).not.toMatch(/tamamlanan kısım korunur/i);
  });

  it("a terminal job never shows a health warning, even if stalled is somehow true", () => {
    expect(healthWarning(job({ status: "completed", stalled: true }))).toBeNull();
    expect(healthWarning(job({ status: "failed", stalled: true }))).toBeNull();
    expect(healthWarning(job({ status: "cancelled", stalled: true }))).toBeNull();
  });
});

describe("terminalMessage — reconciliation", () => {
  it("completed clears any message for this job", () => {
    expect(terminalMessage(job({ status: "completed" }))).toBe("");
  });

  it("failed surfaces the backend's own reason", () => {
    expect(terminalMessage(job({ status: "failed", error: "ffprobe yok" }))).toBe("ffprobe yok");
  });

  it("a failed job with no reason still says something", () => {
    expect(terminalMessage(job({ status: "failed", error: null }))).toBe("İş tamamlanamadı.");
  });

  it("cancelled needs no error message", () => {
    expect(terminalMessage(job({ status: "cancelled" }))).toBe("");
  });
});

describe("unsupported resume wording is gone", () => {
  it("nothing in this module ever mentions resuming", () => {
    const everything = [
      healthWarning(job({ status: "running", stalled: true })),
      terminalMessage(job({ status: "failed", error: "x" })),
      statusLine(job({})),
    ].join(" ");
    expect(everything.toLowerCase()).not.toContain("yeniden başlat");
    expect(everything.toLowerCase()).not.toContain("resume");
  });
});
