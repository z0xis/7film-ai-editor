"""HTTP orchestration layer for the local 7Film prototype."""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
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
from .db import (
    TERMINAL_STATUSES,
    Database,
    DuplicateActiveJobError,
    JobCancelled,
    now,
    raise_if_cancelled,
    recover_orphaned_jobs,
)
from .domain import MusicSegment
from .services.analysis import (
    NOT_READY_FOR_ROUGH_CUT,
    analyze_music,
    analyze_shots,
    project_music,
    project_shots,
    semantic_readiness,
    stale_analysis,
)
from .services.exporter import export_all, plan_as_dict
from .services.media import generate_derivatives, index_folder, project_assets
from .services.moments import (
    project_distractions,
    project_embeddings,
    project_moments,
    project_obstructions,
    project_opening_signs,
    project_table_settings,
)
from .services.music import plan_music
from .services.planner import build_timeline, get_timeline, persist_timeline
from .services.rejections import (
    project_rejections,
    reject_clips,
    rejected_names,
    restore_clips,
)
from .services.vision import semantic_backend_status
from .services.windows import project_windows
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


class ShotAnalysisRequest(BaseModel):
    """Options for a `shots` job.

    `force_reencode` recomputes technical_quality and embeddings for assets that already have
    `shot_features` (a degraded earlier run left them stale). Default false keeps the ordinary
    reuse behaviour untouched -- an asset that already has features is not decoded again.
    """

    force_reencode: bool = False


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


def _with_proxies(payload: dict[str, Any], project_id: str) -> dict[str, Any]:
    """Name each clip's proxy, when one has been made.

    The 4K 10 bit 4:2:2 H.264 this shoot is in has no hardware decoder on this machine, so a
    cut every second brings playback to a stop. Resolve plays the proxy instead once the clip
    is linked to it, and the adapter can only link what the payload names.
    """
    cache = _project_cache(project_id)
    for item in payload.get("items", []):
        proxy = cache / "proxies" / f"{item['asset_id']}.mp4"
        item["proxy_path"] = str(proxy) if proxy.exists() else None
    return payload


def _plan_payload(plan) -> dict[str, Any]:
    # The music comes from the plan, which knows the songs it was actually cut to. This used to
    # overwrite it with the newest music_tracks row, which contradicted the segments beside it
    # the moment an edit held more than one song.
    return _with_proxies(plan_as_dict(plan), plan.project_id)


def _style_profile() -> dict[str, Any] | None:
    profile_path = ROOT / "references" / "7film-style-profile.json"
    if not profile_path.is_file():
        return None
    return json.loads(profile_path.read_text(encoding="utf-8"))


def _create_job(project_id: str, kind: str, checkpoint: dict[str, Any]) -> str:
    job_id = str(uuid.uuid4())
    try:
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
    except sqlite3.IntegrityError as error:
        # The partial unique index on (project_id, kind) is what actually enforces this; the
        # `IntegrityError` it raises on a conflicting INSERT is the only place this can be
        # caught, which is also what makes it race-safe against two requests arriving together.
        raise DuplicateActiveJobError(project_id, kind) from error
    return job_id


def _create_job_or_409(project_id: str, kind: str, checkpoint: dict[str, Any]) -> str:
    try:
        return _create_job(project_id, kind, checkpoint)
    except DuplicateActiveJobError as error:
        raise HTTPException(
            status_code=409,
            detail=f"Bu proje için zaten aktif bir {kind!r} işi var.") from error


def _run_job(job_id: str) -> None:
    job = DATABASE.fetch_one("SELECT * FROM jobs WHERE id = ?", (job_id,))
    if job is None:
        return
    if job["status"] in TERMINAL_STATUSES:
        # A `queued` job can be cancelled before this BackgroundTask ever gets a turn to run —
        # the HTTP response for "start" and the cancel request are two separate round trips,
        # and nothing stops the second from winning the race. Finding the job already settled
        # means there is nothing left for this call to do.
        return
    checkpoint = json.loads(job["checkpoint_json"])
    # Cheap, and it closes a failure that cost an evening: a backend left running from before a
    # release serves the old schema, and the first job that writes a new column dies with a
    # message no one can read. Adding a missing column is a PRAGMA and an ALTER, nothing more.
    DATABASE.migrate()
    # A compare-and-swap, not the plain `update_job` every write below it is: the entry check
    # above reads status once, and a cancel of this still-`queued` job can land in the gap
    # between that read and this write. Losing the race here means returning, the same as
    # finding the job already terminal above -- not overwriting the cancel that got there first.
    # `running` is accepted too -- re-affirming a job this call already owns is a no-op, not a
    # race to lose -- so only `cancel_requested` and the terminal statuses are refused here.
    if not DATABASE.transition_job(job_id, "running", from_statuses=frozenset({"queued", "running"})):
        return
    try:
        if job["kind"] == "index":
            index_folder(DATABASE, job["project_id"], Path(checkpoint["folder"]), job_id)
        elif job["kind"] == "derivatives":
            generate_derivatives(DATABASE, job["project_id"], _project_cache(job["project_id"]), job_id)
        elif job["kind"] == "shots":
            analyze_shots(DATABASE, job["project_id"], job_id,
                          force_reencode=bool(checkpoint.get("force_reencode", False)))
        elif job["kind"] == "music":
            total_songs = len(checkpoint["paths"])
            for position, raw in enumerate(checkpoint["paths"]):
                raise_if_cancelled(DATABASE, job_id)
                DATABASE.touch_heartbeat(job_id)
                analyze_music(DATABASE, job["project_id"], Path(raw), position)
                DATABASE.update_job_progress(
                    job_id, stage="music", processed=position + 1, total=total_songs,
                    checkpoint={"paths": checkpoint["paths"], "current_song_display": Path(raw).name},
                )
        else:
            raise ValueError(f"Bilinmeyen job türü: {job['kind']}")
        DATABASE.update_job(job_id, status="completed", progress=1.0)
        LOGGER.info(json.dumps({"event": "job_completed", "job_id": job_id, "kind": job["kind"]}))
    except JobCancelled:
        current = DATABASE.fetch_one("SELECT progress FROM jobs WHERE id = ?", (job_id,))
        # `cancel_requested` -> `cancelled` here specifically, never through the generic
        # exception branch below: a cancellation the worker itself observed and stopped for is
        # not a failure, and showing it as one would make every deliberate cancel look broken.
        DATABASE.transition_job(
            job_id, "cancelled", from_statuses=frozenset({"cancel_requested", "running"}))
        LOGGER.info(json.dumps({
            "event": "job_cancelled", "job_id": job_id, "kind": job["kind"],
            "progress": float(current["progress"] if current else 0),
        }))
    except Exception as error:  # Boundary records safe-to-display job errors; traceback remains server-side.
        current = DATABASE.fetch_one("SELECT progress FROM jobs WHERE id = ?", (job_id,))
        DATABASE.update_job(job_id, status="failed", progress=float(current["progress"] if current else 0), error=str(error))
        LOGGER.exception(json.dumps({"event": "job_failed", "job_id": job_id, "kind": job["kind"]}))


@app.on_event("startup")
def startup() -> None:
    DATABASE.migrate()
    # Anything still `queued`, `running` or `cancel_requested` at this instant belonged to a
    # process that is not this one — nothing in this codebase resumes a job on its own, so a
    # row in one of those states can only be left over from before this process existed. See
    # `recover_orphaned_jobs` for why that is a `failed`, not silently forgotten or left to
    # look like still-running work with no worker behind it.
    recovered = recover_orphaned_jobs(DATABASE)
    if recovered:
        LOGGER.info(json.dumps({"event": "orphaned_jobs_recovered", "job_ids": recovered}))


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
    project["semantic_readiness"] = semantic_readiness(DATABASE, project_id)
    return project


@app.get("/api/capabilities")
def capabilities() -> dict[str, Any]:
    """What this backend can actually do right now, checked live -- not cached, not inferred
    from a previous job's outcome. Meant to be called before starting a multi-hour shot
    analysis, so a missing semantic model is a decision made in seconds rather than discovered
    hours into a job that only produced the OpenCV fallback's face-count labels.
    """
    return {"semantic": semantic_backend_status()}


@app.post("/api/projects/{project_id}/index", status_code=202)
def start_index(project_id: str, request: FolderRequest, background_tasks: BackgroundTasks) -> dict[str, str]:
    _project(project_id)
    folder = _normalize_path(request.folder)
    job_id = _create_job_or_409(project_id, "index", {"folder": str(folder), "completed_paths": []})
    background_tasks.add_task(_run_job, job_id)
    return {"job_id": job_id, "status": "queued"}


@app.post("/api/projects/{project_id}/derivatives", status_code=202)
def start_derivatives(project_id: str, background_tasks: BackgroundTasks) -> dict[str, str]:
    _project(project_id)
    job_id = _create_job_or_409(project_id, "derivatives", {})
    background_tasks.add_task(_run_job, job_id)
    return {"job_id": job_id, "status": "queued"}


@app.post("/api/projects/{project_id}/shots", status_code=202)
def start_shot_analysis(
    project_id: str, background_tasks: BackgroundTasks,
    request: ShotAnalysisRequest | None = None,
) -> dict[str, str]:
    _project(project_id)
    # Optional body: an empty POST keeps the historical behaviour (reuse existing features). The
    # flag is recorded in the job checkpoint so `_run_job` -> `analyze_shots` can honour it, and so
    # the job row itself is an audit record that this was a force-reencode.
    force_reencode = bool(request.force_reencode) if request is not None else False
    job_id = _create_job_or_409(project_id, "shots", {"force_reencode": force_reencode})
    background_tasks.add_task(_run_job, job_id)
    return {"job_id": job_id, "status": "queued", "force_reencode": str(force_reencode).lower()}


@app.post("/api/projects/{project_id}/music", status_code=202)
def start_music_analysis(project_id: str, request: MusicRequest, background_tasks: BackgroundTasks) -> dict[str, str]:
    _project(project_id)
    chosen = request.chosen()
    if not chosen:
        raise HTTPException(status_code=422, detail="En az bir şarkı seçilmeli.")
    paths = [str(_normalize_path(item)) for item in chosen]
    # Checked before anything is deleted: a rejected duplicate must leave the previous
    # selection exactly as it was, not half-replaced.
    job_id = _create_job_or_409(project_id, "music", {"paths": paths})
    # The chosen songs replace the previous selection outright: leaving the old rows behind
    # would silently add a song the editor has taken out of the running order.
    DATABASE.execute("DELETE FROM music_tracks WHERE project_id = ?", (project_id,))
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
    # Fail loud, before any planning runs: a project whose shots exist but were not all
    # produced by the semantic classifier has no way to hold `bride_prep`/`ceremony`/`party`/
    # `groom_prep`/`groom` candidates, whatever its technical measurements say. `total == 0`
    # (no shots yet) is left to `build_timeline`'s own "index and analyse first" error below --
    # that is a different problem than degraded semantics, and deserves its own message.
    readiness = semantic_readiness(DATABASE, project_id)
    if readiness["total"] and readiness["status"] == NOT_READY_FOR_ROUGH_CUT:
        raise HTTPException(status_code=422, detail=(
            "Semantik görüntü analizi eksik: "
            f"{readiness['total'] - readiness['full']}/{readiness['total']} shot tam CLIP "
            "modeliyle değil, düşürülmüş (opencv_fallback) yöntemle analiz edilmiş. Bu "
            "kategoriler (hazırlık, nikâh, parti vb.) düğün hikâyesi için yeterli değil. Kaba "
            "kurgu oluşturmadan önce shot analizini tam semantik modelle yeniden çalıştırın."
        ))
    target = Fraction(request.target_duration_seconds or project["target_duration_seconds"])
    songs = project_music(DATABASE, project_id)
    music_segments: tuple[MusicSegment, ...] = ()
    music_warnings: list[str] = []
    if songs:
        music_grid, music_segments, music_warnings = plan_music(songs, target, _style_profile())
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
            windows_by_shot=project_windows(DATABASE, project_id),
            rejected=project_rejections(DATABASE, project_id),
            moments=project_moments(DATABASE, project_id),
            distractions=project_distractions(DATABASE, project_id),
            obstructions=project_obstructions(DATABASE, project_id),
            opening_signs=project_opening_signs(DATABASE, project_id),
            table_settings=project_table_settings(DATABASE, project_id),
            embeddings=project_embeddings(DATABASE, project_id),
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


# A job whose *heartbeat* has not moved for this long is not being worked on any more: the
# process that was running it is gone, and nothing will ever mark it finished. This used to be
# read off `updated_at` -- the same column a progress write touches -- which is exactly how a
# job that was genuinely still running, CPU busy, `_measure_shot_windows` landing new rows every
# few seconds, read as "unresponsive": that stage wrote neither a progress update nor anything
# else for hours at a time. See `Database.touch_heartbeat`.
STALLED_JOB_SECONDS = 300

# Every stage a job of this kind moves through, in the order it moves through them. A stage
# absent from a kind's own `STAGE_WEIGHTS` (or a kind absent here entirely -- a job row this old
# never recorded one) falls back to treating whatever `stage_progress` it has as the whole of
# `overall_progress`, still subject to the same non-terminal cap below.
STAGE_ORDER: dict[str, tuple[str, ...]] = {
    "shots": ("encode", "label", "windows", "finalize"),
    "index": ("index",),
    "derivatives": ("derivatives",),
    "music": ("music",),
}
# Deliberately not measured off this shoot's own timings: P2 is an observability contract, not
# a performance claim, and calibrating these against one project's runtime would smuggle a
# performance number in under a different name. `encode`/`label` cost about the same per asset
# (one CLIP pass each); `windows` is the one pass with no natural per-asset unit, and measured
# far more expensive in wall time than either on real footage, so it is weighted heaviest of the
# three. `finalize` does no real work today -- see the comment where `analyze_shots` writes it --
# and exists so `stage` has somewhere to be between the last `windows` shot and `completed`
# rather than jumping straight from "windows, shot 2638/2638" to "completed" with nothing
# between. These may be recalibrated once P4's own profiling has real evidence to calibrate
# them against; until then this is a deterministic, documented placeholder, not a measurement.
STAGE_WEIGHTS: dict[str, dict[str, float]] = {
    "shots": {"encode": 0.30, "label": 0.30, "windows": 0.39, "finalize": 0.01},
    "index": {"index": 1.0},
    "derivatives": {"derivatives": 1.0},
    "music": {"music": 1.0},
}
# However close the weighted sum below gets to 1.0, nothing but `status == "completed"` may ever
# read as fully done: `_measure_shot_windows` finishing its last shot is not the same instant as
# `_run_job` writing `completed`, and the gap between them is exactly where the false "100%,
# then stalled" reading this package exists to fix came from.
NON_TERMINAL_PROGRESS_CAP = 0.99


def _stage_progress(processed: Any, total: Any) -> float | None:
    """`processed/total` inside the current stage, or `None` when `total` is not a real count.

    Never invented: a stage that cannot count its own work in advance (none of this codebase's
    job kinds currently work that way, but the contract allows for one) reports `None` here
    rather than a percentage nothing measured.
    """
    if not isinstance(processed, int) or not isinstance(total, int) or total <= 0:
        return None
    return max(0.0, min(1.0, processed / total))


def _overall_progress(kind: str, stage: str, stage_progress: float | None, status: str) -> float:
    """The one number `progress`/`overall_progress` in the response actually carries.

    Monotonic within a job and across its stage transitions: each stage's full weight is only
    ever added once it is genuinely behind the current stage in that kind's `STAGE_ORDER`, so a
    transition from `encode` to `label` cannot read as a drop, and `windows` starting cannot
    read as `encode`+`label` costing anything less than they already earned. Never 1.0 outside
    `status == "completed"` -- see `NON_TERMINAL_PROGRESS_CAP`.
    """
    if status == "completed":
        return 1.0
    order = STAGE_ORDER.get(kind)
    weights = STAGE_WEIGHTS.get(kind)
    if not order or not weights or stage not in weights:
        # An unrecognised stage (a pre-P2 job row that never recorded one, or a job kind this
        # table does not know) has nothing better to report than its own stage_progress, honestly
        # capped -- not zero, which would look like no work has happened at all.
        return min(stage_progress if stage_progress is not None else 0.0, NON_TERMINAL_PROGRESS_CAP)
    completed_weight = sum(weights[s] for s in order[: order.index(stage)])
    value = completed_weight + weights[stage] * (stage_progress if stage_progress is not None else 0.0)
    return min(value, NON_TERMINAL_PROGRESS_CAP)


def _job_payload(job: dict[str, Any]) -> dict[str, Any]:
    checkpoint = json.loads(job.pop("checkpoint_json"))
    job["checkpoint"] = checkpoint
    status = job["status"]
    kind = job["kind"]

    stage = checkpoint.get("stage") or ("queued" if status == "queued" else "")
    processed = checkpoint.get("processed")
    total = checkpoint.get("total")
    stage_progress = _stage_progress(processed, total)

    job["stage"] = stage
    job["processed"] = processed if isinstance(processed, int) else None
    job["total"] = total if isinstance(total, int) else None
    job["stage_progress"] = stage_progress
    overall_progress = _overall_progress(kind, stage, stage_progress, status)
    job["overall_progress"] = overall_progress
    # The field every existing consumer (backend tests, the desktop app) already reads. Same
    # name, same JSON position, same 0..1 float -- what changed is that this now always agrees
    # with `overall_progress` instead of a formula that could reach 1.0 hours before the job
    # that computed it was actually done.
    job["progress"] = overall_progress

    job["current_asset_id"] = checkpoint.get("current_asset_id") or checkpoint.get("last_asset_id")
    job["current_asset_display"] = checkpoint.get("current_asset_display")
    job["current_shot_id"] = checkpoint.get("last_shot_id")
    job["current_shot_index"] = checkpoint.get("last_shot_index")

    job["last_progress_at"] = job.get("last_progress_at")
    job["last_heartbeat_at"] = job.get("last_heartbeat_at")

    if status in TERMINAL_STATUSES:
        job["stalled"] = False
    elif status == "queued":
        # Nothing has run yet, so there is no heartbeat to check -- a queued job is only ever
        # "stalled" in the sense of "the backend has not picked it up", measured off when it was
        # created rather than a liveness signal that does not exist yet.
        created = datetime.fromisoformat(job["created_at"])
        job["stalled"] = (datetime.now(UTC) - created).total_seconds() > STALLED_JOB_SECONDS
    else:
        # `running` and `cancel_requested` both mean a worker owns this job and is expected to
        # be checking in -- `cancel_requested` is not yet settled, so it is judged the same way.
        # `last_heartbeat_at` first; `updated_at` only for a row from before this column existed
        # or one `recover_orphaned_jobs` never gave a heartbeat to attribute this failure to.
        heartbeat = job.get("last_heartbeat_at") or job["updated_at"]
        age = (datetime.now(UTC) - datetime.fromisoformat(heartbeat)).total_seconds()
        job["stalled"] = age > STALLED_JOB_SECONDS
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


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str) -> dict[str, Any]:
    """Ask a job to stop. Cooperative: this returns as soon as the request is recorded, not
    when the worker actually stops — the caller polls `GET /api/jobs/{job_id}` for that, the
    same way it already polls for progress.

    Addressed by job id alone, the same shape as `read_job` above and deliberately not
    `/api/projects/{project_id}/jobs/{job_id}/cancel`: a job's `project_id` is immutable and
    already stored on the row `_run_job` reads, so there is no ambient "current project" this
    endpoint could be confused about the way project creation was. Accepting a `project_id`
    from the caller here would only add a second, possibly stale opinion about who owns a job
    that already has one, unambiguous answer sitting in the database.
    """
    job = DATABASE.fetch_one("SELECT * FROM jobs WHERE id = ?", (job_id,))
    if job is None:
        raise HTTPException(status_code=404, detail="Job bulunamadı.")

    status = job["status"]
    if status in TERMINAL_STATUSES or status == "cancel_requested":
        # Idempotent: asking twice, or asking after it already finished on its own, is not an
        # error — it is the answer "there is nothing left to cancel", reported honestly.
        return _job_payload(job)
    if status == "queued":
        # No worker has started this job yet — there is nothing to cooperate with, so it can
        # be settled immediately rather than waiting for a `_run_job` call that has not
        # happened yet to notice a request it might never check for.
        DATABASE.transition_job(job_id, "cancelled", from_statuses=frozenset({"queued"}))
    elif status == "running":
        DATABASE.transition_job(job_id, "cancel_requested", from_statuses=frozenset({"running"}))
    else:
        raise HTTPException(status_code=409, detail=f"Bilinmeyen job durumu: {status!r}")

    refreshed = DATABASE.fetch_one("SELECT * FROM jobs WHERE id = ?", (job_id,))
    return _job_payload(refreshed)


class RejectionRequest(BaseModel):
    """Clips the editor has looked at and does not want the edit to use."""

    clips: list[str] = Field(default_factory=list)
    reason: str = ""


@app.get("/api/projects/{project_id}/rejections")
def list_rejections(project_id: str) -> dict[str, Any]:
    _project(project_id)
    return {"clips": rejected_names(DATABASE, project_id)}


@app.post("/api/projects/{project_id}/rejections")
def add_rejections(project_id: str, request: RejectionRequest) -> dict[str, Any]:
    """Take clips out of every future edit of this project.

    Unrecognised names come back rather than failing the call: the editor is typing clip names
    off a Resolve timeline and a typo should say so, not lose the ones that were right.
    """
    _project(project_id)
    DATABASE.migrate()
    taken, unknown = reject_clips(DATABASE, project_id, request.clips, request.reason)
    return {
        "clips": rejected_names(DATABASE, project_id),
        "added": taken,
        "unknown": unknown,
    }


@app.delete("/api/projects/{project_id}/rejections")
def remove_rejections(project_id: str, request: RejectionRequest) -> dict[str, Any]:
    _project(project_id)
    DATABASE.migrate()
    restore_clips(DATABASE, project_id, request.clips)
    return {"clips": rejected_names(DATABASE, project_id)}


# The panel is served from "/", which swallows every route declared after it, so this mount
# stays the last thing in the file. Endpoints added below it are silently dead: the rejection
# routes were, and answered 404 on a freshly started engine.
REACT_ROOT = Path(__file__).resolve().parents[2] / "desktop" / "dist"
STATIC_ROOT = REACT_ROOT if (REACT_ROOT / "index.html").is_file() else Path(__file__).parent / "static"
if STATIC_ROOT.is_dir():
    app.mount("/", StaticFiles(directory=STATIC_ROOT, html=True), name="frontend")
