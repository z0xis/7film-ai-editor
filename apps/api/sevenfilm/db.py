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
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS music_tracks (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    path TEXT NOT NULL,
    duration_seconds TEXT NOT NULL,
    bpm REAL NOT NULL,
    beats_json TEXT NOT NULL,
    sections_json TEXT NOT NULL DEFAULT '[]',
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
    shot_id TEXT NOT NULL REFERENCES shots(id),
    asset_id TEXT NOT NULL REFERENCES media_assets(id),
    source_start_frame INTEGER NOT NULL,
    source_duration_frames INTEGER NOT NULL,
    source_rate TEXT NOT NULL,
    timeline_start_frame INTEGER NOT NULL,
    timeline_duration_frames INTEGER NOT NULL,
    score REAL NOT NULL,
    reason TEXT NOT NULL,
    alternatives_json TEXT NOT NULL DEFAULT '[]'
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

