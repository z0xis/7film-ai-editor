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


STORY_BANDS = 10


def story_arc(paths: list[Path]) -> list[dict[str, float]] | None:
    """What the reference films show at each tenth of their length.

    Until this existed the profile carried only rhythm and colour — cut lengths, beats per cut,
    brightness — and the story order the planner worked to was written by hand rather than read
    off the films. An edit built from it put the shots on the beat and nothing else.

    Sampled every 1.5 seconds and read with the same classifier and the same prompt-prior
    correction the footage gets. Twelve frames were pulled out and checked by eye across three
    categories and three parts of the film: eleven were plainly right and one was arguable, so
    the categories carry across the grade even though the shot scale does not.
    """
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))
    from sevenfilm.services.vision import CATEGORY_PROMPTS, VisionClassifier, measure_frames

    classifier = VisionClassifier()
    if not classifier._load():
        return None
    frames: list[np.ndarray] = []
    progress: list[float] = []
    for path in paths:
        capture = cv2.VideoCapture(str(path))
        rate = capture.get(cv2.CAP_PROP_FPS) or 25
        total = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        for frame_number in range(0, total, max(1, int(rate * 1.5))):
            capture.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
            ok, image = capture.read()
            if ok:
                frames.append(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
                progress.append(frame_number / total)
        capture.release()
    if not frames:
        return None
    features = classifier.encode(frames)
    metrics = [measure_frames([frame]) for frame in frames]
    labelled = classifier.classify_features(features, metrics, classifier.prompt_priors(features))
    bands = [dict.fromkeys(CATEGORY_PROMPTS, 0.0) for _ in range(STORY_BANDS)]
    counts = [0] * STORY_BANDS
    for result, position in zip(labelled, progress, strict=True):
        band = min(STORY_BANDS - 1, int(position * STORY_BANDS))
        bands[band][str(result["category"])] += 1
        counts[band] += 1
    return [
        {name: round(value / count, 4) for name, value in band.items()}
        for band, count in zip(bands, counts, strict=True)
        if count
    ]


HELD_SHOT_SECONDS = 3.0


def held_shot_profile(videos: list[dict[str, object]], bands: int = STORY_BANDS) -> dict[str, object]:
    """How much of each part of a reference film is spent on a shot that is simply held.

    The profile described the middle of the cut distribution and nothing else, so an edit built
    from it came out uniformly around a second: median 0.96s, longest cut 2.48s, nothing over
    three seconds anywhere. The references are not like that. A quarter of their total running
    time sits in shots longer than three seconds, they reach 19 seconds, and those shots are not
    spread evenly — they open the film and they close it.

    Measured across the 18 references: 38% of the first tenth and 56% of the last tenth is held,
    against 10-19% through the middle. That shape is the difference between an edit that has an
    entrance and a slow passage and one that only ever runs on the beat.
    """
    held = [0.0] * bands
    total = [0.0] * bands
    lengths: list[float] = []
    by_band: list[list[float]] = [[] for _ in range(bands)]
    for video in videos:
        durations = list(video["shot_durations_seconds"])
        running = sum(durations)
        if running <= 0:
            continue
        elapsed = 0.0
        for duration in durations:
            band = min(bands - 1, int((elapsed + duration / 2) / running * bands))
            total[band] += duration
            if duration > HELD_SHOT_SECONDS:
                held[band] += duration
                lengths.append(duration)
                by_band[band].append(duration)
            elapsed += duration
    if not lengths:
        return {}
    return {
        "threshold_seconds": HELD_SHOT_SECONDS,
        "share_by_band": [
            round(held[band] / total[band], 4) if total[band] else 0.0 for band in range(bands)
        ],
        "median_seconds": round(float(np.median(lengths)), 3),
        "p90_seconds": round(float(np.quantile(lengths, 0.9)), 3),
        # How long a hold runs where it happens. The references hold longest at the two ends,
        # so one figure for the whole film makes the opening and the ending too brisk.
        "median_seconds_by_band": [
            round(float(np.median(values)), 3) if values else None for values in by_band
        ],
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
    media_paths: list[Path] = []
    for media_path in sorted(media_dir.glob("*")):
        if not media_path.is_file() or media_path.suffix.lower() not in {".mkv", ".mp4", ".webm", ".mov"}:
            continue
        info_path = next(info_dir.glob(f"*-{media_path.stem}.info.json"), None)
        info = json.loads(info_path.read_text()) if info_path else {"id": media_path.stem}
        print(f"Analiz: {info.get('title', media_path.stem)}", flush=True)
        media_paths.append(media_path)
        videos.append(analyze_video(media_path, info))

    print("Hikâye akışı ölçülüyor...", flush=True)
    arc = story_arc(media_paths)

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
        "schema_version": "1.1",
        "name": "7Film Reference Style",
        "reference_count": len(videos),
        "total_reference_duration_seconds": round(sum(video["duration_seconds"] for video in videos), 3),
        "detected_shot_count": sum(video["detected_shots"] for video in videos),
        "median_reference_bpm": round(median_bpm, 3),
        "median_shot_duration_seconds": round(median, 3),
        # What the references show at each tenth of their length, so the planner reads the
        # story order off the films instead of a list written by hand.
        "story_arc": arc,
        # How long the references hold a shot, and where in the film they do it.
        "held_shots": held_shot_profile(videos),
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
