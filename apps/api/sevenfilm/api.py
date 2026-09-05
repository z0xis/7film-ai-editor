"""HTTP orchestration layer for the local 7Film prototype."""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import UTC, datetime
from fractions import Fraction
from pathlib import Path
from typing import Any, Literal
from urllib.parse import unquote

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from .config import data_root, database_path
from .db import Database, now
from .domain import MusicSegment
from .services.analysis import (
    analyze_music,
    analyze_shots,
    project_music,
    project_shots,
    stale_analysis,
)
from .services.exporter import export_all, plan_as_dict
from .services.media import generate_derivatives, index_folder, project_assets
from .services.music import plan_music
from .services.planner import build_timeline, get_timeline, persist_timeline
from .timebase import FrameRate

LOGGER = logging.getLogger("sevenfilm")
ROOT = data_root()
DATABASE = Database(database_path())
# The plugin refuses to reuse a running engine whose version differs from its own, so this is
# what replaces a backend left over from an earlier release. Bump it whenever the HTTP contract
# changes: an engine started twelve hours before this line moved was still answering, and the
# app's new "several songs" request came back as "path: Field required".
ENGINE_VERSION = "0.4.0"


def _normalize_path(raw: str) -> Path:
    """Fix macOS Finder drag-drop (file://) and URL encoded paths."""
    decoded = unquote(raw).strip()
    if decoded.startswith("file://localhost"):
        decoded = decoded[16:]
    elif decoded.startswith("file://"):
        decoded = decoded[7:]
    elif decoded.startswith("file:"):
        decoded = decoded[5:]
    return Path(decoded).expanduser().resolve()


app = FastAPI(title="7Film AI Engine", version=ENGINE_VERSION)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def disable_local_ui_cache(request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    return response


class CreateProjectRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    workspace_path: str
    target_duration_seconds: str = "150"
    frame_rate: str = "25/1"

    @field_validator("target_duration_seconds")
    @classmethod
    def validate_duration(cls, value: str) -> str:
        if Fraction(value) <= 0:
            raise ValueError("Target duration must be positive")
        return value

    @field_validator("frame_rate")
    @classmethod
    def validate_rate(cls, value: str) -> str:
        FrameRate.parse(value)
        return value


class FolderRequest(BaseModel):
    folder: str


class MusicRequest(BaseModel):
    """One song or several, in the order they should play under the edit."""

    path: str | None = None
    paths: list[str] | None = None

    def chosen(self) -> list[str]:
        if self.paths:
            return self.paths
        return [self.path] if self.path else []


class TimelineRequest(BaseModel):
    target_duration_seconds: str | None = None
    seed: int = 1
    name: str = Field(default="AI Rough Cut", min_length=1, max_length=120)


def _project(project_id: str) -> dict[str, Any]:
    project = DATABASE.fetch_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if project is None:
        raise HTTPException(status_code=404, detail="Proje bulunamadı.")
    return project


def _project_cache(project_id: str) -> Path:
    path = ROOT / "projects" / project_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def _plan_payload(plan) -> dict[str, Any]:
    payload = plan_as_dict(plan)
    music = DATABASE.fetch_one(
        "SELECT path, duration_seconds FROM music_tracks WHERE project_id = ? ORDER BY created_at DESC LIMIT 1",
        (plan.project_id,),
    )
    payload["music_path"] = music["path"] if music else None
    payload["music_duration_seconds"] = music["duration_seconds"] if music else None
    return payload


def _style_profile() -> dict[str, Any] | None:
    profile_path = ROOT / "references" / "7film-style-profile.json"
    if not profile_path.is_file():
        return None
    return json.loads(profile_path.read_text(encoding="utf-8"))


def _create_job(project_id: str, kind: str, checkpoint: dict[str, Any]) -> str:
    job_id = str(uuid.uuid4())
    DATABASE.insert(
        "jobs",
        {
            "id": job_id,
            "project_id": project_id,
            "kind": kind,
            "status": "queued",
            "progress": 0.0,
            "checkpoint_json": checkpoint,
            "error": None,
            "created_at": now(),
            "updated_at": now(),
        },
    )
    return job_id


def _run_job(job_id: str) -> None:
    job = DATABASE.fetch_one("SELECT * FROM jobs WHERE id = ?", (job_id,))
    if job is None:
        return
    checkpoint = json.loads(job["checkpoint_json"])
    # Cheap, and it closes a failure that cost an evening: a backend left running from before a
    # release serves the old schema, and the first job that writes a new column dies with a
    # message no one can read. Adding a missing column is a PRAGMA and an ALTER, nothing more.
    DATABASE.migrate()
    DATABASE.update_job(job_id, status="running", progress=float(job["progress"]), checkpoint=checkpoint)
    try:
        if job["kind"] == "index":
            index_folder(DATABASE, job["project_id"], Path(checkpoint["folder"]), job_id)
        elif job["kind"] == "derivatives":
            generate_derivatives(DATABASE, job["project_id"], _project_cache(job["project_id"]), job_id)
        elif job["kind"] == "shots":
            analyze_shots(DATABASE, job["project_id"], job_id)
        elif job["kind"] == "music":
            for position, raw in enumerate(checkpoint["paths"]):
                analyze_music(DATABASE, job["project_id"], Path(raw), position)
                DATABASE.update_job(
                    job_id, status="running", progress=(position + 1) / len(checkpoint["paths"]))
        else:
            raise ValueError(f"Bilinmeyen job türü: {job['kind']}")
        DATABASE.update_job(job_id, status="completed", progress=1.0)
        LOGGER.info(json.dumps({"event": "job_completed", "job_id": job_id, "kind": job["kind"]}))
    except Exception as error:  # Boundary records safe-to-display job errors; traceback remains server-side.
        current = DATABASE.fetch_one("SELECT progress FROM jobs WHERE id = ?", (job_id,))
        DATABASE.update_job(job_id, status="failed", progress=float(current["progress"] if current else 0), error=str(error))
        LOGGER.exception(json.dumps({"event": "job_failed", "job_id": job_id, "kind": job["kind"]}))


@app.on_event("startup")
def startup() -> None:
    DATABASE.migrate()


def source_fingerprint() -> str:
    """A digest of the engine's own Python source, as it was when this process imported it.

    A running engine holds the modules it imported at startup, so editing the planner does not
    change what it serves. That has now cost three evenings: the sequence work landed 29
    minutes after this process began, and every edit built afterwards was cut by the code from
    before it. The plugin compares this against the source on disk and starts a fresh engine
    when they differ, which is the only thing that makes an edit reflect the code.
    """
    root = Path(__file__).resolve().parent
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*.py"), key=lambda item: item.relative_to(root).as_posix()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()[:16]


SOURCE_FINGERPRINT = source_fingerprint()


@app.get("/api/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "engine_version": ENGINE_VERSION,
        "source_fingerprint": SOURCE_FINGERPRINT,
        "data_root": str(ROOT),
    }


@app.get("/api/projects")
def list_projects() -> list[dict[str, Any]]:
    return DATABASE.fetch_all("SELECT * FROM projects ORDER BY created_at DESC")


@app.post("/api/projects", status_code=201)
def create_project(request: CreateProjectRequest) -> dict[str, Any]:
    source_workspace = _normalize_path(request.workspace_path)
    if not source_workspace.is_dir():
        raise HTTPException(status_code=422, detail="Proje çalışma klasörü bulunamadı.")
    project_id = str(uuid.uuid4())
    timestamp = now()
    project = {
        "id": project_id,
        "name": request.name.strip(),
        "workspace_path": str(source_workspace),
        "target_duration_seconds": request.target_duration_seconds,
        "frame_rate": request.frame_rate,
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    DATABASE.insert("projects", project)
    _project_cache(project_id)
    return project


@app.get("/api/projects/{project_id}")
def get_project(project_id: str) -> dict[str, Any]:
    project = _project(project_id)
    project["assets"] = len(project_assets(DATABASE, project_id))
    project["shots"] = len(project_shots(DATABASE, project_id))
    songs = project_music(DATABASE, project_id)
    # The running order the editor chose, so the app can show it back rather than one file name.
    project["music_paths"] = [str(track.path) for track in songs]
    project["music_path"] = str(songs[0].path) if songs else None
    project["latest_music"] = bool(songs)
    profile = _style_profile()
    project["style_reference_count"] = int(profile.get("reference_count", 0)) if profile else 0
    project["stale_analysis"] = stale_analysis(DATABASE, project_id)
    return project


@app.post("/api/projects/{project_id}/index", status_code=202)
def start_index(project_id: str, request: FolderRequest, background_tasks: BackgroundTasks) -> dict[str, str]:
    _project(project_id)
    folder = _normalize_path(request.folder)
    job_id = _create_job(project_id, "index", {"folder": str(folder), "completed_paths": []})
    background_tasks.add_task(_run_job, job_id)
    return {"job_id": job_id, "status": "queued"}


@app.post("/api/projects/{project_id}/derivatives", status_code=202)
def start_derivatives(project_id: str, background_tasks: BackgroundTasks) -> dict[str, str]:
    _project(project_id)
    job_id = _create_job(project_id, "derivatives", {})
    background_tasks.add_task(_run_job, job_id)
    return {"job_id": job_id, "status": "queued"}


@app.post("/api/projects/{project_id}/shots", status_code=202)
def start_shot_analysis(project_id: str, background_tasks: BackgroundTasks) -> dict[str, str]:
    _project(project_id)
    job_id = _create_job(project_id, "shots", {})
    background_tasks.add_task(_run_job, job_id)
    return {"job_id": job_id, "status": "queued"}


@app.post("/api/projects/{project_id}/music", status_code=202)
def start_music_analysis(project_id: str, request: MusicRequest, background_tasks: BackgroundTasks) -> dict[str, str]:
    _project(project_id)
    chosen = request.chosen()
    if not chosen:
        raise HTTPException(status_code=422, detail="En az bir şarkı seçilmeli.")
    paths = [str(_normalize_path(item)) for item in chosen]
    # The chosen songs replace the previous selection outright: leaving the old rows behind
    # would silently add a song the editor has taken out of the running order.
    DATABASE.execute("DELETE FROM music_tracks WHERE project_id = ?", (project_id,))
    job_id = _create_job(project_id, "music", {"paths": paths})
    background_tasks.add_task(_run_job, job_id)
    return {"job_id": job_id, "status": "queued"}


@app.get("/api/projects/{project_id}/assets")
def list_assets(project_id: str) -> list[dict[str, Any]]:
    _project(project_id)
    return DATABASE.fetch_all(
        """SELECT id, path, file_name, duration_seconds, frame_rate, width, height, codec,
                  timecode, proxy_path, thumbnail_path, created_at
           FROM media_assets WHERE project_id = ? ORDER BY path""",
        (project_id,),
    )


@app.get("/api/projects/{project_id}/shots")
def list_shots(project_id: str) -> list[dict[str, Any]]:
    _project(project_id)
    return DATABASE.fetch_all(
        """SELECT shots.* FROM shots JOIN media_assets ON media_assets.id = shots.asset_id
           WHERE media_assets.project_id = ? ORDER BY media_assets.path, shots.start_frame""",
        (project_id,),
    )


@app.post("/api/projects/{project_id}/timelines", status_code=201)
def create_timeline(project_id: str, request: TimelineRequest) -> dict[str, Any]:
    project = _project(project_id)
    target = Fraction(request.target_duration_seconds or project["target_duration_seconds"])
    songs = project_music(DATABASE, project_id)
    music_segments: tuple[MusicSegment, ...] = ()
    music_warnings: list[str] = []
    if songs:
        music_grid, music_segments, music_warnings = plan_music(songs, target)
    else:
        music_grid = _missing_music()
    try:
        plan = build_timeline(
            project_id=project_id,
            assets=project_assets(DATABASE, project_id),
            shots=project_shots(DATABASE, project_id),
            music=music_grid,
            frame_rate=FrameRate.parse(project["frame_rate"]),
            target_duration=target,
            style_profile=_style_profile(),
            seed=request.seed,
            name=request.name,
        )
        plan.music_segments = music_segments
        plan.music_path = music_segments[0].path if music_segments else None
        plan.music_duration = music_segments[0].duration if music_segments else None
        plan.warnings.extend(music_warnings)
        persist_timeline(DATABASE, plan)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return _plan_payload(plan)


@app.get("/api/projects/{project_id}/timelines/latest")
def latest_timeline(project_id: str) -> dict[str, Any]:
    _project(project_id)
    row = DATABASE.fetch_one(
        "SELECT id FROM timeline_versions WHERE project_id = ? ORDER BY created_at DESC LIMIT 1",
        (project_id,),
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Bu proje için kayıtlı kurgu planı yok.")
    return _plan_payload(get_timeline(DATABASE, row["id"]))


def _missing_music():
    raise HTTPException(status_code=422, detail="Önce bir müzik dosyasını analiz edin.")


@app.get("/api/timelines/{timeline_id}")
def read_timeline(timeline_id: str) -> dict[str, Any]:
    try:
        return _plan_payload(get_timeline(DATABASE, timeline_id))
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.post("/api/timelines/{timeline_id}/export")
def export_timeline(timeline_id: str) -> dict[str, str]:
    try:
        plan = get_timeline(DATABASE, timeline_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    paths = export_all(plan, _project_cache(plan.project_id) / "exports")
    return {kind: f"/api/timelines/{timeline_id}/exports/{kind}" for kind in paths}


@app.get("/api/timelines/{timeline_id}/exports/{kind}")
def download_export(timeline_id: str, kind: Literal["plan", "otio", "fcpxml"]) -> FileResponse:
    try:
        plan = get_timeline(DATABASE, timeline_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    paths = export_all(plan, _project_cache(plan.project_id) / "exports")
    return FileResponse(paths[kind], filename=paths[kind].name)


# A job whose progress has not moved for this long is not being worked on any more: the
# process that was running it is gone, and nothing will ever mark it finished.
STALLED_JOB_SECONDS = 300


def _job_payload(job: dict[str, Any]) -> dict[str, Any]:
    job["checkpoint"] = json.loads(job.pop("checkpoint_json"))
    if job["status"] in {"queued", "running"}:
        updated = datetime.fromisoformat(job["updated_at"])
        job["stalled"] = (datetime.now(UTC) - updated).total_seconds() > STALLED_JOB_SECONDS
    else:
        job["stalled"] = False
    return job


@app.get("/api/projects/{project_id}/jobs/latest")
def latest_job(project_id: str) -> dict[str, Any]:
    """The job the desktop app should still be showing, after a reload or a restart."""
    _project(project_id)
    job = DATABASE.fetch_one(
        "SELECT * FROM jobs WHERE project_id = ? ORDER BY created_at DESC LIMIT 1", (project_id,)
    )
    if job is None:
        raise HTTPException(status_code=404, detail="Bu proje için kayıtlı iş yok.")
    return _job_payload(job)


@app.get("/api/jobs/{job_id}")
def read_job(job_id: str) -> dict[str, Any]:
    job = DATABASE.fetch_one("SELECT * FROM jobs WHERE id = ?", (job_id,))
    if job is None:
        raise HTTPException(status_code=404, detail="Job bulunamadı.")
    return _job_payload(job)


REACT_ROOT = Path(__file__).resolve().parents[2] / "desktop" / "dist"
STATIC_ROOT = REACT_ROOT if (REACT_ROOT / "index.html").is_file() else Path(__file__).parent / "static"
if STATIC_ROOT.is_dir():
    app.mount("/", StaticFiles(directory=STATIC_ROOT, html=True), name="frontend")
