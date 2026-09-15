import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Job, Project } from "./api";

// The whole `api` module is mocked so these tests never touch a network or a real backend —
// see P3.12: no disposable backend job, no chance of touching the real project database.
vi.mock("./api", async () => {
  const actual = await vi.importActual<typeof import("./api")>("./api");
  return {
    ...actual,
    api: {
      projects: vi.fn(),
      project: vi.fn(),
      getProject: vi.fn(),
      latestTimeline: vi.fn(),
      startJob: vi.fn(),
      job: vi.fn(),
      latestJob: vi.fn(),
      cancel: vi.fn(),
      timeline: vi.fn(),
      export: vi.fn(),
      rejections: vi.fn(),
      reject: vi.fn(),
      restore: vi.fn(),
    },
  };
});

import { api } from "./api";
import { App } from "./main";

const mocked = api as unknown as Record<string, ReturnType<typeof vi.fn>>;

function project(overrides: Partial<Project> = {}): Project {
  return {
    id: "proj-a", name: "Proje A", workspace_path: "/tmp/a",
    target_duration_seconds: "150", frame_rate: "25/1",
    assets: 10, shots: 100, latest_music: true, style_reference_count: 0,
    ...overrides,
  };
}

function job(overrides: Partial<Job> = {}): Job {
  return {
    id: "job-1", kind: "shots", status: "running", progress: 0.4,
    overall_progress: 0.4, stalled: false,
    ...overrides,
  };
}

function stubBaseline(activeProject: Project, latest: Job | null) {
  mocked.projects.mockResolvedValue([activeProject]);
  mocked.getProject.mockResolvedValue(activeProject);
  mocked.latestTimeline.mockRejectedValue(new Error("no timeline"));
  mocked.latestJob.mockImplementation(() =>
    latest ? Promise.resolve(latest) : Promise.reject(new Error("no job")));
  mocked.rejections.mockResolvedValue({ clips: [] });
}

// Real timers, not fake ones: `follow`'s 700ms poll interval is short enough to just let run in
// real time, and React Testing Library's own `waitFor` polling does not reliably cooperate with
// fake timers. Each test below budgets a generous `waitFor` timeout instead.
beforeEach(() => {
  localStorage.clear();
  Object.values(mocked).forEach((fn) => fn.mockReset());
});

// Explicit, not relied on implicitly: without this, a previous test's `App` instance stays
// mounted (and its background `follow` poll loop keeps running, against mocks the *next* test
// has already reset) for the rest of the suite — see the `mounted` ref this exact leak led to
// adding in main.tsx itself.
afterEach(() => {
  cleanup();
});

describe("P3 production regression — stale derivatives error", () => {
  it("a stalled-then-completed job clears the warning, stops erroring, and un-busies the UI", async () => {
    const proj = project();
    stubBaseline(proj, job({ kind: "derivatives", status: "running", stalled: true }));
    mocked.job
      .mockResolvedValueOnce(job({ kind: "derivatives", status: "running", stalled: true }))
      .mockResolvedValueOnce(job({ kind: "derivatives", status: "completed", overall_progress: 1, stalled: false }));

    render(<App />);
    await waitFor(() => expect(screen.getByText("Proje A")).toBeInTheDocument());

    // Reattaches to the still-running (but stalled) job on open, and shows a warning for it —
    // not an error, and the workflow buttons stay disabled because the backend still owns it.
    await waitFor(() => expect(screen.getByText(/yanıt vermiyor/)).toBeInTheDocument());
    expect(screen.queryByText(/tamamlanamadı/)).not.toBeInTheDocument();
    expect(screen.getByText(/1\. İndeksle/).closest("button")).toBeDisabled();

    // The exact regression: this used to throw on `stalled` and never poll again. It must
    // poll again, and the authoritative `completed` response must win over the stale warning.
    await waitFor(() => expect(screen.getByText(/tamamlandı/)).toBeInTheDocument(), { timeout: 3000 });
    expect(screen.queryByText(/yanıt vermiyor/)).not.toBeInTheDocument();
    expect(screen.getByText(/1\. İndeksle/).closest("button")).not.toBeDisabled();
  }, 10000);
});

describe("P3 production regression — shots false 100%", () => {
  it("a running job at overall_progress 0.99 never shows 100%, and clears once healthy", async () => {
    const proj = project();
    stubBaseline(proj, job({ kind: "shots", status: "running", overall_progress: 0.99, stalled: true }));
    mocked.job
      .mockResolvedValueOnce(job({ kind: "shots", status: "running", overall_progress: 0.99, stalled: true }))
      .mockResolvedValueOnce(job({ kind: "shots", status: "running", overall_progress: 0.995, stalled: false }));

    render(<App />);
    await waitFor(() => expect(screen.getByText(/%99/)).toBeInTheDocument());
    expect(screen.queryByText(/%100/)).not.toBeInTheDocument();

    await waitFor(() => expect(screen.queryByText(/yanıt vermiyor/)).not.toBeInTheDocument(),
      { timeout: 3000 });
    // Still not completed, so still not 100 — even though the backend value rounds high.
    expect(screen.queryByText(/%100/)).not.toBeInTheDocument();
  }, 10000);
});

describe("P3 project isolation — late async responses", () => {
  it("a late poll response for project A cannot overwrite project B after the user switches", async () => {
    const projA = project({ id: "proj-a", name: "Proje A" });
    const projB = project({ id: "proj-b", name: "Proje B" });
    mocked.projects.mockResolvedValue([projA, projB]);
    mocked.latestTimeline.mockRejectedValue(new Error("no timeline"));
    mocked.rejections.mockResolvedValue({ clips: [] });

    // Project A's own job poll is held open deliberately, to resolve *after* the switch.
    let resolveLateA: (value: Job) => void = () => undefined;
    const lateA = new Promise<Job>((resolve) => { resolveLateA = resolve; });

    mocked.getProject.mockImplementation((id: string) => Promise.resolve(id === "proj-a" ? projA : projB));
    mocked.latestJob.mockImplementation((id: string) =>
      id === "proj-a" ? Promise.resolve(job({ id: "job-a", status: "running" })) : Promise.reject(new Error("none")));
    mocked.job.mockImplementation((jobId: string) => (jobId === "job-a" ? lateA : Promise.reject(new Error("unexpected"))));

    render(<App />);
    await waitFor(() => expect(screen.getByText("Proje A")).toBeInTheDocument());
    // The poll for project A's job is now in flight (awaiting `lateA`).

    // The user switches away before that poll resolves.
    screen.getByText("Değiştir").click();
    await waitFor(() => expect(screen.getByText("Proje B")).not.toBeNull());
    const openProjectB = screen.getAllByText("Proje B")[0].closest("button")!;
    openProjectB.click();
    await waitFor(() => expect(screen.getByText(/proje bekleniyor|referans profili/)).toBeInTheDocument());

    // Now the stale project-A response resolves, long after the switch.
    resolveLateA(job({ id: "job-a", kind: "shots", status: "failed", error: "kaynak bulunamadı" }));
    // Give the stale promise's `.then` chain a real turn to run, then assert it changed nothing.
    await new Promise((resolve) => setTimeout(resolve, 50));

    // Project B's UI must show no trace of project A's late failure.
    expect(screen.queryByText(/kaynak bulunamadı/)).not.toBeInTheDocument();
    expect(screen.getByText("Proje B")).toBeInTheDocument();
  }, 10000);
});

describe("P3 cancel UX", () => {
  it("shows Cancel for a running job, calls the backend, and reflects cancel_requested", async () => {
    const proj = project();
    stubBaseline(proj, job({ status: "running" }));
    mocked.cancel.mockResolvedValue(job({ status: "cancel_requested" }));
    // The background poll's *first* tick must still see "running" -- only after the click
    // does the backend (and so the next poll) know about the cancel request.
    mocked.job
      .mockResolvedValueOnce(job({ status: "running" }))
      .mockResolvedValue(job({ status: "cancel_requested" }));

    render(<App />);
    await waitFor(() => expect(screen.getByText("İptal et")).toBeInTheDocument());

    screen.getByText("İptal et").click();
    await waitFor(() => expect(mocked.cancel).toHaveBeenCalledWith("job-1"));
    await waitFor(() => expect(screen.getByText(/iptal ediliyor/)).toBeInTheDocument());
    // Not cancelled yet -- cooperative, and the button must not claim it already happened.
    expect(screen.queryByText("İptal et")).not.toBeInTheDocument();
  });

  it("terminal jobs show no Cancel action", async () => {
    const proj = project();
    stubBaseline(proj, null);
    render(<App />);
    await waitFor(() => expect(screen.getByText("Proje A")).toBeInTheDocument());
    expect(screen.queryByText("İptal et")).not.toBeInTheDocument();
  });

  it("a failed cancel request leaves the job's visible state unchanged", async () => {
    const proj = project();
    stubBaseline(proj, job({ status: "running" }));
    mocked.cancel.mockRejectedValue(new Error("job bulunamadı"));
    mocked.job.mockResolvedValue(job({ status: "running" }));

    render(<App />);
    await waitFor(() => expect(screen.getByText("İptal et")).toBeInTheDocument());
    screen.getByText("İptal et").click();
    await waitFor(() => expect(screen.getByText(/job bulunamadı/)).toBeInTheDocument());
    // Still shows Cancel -- the job was never locally marked cancelled.
    expect(screen.getByText("İptal et")).toBeInTheDocument();
  });
});

describe("P3 wording audit", () => {
  it("never promises a resume/restart capability that does not exist", async () => {
    const proj = project();
    stubBaseline(proj, job({ status: "running", stalled: true }));
    mocked.job.mockResolvedValue(job({ status: "running", stalled: true }));

    render(<App />);
    await waitFor(() => expect(screen.getByText(/yanıt vermiyor/)).toBeInTheDocument());
    expect(document.body.textContent).not.toMatch(/yeniden başlatabilirsiniz/i);
    expect(document.body.textContent).not.toMatch(/tamamlanan kısım korunur/i);
  });
});

describe("P3 regression — 7d261b5 ticket guard still holds", () => {
  // This package did not touch `openProject`/`create`'s own ticket logic, only reused the same
  // `projectSelection` ref inside `follow`/`run`/`cancelJob` — but a background poll left over
  // from before a project switch is exactly the kind of "late response" this guard exists for,
  // so it is worth proving the original invariant survives sitting beside the new one.
  it("a page-load project restore that resolves after a manual open does not win", async () => {
    const projA = project({ id: "proj-a", name: "Proje A" });
    const projB = project({ id: "proj-b", name: "Proje B" });
    localStorage.setItem("sevenfilm.projectId", "proj-a");
    mocked.projects.mockResolvedValue([projA, projB]);
    mocked.latestTimeline.mockRejectedValue(new Error("no timeline"));
    mocked.latestJob.mockRejectedValue(new Error("no job"));
    mocked.rejections.mockResolvedValue({ clips: [] });

    // The page-load restore of project A is held open, to resolve *after* B is opened by hand.
    let resolveA: (value: Project) => void = () => undefined;
    const lateA = new Promise<Project>((resolve) => { resolveA = resolve; });
    mocked.getProject.mockImplementation((id: string) => (id === "proj-a" ? lateA : Promise.resolve(projB)));

    render(<App />);
    await waitFor(() => expect(mocked.getProject).toHaveBeenCalledWith("proj-a"));

    // The user opens B by hand before A's restore has resolved.
    const openB = await screen.findAllByText("Proje B");
    openB[0].closest("button")!.click();
    await waitFor(() => expect(screen.getByText("Proje B")).toBeInTheDocument());

    // Now the stale page-load restore of A resolves.
    resolveA(projA);
    await new Promise((resolve) => setTimeout(resolve, 50));

    expect(screen.getByText("Proje B")).toBeInTheDocument();
    expect(screen.queryByText("Proje A")).not.toBeInTheDocument();
  }, 10000);
});
