// 7Film AI Editor — DaVinci Resolve Workflow Integration main process.
// The native bridge is copied from Resolve's own Developer examples at install time.

const { app, BrowserWindow, dialog, ipcMain } = require("electron");
const { spawn } = require("child_process");
const crypto = require("crypto");
const fs = require("fs");
const http = require("http");
const path = require("path");
const WorkflowIntegration = require("./WorkflowIntegration.node");
const {
  appendClipsInBatches,
  buildMusicClipInfos,
  buildVideoClipInfos,
  frameRatesAgree,
  closingFadeFrames,
  hasRetiming,
  monitorFormatForRate,
  parseFrameRate,
  musicSegments,
  resolveFrameRateSetting,
} = require("./timeline-builder");

const PLUGIN_ID = "com.sevenfilm.ai.editor";
// Must match apps/api/sevenfilm/api.py. ensureBackend will not reuse an engine that reports a
// different version, which is what stops a process from an earlier release serving the app.
const ENGINE_VERSION = "0.4.0";
const BACKEND_PORTS = [17865, 17866, 17867, 17868, 17869];
const APP_ROOT_LINK = path.join(__dirname, "app-root");

let mainWindow = null;
let backendProcess = null;
let backendOrigin = `http://127.0.0.1:${BACKEND_PORTS[0]}`;
let resolveObject = null;
let initialized = false;

function applicationRoot() {
  if (!fs.existsSync(APP_ROOT_LINK)) {
    throw new Error("7Film uygulama bağlantısı bulunamadı. Eklentiyi yeniden kurun.");
  }
  return fs.realpathSync(APP_ROOT_LINK);
}

function request(method, route, origin = backendOrigin) {
  return new Promise((resolve, reject) => {
    const target = new URL(route, origin);
    const req = http.request(target, { method, timeout: 10000 }, (response) => {
      const chunks = [];
      response.on("data", (chunk) => chunks.push(chunk));
      response.on("end", () => {
        const body = Buffer.concat(chunks);
        if (response.statusCode < 200 || response.statusCode >= 300) {
          reject(new Error(`7Film API ${response.statusCode}: ${body.toString("utf8")}`));
          return;
        }
        resolve({ body, headers: response.headers });
      });
    });
    req.on("timeout", () => req.destroy(new Error("7Film API zaman aşımı")));
    req.on("error", reject);
    req.end();
  });
}

async function requestJson(method, route, origin = backendOrigin) {
  const response = await request(method, route, origin);
  return JSON.parse(response.body.toString("utf8"));
}

async function backendHealth(origin) {
  try {
    return await requestJson("GET", "/api/health", origin);
  } catch (_error) {
    return null;
  }
}

/**
 * The same digest apps/api/sevenfilm/api.py computes over its own source: every .py under the
 * package, sorted by path, each contributing "relative path\0contents\0". A running engine
 * serves the modules it imported at startup, so without this an edit is cut by whatever the
 * code was when the process began — which is how a planner change made at 02:34 never reached
 * an edit built at 07:50 by an engine started at 02:05.
 */
function sourceFingerprint(root) {
  const packageRoot = path.join(root, "apps", "api", "sevenfilm");
  const files = [];
  const walk = (directory) => {
    for (const entry of fs.readdirSync(directory, { withFileTypes: true }).sort((a, b) => (a.name < b.name ? -1 : 1))) {
      const full = path.join(directory, entry.name);
      if (entry.isDirectory()) walk(full);
      else if (entry.name.endsWith(".py")) files.push(full);
    }
  };
  try {
    walk(packageRoot);
  } catch (_error) {
    return null;
  }
  const digest = crypto.createHash("sha256");
  for (const file of files.sort((a, b) => (path.relative(packageRoot, a) < path.relative(packageRoot, b) ? -1 : 1))) {
    digest.update(path.relative(packageRoot, file).split(path.sep).join("/"));
    digest.update(Buffer.from([0]));
    digest.update(fs.readFileSync(file));
    digest.update(Buffer.from([0]));
  }
  return digest.digest("hex").slice(0, 16);
}

async function ensureBackend() {
  const wanted = sourceFingerprint(applicationRoot());
  let availableOrigin = null;
  for (const port of BACKEND_PORTS) {
    const origin = `http://127.0.0.1:${port}`;
    const health = await backendHealth(origin);
    const current = health?.status === "ok"
      && health?.engine_version === ENGINE_VERSION
      && (wanted === null || health?.source_fingerprint === wanted);
    if (current) {
      backendOrigin = origin;
      return;
    }
    if (health === null && availableOrigin === null) availableOrigin = origin;
  }
  if (!availableOrigin) {
    throw new Error("7Film analiz motoru için boş yerel port bulunamadı.");
  }
  backendOrigin = availableOrigin;
  const root = applicationRoot();
  const launcher = path.join(root, "scripts", "run_app.sh");
  const backendPort = new URL(backendOrigin).port;
  // The engine's output used to go to /dev/null, so when a request failed there was nothing
  // anywhere to say why — not the status code, not the traceback. Keeping it costs a file.
  const logPath = path.join(root, "data", "engine.log");
  fs.mkdirSync(path.dirname(logPath), { recursive: true });
  const logFile = fs.openSync(logPath, "a");
  fs.writeSync(logFile, `\n=== ${new Date().toISOString()} · eklenti ${ENGINE_VERSION} motoru başlatıyor ===\n`);
  backendProcess = spawn(launcher, [], {
    cwd: root,
    env: { ...process.env, SEVENFILM_PLUGIN: "1", SEVENFILM_PORT: backendPort },
    stdio: ["ignore", logFile, logFile],
  });
  backendProcess.on("exit", () => { backendProcess = null; });
  let mismatched = null;
  for (let attempt = 0; attempt < 40; attempt += 1) {
    const health = await backendHealth(backendOrigin);
    if (health?.status === "ok") {
      if (health.engine_version === ENGINE_VERSION
        && (wanted === null || health.source_fingerprint === wanted)) return;
      mismatched = health.engine_version;
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  // An engine that answers with the wrong version is a plugin that was not reinstalled after
  // the code moved: this copy is installed under Workflow Integration Plugins and does not
  // change when the repository does. Waiting twenty seconds and reporting "did not start" sent
  // the user looking for a backend that was running the whole time.
  if (mismatched) {
    throw new Error(
      `7Film eklentisi ${ENGINE_VERSION} bekliyor, çalışan motor ${mismatched} bildiriyor. `
      + "scripts/install_resolve_plugin.sh çalıştırıp Resolve'u yeniden başlatın.",
    );
  }
  throw new Error("7Film analiz motoru 20 saniye içinde başlamadı.");
}

async function getResolve() {
  if (resolveObject) return resolveObject;
  if (!initialized) {
    initialized = await WorkflowIntegration.InitializePromise(PLUGIN_ID);
    if (!initialized) throw new Error("Resolve Workflow Integration başlatılamadı.");
  }
  resolveObject = await WorkflowIntegration.GetResolvePromise();
  if (!resolveObject) throw new Error("DaVinci Resolve API nesnesi alınamadı.");
  return resolveObject;
}

async function currentProject() {
  const resolve = await getResolve();
  const manager = await resolve.GetProjectManager();
  const project = manager ? await manager.GetCurrentProject() : null;
  return { resolve, manager, project };
}

async function getContext() {
  const { resolve, project } = await currentProject();
  const timeline = project ? await project.GetCurrentTimeline() : null;
  return {
    connected: true,
    product: await resolve.GetProductName(),
    version: await resolve.GetVersionString(),
    projectName: project ? await project.GetName() : null,
    timelineName: timeline ? await timeline.GetName() : null,
  };
}

async function downloadExport(route, destination) {
  const response = await request("GET", route);
  fs.mkdirSync(path.dirname(destination), { recursive: true });
  fs.writeFileSync(destination, response.body);
  return destination;
}

// An audio media pool item reports Frames, Start and End as empty strings, so its length is
// unknown here and comes from the plan instead.
async function frameCountOf(mediaPoolItem) {
  const properties = await mediaPoolItem.GetClipProperty();
  const frames = Number(properties?.Frames);
  return Number.isFinite(frames) && frames >= 1 ? Math.floor(frames) : null;
}

async function resolveMediaPool(mediaPool, poolPaths) {
  const itemByPath = new Map();
  const currentFolder = await mediaPool.GetCurrentFolder();
  const existingItems = currentFolder ? await currentFolder.GetClipList() : [];
  for (const mediaPoolItem of existingItems || []) {
    const properties = await mediaPoolItem.GetClipProperty();
    const filePath = properties?.["File Path"];
    if (filePath) itemByPath.set(path.resolve(filePath), mediaPoolItem);
  }
  const missingPaths = poolPaths.filter((sourcePath) => !itemByPath.has(path.resolve(sourcePath)));
  const importedItems = missingPaths.length ? await mediaPool.ImportMedia(missingPaths) : [];
  for (let index = 0; index < (importedItems || []).length; index += 1) {
    const mediaPoolItem = importedItems[index];
    const properties = await mediaPoolItem.GetClipProperty();
    const filePath = properties?.["File Path"];
    itemByPath.set(path.resolve(filePath || missingPaths[index]), mediaPoolItem);
  }
  const unresolved = poolPaths.filter((sourcePath) => !itemByPath.has(path.resolve(sourcePath)));
  if (unresolved.length) {
    throw new Error(`Resolve Media Pool aktarımı tamamlanamadı: ${unresolved.length} dosya bulunamadı.`);
  }
  const media = new Map();
  for (const sourcePath of poolPaths) {
    const key = path.resolve(sourcePath);
    const mediaPoolItem = itemByPath.get(key);
    media.set(key, { mediaPoolItem, frameCount: await frameCountOf(mediaPoolItem) });
  }
  return media;
}

/**
 * Point each clip at its proxy, where one has been made.
 *
 * This footage is 4K 10 bit 4:2:2 H.264 at 141 Mbit/s, which no hardware decoder on this
 * machine touches, so a cut every second stops playback dead. Resolve plays a linked proxy
 * instead. LinkProxyMedia is strict about what it will accept — a proxy without the source's
 * audio and start timecode is refused outright, measured — so a refusal is reported rather
 * than passed over: a proxy nobody can use is worse than none, because it looks like one.
 */
async function linkProxies(media, items) {
  let linked = 0;
  const refused = [];
  const seen = new Set();
  for (const item of items || []) {
    const proxyPath = item?.proxy_path ? String(item.proxy_path) : null;
    const sourcePath = item?.source_path ? path.resolve(String(item.source_path)) : null;
    if (!proxyPath || !sourcePath || seen.has(sourcePath)) continue;
    seen.add(sourcePath);
    const mediaPoolItem = media.get(sourcePath)?.mediaPoolItem;
    if (!mediaPoolItem || !fs.existsSync(proxyPath)) continue;
    if (await mediaPoolItem.LinkProxyMedia(proxyPath)) linked += 1;
    else refused.push(path.basename(proxyPath));
  }
  if (refused.length) {
    console.warn(`7Film: ${refused.length} proxy Resolve tarafından kabul edilmedi: ${refused.slice(0, 3).join(", ")}`);
  }
  return { linked, refused };
}

// Blueprint track layout for the Resolve adapter: A1 Music, A2 sync audio / ambience,
// A3 voice / vows / speeches. The rough cut only fills A1; A2 and A3 stay empty so the
// editor can drop camera audio and speeches in without rebuilding the timeline.
const MUSIC_TRACK_INDEX = 1;
const AUDIO_TRACK_COUNT = 3;

async function ensureAudioTracks(timeline, wanted) {
  let count = Number(await timeline.GetTrackCount("audio")) || 0;
  while (count < wanted) {
    if (!(await timeline.AddTrack("audio", "stereo"))) break;
    count += 1;
  }
  return count;
}

async function appendMusic(mediaPool, timeline, plan, media) {
  const segments = musicSegments(plan);
  if (!segments.length) return false;
  const audioTracks = await ensureAudioTracks(timeline, AUDIO_TRACK_COUNT);
  if (audioTracks < MUSIC_TRACK_INDEX) throw new Error("Resolve timeline'ında müzik için audio track açılamadı.");
  const timelineStart = Number(await timeline.GetStartFrame()) || 0;
  const { clipInfos, missing } = buildMusicClipInfos({
    plan,
    lookup: (musicPath) => media.get(path.resolve(musicPath))?.mediaPoolItem,
    timelineStart,
    trackIndex: MUSIC_TRACK_INDEX,
  });
  if (missing.length) throw new Error(`Müzik Media Pool öğesi bulunamadı: ${missing.join(", ")}`);
  if (!clipInfos.length) throw new Error("Müzik süresi hesaplanamadı; Resolve timeline'ına eklenemedi.");
  const audioItems = await mediaPool.AppendToTimeline(clipInfos);
  // AppendToTimeline drops invalid items and keeps the rest, so the count is the check.
  if (!audioItems || audioItems.length !== clipInfos.length) {
    throw new Error(`Müzik Resolve timeline'ına eklenemedi (${audioItems?.length || 0}/${clipInfos.length}).`);
  }
  return true;
}

async function createTimelineFromPlan(mediaPool, project, plan, timelineName) {
  const sourcePaths = [...new Set((plan.items || []).map((item) => String(item.source_path)))];
  const songPaths = musicSegments(plan).map((segment) => segment.path);
  const poolPaths = [...new Set([...sourcePaths, ...songPaths])];
  const media = await resolveMediaPool(mediaPool, poolPaths);
  const proxies = await linkProxies(media, plan.items);
  if (proxies.linked) console.log(`7Film: ${proxies.linked} klip proxy'ye bağlandı.`);

  const { clipInfos, labels, dropped } = buildVideoClipInfos(
    plan.items || [],
    (sourcePath) => media.get(path.resolve(sourcePath)),
  );
  if (!clipInfos.length) throw new Error("Kurgu planında video klibi bulunamadı.");
  if (dropped.length) {
    console.warn(`7Film: ${dropped.length} klip tek kare uzunluğunda kalacağı için atlandı.`);
  }
  // A plan is a list of frame numbers. Laid into a timeline running at another rate, every
  // clip lands at the wrong place: the user's project was at 24 fps and the plan at 50, and
  // the timeline came out with 114 clips, 113 gaps and 3837 frames of black between them.
  const wantedRate = plan.frame_rate;
  const currentRate = await project.GetSetting("timelineFrameRate");
  if (!frameRatesAgree(currentRate, wantedRate)) {
    const setting = resolveFrameRateSetting(wantedRate);
    const changed = setting ? await project.SetSetting("timelineFrameRate", setting) : false;
    const nowRate = changed ? await project.GetSetting("timelineFrameRate") : currentRate;
    if (!frameRatesAgree(nowRate, wantedRate)) {
      throw new Error(
        `Resolve projesi ${currentRate} fps, kurgu ${setting || wantedRate} fps. `
        + "Resolve bu ayarı yalnızca timeline'ı olmayan projede değiştirebiliyor: "
        + "yeni bir proje açıp tekrar gönderin.",
      );
    }
  }
  const suffix = new Date().toISOString().slice(11, 19).replaceAll(":", "");
  // CreateTimelineFromClips ignores mediaType and pulls the camera audio of every source clip
  // onto A1; AppendToTimeline honours it. Verified against Resolve Studio 21.0.2: the first
  // builds a timeline with an audio clip per source, the second lays down picture only.
  const timeline = await mediaPool.CreateEmptyTimeline(`${timelineName} · ${suffix}`);
  if (!timeline) throw new Error("Resolve video timeline'ını oluşturamadı.");
  await project.SetCurrentTimeline(timeline);
  await appendClipsInBatches({ mediaPool, clipInfos, labels });
  await applySpeeds(timeline, clipInfos);

  await appendMusic(mediaPool, timeline, plan, media);
  return timeline;
}

/**
 * Slow the clips the edit asked to be slowed.
 *
 * Before 21.1 this was impossible through the API — SetProperty offered pan, tilt, zoom, crop
 * and the retime *method* and no speed — so a plan with a retimed clip had to go through
 * FCPXML, where each retimed item needed an asset of its own because an asset-clip carrying a
 * timeMap has its `start` in-point ignored.
 *
 * 21.1 adds TimelineItem.SetSpeed, measured on this footage against the FCPXML path: rendered
 * frame for frame the two are identical — same first source frame, same progression, same last
 * frame. The difference is in what Resolve then knows. Through FCPXML the item reports its
 * source as 0-122, because the asset it points at was cut to the in-point already; through
 * SetSpeed it reports 743-865, the real position in the source clip, so the editor can still
 * trim it and can see where it came from.
 *
 * Throws rather than continuing quietly: a clip that stays at full speed is not the edit that
 * was planned, and the caller falls back to FCPXML.
 */
async function applySpeeds(timeline, clipInfos) {
  const wanted = clipInfos
    .map((info, index) => ({ index, speed: info.sevenfilmSpeed }))
    .filter((entry) => entry.speed != null);
  if (!wanted.length) return 0;
  const items = (await timeline.GetItemListInTrack("video", 1)) || [];
  let applied = 0;
  for (const { index, speed } of wanted) {
    const item = items[index];
    if (!item || typeof item.SetSpeed !== "function") {
      throw new Error("Bu Resolve sürümü klip hızını değiştiremiyor (21.1 gerekiyor).");
    }
    const before = await item.GetDuration();
    const ok = await item.SetSpeed({ Percentage: speed });
    // Read it back: on this API a call returning true has not always meant it did something.
    const now = await item.GetSpeed();
    if (!ok || Math.abs(Number(now?.Percentage) - speed) > 0.01) {
      throw new Error(`Klip hızı uygulanamadı: ${await item.GetName()}`);
    }
    // And check the length, because SetSpeed does not always keep it. Measured on 21.1: a
    // clip in the middle of a timeline kept its 100 frames and gave up half its source, while
    // the first clip of a real edit went from 126 frames to 252 and overwrote the two clips
    // after it. The cut lengths are the edit — they are where the music lands — so a clip that
    // changed length is not the plan any more and the whole timeline falls back to FCPXML.
    const after = await item.GetDuration();
    if (after !== before) {
      throw new Error(
        `Hız değişikliği klip süresini bozdu (${before} → ${after} kare): `
        + `${await item.GetName()}`,
      );
    }
    applied += 1;
  }
  return applied;
}

/**
 * Play the edit back at the rate it was cut at.
 *
 * Resolve gives a new timeline the project's monitor format rather than the timeline's own
 * rate. Measured across nineteen timelines here, four 50 fps edits were set to "HD 1080p 25"
 * and one to "HD 1080PsF 25", and the viewer judders on all five - which the editor found for
 * themselves before this existed. timelinePlaybackFrameRate refuses to be set; the monitor
 * format takes.
 *
 * Best effort: a monitoring format that will not take is not a reason to fail an edit that is
 * otherwise sitting correctly in the timeline.
 */
/**
 * Turn the clips the camera labelled the wrong way up, and resize them to fill the frame.
 *
 * The angle is the opposite of what the camera wrote, not a fixed one. A first attempt turned
 * every such clip by -90; the two written +90 came out right and the other fourteen came out
 * upside down — "yine ters hepsini kontrol et".
 *
 * Both the angle and the scale travel in the plan; this only applies them. Best effort — a
 * rotation that will not take is not a reason to fail an edit that is otherwise correct.
 */
async function applyRotations(timeline, plan) {
  const items = (await timeline.GetItemListInTrack("video", 1)) || [];
  let turned = 0;
  for (let index = 0; index < items.length; index += 1) {
    const wanted = Number(plan.items?.[index]?.rotation_degrees || 0);
    if (!wanted) continue;
    const item = items[index];
    if (typeof item.SetProperty !== "function") continue;
    await item.SetProperty("RotationAngle", wanted);
    // Resolve fits the clip by the height of the frame it thinks it has, so a clip turned
    // back sits at 1080x607 inside 1920x1080 until it is scaled: "fit olmamış monitöre".
    const zoom = Number(plan.items[index].rotation_zoom || 1);
    if (zoom !== 1) {
      await item.SetProperty("ZoomX", zoom);
      await item.SetProperty("ZoomY", zoom);
    }
    const now = await item.GetProperty("RotationAngle");
    if (Math.abs(Number(now) - wanted) < 0.01) turned += 1;
  }
  return turned;
}

// Take the last shot to black. Resolve 21.1 only; on 21.0.2 SetFades does not exist and the
// edit is handed over as it always was, with the music fade carrying the ending alone.
async function applyClosingFade(timeline, plan) {
  const items = (await timeline.GetItemListInTrack("video", 1)) || [];
  const last = items[items.length - 1];
  if (!last || typeof last.SetFades !== "function") return 0;
  const frames = closingFadeFrames(plan, await last.GetDuration());
  if (!frames) return 0;
  const applied = await last.SetFades({ FadeIn: 0, FadeOut: frames });
  if (!applied) return 0;
  // Read it back: on this API a call returning true has not always meant it did something.
  const now = await last.GetFades();
  return Number(now?.FadeOut) === frames ? frames : 0;
}

async function matchMonitorToTimeline(timeline, plan) {
  try {
    const rate = parseFrameRate(plan?.frame_rate, 0);
    const current = await timeline.GetSetting("videoMonitorFormat");
    const wanted = monitorFormatForRate(current, rate);
    if (wanted) await timeline.SetSetting("videoMonitorFormat", wanted);
  } catch (error) {
    console.error("monitor format:", error && error.message);
  }
}

async function importTimeline(_event, payload) {
  const timelineId = String(payload?.timelineId || "");
  if (!/^[0-9a-f-]{36}$/i.test(timelineId)) throw new Error("Geçersiz timeline kimliği.");

  await ensureBackend();
  const exportLinks = await requestJson("POST", `/api/timelines/${timelineId}/export`);
  const plan = await requestJson("GET", `/api/timelines/${timelineId}`);
  const importFile = path.join(app.getPath("temp"), "sevenfilm-ai-editor", `${timelineId}.fcpxml`);
  await downloadExport(exportLinks.fcpxml, importFile);

  const { resolve, manager, project } = await currentProject();
  if (!project) throw new Error("Resolve'da açık bir proje yok.");
  const mediaPool = await project.GetMediaPool();
  const timelineName = String(payload?.timelineName || plan.name || "7Film AI Rough Cut");
  // The Resolve API is the primary path: it is the only one that can say picture-only, put the
  // music on A1 and leave A2 and A3 for the editor, and add the markers. Importing the FCPXML
  // does work now that its assets carry the media's own start timecode - the same 141 cut file
  // comes in whole, music included - but it decides the track layout itself, so it is the
  // fallback rather than the lead.
  //
  // Except when the plan holds a retimed clip. AppendToTimeline lays a clip down at its own
  // speed and there is no way to change that afterwards: TimelineItem.SetProperty offers pan,
  // tilt, zoom, crop and the retime method, and no speed. Taking the API path anyway would
  // drop the slow motion silently and, worse, lay the clip down at the wrong length. So a plan
  // that asks for a speed goes through FCPXML, where the map comes back at exactly 0.50x.
  //
  // 21.1 added SetSpeed, so a retimed plan can take the API path too. It is still only tried:
  // where the version is older, where a clip has too little source to be laid down at its
  // timeline length, or where the speed does not read back, this falls through to FCPXML —
  // which is measured to produce an identical render and is not going anywhere.
  let timeline = null;
  let importMethod = "Resolve API";
  try {
    timeline = await createTimelineFromPlan(mediaPool, project, plan, timelineName);
  } catch (error) {
    importMethod = hasRetiming(plan) ? "FCPXML (yavaş çekim)" : "FCPXML";
    timeline = await mediaPool.ImportTimelineFromFile(importFile, {
      timelineName,
      importSourceClips: true,
    });
    if (!timeline) throw error;
  }

  await project.SetCurrentTimeline(timeline);
  await matchMonitorToTimeline(timeline, plan);
  const closingFadeFrames_ = await applyClosingFade(timeline, plan);
  const rotated = await applyRotations(timeline, plan);
  let markerCount = 0;
  for (const item of plan.items || []) {
    const markerFrame = Number(item.timeline_in?.start_frame || 0);
    const duration = Math.max(1, Number(item.timeline_in?.duration_frames || 1));
    const customData = JSON.stringify({ sevenfilm: true, timelineId, itemId: item.id, score: item.score });
    const added = await timeline.AddMarker(
      markerFrame,
      item.score >= 0.8 ? "Green" : item.score >= 0.65 ? "Blue" : "Yellow",
      `7Film · ${item.category} · ${Number(item.score).toFixed(3)}`,
      item.selection_reason,
      duration,
      customData,
    );
    if (added) markerCount += 1;
  }
  await manager.SaveProject();
  await resolve.OpenPage("edit");
  return {
    ok: true,
    timelineName: await timeline.GetName(),
    markerCount,
    importMethod,
    closingFadeFrames: closingFadeFrames_,
    rotatedClips: rotated,
  };
}

async function createWindow() {
  await ensureBackend();
  mainWindow = new BrowserWindow({
    width: 1120,
    height: 840,
    minWidth: 820,
    minHeight: 620,
    backgroundColor: "#131312",
    title: "7Film AI Editor",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  mainWindow.setMenu(null);
  await mainWindow.webContents.session.clearCache();
  mainWindow.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
  mainWindow.webContents.on("will-navigate", (event, target) => {
    if (!target.startsWith(backendOrigin)) event.preventDefault();
  });
  await mainWindow.loadURL(`${backendOrigin}/?engine=${encodeURIComponent(ENGINE_VERSION)}`);
  mainWindow.on("closed", () => { mainWindow = null; app.quit(); });
}

ipcMain.handle("resolve:getContext", getContext);
ipcMain.handle("resolve:importTimeline", importTimeline);
ipcMain.handle("system:selectFolder", async (_event, title) => {
  const result = await dialog.showOpenDialog(mainWindow, {
    title: String(title || "Klasör seç"),
    buttonLabel: "Klasörü seç",
    properties: ["openDirectory"],
  });
  return result.canceled ? null : result.filePaths[0];
});
ipcMain.handle("system:selectMusic", async () => {
  const result = await dialog.showOpenDialog(mainWindow, {
    title: "Müzik dosyasını seç",
    buttonLabel: "Müziği seç",
    properties: ["openFile"],
    filters: [
      { name: "Müzik", extensions: ["wav", "mp3", "m4a", "aac", "aif", "aiff", "flac", "ogg"] },
      { name: "Tüm dosyalar", extensions: ["*"] },
    ],
  });
  return result.canceled ? null : result.filePaths[0];
});
ipcMain.handle("resolve:openPage", async (_event, pageName) => {
  const allowed = new Set(["media", "cut", "edit", "fusion", "color", "fairlight", "deliver"]);
  if (!allowed.has(pageName)) return false;
  return (await getResolve()).OpenPage(pageName);
});
ipcMain.handle("resolve:cleanup", () => {
  if (initialized) WorkflowIntegration.CleanUp();
  initialized = false;
  resolveObject = null;
  return true;
});

app.whenReady().then(createWindow).catch((error) => {
  console.error(error);
  app.quit();
});
app.on("before-quit", () => {
  if (initialized) WorkflowIntegration.CleanUp();
  if (backendProcess) backendProcess.kill("SIGTERM");
});
app.on("window-all-closed", () => app.quit());
