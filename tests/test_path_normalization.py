import os
from pathlib import Path
import sys

# Add project root to path for absolute imports if needed
sys.path.insert(0, str(Path(__file__).parent.parent))
from apps.api.sevenfilm.api import _normalize_path

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
