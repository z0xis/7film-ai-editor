"""Build a deterministic pacing/beat style profile from finished reference edits."""

from __future__ import annotations

import argparse
import json
import subprocess
from bisect import bisect_left
from pathlib import Path

import cv2  # type: ignore[import-not-found]
import librosa  # type: ignore[import-not-found]
import numpy as np  # type: ignore[import-not-found]
from scenedetect import SceneManager, open_video  # type: ignore[import-not-found]
from scenedetect.detectors import AdaptiveDetector  # type: ignore[import-not-found]


def audio_samples(path: Path, sample_rate: int = 22050) -> np.ndarray:
    result = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", str(sample_rate), "-f", "f32le", "-"],
        check=True,
        capture_output=True,
    )
    return np.frombuffer(result.stdout, dtype=np.float32)


def nearest_distance(value: float, points: list[float]) -> float:
    if not points:
        return float("inf")
    index = bisect_left(points, value)
    candidates = points[max(0, index - 1) : min(len(points), index + 1)]
    return min(abs(value - point) for point in candidates)


def visual_summary(path: Path, duration: float) -> dict[str, float]:
    capture = cv2.VideoCapture(str(path))
    brightness: list[float] = []
    saturation: list[float] = []
    motion: list[float] = []
    previous = None
    for second in np.linspace(0, max(0.0, duration - 0.1), num=max(2, min(180, int(duration) + 1))):
        capture.set(cv2.CAP_PROP_POS_MSEC, float(second) * 1000)
        ok, frame = capture.read()
        if not ok:
            continue
        frame = cv2.resize(frame, (160, 90))
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        brightness.append(float(hsv[..., 2].mean() / 255))
        saturation.append(float(hsv[..., 1].mean() / 255))
        if previous is not None:
            motion.append(float(cv2.absdiff(gray, previous).mean() / 255))
        previous = gray
    capture.release()
    return {
        "mean_brightness": round(float(np.mean(brightness)), 4) if brightness else 0.0,
        "mean_saturation": round(float(np.mean(saturation)), 4) if saturation else 0.0,
        "mean_visual_change": round(float(np.mean(motion)), 4) if motion else 0.0,
    }


def analyze_video(path: Path, info: dict[str, object]) -> dict[str, object]:
    video = open_video(str(path))
    manager = SceneManager()
    manager.add_detector(AdaptiveDetector(adaptive_threshold=3.0, min_scene_len=6, min_content_val=12.0))
    manager.detect_scenes(video=video, show_progress=False)
    scenes = manager.get_scene_list(start_in_scene=True)
    duration = float(info.get("duration") or video.duration.get_seconds())
    ranges = [(start.seconds, end.seconds) for start, end in scenes]
    shot_durations = [end - start for start, end in ranges if end > start]

    samples = audio_samples(path)
    tempo, beat_frames = librosa.beat.beat_track(y=samples, sr=22050, units="frames")
    beat_times = [float(value) for value in librosa.frames_to_time(beat_frames, sr=22050)]
    cuts = [start for start, _end in ranges[1:]]
    distances = [nearest_distance(cut, beat_times) for cut in cuts]
    section_durations: dict[str, list[float]] = {key: [] for key in ("intro", "build", "core", "finale")}
    section_names = tuple(section_durations)
    for start, end in ranges:
        section_index = min(3, int((start / max(duration, 0.001)) * 4))
        section_durations[section_names[section_index]].append(end - start)

    bpm = float(tempo.item() if hasattr(tempo, "item") else tempo)
    return {
        "id": info.get("id") or path.stem,
        "title": info.get("title") or path.stem,
        "url": info.get("webpage_url"),
        "duration_seconds": round(duration, 3),
        "detected_shots": len(shot_durations),
        "bpm": round(bpm, 3),
        "median_shot_duration_seconds": round(float(np.median(shot_durations)), 3),
        "shot_duration_p25_seconds": round(float(np.quantile(shot_durations, 0.25)), 3),
        "shot_duration_p75_seconds": round(float(np.quantile(shot_durations, 0.75)), 3),
        "beat_alignment_ratio_120ms": round(float(np.mean(np.array(distances) <= 0.12)), 4) if distances else 0.0,
        "beat_alignment_ratio_200ms": round(float(np.mean(np.array(distances) <= 0.20)), 4) if distances else 0.0,
        "section_median_shot_duration_seconds": {
            key: round(float(np.median(values)), 3) if values else None for key, values in section_durations.items()
        },
        **visual_summary(path, duration),
        "shot_durations_seconds": [round(value, 3) for value in shot_durations],
    }


def build_profile(media_dir: Path, info_dir: Path) -> dict[str, object]:
    videos = []
    for media_path in sorted(media_dir.glob("*")):
        if not media_path.is_file() or media_path.suffix.lower() not in {".mkv", ".mp4", ".webm", ".mov"}:
            continue
        info_path = next(info_dir.glob(f"*-{media_path.stem}.info.json"), None)
        info = json.loads(info_path.read_text()) if info_path else {"id": media_path.stem}
        print(f"Analiz: {info.get('title', media_path.stem)}", flush=True)
        videos.append(analyze_video(media_path, info))

    all_durations = [value for video in videos for value in video["shot_durations_seconds"]]
    section_profile = {}
    for section in ("intro", "build", "core", "finale"):
        values = [video["section_median_shot_duration_seconds"][section] for video in videos]
        usable = [value for value in values if value is not None]
        section_profile[section] = round(float(np.median(usable)), 3) if usable else None
    median_bpm = float(np.median([video["bpm"] for video in videos]))
    p25 = float(np.quantile(all_durations, 0.25))
    median = float(np.median(all_durations))
    p75 = float(np.quantile(all_durations, 0.75))
    return {
        "schema_version": "1.0",
        "name": "7Film Reference Style",
        "reference_count": len(videos),
        "total_reference_duration_seconds": round(sum(video["duration_seconds"] for video in videos), 3),
        "detected_shot_count": sum(video["detected_shots"] for video in videos),
        "median_reference_bpm": round(median_bpm, 3),
        "median_shot_duration_seconds": round(median, 3),
        "shot_duration_p25_seconds": round(p25, 3),
        "shot_duration_p75_seconds": round(p75, 3),
        "section_median_shot_duration_seconds": section_profile,
        "beat_alignment_ratio_120ms": round(float(np.mean([video["beat_alignment_ratio_120ms"] for video in videos])), 4),
        "beat_alignment_ratio_200ms": round(float(np.mean([video["beat_alignment_ratio_200ms"] for video in videos])), 4),
        "beats_per_cut": {
            "low": max(1, round(p75 * median_bpm / 60)),
            "medium": max(1, round(median * median_bpm / 60)),
            "high": max(1, round(p25 * median_bpm / 60)),
        },
        "visual_profile": {
            "mean_brightness": round(float(np.mean([video["mean_brightness"] for video in videos])), 4),
            "mean_saturation": round(float(np.mean([video["mean_saturation"] for video in videos])), 4),
            "mean_visual_change": round(float(np.mean([video["mean_visual_change"] for video in videos])), 4),
        },
        "references": videos,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--media-dir", type=Path, required=True)
    parser.add_argument("--info-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    profile = build_profile(args.media_dir, args.info_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in profile.items() if key != "references"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
