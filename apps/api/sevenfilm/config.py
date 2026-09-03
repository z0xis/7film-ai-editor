from __future__ import annotations

import os
from pathlib import Path


def data_root() -> Path:
    """Return a project-owned data directory, never a source-media directory."""
    configured = os.environ.get("SEVENFILM_DATA_ROOT")
    root = Path(configured).expanduser() if configured else Path.cwd() / "data"
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def database_path() -> Path:
    return data_root() / "sevenfilm.sqlite3"

