// 7Film AI Editor — DaVinci Resolve Workflow Integration main process.
// The native bridge is copied from Resolve's own Developer examples at install time.

const { app, BrowserWindow, dialog, ipcMain } = require("electron");
const { spawn } = require("child_process");
const fs = require("fs");
const http = require("http");
const path = require("path");
const WorkflowIntegration = require("./WorkflowIntegration.node");

const PLUGIN_ID = "com.sevenfilm.ai.editor";
const ENGINE_VERSION = "0.3.0";
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

async function ensureBackend() {
  let availableOrigin = null;
  for (const port of BACKEND_PORTS) {
    const origin = `http://127.0.0.1:${port}`;
    const health = await backendHealth(origin);
    if (health?.status === "ok" && health?.engine_version === ENGINE_VERSION) {
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
  backendProcess = spawn(launcher, [], {
    cwd: root,
    env: { ...process.env, SEVENFILM_PLUGIN: "1", SEVENFILM_PORT: backendPort },
    stdio: "ignore",
  });
  backendProcess.on("exit", () => { backendProcess = null; });
  for (let attempt = 0; attempt < 40; attempt += 1) {
    const health = await backendHealth(backendOrigin);
    if (health?.status === "ok" && health?.engine_version === ENGINE_VERSION) return;
    await new Promise((resolve) => setTimeout(resolve, 500));
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

async function createTimelineFromPlan(mediaPool, project, plan, timelineName) {
  const sourcePaths = [...new Set((plan.items || []).map((item) => String(item.source_path)))];
  const musicPath = plan.music_path ? String(plan.music_path) : null;
  const poolPaths = musicPath ? [...new Set([...sourcePaths, musicPath])] : sourcePaths;
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

  const clipInfos = (plan.items || []).map((item) => {
    const mediaPoolItem = itemByPath.get(path.resolve(String(item.source_path)));
    if (!mediaPoolItem) throw new Error(`Media Pool öğesi bulunamadı: ${item.source_path}`);
    const startFrame = Number(item.source_in?.start_frame || 0);
    const durationFrames = Math.max(1, Number(item.source_in?.duration_frames || 1));
    return {
      mediaPoolItem,
      startFrame,
      endFrame: startFrame + durationFrames - 1,
      mediaType: 1,
    };
  });
  if (!clipInfos.length) throw new Error("Kurgu planında video klibi bulunamadı.");
  const suffix = new Date().toISOString().slice(11, 19).replaceAll(":", "");
  // Resolve 21 rejects very large CreateTimelineFromClips payloads as "Invalid items".
  // A conservative first batch creates the timeline; later batches append in order.
  const batchSize = 40;
  const timeline = await mediaPool.CreateTimelineFromClips(
    `${timelineName} · ${suffix}`,
    clipInfos.slice(0, batchSize),
  );
  if (!timeline) throw new Error("Resolve video timeline’ını oluşturamadı.");
  await project.SetCurrentTimeline(timeline);
  for (let start = batchSize; start < clipInfos.length; start += batchSize) {
    const batch = clipInfos.slice(start, start + batchSize);
    let appended = null;
    try {
      appended = await mediaPool.AppendToTimeline(batch);
    } catch (error) {
      throw new Error(
        `Resolve ${start + 1}-${start + batch.length}. video kliplerini ekleyemedi: ${error.message || error}`,
      );
    }
    if (!appended || appended.length !== batch.length) {
      throw new Error(`Resolve ${start + 1}-${start + batch.length}. video grubunu eksik ekledi.`);
    }
  }

  if (musicPath) {
    const musicItem = itemByPath.get(path.resolve(musicPath));
    const timelineStart = Number(await timeline.GetStartFrame());
    const targetFrames = Number(plan.items?.reduce(
      (total, item) => total + Number(item.timeline_in?.duration_frames || 0),
      0,
    ) || 1);
    const audioItems = await mediaPool.AppendToTimeline([{
      mediaPoolItem: musicItem,
      startFrame: 0,
      endFrame: Math.max(0, targetFrames - 1),
      mediaType: 2,
      trackIndex: 1,
      recordFrame: timelineStart,
    }]);
    if (!audioItems || audioItems.length !== 1) {
      throw new Error("Müzik Resolve timeline’ına eklenemedi.");
    }
  }
  return timeline;
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
  let timeline = null;
  let importMethod = "FCPXML";
  try {
    timeline = await mediaPool.ImportTimelineFromFile(importFile, {
      timelineName,
      importSourceClips: true,
    });
  } catch (_error) {
    timeline = null;
  }
  if (!timeline) {
    importMethod = "Resolve API";
    timeline = await createTimelineFromPlan(mediaPool, project, plan, timelineName);
  }

  await project.SetCurrentTimeline(timeline);
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
  return { ok: true, timelineName: await timeline.GetName(), markerCount, importMethod };
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
