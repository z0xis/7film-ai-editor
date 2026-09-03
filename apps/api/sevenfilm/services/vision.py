"""Local visual understanding for wedding footage.

CLIP provides semantic labels while OpenCV provides measurements that should not
depend on a language model: focus, exposure, contrast, motion and a perceptual hash.
The model is loaded lazily and cached by Hugging Face under the project runtime.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from itertools import pairwise
from typing import Any

import cv2  # type: ignore[import-not-found]
import numpy as np

LOGGER = logging.getLogger(__name__)
MODEL_NAME = "openai/clip-vit-base-patch32"

CATEGORY_PROMPTS = {
    "couple": "a cinematic wedding shot of the bride and groom together",
    "bride": "a cinematic wedding shot focused on the bride",
    "groom": "a cinematic wedding shot focused on the groom",
    "family": "a wedding shot of family members or wedding guests",
    "venue": "a wide establishing shot of a wedding venue or landscape",
    "detail": "a close detail shot of wedding rings flowers dress table or decoration",
    "ceremony": "a wedding ceremony vow aisle altar or ring exchange",
    "party": "a lively wedding reception dance floor celebration or party",
}

SCALE_PROMPTS = {
    "wide": "a wide establishing shot showing the whole scene",
    "medium": "a medium shot showing people from the waist up",
    "close_up": "a close-up portrait shot of a face",
    "detail": "an extreme close-up detail or macro shot of an object",
}

AESTHETIC_PROMPTS = (
    "a beautiful professional cinematic wedding film frame",
    "an accidental unusable poorly composed video frame",
)


@dataclass(frozen=True)
class FrameMetrics:
    technical_quality: float
    motion_score: float
    perceptual_hash: str
    face_count: int


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _perceptual_hash(frame: np.ndarray) -> str:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    small = cv2.resize(gray, (9, 8), interpolation=cv2.INTER_AREA)
    bits = small[:, 1:] > small[:, :-1]
    packed = np.packbits(bits.reshape(-1))
    return packed.tobytes().hex()


def measure_frames(frames: list[np.ndarray]) -> FrameMetrics:
    """Measure a shot from three representative BGR frames."""
    if not frames:
        return FrameMetrics(0.0, 0.0, "missing", 0)
    middle = frames[len(frames) // 2]
    gray = cv2.cvtColor(middle, cv2.COLOR_BGR2GRAY)
    gray_float = gray.astype(np.float32) / 255.0
    sharpness = 1.0 - math.exp(-float(cv2.Laplacian(gray, cv2.CV_64F).var()) / 280.0)
    mean_light = float(gray_float.mean())
    exposure = _clamp(1.0 - abs(mean_light - 0.5) * 2.2)
    contrast = _clamp(float(gray_float.std()) / 0.24)
    technical = _clamp(0.45 * sharpness + 0.35 * exposure + 0.20 * contrast)

    motion_values = []
    for first, second in pairwise(frames):
        first_gray = cv2.resize(cv2.cvtColor(first, cv2.COLOR_BGR2GRAY), (160, 90))
        second_gray = cv2.resize(cv2.cvtColor(second, cv2.COLOR_BGR2GRAY), (160, 90))
        difference = float(cv2.absdiff(first_gray, second_gray).mean()) / 255.0
        motion_values.append(difference)
    motion = _clamp((sum(motion_values) / len(motion_values)) / 0.20) if motion_values else 0.0

    cascade_class = getattr(cv2, "CascadeClassifier", None)
    faces: list[object] = []
    if cascade_class is not None:
        cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        cascade = cascade_class(cascade_path)
        faces = list(
            cascade.detectMultiScale(gray, scaleFactor=1.15, minNeighbors=5, minSize=(28, 28))
        )
    return FrameMetrics(
        technical_quality=round(technical, 3),
        motion_score=round(motion, 3),
        perceptual_hash=_perceptual_hash(middle),
        face_count=len(faces),
    )


class VisionClassifier:
    """Lazy, batched CLIP classifier with an explainable OpenCV fallback."""

    def __init__(self) -> None:
        self._model: Any = None
        self._processor: Any = None
        self._torch: Any = None
        self._text_features: Any = None
        self._device = "cpu"
        self._load_error: Exception | None = None

    def _load(self) -> bool:
        if self._model is not None:
            return True
        if self._load_error is not None:
            return False
        try:
            import torch  # type: ignore[import-not-found]
            from transformers import CLIPModel, CLIPProcessor  # type: ignore[import-not-found]

            self._device = "mps" if torch.backends.mps.is_available() else "cpu"
            self._processor = CLIPProcessor.from_pretrained(MODEL_NAME, local_files_only=True)
            self._model = CLIPModel.from_pretrained(MODEL_NAME, local_files_only=True).to(self._device)
            self._model.eval()
            self._torch = torch
            prompts = [*CATEGORY_PROMPTS.values(), *SCALE_PROMPTS.values(), *AESTHETIC_PROMPTS]
            text_inputs = self._processor(text=prompts, return_tensors="pt", padding=True)
            text_inputs = {key: value.to(self._device) for key, value in text_inputs.items()}
            with torch.inference_mode():
                text_features = self._model.get_text_features(**text_inputs)
                if hasattr(text_features, "pooler_output"):
                    text_features = text_features.pooler_output
                self._text_features = text_features / text_features.norm(dim=-1, keepdim=True)
            LOGGER.info("CLIP vision model loaded on %s", self._device)
            return True
        except Exception as error:  # noqa: BLE001 - optional ML boundary has a safe CV fallback.
            self._load_error = error
            LOGGER.warning("CLIP unavailable; using OpenCV visual fallback: %s", error)
            return False

    @staticmethod
    def _fallback(metrics: FrameMetrics) -> dict[str, object]:
        if metrics.face_count >= 3:
            category = "family"
        elif metrics.face_count >= 2:
            category = "couple"
        elif metrics.face_count == 1:
            category = "bride"
        else:
            category = "detail" if metrics.technical_quality > 0.65 else "venue"
        scale = "close_up" if metrics.face_count == 1 else "medium" if metrics.face_count else "wide"
        return {
            "category": category,
            "shot_scale": scale,
            "aesthetic_score": metrics.technical_quality,
            "confidence": 0.25,
            "labels": (category, scale, f"faces:{metrics.face_count}", "opencv_fallback"),
        }

    def classify(self, frames: list[np.ndarray], metrics: list[FrameMetrics]) -> list[dict[str, object]]:
        if not frames:
            return []
        if not self._load():
            return [self._fallback(item) for item in metrics]

        from PIL import Image  # type: ignore[import-not-found]

        category_names = list(CATEGORY_PROMPTS)
        scale_names = list(SCALE_PROMPTS)
        images = [Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)) for frame in frames]
        inputs = self._processor(images=images, return_tensors="pt")
        inputs = {key: value.to(self._device) for key, value in inputs.items()}
        with self._torch.inference_mode():
            image_features = self._model.get_image_features(**inputs)
            if hasattr(image_features, "pooler_output"):
                image_features = image_features.pooler_output
            image_features = image_features / image_features.norm(dim=-1, keepdim=True)
            logits = (image_features @ self._text_features.T * self._model.logit_scale.exp()).float().cpu()

        category_end = len(category_names)
        scale_end = category_end + len(scale_names)
        category_probabilities = logits[:, :category_end].softmax(dim=1)
        scale_probabilities = logits[:, category_end:scale_end].softmax(dim=1)
        aesthetic_probabilities = logits[:, scale_end:].softmax(dim=1)
        results = []
        for index, frame_metrics in enumerate(metrics):
            category_index = int(category_probabilities[index].argmax())
            scale_index = int(scale_probabilities[index].argmax())
            category = category_names[category_index]
            scale = scale_names[scale_index]
            confidence = float(category_probabilities[index, category_index])
            aesthetic = float(aesthetic_probabilities[index, 0])
            top_categories = self._torch.topk(category_probabilities[index], k=3).indices.tolist()
            labels = tuple(category_names[item] for item in top_categories)
            results.append(
                {
                    "category": category,
                    "shot_scale": scale,
                    "aesthetic_score": round(aesthetic, 3),
                    "confidence": round(confidence, 3),
                    "labels": (*labels, scale, f"faces:{frame_metrics.face_count}", "clip_vision"),
                }
            )
        return results
