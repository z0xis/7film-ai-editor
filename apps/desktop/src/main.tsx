import { FormEvent, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { api, CreateProject, Job, Project, Timeline } from "./api";
import "./styles.css";

type ResolveContext = {
  connected: boolean;
  product: string;
  version: string;
  projectName: string | null;
  timelineName: string | null;
};

type ResolveImportResult = { ok: boolean; timelineName: string; markerCount: number };

declare global {
  interface Window {
    resolveAPI?: {
      getContext: () => Promise<ResolveContext>;
      selectFolder: (title: string) => Promise<string | null>;
      selectMusic: () => Promise<string | null>;
      importTimeline: (timelineId: string, timelineName: string) => Promise<ResolveImportResult>;
      openPage: (pageName: string) => Promise<boolean>;
      cleanup: () => Promise<boolean>;
    };
  }
}

function Field({
  label,
  name,
  value,
  type = "text",
  min,
}: {
  label: string;
  name: string;
  value?: string;
  type?: string;
  min?: string;
}) {
  return <label>{label}<input required name={name} defaultValue={value} type={type} min={min} /></label>;
}

function PathField({
  label,
  name,
  value,
  onChange,
  picker,
}: {
  label: string;
  name: string;
  value: string;
  onChange: (value: string) => void;
  picker: "folder" | "music";
}) {
  async function browse() {
    if (!window.resolveAPI) return;
    const selected = picker === "folder"
      ? await window.resolveAPI.selectFolder(label)
      : await window.resolveAPI.selectMusic();
    if (selected) onChange(selected);
  }

  return (
    <label>
      {label}
      <span className="path-control">
        <input required name={name} value={value} onChange={(event) => onChange(event.target.value)} />
        {window.resolveAPI && <button type="button" className="browse-button" onClick={browse}>Finder’dan seç</button>}
      </span>
    </label>
  );
}

function App() {
  const [project, setProject] = useState<Project | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState("");
  const [timeline, setTimeline] = useState<Timeline | null>(null);
  const [exports, setExports] = useState<Record<string, string> | null>(null);
  const [resolveContext, setResolveContext] = useState<ResolveContext | null>(null);
  const [resolveMessage, setResolveMessage] = useState("");
  const [workspacePath, setWorkspacePath] = useState("");
  const [rawFolder, setRawFolder] = useState("");
  const [musicPath, setMusicPath] = useState("");

  useEffect(() => {
    api.projects().then(async (availableProjects) => {
      setProjects(availableProjects);
      const savedId = localStorage.getItem("sevenfilm.projectId");
      const selected = availableProjects.find(({ id }) => id === savedId) || availableProjects[0];
      if (selected) await openProject(selected);
    }).catch((cause) => setError(String(cause)));
    if (window.resolveAPI) {
      window.resolveAPI.getContext().then(setResolveContext).catch((cause) => setError(String(cause)));
    }
  }, []);

  async function openProject(selected: Project) {
    try {
      const detailedProject = await api.getProject(selected.id);
      localStorage.setItem("sevenfilm.projectId", detailedProject.id);
      setProject(detailedProject);
      setTimeline(await api.latestTimeline(detailedProject.id).catch(() => null));
      setError("");
    } catch (cause) { setError(String(cause)); }
  }

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try {
      const values = Object.fromEntries(new FormData(event.currentTarget));
      const payload: CreateProject = {
        name: String(values.name),
        workspace_path: String(values.workspace_path),
        target_duration_seconds: String(values.target_duration_seconds),
        frame_rate: String(values.frame_rate),
      };
      const newProject = await api.project(payload);
      localStorage.setItem("sevenfilm.projectId", newProject.id);
      setProject(newProject);
      setProjects((current) => [newProject, ...current]);
      setError("");
    } catch (cause) { setError(String(cause)); }
  }

  async function run(endpoint: string, payload?: object) {
    if (!project) return;
    try {
      const { job_id } = await api.startJob(project.id, endpoint, payload);
      for (;;) {
        const next = await api.job(job_id);
        setJob(next);
        if (next.status === "completed") break;
        if (next.status === "failed") throw new Error(next.error || "İş tamamlanamadı.");
        await new Promise((resolve) => setTimeout(resolve, 700));
      }
      setProject(await api.getProject(project.id));
    } catch (cause) { setError(String(cause)); }
  }

  async function build(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!project) return;
    try {
      setTimeline(await api.timeline(project.id, Object.fromEntries(new FormData(event.currentTarget))));
      setExports(null);
      setResolveMessage("");
    } catch (cause) { setError(String(cause)); }
  }

  async function sendToResolve() {
    if (!timeline || !window.resolveAPI) return;
    setResolveMessage("Resolve timeline’ı oluşturuluyor…");
    try {
      const result = await window.resolveAPI.importTimeline(timeline.id, timeline.name);
      setResolveMessage(`${result.timelineName} oluşturuldu · ${result.markerCount} açıklama marker’ı eklendi.`);
      setResolveContext(await window.resolveAPI.getContext());
    } catch (cause) {
      setResolveMessage("");
      setError(String(cause));
    }
  }

  return (
    <main>
      <div className="topline">
        <p className="eyebrow">LOCAL-FIRST ROUGH CUT ASSISTANT</p>
        {resolveContext && <span className="resolve-badge">Resolve {resolveContext.version} · {resolveContext.projectName || "proje açık değil"}</span>}
      </div>
      <h1>7Film AI Editor</h1>
      <p className="lede">Yerelde analiz et, müziğe hizala, Resolve’da düzenle.</p>

      {!project && (
        <section className="card">
          {projects.length > 0 && (
            <div className="existing-projects">
              <h2>Mevcut projeler</h2>
              <div className="project-list">
                {projects.map((availableProject) => (
                  <button type="button" className="project-choice" key={availableProject.id} onClick={() => openProject(availableProject)}>
                    <strong>{availableProject.name}</strong>
                    <span>{availableProject.target_duration_seconds} sn · {availableProject.frame_rate} FPS</span>
                  </button>
                ))}
              </div>
            </div>
          )}
          <h2>Yeni proje</h2>
          <form onSubmit={create}>
            <Field label="Proje adı" name="name" />
            <PathField label="Çalışma klasörü" name="workspace_path" value={workspacePath} onChange={setWorkspacePath} picker="folder" />
            <Field label="Hedef süre (sn)" name="target_duration_seconds" value="150" type="number" min="120" />
            <Field label="FPS" name="frame_rate" value="25/1" />
            <button>Proje oluştur</button>
          </form>
        </section>
      )}

      {project && (
        <>
          <section className="card">
            <div className="heading">
              <div><p className="eyebrow">AÇIK PROJE</p><h2>{project.name}</h2></div>
              <button className="secondary" onClick={() => { setTimeline(null); setProject(null); }}>Değiştir</button>
            </div>
            <div className="workflow">
              <form onSubmit={(event) => { event.preventDefault(); run("index", Object.fromEntries(new FormData(event.currentTarget))); }}>
                <PathField label="Ham video klasörü" name="folder" value={rawFolder} onChange={setRawFolder} picker="folder" /><button>1. İndeksle</button>
              </form>
              <form onSubmit={(event) => { event.preventDefault(); run("music", Object.fromEntries(new FormData(event.currentTarget))); }}>
                <PathField label="Müzik dosyası" name="path" value={musicPath} onChange={setMusicPath} picker="music" /><button>2. Müziği analiz et</button>
              </form>
              <div className="actions">
                <button onClick={() => run("shots")}>3. Shot’ları çıkar</button>
                <button className="secondary" onClick={() => run("derivatives")}>Proxy + thumbnail</button>
              </div>
              <form onSubmit={build}>
                <Field label="Alternatif seed" name="seed" type="number" value="1" /><button>4. Kaba kurgu oluştur</button>
              </form>
            </div>
          </section>
          <section className="card">
            <h2>Durum</h2>
            <pre>{error || resolveMessage || (job ? `${job.kind}: ${job.status} · ${Math.round(job.progress * 100)}%` : `${project.assets || 0} medya · ${project.shots || 0} shot · ${project.latest_music ? "müzik hazır" : "müzik bekleniyor"} · ${project.style_reference_count || 0} referans profili`)}</pre>
          </section>
        </>
      )}

      {timeline && (
        <section className="card">
          <div className="heading">
            <div><h2>Kurgu planı</h2><p>{timeline.items.length} klip · {timeline.actual_duration_seconds} sn · {timeline.frame_rate} FPS</p></div>
            <div className="timeline-actions">
              {window.resolveAPI && <button onClick={sendToResolve}>Resolve’a gönder</button>}
              <button className={window.resolveAPI ? "secondary" : ""} onClick={async () => setExports(await api.export(timeline.id))}>Dosya olarak dışa aktar</button>
            </div>
          </div>
          {timeline.warnings.map((warning) => <p className="warning" key={warning}>{warning}</p>)}
          <ol>{timeline.items.map((item, index) => <li key={`${item.source_path}-${index}`}><strong>{item.category} · {item.shot_scale} · {item.score.toFixed(3)}</strong><span>{item.clip_name}</span><small>{item.selection_reason}</small></li>)}</ol>
          {exports && <p className="exports">{Object.entries(exports).map(([kind, url]) => <a key={kind} href={url}>{kind.toUpperCase()} indir</a>)}</p>}
        </section>
      )}
    </main>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
