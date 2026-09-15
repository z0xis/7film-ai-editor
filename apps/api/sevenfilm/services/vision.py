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
from pathlib import Path
from typing import Any

import cv2  # type: ignore[import-not-found]
import numpy as np

LOGGER = logging.getLogger(__name__)
MODEL_NAME = "openai/clip-vit-base-patch32"
# The last label `classify_features`/`_fallback` ever write is which of these produced the
# row -- the one piece of machine-readable provenance this module has always carried, even
# before anything read it back. `SEMANTIC_BACKEND_CLIP` is the semantics the wedding story
# vocabulary (bride_prep, ceremony, party, ...) actually depends on; `SEMANTIC_BACKEND_FALLBACK`
# can only ever produce {family, couple, bride, detail, venue} off a face count -- see
# `semantic_readiness` in analysis.py, which is what actually reads this back.
SEMANTIC_BACKEND_CLIP = "clip_vision"
SEMANTIC_BACKEND_FALLBACK = "opencv_fallback"
# A quarter of the frame blown to pure white, or almost no contrast at all, is the
# point where a frame stops being usable footage and becomes a flare or a blank wall.
CLIPPING_LIMIT = 0.25
FLAT_CONTRAST_LIMIT = 0.15

# The preparation shots were indexed, measured well and never once reached an edit: nothing
# here could tell the bride having her makeup done from the bride at the reception, so nine
# good files competed as "bride" against 198 and lost every time. A wedding film opens on the
# preparation, and the vocabulary has to be able to say so.
CATEGORY_PROMPTS = {
    "couple": "a cinematic wedding shot of the bride and groom together",
    "bride_prep": "the bride getting ready, hair and makeup, putting on the wedding dress",
    "groom_prep": "the groom getting ready, putting on his suit, tie, cufflinks or watch",
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

# A blown out white wall reads to CLIP as a wedding dress, so the unusable side of this
# comparison names the concrete failure modes instead of one vague "bad frame" prompt.
AESTHETIC_PROMPTS = (
    "a beautiful professional cinematic wedding film frame",
    "an accidental unusable poorly composed video frame",
    "a blurry out of focus smeared video frame",
    "an overexposed blown out white frame with no detail",
    "an empty flat featureless wall or blank surface",
)


@dataclass(frozen=True)
class PromptPriors:
    """CLIP's standing preference among each set of phrases, measured over a whole shoot."""

    category: np.ndarray
    scale: np.ndarray


def _without_prior(probabilities: np.ndarray, prior: np.ndarray) -> np.ndarray:
    """Take the standing offset off, keeping only the shape.

    Shifting the least likely phrase to zero and renormalising turns the corrected scores
    back into a distribution.
    """
    corrected = probabilities - prior
    corrected = corrected - corrected.min(axis=1, keepdims=True)
    total = corrected.sum(axis=1, keepdims=True)
    width = probabilities.shape[1]
    return np.divide(corrected, total, out=np.full_like(corrected, 1 / width), where=total > 0)


@dataclass(frozen=True)
class FrameMetrics:
    technical_quality: float
    motion_score: float
    perceptual_hash: str
    face_count: int
    # The largest face's share of the frame, and how close that face sits to the edge. Both
    # come out of the detector that was already running; only the count was being kept.
    face_ratio: float = 0.0
    face_edge: float = 0.0
    brightness: float = 0.0
    saturation: float = 0.0
    highlight_clipping: float = 0.0
    sharpness: float = 0.0
    contrast: float = 0.0


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _face_framing(faces: list, width: int, height: int) -> tuple[float, float]:
    """How big the subject is, and how close it sits to the edge of the frame.

    A face is what a wedding shot is about, and both of these are things a viewer sees at once
    and no score here could: a couple across a hotel atrium behind a hanging lamp reads as a
    couple to a semantic model and as nothing at all to a person, and a head cut by the frame
    edge is a shot an editor would never hold.

    The ratio is the largest face's area over the frame's. The edge figure is 0 when that face
    sits clear of the border and rises to 1 as it touches it, measured against a margin of a
    twentieth of the frame — enough to catch a head against the edge without complaining about
    an ordinary portrait near the rule-of-thirds line.
    """
    if not faces or width <= 0 or height <= 0:
        return 0.0, 0.0
    boxes = [(float(f[0]), float(f[1]), float(f[2]), float(f[3])) for f in faces]
    x, y, w, h = max(boxes, key=lambda box: box[2] * box[3])
    ratio = _clamp(w * h / (width * height))
    margin_x = width / 20
    margin_y = height / 20
    gaps = (x, y, width - (x + w), height - (y + h))
    margins = (margin_x, margin_y, margin_x, margin_y)
    edge = max(_clamp(1.0 - gap / margin) for gap, margin in zip(gaps, margins, strict=True))
    return round(ratio, 5), round(edge, 3)


# The shoot is 10 bit S-Log3, which is flat and grey by design, and CLIP was trained on
# ordinary pictures. Measured on 120 frames of this shoot: shown the log frame and the same
# frame with the curve undone, CLIP changes its mind about the category on 36% of them — and
# by eye the graded answer is right on eleven of the twelve checked. On the log frame it calls
# almost everything "bride", because a white dress is the only thing that survives the flat
# grey; crowded dance floors, a mother dancing, and a bride at her mirror all came back as
# "bride". That is why this edit ran 35% bride against the references' 21%, and 2% party
# against their 17%.
#
# The shot scale survives the log curve (86% unchanged) and so does the ranking of the
# aesthetic score (Spearman 0.90), so those measurements were sound; the category was not.
#
# Sony's own S-Log3 decode, then a Rec.709 transfer. The colour primaries are left alone:
# undoing the tone curve is what the category depends on, and a full S-Gamut3.Cine matrix
# would be a second, unmeasured change.
_SLOG3_BREAK = 171.2102946929 / 1023.0


def _slog3_to_rec709(frame: np.ndarray) -> np.ndarray:
    """Undo the S-Log3 curve so the picture reads the way a viewer would see it."""
    x = frame.astype(np.float32) / 255.0
    code = x * 1023.0
    high = (np.power(10.0, (code - 420.0) / 261.5) * 0.19) - 0.01
    low = (code - 95.0) * 0.01125 / (171.2102946929 - 95.0)
    linear = np.where(x >= _SLOG3_BREAK, high, low)
    linear = np.clip(linear, 0.0, 1.0)
    # Rec.709 opto-electronic transfer, so mid grey lands where the eye expects it.
    encoded = np.where(
        linear < 0.018, linear * 4.5, 1.099 * np.power(linear, 0.45) - 0.099
    )
    return np.clip(encoded * 255.0, 0, 255).astype(np.uint8)


def _perceptual_hash(frame: np.ndarray) -> str:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    small = cv2.resize(gray, (9, 8), interpolation=cv2.INTER_AREA)
    bits = small[:, 1:] > small[:, :-1]
    packed = np.packbits(bits.reshape(-1))
    return packed.tobytes().hex()


def _frame_measurements(frame: np.ndarray) -> dict[str, float]:
    """Measure one BGR frame the way the reference analyzer measures a reference edit."""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    gray_float = gray.astype(np.float32) / 255.0
    return {
        "sharpness": 1.0 - math.exp(-float(cv2.Laplacian(gray, cv2.CV_64F).var()) / 280.0),
        "exposure": _clamp(1.0 - abs(float(gray_float.mean()) - 0.5) * 2.2),
        "contrast": _clamp(float(gray_float.std()) / 0.24),
        "highlight_clipping": float((gray >= 250).mean()),
        "brightness": float(hsv[..., 2].mean()) / 255.0,
        "saturation": float(hsv[..., 1].mean()) / 255.0,
    }


def _usable_quality(measured: dict[str, float]) -> float:
    """Score focus, exposure and contrast, then veto the frames an editor never uses.

    A smeared or blown out frame is unusable however a semantic model labels it, and CLIP
    reliably labels a large white blurry area as a bride. The two penalties below are
    multiplicative so no amount of sharpness or exposure can rescue such a frame.
    """
    base = (
        0.45 * measured["sharpness"]
        + 0.35 * measured["exposure"]
        + 0.20 * measured["contrast"]
    )
    clipping_penalty = _clamp(measured["highlight_clipping"] / CLIPPING_LIMIT)
    flat_penalty = _clamp(1.0 - measured["contrast"] / FLAT_CONTRAST_LIMIT)
    return _clamp(base * (1.0 - clipping_penalty) * (1.0 - flat_penalty))


def measure_frames(frames: list[np.ndarray]) -> FrameMetrics:
    """Measure a shot from its representative BGR frames.

    Every sampled frame is measured and the median is kept, so one lucky sharp frame cannot
    carry a shot that is out of focus or blown out for most of its length.
    """
    if not frames:
        return FrameMetrics(0.0, 0.0, "missing", 0)
    middle = frames[len(frames) // 2]
    measurements = [_frame_measurements(frame) for frame in frames]

    def median(key: str) -> float:
        return float(np.median([item[key] for item in measurements]))

    technical = float(np.median([_usable_quality(item) for item in measurements]))

    motion_values = []
    for first, second in pairwise(frames):
        first_gray = cv2.resize(cv2.cvtColor(first, cv2.COLOR_BGR2GRAY), (160, 90))
        second_gray = cv2.resize(cv2.cvtColor(second, cv2.COLOR_BGR2GRAY), (160, 90))
        difference = float(cv2.absdiff(first_gray, second_gray).mean()) / 255.0
        motion_values.append(difference)
    motion = _clamp((sum(motion_values) / len(motion_values)) / 0.20) if motion_values else 0.0

    faces = []
    if hasattr(cv2, "FaceDetectorYN"):
        model_path = Path(__file__).parent.parent / "models" / "face_detection_yunet_2023mar.onnx"
        if model_path.exists():
            h, w = middle.shape[:2]
            detector = cv2.FaceDetectorYN.create(
                str(model_path), "", (w, h), score_threshold=0.6, nms_threshold=0.3
            )
            _success, detected_faces = detector.detect(middle)
            if detected_faces is not None:
                faces = list(detected_faces)

    face_ratio, face_edge = _face_framing(faces, middle.shape[1], middle.shape[0])
    return FrameMetrics(
        technical_quality=round(technical, 3),
        motion_score=round(motion, 3),
        perceptual_hash=_perceptual_hash(middle),
        face_count=len(faces),
        face_ratio=face_ratio,
        face_edge=face_edge,
        brightness=round(median("brightness"), 3),
        saturation=round(median("saturation"), 3),
        highlight_clipping=round(median("highlight_clipping"), 3),
        sharpness=round(median("sharpness"), 3),
        contrast=round(median("contrast"), 3),
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
            "labels": (category, scale, f"faces:{metrics.face_count}", SEMANTIC_BACKEND_FALLBACK),
        }

    def encode(self, frames: list[np.ndarray]) -> np.ndarray | None:
        """Turn frames into normalised CLIP image features, or None when CLIP is unavailable."""
        if not frames or not self._load():
            return None
        from PIL import Image  # type: ignore[import-not-found]

        images = [
            Image.fromarray(cv2.cvtColor(_slog3_to_rec709(frame), cv2.COLOR_BGR2RGB))
            for frame in frames
        ]
        inputs = self._processor(images=images, return_tensors="pt")
        inputs = {key: value.to(self._device) for key, value in inputs.items()}
        with self._torch.inference_mode():
            features = self._model.get_image_features(**inputs)
            if hasattr(features, "pooler_output"):
                features = features.pooler_output
            features = features / features.norm(dim=-1, keepdim=True)
        return features.float().cpu().numpy()

    def _probabilities(self, features: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        with self._torch.inference_mode():
            logits = (
                self._torch.from_numpy(features).to(self._device)
                @ self._text_features.T
                * self._model.logit_scale.exp()
            ).float().cpu()
        category_end = len(CATEGORY_PROMPTS)
        scale_end = category_end + len(SCALE_PROMPTS)
        return (
            logits[:, :category_end].softmax(dim=1).numpy().copy(),
            logits[:, category_end:scale_end].softmax(dim=1).numpy().copy(),
            logits[:, scale_end:].softmax(dim=1).numpy().copy(),
        )

    def prompt_priors(self, features: np.ndarray) -> PromptPriors | None:
        """The share of every phrase CLIP awards on average across a whole shoot.

        CLIP does not answer "which of these is it" so much as "how close is each phrase", and
        some phrases sit closer to wedding footage than others whatever the frame shows. On this
        project's own material a wide, blurred white ceiling and a hotel room sign both came back
        as the bride, with the model confident: 93% of frames were bride or groom, at a median
        confidence of 0.59. Averaging each phrase over the shoot measures that standing offset
        so it can be taken back off, which leaves the part of the score that is about the frame.

        The shot scale has the same standing offset and was left uncorrected: measured over this
        shoot's 1405 frames, "a medium shot showing people from the waist up" took 60.8% of the
        probability on average against 3.9% for the close-up phrase, and the edit that came out
        held 141 clips without a single close-up in it.
        """
        if features is None or not len(features) or not self._load():
            return None
        categories, scales, _ = self._probabilities(features)
        return PromptPriors(category=categories.mean(axis=0), scale=scales.mean(axis=0))

    def classify_features(
        self,
        features: np.ndarray,
        metrics: list[FrameMetrics],
        priors: PromptPriors | None = None,
    ) -> list[dict[str, object]]:
        if features is None or not self._load():
            return [self._fallback(item) for item in metrics]
        category_names = list(CATEGORY_PROMPTS)
        scale_names = list(SCALE_PROMPTS)
        categories, scales, aesthetics = self._probabilities(features)
        if priors is not None:
            categories = _without_prior(categories, priors.category)
            scales = _without_prior(scales, priors.scale)
        results = []
        for index, frame_metrics in enumerate(metrics):
            category_index = int(categories[index].argmax())
            scale_index = int(scales[index].argmax())
            order = list(np.argsort(categories[index])[::-1][:3])
            results.append(
                {
                    "category": category_names[category_index],
                    "shot_scale": scale_names[scale_index],
                    "aesthetic_score": round(float(aesthetics[index, 0]), 3),
                    "confidence": round(float(categories[index, category_index]), 3),
                    "labels": (
                        *(category_names[int(item)] for item in order),
                        scale_names[scale_index],
                        f"faces:{frame_metrics.face_count}",
                        SEMANTIC_BACKEND_CLIP,
                    ),
                }
            )
        return results

    def classify(
        self,
        frames: list[np.ndarray],
        metrics: list[FrameMetrics],
        priors: PromptPriors | None = None,
    ) -> list[dict[str, object]]:
        if not frames:
            return []
        return self.classify_features(self.encode(frames), metrics, priors)


def semantic_backend_status() -> dict[str, object]:
    """Whether the intended CLIP semantic classifier would actually load right now, checked
    the same way `VisionClassifier.encode`/`classify` do -- not inferred from a previous run,
    a cached flag, or an old failure. Cheap enough to call before starting a multi-hour shot
    analysis job: the load attempt itself is the cost (a few seconds either way), and nothing
    here decodes a frame or runs inference.

    This is a live, process-local answer: the local model cache this checks can change between
    calls (an operator installs or removes the model), so nothing should cache this result
    beyond the request that asked for it.
    """
    classifier = VisionClassifier()
    available = classifier._load()
    return {
        "available": available,
        "backend": SEMANTIC_BACKEND_CLIP if available else SEMANTIC_BACKEND_FALLBACK,
        "model_id": MODEL_NAME if available else None,
        "device": classifier._device if available else None,
        "reason": None if available else (
            f"{type(classifier._load_error).__name__}: {classifier._load_error}"
            if classifier._load_error else "unknown"
        ),
    }
