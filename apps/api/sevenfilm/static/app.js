const $ = (selector) => document.querySelector(selector);
let currentProject = localStorage.getItem("sevenfilm.projectId") || "";
let currentTimeline = "";
const status = (value) => { $("#status").textContent = typeof value === "string" ? value : JSON.stringify(value, null, 2); };

async function request(path, options = {}) {
  const response = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || "İstek tamamlanamadı.");
  return body;
}

function showProject(project) {
  currentProject = project.id;
  localStorage.setItem("sevenfilm.projectId", project.id);
  $("#project-name").textContent = project.name;
  $("#create-card").classList.add("hidden");
  $("#project-card").classList.remove("hidden");
  status({ project: project.name, assets: project.assets || 0, shots: project.shots || 0, music_ready: Boolean(project.latest_music) });
}

async function pollJob(jobId) {
  for (;;) {
    const job = await request(`/api/jobs/${jobId}`);
    status({ job: job.kind, status: job.status, progress: `${Math.round(job.progress * 100)}%`, error: job.error });
    if (job.status === "completed") return job;
    if (job.status === "failed") throw new Error(job.error || "İş tamamlanamadı.");
    await new Promise((resolve) => setTimeout(resolve, 700));
  }
}

$("#create-project").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const data = Object.fromEntries(new FormData(event.currentTarget));
    showProject(await request("/api/projects", { method: "POST", body: JSON.stringify(data) }));
  } catch (error) { status(error.message); }
});

function jobForm(selector, endpoint) {
  $(selector).addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!currentProject) return status("Önce proje oluşturun.");
    try {
      const data = Object.fromEntries(new FormData(event.currentTarget));
      const job = await request(`/api/projects/${currentProject}/${endpoint}`, { method: "POST", body: JSON.stringify(data) });
      await pollJob(job.job_id); status("Tamamlandı.");
    } catch (error) { status(error.message); }
  });
}
jobForm("#index-form", "index");
jobForm("#music-form", "music");

function jobButton(selector, endpoint) {
  $(selector).addEventListener("click", async () => {
    if (!currentProject) return status("Önce proje oluşturun.");
    try { const job = await request(`/api/projects/${currentProject}/${endpoint}`, { method: "POST" }); await pollJob(job.job_id); status("Tamamlandı."); }
    catch (error) { status(error.message); }
  });
}
jobButton("#shots-button", "shots");
jobButton("#proxy-button", "derivatives");

$("#timeline-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const data = Object.fromEntries(new FormData(event.currentTarget));
    const plan = await request(`/api/projects/${currentProject}/timelines`, { method: "POST", body: JSON.stringify(data) });
    currentTimeline = plan.id;
    $("#timeline-summary").textContent = `${plan.items.length} klip · ${plan.actual_duration_seconds} sn · ${plan.frame_rate} FPS`;
    $("#timeline-items").replaceChildren(...plan.items.map((item) => {
      const li = document.createElement("li"); li.innerHTML = `<strong>${item.category} · ${item.shot_scale}</strong> <span>${item.clip_name}</span><small>${item.selection_reason}</small>`; return li;
    }));
    $("#timeline-card").classList.remove("hidden"); status("Kaba kurgu hazır. Her satırda seçim nedeni ve puanlama kaydı var.");
  } catch (error) { status(error.message); }
});

$("#export-button").addEventListener("click", async () => {
  if (!currentTimeline) return;
  try { const result = await request(`/api/timelines/${currentTimeline}/export`, { method: "POST" }); $("#exports").innerHTML = Object.entries(result).map(([name, url]) => `<a href="${url}">${name.toUpperCase()} indir</a>`).join(" "); status("OTIO ve FCPXML dışa aktarıldı. Resolve'da FCPXML içe aktarımını kullanın."); }
  catch (error) { status(error.message); }
});

$("#change-project").addEventListener("click", () => { localStorage.removeItem("sevenfilm.projectId"); location.reload(); });
if (currentProject) request(`/api/projects/${currentProject}`).then(showProject).catch(() => localStorage.removeItem("sevenfilm.projectId"));

