#!/usr/bin/env python3
"""Report missing local prerequisites before a first real media project."""

import sys
from importlib.util import find_spec
from shutil import which

print(f"Python: {sys.version.split()[0]} ({'OK' if sys.version_info >= (3, 12) else 'Python 3.12+ gerekli'})")
for binary in ("ffmpeg", "ffprobe"):
    print(f"{binary}: {which(binary) or 'BULUNAMADI'}")
for package in ("fastapi", "uvicorn", "pydantic", "scenedetect", "librosa", "opentimelineio"):
    print(f"{package}: {'OK' if find_spec(package) else 'BULUNAMADI'}")

