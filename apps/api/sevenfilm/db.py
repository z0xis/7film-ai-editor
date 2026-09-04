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

