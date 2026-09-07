import sys
from pathlib import Path

# The import below is absolute from the repository root rather than from apps/api, so the
# root has to be on the path before it runs. Ruff sorts around the statement, not through it.
sys.path.insert(0, str(Path(__file__).parent.parent))

from apps.api.sevenfilm.api import _normalize_path  # noqa: I001

def test_normalize_path_plain():
    path = "/Users/foo/bar.mp3"
    assert _normalize_path(path) == Path("/Users/foo/bar.mp3")

def test_normalize_path_file_uri():
    path = "file:///Users/foo/bar.mp3"
    assert _normalize_path(path) == Path("/Users/foo/bar.mp3")

def test_normalize_path_file_localhost_uri():
    path = "file://localhost/Users/foo/bar.mp3"
    assert _normalize_path(path) == Path("/Users/foo/bar.mp3")

def test_normalize_path_file_single_slash():
    path = "file:/Users/foo/bar.mp3"
    assert _normalize_path(path) == Path("/Users/foo/bar.mp3")

def test_normalize_path_url_encoded():
    path = "file:/Users/foo/Calum%20Scott.mp3"
    assert _normalize_path(path) == Path("/Users/foo/Calum Scott.mp3")

def test_normalize_path_home_expansion():
    path = "~/Desktop/file.mp4"
    expected = Path.home() / "Desktop/file.mp4"
    assert _normalize_path(path) == expected
