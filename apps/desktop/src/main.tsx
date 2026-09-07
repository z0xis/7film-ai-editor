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

/**
 * The songs an edit is cut to, in the order they play. One song is the common case and stays a
 * single row; a second turns the opening into a slow passage and hands the party its own track,
 * with the change falling where the story arc turns.
 */
function SongList({
  songs,
  onChange,
  disabled,
}: {
  songs: string[];
  onChange: (songs: string[]) => void;
  disabled: boolean;
}) {
  const replace = (index: number, value: string) =>
    onChange(songs.map((song, position) => (position === index ? value : song)));

  async function browse(index: number) {
    if (!window.resolveAPI) return;
    const selected = await window.resolveAPI.selectMusic();
    if (selected) replace(index, selected);
  }

  return (
    <div className="song-list">
      <span className="song-list-label">
        {songs.length > 1 ? `Şarkılar (${songs.length}, sırayla çalar)` : "Müzik dosyası"}
      </span>
      {songs.map((song, index) => (
        <span className="path-control" key={index}>
          {songs.length > 1 && <span className="song-order">{index + 1}</span>}
          <input
            required
            value={song}
            onChange={(event) => replace(index, event.target.value)}
            placeholder={index === 0 ? "Açılış şarkısı" : "Sonraki şarkı"}
          />
          {window.resolveAPI && (
            <button type="button" className="browse-button" onClick={() => browse(index)}>
              Finder’dan seç
            </button>
          )}
          {songs.length > 1 && (
            <button
              type="button"
              className="browse-button"
              title="Bu şarkıyı çıkar"
              onClick={() => onChange(songs.filter((_, position) => position !== index))}
            >
              ×
            </button>
          )}
        </span>
      ))}
      <button
        type="button"
        className="secondary"
        disabled={disabled}
        onClick={() => onChange([...songs, ""])}
      >
        + Şarkı ekle
      </button>
    </div>
  );
}

/** When this plan was built, in the editor's own clock. */
function builtAt(value: string): string {
  const when = new Date(value);
  if (Number.isNaN(when.getTime())) return "";
  const today = when.toDateString() === new Date().toDateString();
  const time = when.toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit" });
  return today ? `${time}'de kuruldu` : `${when.toLocaleDateString("tr-TR")} ${time}`;
}

/** A stale analysis looks like a finished one, and quietly cuts the edit wrong. */
function staleWarning(project: Project): string | null {
  const stale = project.stale_analysis;
  if (!stale) return null;
  const parts: string[] = [];
  if (stale.shots) parts.push("shot analizi");
  if (stale.music) parts.push("müzik analizi");
  if (!parts.length) return null;
  return `${parts.join(" ve ")} eski sürümle yapılmış — kurgu kalitesi için yeniden çalıştırın.`;
}


function RejectList({ projectId, disabled }: { projectId: string; disabled: boolean }) {
  const [clips, setClips] = useState<string[]>([]);
  const [entry, setEntry] = useState("");
  const [note, setNote] = useState("");

  useEffect(() => {
    api.rejections(projectId).then((result) => setClips(result.clips)).catch(() => undefined);
  }, [projectId]);

  async function add(event: FormEvent) {
    event.preventDefault();
    const names = entry.split(/[\s,]+/).filter(Boolean);
    if (!names.length) return;
    try {
      const result = await api.reject(projectId, names);
      setClips(result.clips);
      setEntry("");
      // A typo should say so rather than quietly losing the names beside it that were right.
      setNote(result.unknown?.length ? `bu projede yok: ${result.unknown.join(", ")}` : "");
    } catch (error) {
      setNote(error instanceof Error ? error.message : String(error));
    }
  }

  async function restore(name: string) {
    try {
      setClips((await api.restore(projectId, [name])).clips);
    } catch (error) {
      setNote(error instanceof Error ? error.message : String(error));
    }
  }

  return (
    <div className="reject-list">
      <form onSubmit={add}>
        <span className="song-list-label">Kullanılmasın</span>
        <span className="path-control">
          <input
            value={entry}
            onChange={(event) => setEntry(event.target.value)}
            placeholder="C1968, C2181"
            disabled={disabled}
          />
          <button disabled={disabled || !entry.trim()}>Ekle</button>
        </span>
      </form>
      <p className="reject-hint">
        Resolve’da beğenmediğiniz klibin adını yazın; bundan sonraki hiçbir kurguya girmez.
      </p>
      {note && <p className="reject-note">{note}</p>}
      {clips.length > 0 && (
        <ul className="reject-clips">
          {clips.map((name) => (
            <li key={name}>
              <span>{name}</span>
              <button type="button" className="link" onClick={() => restore(name)}>geri al</button>
            </li>
          ))}
        </ul>
      )}
    </div>
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
  const [songs, setSongs] = useState<string[]>([""]);

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
      // Show the running order back, so re-analysing does not silently drop the second song.
      setSongs(detailedProject.music_paths?.length ? detailedProject.music_paths : [""]);
      setTimeline(await api.latestTimeline(detailedProject.id).catch(() => null));
      setError("");
      const running = await api.latestJob(detailedProject.id).catch(() => null);
      setJob(running && !running.stalled && running.status !== "completed" ? running : null);
    } catch (cause) { setError(String(cause)); }
  }

  const busy = job !== null && (job.status === "queued" || job.status === "running") && !job.stalled;

  useEffect(() => {
    if (project && busy) follow(job!.id);
    // Only re-attach when the project changes, not on every progress tick.
  }, [project?.id]);

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

  /** Follow a job to its end. Shot analysis runs for tens of minutes, so this has to survive
   *  a reload: the job is found again from the project rather than remembered in this tab. */
  async function follow(jobId: string) {
    if (!project) return;
    try {
      for (;;) {
        const next = await api.job(jobId);
        setJob(next);
        if (next.status === "completed") break;
        if (next.status === "failed") throw new Error(next.error || "İş tamamlanamadı.");
        if (next.stalled) throw new Error(
          `${next.kind}: iş yanıt vermiyor, ilerleme %${Math.round(next.progress * 100)}'te durdu. ` +
          "Yeniden başlatabilirsiniz; tamamlanan kısım korunur.");
        await new Promise((resolve) => setTimeout(resolve, 700));
      }
      setProject(await api.getProject(project.id));
    } catch (cause) { setError(String(cause)); }
  }

  async function run(endpoint: string, payload?: object) {
    if (!project || busy) return;
    try {
      const { job_id } = await api.startJob(project.id, endpoint, payload);
      await follow(job_id);
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
                <PathField label="Ham video klasörü" name="folder" value={rawFolder} onChange={setRawFolder} picker="folder" /><button disabled={busy}>1. İndeksle</button>
              </form>
              <form onSubmit={(event) => { event.preventDefault(); run("music", { paths: songs.map((song) => song.trim()).filter(Boolean) }); }}>
                <SongList songs={songs} onChange={setSongs} disabled={busy} />
                <button disabled={busy || !songs.some((song) => song.trim())}>2. Müziği analiz et</button>
              </form>
              <div className="actions">
                <button disabled={busy} onClick={() => run("shots")}>3. Shot’ları çıkar</button>
                <button className="secondary" disabled={busy} onClick={() => run("derivatives")}>Proxy + thumbnail</button>
              </div>
              <RejectList projectId={project.id} disabled={busy} />
              <form onSubmit={build}>
                <Field label="Alternatif seed" name="seed" type="number" value="1" /><button>4. Kaba kurgu oluştur</button>
              </form>
            </div>
          </section>
          <section className="card">
            <h2>Durum</h2>
            <pre>{error || resolveMessage || (job ? `${job.kind}: ${job.status} · ${Math.round(job.progress * 100)}%` : `${project.assets || 0} medya · ${project.shots || 0} shot · ${project.latest_music ? "müzik hazır" : "müzik bekleniyor"} · ${project.style_reference_count || 0} referans profili`)}</pre>
            {staleWarning(project) && <p className="stale-analysis">{staleWarning(project)}</p>}
          </section>
        </>
      )}

      {timeline && (
        <section className="card">
          <div className="heading">
            <div>
              <h2>Kurgu planı</h2>
              <p>
                {timeline.items.length} klip · {timeline.actual_duration_seconds} sn · {timeline.frame_rate} FPS
                {/* An edit built minutes ago and one from this morning look identical without
                    this, and "Resolve'a gönder" sends whatever the panel is holding. */}
                {timeline.created_at && <> · {builtAt(timeline.created_at)}</>}
              </p>
            </div>
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
