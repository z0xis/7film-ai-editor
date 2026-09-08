"""Small SQLite repository with explicit schema migrations and JSON payload columns."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    workspace_path TEXT NOT NULL,
    target_duration_seconds TEXT NOT NULL,
    frame_rate TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS media_assets (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    path TEXT NOT NULL,
    file_name TEXT NOT NULL,
    content_hash TEXT,
    duration_seconds TEXT NOT NULL,
    frame_rate TEXT NOT NULL,
    width INTEGER NOT NULL DEFAULT 0,
    height INTEGER NOT NULL DEFAULT 0,
    codec TEXT,
    timecode TEXT,
    proxy_path TEXT,
    thumbnail_path TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    UNIQUE(project_id, path)
);

CREATE TABLE IF NOT EXISTS shots (
    id TEXT PRIMARY KEY,
    asset_id TEXT NOT NULL REFERENCES media_assets(id) ON DELETE CASCADE,
    start_frame INTEGER NOT NULL,
    duration_frames INTEGER NOT NULL,
    frame_rate TEXT NOT NULL,
    category TEXT NOT NULL,
    shot_scale TEXT NOT NULL,
    technical_quality REAL NOT NULL,
    aesthetic_score REAL NOT NULL,
    motion_score REAL NOT NULL,
    confidence REAL NOT NULL,
    duplicate_group TEXT,
    labels_json TEXT NOT NULL DEFAULT '[]',
    analysis_version TEXT NOT NULL DEFAULT '',
    brightness REAL NOT NULL DEFAULT 0,
    saturation REAL NOT NULL DEFAULT 0,
    highlight_clipping REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

-- The expensive half of shot analysis: decoding the video, measuring the frames and running
-- them through CLIP. Keeping the embedding means a re-label costs seconds instead of hours,
-- and lets the encoding pass resume where it stopped.
CREATE TABLE IF NOT EXISTS shot_features (
    shot_id TEXT PRIMARY KEY,
    asset_id TEXT NOT NULL REFERENCES media_assets(id) ON DELETE CASCADE,
    start_frame INTEGER NOT NULL,
    duration_frames INTEGER NOT NULL,
    frame_rate TEXT NOT NULL,
    embedding BLOB,
    metrics_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS shot_features_asset ON shot_features(asset_id, start_frame);

CREATE TABLE IF NOT EXISTS music_tracks (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    path TEXT NOT NULL,
    duration_seconds TEXT NOT NULL,
    bpm REAL NOT NULL,
    beats_json TEXT NOT NULL,
    sections_json TEXT NOT NULL DEFAULT '[]',
    analysis_version TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE(project_id, path)
);

CREATE TABLE IF NOT EXISTS timeline_versions (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    target_duration_seconds TEXT NOT NULL,
    frame_rate TEXT NOT NULL,
    seed INTEGER NOT NULL,
    warnings_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS timeline_items (
    id TEXT PRIMARY KEY,
    timeline_id TEXT NOT NULL REFERENCES timeline_versions(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    -- Deliberately not enforced: re-analysing the footage replaces every shot row, and a
    -- rough cut the editor has already been given must survive that. The descriptive fields
    -- below are the item's own copy, and get_timeline reads shots with a LEFT JOIN.
    shot_id TEXT NOT NULL,
    asset_id TEXT NOT NULL REFERENCES media_assets(id),
    source_start_frame INTEGER NOT NULL,
    source_duration_frames INTEGER NOT NULL,
    source_rate TEXT NOT NULL,
    timeline_start_frame INTEGER NOT NULL,
    timeline_duration_frames INTEGER NOT NULL,
    score REAL NOT NULL,
    reason TEXT NOT NULL,
    alternatives_json TEXT NOT NULL DEFAULT '[]',
    category TEXT NOT NULL DEFAULT '',
    shot_scale TEXT NOT NULL DEFAULT ''
);

-- What a shot looks like along its length, half a second at a time.
--
-- Until this existed a shot was judged on three frames spanning 0.2 seconds taken from its
-- middle, and its framing on the single frame between them; the planner then cut a segment
-- out of it by arithmetic, always starting a fixed handle after the shot began. Measured on
-- six clips the editor complained about, the bad moment was inside the cut and the
-- measurement had never looked at it: a head against the frame edge (0.76 and 1.00 where the
-- stored value was 0.00), a whip at 9 sharpness against the shoot's 45-78, a bystander
-- standing in a doorway.
--
-- Rows are optional. A shot with none is planned the way it always was.
CREATE TABLE IF NOT EXISTS shot_windows (
    shot_id TEXT NOT NULL,
    offset_frames INTEGER NOT NULL,
    sharpness REAL NOT NULL DEFAULT 0,
    motion REAL NOT NULL DEFAULT 0,
    face_ratio REAL NOT NULL DEFAULT 0,
    face_edge REAL NOT NULL DEFAULT 0,
    face_count INTEGER NOT NULL DEFAULT 0,
    bystanders INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (shot_id, offset_frames)
);

-- Clips and shots the editor has told the edit to leave alone.
--
-- Some of what makes a shot unusable is not measurable here at any sensible cost. A man
-- standing in a doorway is fifteen ten-thousandths of the frame and vanishes in the proxies;
-- finding him needs the 4K originals, at 661ms a frame. A bride catching her step has no
-- measure at all. The editor sees both in a second, so this is where that judgement is kept.
--
-- A row with shot_id NULL rejects the whole clip, which is the usual case: what is wrong is
-- normally wrong throughout.
CREATE TABLE IF NOT EXISTS rejections (
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    asset_id TEXT NOT NULL REFERENCES media_assets(id) ON DELETE CASCADE,
    shot_id TEXT,
    reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS rejections_unique
    ON rejections (project_id, asset_id, IFNULL(shot_id, ''));

-- Who is in which clip.
--
-- The identity comes from Resolve's face analysis, which labels the same person consistently
-- across a shoot; the *name* does not, because Resolve will not take one through the API and
-- asking the editor to label anything defeats the tool. The role is worked out from our own
-- shot categories and stored beside the identity, with the counts it was decided from, so a
-- wrong match can be seen rather than trusted.
--
-- Kept per asset rather than per shot because that is the grain Resolve reports at.
CREATE TABLE IF NOT EXISTS asset_people (
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    asset_id TEXT NOT NULL REFERENCES media_assets(id) ON DELETE CASCADE,
    identity TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS asset_people_unique
    ON asset_people (project_id, asset_id, identity);

-- What each identity turned out to be. `role` is 'bride', 'groom' or 'couple?' — the last
-- meaning the evidence did not lean far enough to say.
CREATE TABLE IF NOT EXISTS people_roles (
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    identity TEXT NOT NULL,
    role TEXT NOT NULL,
    clips INTEGER NOT NULL,
    bride_shots INTEGER NOT NULL,
    groom_shots INTEGER NOT NULL,
    created_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS people_roles_unique
    ON people_roles (project_id, identity);

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    status TEXT NOT NULL,
    progress REAL NOT NULL DEFAULT 0,
    checkpoint_json TEXT NOT NULL DEFAULT '{}',
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


# Columns added after the first release; migrate() adds any that an existing file is missing.
ADDED_COLUMNS = (
    ("shots", "brightness", "REAL NOT NULL DEFAULT 0"),
    ("shots", "saturation", "REAL NOT NULL DEFAULT 0"),
    ("shots", "highlight_clipping", "REAL NOT NULL DEFAULT 0"),
    # A saved rough cut keeps its own copy of what each clip is, so re-analysing the footage
    # cannot quietly hollow it out. See get_timeline, which reads shots with a LEFT JOIN.
    ("timeline_items", "category", "TEXT NOT NULL DEFAULT ''"),
    ("timeline_items", "shot_scale", "TEXT NOT NULL DEFAULT ''"),
    # Stamped with the analysis semantics that produced the row, so work left over from an
    # older version can be recognised instead of quietly producing a worse edit.
    ("shots", "analysis_version", "TEXT NOT NULL DEFAULT ''"),
    ("music_tracks", "analysis_version", "TEXT NOT NULL DEFAULT ''"),
    # A saved rough cut keeps the songs it was cut to, and which part of each was used. Reading
    # "the newest music row" back instead would hand an old timeline whatever was imported since.
    ("timeline_versions", "music_segments_json", "TEXT NOT NULL DEFAULT '[]'"),
    # Where a song sits in the running order the editor chose. One song leaves it at 0.
    ("music_tracks", "position", "INTEGER NOT NULL DEFAULT 0"),
    # What the face detector already knew and nothing kept: how big the subject is, and whether
    # the frame cuts it. Zero reads as "no face" and as "measured before this existed" alike.
    ("shots", "face_ratio", "REAL NOT NULL DEFAULT 0"),
    ("shots", "face_edge", "REAL NOT NULL DEFAULT 0"),
)


def now() -> str:
    return datetime.now(UTC).isoformat()


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def migrate(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as connection:
            connection.executescript(SCHEMA)
            self._add_missing_columns(connection)

    @staticmethod
    def _add_missing_columns(connection: sqlite3.Connection) -> None:
        """Widen tables created by an earlier version without touching their rows."""
        for table, column, definition in ADDED_COLUMNS:
            existing = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
            if column not in existing:
                connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        with self.connection() as connection:
            connection.execute(sql, params)

    def fetch_one(self, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        with self.connection() as connection:
            row = connection.execute(sql, params).fetchone()
        return dict(row) if row else None

    def fetch_all(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self.connection() as connection:
            rows = connection.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def insert(self, table: str, values: dict[str, Any]) -> None:
        columns = ", ".join(values)
        placeholders = ", ".join("?" for _ in values)
        normalized = [json.dumps(v) if isinstance(v, (list, dict)) else v for v in values.values()]
        self.execute(f"INSERT INTO {table} ({columns}) VALUES ({placeholders})", tuple(normalized))

    def update_job(
        self,
        job_id: str,
        *,
        status: str,
        progress: float,
        checkpoint: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        sql = "UPDATE jobs SET status = ?, progress = ?, updated_at = ?, error = ?"
        params: list[Any] = [status, progress, now(), error]
        if checkpoint is not None:
            sql += ", checkpoint_json = ?"
            params.append(json.dumps(checkpoint))
        sql += " WHERE id = ?"
        params.append(job_id)
        self.execute(sql, tuple(params))

