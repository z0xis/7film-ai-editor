"""Safe local media indexing and derivative generation."""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import subprocess
import uuid
from collections.abc import Iterator
from fractions import Fraction
from pathlib import Path
from typing import Any

from ..db import Database, now
from ..domain import MediaAsset
from ..timebase import FrameRate

LOGGER = logging.getLogger(__name__)
VIDEO_EXTENSIONS = {".avi", ".m2ts", ".m4v", ".mkv", ".mov", ".mp4", ".mpeg", ".mpg", ".mts", ".webm"}
AUDIO_EXTENSIONS = {".aac", ".aif", ".aiff", ".flac", ".m4a", ".mp3", ".ogg", ".wav"}


class MediaToolUnavailable(RuntimeError):
    pass


# ffprobe exits non-zero on a file it cannot read, and metadata_from_probe raises when a file
# has no video stream or no duration. A card that filled mid-recording leaves exactly that, and
# one of them used to abort the whole job before anything was indexed.
UNREADABLE_MEDIA = (subprocess.CalledProcessError, ValueError, json.JSONDecodeError)


def require_tool(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise MediaToolUnavailable(
            f"{name} PATH içinde bulunamadı. FFmpeg kurulumunu tamamlayıp uygulamayı yeniden başlatın."
        )
    return path


def hash_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    """Full SHA-256: identical source files collapse reliably, not approximately."""
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def iter_media_files(folder: Path, extensions: set[str]) -> Iterator[Path]:
    for path in folder.rglob("*"):
        if path.is_file() and path.suffix.lower() in extensions:
            yield path.resolve()


def probe(path: Path) -> dict[str, Any]:
    ffprobe = require_tool("ffprobe")
    command = [
        ffprobe,
        "-v",
        "error",
        "-show_format",
        "-show_streams",
        "-of",
        "json",
        str(path),
    ]
    completed = subprocess.run(command, check=True, capture_output=True, text=True)
    return json.loads(completed.stdout)


def _first_video_stream(payload: dict[str, Any]) -> dict[str, Any]:
    stream = next((item for item in payload.get("streams", []) if item.get("codec_type") == "video"), None)
    if stream is None:
        raise ValueError(f"Video stream bulunamadı: {payload.get('format', {}).get('filename', 'bilinmeyen dosya')}")
    return stream


def _start_timecode(payload: dict[str, Any]) -> str | None:
    """Find the recorded start timecode wherever the camera put it.

    Sony XAVC writes it to a separate real-time metadata track, not to the video stream, so
    reading only the video stream's tags missed it on every clip of this shoot. Resolve reads
    it, and conforming against the original media depends on the two agreeing.
    """
    for stream in payload.get("streams", []):
        timecode = (stream.get("tags") or {}).get("timecode")
        if timecode:
            return str(timecode)
    timecode = (payload.get("format", {}).get("tags") or {}).get("timecode")
    return str(timecode) if timecode else None


def metadata_from_probe(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    stream = _first_video_stream(payload)
    raw_rate = stream.get("avg_frame_rate") or stream.get("r_frame_rate") or "25/1"
    if raw_rate == "0/0":
        raw_rate = "25/1"
    frame_rate = FrameRate.parse(raw_rate)
    raw_duration = stream.get("duration") or payload.get("format", {}).get("duration")
    if raw_duration is None:
        raise ValueError(f"Süre bilgisi bulunamadı: {path}")
    return {
        "duration": Fraction(str(raw_duration)),
        "frame_rate": frame_rate,
        "width": int(stream.get("width") or 0),
        "height": int(stream.get("height") or 0),
        "codec": stream.get("codec_name"),
        "timecode": _start_timecode(payload),
        "raw": payload,
    }


def row_to_asset(row: dict[str, Any]) -> MediaAsset:
    rate = FrameRate.parse(row["frame_rate"])
    return MediaAsset(
        id=row["id"],
        project_id=row["project_id"],
        path=Path(row["path"]),
        name=row["file_name"],
        duration=Fraction(row["duration_seconds"]),
        frame_rate=rate,
        width=int(row["width"]),
        height=int(row["height"]),
        codec=row.get("codec"),
        timecode=row.get("timecode"),
        content_hash=row.get("content_hash"),
    )


def project_assets(database: Database, project_id: str) -> list[MediaAsset]:
    rows = database.fetch_all("SELECT * FROM media_assets WHERE project_id = ? ORDER BY path", (project_id,))
    return [row_to_asset(row) for row in rows]


def index_folder(database: Database, project_id: str, folder: Path, job_id: str) -> list[MediaAsset]:
    """Index source files. No command in this function writes to source folders."""
    source_folder = folder.expanduser().resolve()
    if not source_folder.is_dir():
        raise ValueError(f"Medya klasörü bulunamadı: {source_folder}")
    candidates = list(iter_media_files(source_folder, VIDEO_EXTENSIONS))
    if not candidates:
        raise ValueError("Seçilen klasörde desteklenen video dosyası bulunamadı.")

    checkpoint_row = database.fetch_one("SELECT checkpoint_json FROM jobs WHERE id = ?", (job_id,))
    checkpoint = json.loads(checkpoint_row["checkpoint_json"]) if checkpoint_row else {}
    completed_paths = set(checkpoint.get("completed_paths", []))
    unreadable: list[str] = []
    for index, path in enumerate(candidates, start=1):
        if str(path) in completed_paths:
            continue
        existing = database.fetch_one(
            "SELECT id FROM media_assets WHERE project_id = ? AND path = ?", (project_id, str(path))
        )
        if existing is None:
            try:
                details = metadata_from_probe(path, probe(path))
            except UNREADABLE_MEDIA as error:
                # Skip it and keep going: the rest of the shoot is still worth indexing, and the
                # editor needs to be told which files were left out rather than losing the run.
                unreadable.append(str(path))
                LOGGER.warning(
                    json.dumps({"event": "media_unreadable", "project_id": project_id,
                                "path": str(path), "reason": type(error).__name__})
                )
                completed_paths.add(str(path))
                database.update_job(
                    job_id,
                    status="running",
                    progress=index / len(candidates),
                    checkpoint={"completed_paths": sorted(completed_paths),
                                "source_folder": str(source_folder),
                                "unreadable": sorted(unreadable)},
                )
                continue
            content_hash = hash_file(path)
            duplicate = database.fetch_one(
                "SELECT id, path FROM media_assets WHERE project_id = ? AND content_hash = ?",
                (project_id, content_hash),
            )
            if duplicate is not None:
                LOGGER.info(
                    json.dumps(
                        {
                            "event": "duplicate_media_skipped",
                            "project_id": project_id,
                            "path": str(path),
                            "canonical_path": duplicate["path"],
                        }
                    )
                )
                completed_paths.add(str(path))
                database.update_job(
                    job_id,
                    status="running",
                    progress=index / len(candidates),
                    checkpoint={"completed_paths": sorted(completed_paths), "source_folder": str(source_folder)},
                )
                continue
            asset_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"sevenfilm:{project_id}:{path}"))
            database.insert(
                "media_assets",
                {
                    "id": asset_id,
                    "project_id": project_id,
                    "path": str(path),
                    "file_name": path.name,
                    "content_hash": content_hash,
                    "duration_seconds": str(details["duration"]),
                    "frame_rate": f"{details['frame_rate'].numerator}/{details['frame_rate'].denominator}",
                    "width": details["width"],
                    "height": details["height"],
                    "codec": details["codec"],
                    "timecode": details["timecode"],
                    "metadata_json": details["raw"],
                    "created_at": now(),
                },
            )
        completed_paths.add(str(path))
        database.update_job(
            job_id,
            status="running",
            progress=index / len(candidates),
            checkpoint={"completed_paths": sorted(completed_paths), "source_folder": str(source_folder),
                        "unreadable": sorted(unreadable)},
        )
        LOGGER.info(json.dumps({"event": "media_indexed", "project_id": project_id, "path": str(path)}))
    assets = project_assets(database, project_id)
    if unreadable and not assets:
        raise ValueError(
            f"Seçilen klasördeki {len(unreadable)} dosyanın hiçbiri okunamadı. "
            "Dosyalar bozuk olabilir veya FFmpeg kurulumu eksik olabilir."
        )
    if unreadable:
        LOGGER.warning(json.dumps({"event": "media_unreadable_total", "project_id": project_id,
                                   "count": len(unreadable)}))
    return project_assets(database, project_id)


def derivative_paths(cache_root: Path, asset: MediaAsset) -> tuple[Path, Path]:
    proxy = cache_root / "proxies" / f"{asset.id}.mp4"
    thumbnail = cache_root / "thumbnails" / f"{asset.id}.jpg"
    proxy.parent.mkdir(parents=True, exist_ok=True)
    thumbnail.parent.mkdir(parents=True, exist_ok=True)
    return proxy, thumbnail


def generate_derivatives(database: Database, project_id: str, cache_root: Path, job_id: str) -> None:
    """Generate small derivatives with atomic temp files; resumable assets are skipped."""
    ffmpeg = require_tool("ffmpeg")
    assets = project_assets(database, project_id)
    if not assets:
        raise ValueError("Önce ham görüntüleri indeksleyin.")
    failed: list[str] = []
    for position, asset in enumerate(assets, start=1):
        proxy, thumbnail = derivative_paths(cache_root, asset)
        try:
            if not proxy.exists():
                proxy_temp = proxy.with_suffix(".partial.mp4")
                subprocess.run(
                    [
                        ffmpeg, "-y", "-i", str(asset.path), "-map", "0:v:0", "-an", "-vf",
                        "scale='min(1280,iw)':-2", "-c:v", "libx264", "-preset", "veryfast", "-crf", "28",
                        "-movflags", "+faststart", str(proxy_temp),
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                proxy_temp.replace(proxy)
            if not thumbnail.exists():
                thumbnail_temp = thumbnail.with_suffix(".partial.jpg")
                timestamp = str(float(asset.duration / 2))
                subprocess.run(
                    [ffmpeg, "-y", "-ss", timestamp, "-i", str(asset.path), "-frames:v", "1", "-q:v", "3", str(thumbnail_temp)],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                thumbnail_temp.replace(thumbnail)
        except (subprocess.CalledProcessError, OSError) as error:
            # One clip ffmpeg cannot transcode must not cost the whole shoot its proxies.
            failed.append(asset.name)
            LOGGER.warning(json.dumps({"event": "derivative_failed", "asset_id": asset.id,
                                       "path": str(asset.path), "reason": type(error).__name__}))
            database.update_job(
                job_id,
                status="running",
                progress=position / len(assets),
                checkpoint={"last_asset_id": asset.id, "failed": sorted(failed)},
            )
            continue
        database.execute(
            "UPDATE media_assets SET proxy_path = ?, thumbnail_path = ? WHERE id = ?",
            (str(proxy), str(thumbnail), asset.id),
        )
        database.update_job(
            job_id,
            status="running",
            progress=position / len(assets),
            checkpoint={"last_asset_id": asset.id, "failed": sorted(failed)},
        )
        LOGGER.info(json.dumps({"event": "derivatives_created", "asset_id": asset.id}))
    if failed and len(failed) == len(assets):
        raise ValueError(
            f"{len(failed)} dosyanın hiçbiri için proxy üretilemedi. FFmpeg kurulumunu doğrulayın."
        )
