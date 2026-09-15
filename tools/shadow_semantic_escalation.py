"""P5.3 shadow-only semantic escalation module.

Defines the ShadowSemanticEscalationResult contract and router logic used to decide whether a
CLIP (fast-tier) prediction should escalate to Qwen3-VL-4B-Instruct (deep/event-tier), and how to
turn a deep-tier structured event prediction into ACCEPT / ABSTAIN / FALLBACK.

This module is NOT wired into the production pipeline. It exists purely for shadow evaluation
against real project data. Nothing here writes to the production database, mutates a timeline,
or changes planner scoring. See docs/p5_3_shadow_semantic_escalation.md for the full report.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

ROUTER_VERSION = "p5.3-r3-story-critical-v1"

# Categories where CLIP's own vocabulary is fine-grained enough that a top1 hit is usually
# correct (measured on the P5.2 42-sample corpus: 65% correct when top1 lands here, vs 18%
# correct when it lands in the complementary "container" set below).
STORY_CRITICAL_CATEGORIES = {"ceremony", "party", "couple", "bride_prep", "groom_prep"}

# Events Qwen showed real positive signal for on the P5.2 event corpus (cake_cutting,
# first_dance: TP with 0 FP). Entrance is explicitly NOT in this set -- P5.2 showed 2/2 FN in
# both single-frame and temporal modes, with no incremental value from temporal context.
QWEN_SUPPORTED_EVENTS = {"cake_cutting", "first_dance"}
QWEN_UNRESOLVED_EVENTS = {"entrance", "ceremony_action"}

Decision = Literal["FAST_ONLY", "DEEP_ACCEPT", "DEEP_ABSTAIN", "DEEP_FAILED"]


@dataclass(frozen=True)
class FastPrediction:
    category: str
    top1_score: float
    top2_category: str
    top2_score: float

    @property
    def margin(self) -> float:
        return round(self.top1_score - self.top2_score, 4)


@dataclass(frozen=True)
class RouterDecision:
    escalate: bool
    router_version: str
    reason: str


def route(pred: FastPrediction, router: str = "r3") -> RouterDecision:
    """Generic, ground-truth-free escalation signal. `router` selects which family (r0-r4b) to
    apply -- see docs/p5_3_shadow_semantic_escalation.md for the measured tradeoffs of each.
    Inputs are restricted to signals that exist in the production CLIP call today: the top1/top2
    category and score. Nothing here reads an event label, filename, or corpus annotation.
    """
    not_story_critical = pred.category not in STORY_CRITICAL_CATEGORIES
    if router == "r0":
        return RouterDecision(False, ROUTER_VERSION, "no escalation (baseline)")
    if router == "r1":
        esc = pred.top1_score < 0.6
        return RouterDecision(esc, ROUTER_VERSION, f"low_confidence({pred.top1_score:.2f})" if esc else "confident")
    if router == "r2":
        esc = pred.margin < 0.15
        return RouterDecision(esc, ROUTER_VERSION, f"low_margin({pred.margin:.2f})" if esc else "clear_margin")
    if router == "r3":
        return RouterDecision(not_story_critical, ROUTER_VERSION,
                               f"top1_not_story_critical({pred.category})" if not_story_critical else "story_critical_hit")
    if router == "r4":
        esc = not_story_critical or pred.margin < 0.15
        return RouterDecision(esc, ROUTER_VERSION, "union(not_story_critical, low_margin)" if esc else "confident_and_story_critical")
    if router == "r4b":
        esc = not_story_critical and pred.margin < 0.3
        return RouterDecision(esc, ROUTER_VERSION, "conservative_intersect(not_story_critical, margin<0.3)" if esc else "not_flagged")
    raise ValueError(f"unknown router {router!r}")


@dataclass(frozen=True)
class DeepPrediction:
    """Shadow structured contract for a Qwen3-VL-4B-Instruct call. Never connected to
    production. `confidence` is the model's own self-reported number and is NOT treated as a
    calibrated probability anywhere in this module -- see `decide` below.
    """

    event_present: str  # one of QWEN_SUPPORTED_EVENTS | QWEN_UNRESOLVED_EVENTS | "none"
    confidence: float
    reason: str
    model_id: str = "Qwen/Qwen3-VL-4B-Instruct"
    model_revision: str | None = None
    prompt_version: str = "p5.2-single-frame-v1"
    source_frame: str | None = None
    latency_ms: float | None = None
    parse_failed: bool = False


@dataclass(frozen=True)
class ShadowSemanticEscalationResult:
    project_id: str
    asset_id: str
    shot_id: str
    source_frame: str
    fast_model: str
    fast_prediction: str
    fast_scores: dict[str, float]
    router_version: str
    router_reason: str
    escalated: bool
    deep_model: str | None
    deep_prediction: str | None
    deep_event: str | None
    deep_parse_status: Literal["ok", "parse_failed", "exception", "not_called"]
    decision: Decision
    decision_reason: str
    latency_ms: dict[str, float] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)


def decide(deep: DeepPrediction | None) -> tuple[Decision, str]:
    """ACCEPT / ABSTAIN / FALLBACK policy. "Qwen was called" never implies "Qwen is right" --
    acceptance is gated on the event type being one this project has actual positive evidence
    for (QWEN_SUPPORTED_EVENTS), not on the model's own confidence number, which P5.2 explicitly
    flagged as an uncalibrated self-report.
    """
    if deep is None:
        return "FAST_ONLY", "not escalated"
    if deep.parse_failed:
        return "DEEP_ABSTAIN", "structured output failed to parse -- fast-tier result preserved"
    if deep.event_present == "none":
        return "DEEP_ABSTAIN", "no event detected by deep tier"
    if deep.event_present in QWEN_UNRESOLVED_EVENTS:
        return "DEEP_ABSTAIN", f"event type '{deep.event_present}' has no positive evidence (P5.2: 2/2 FN) -- treated as unresolved, not accepted"
    if deep.event_present in QWEN_SUPPORTED_EVENTS:
        return "DEEP_ACCEPT", f"event type '{deep.event_present}' has positive shadow evidence (P5.2: TP, 0 FP)"
    return "DEEP_ABSTAIN", f"event type '{deep.event_present}' outside the evaluated vocabulary -- unresolved"


def cache_key(source_fingerprint: str, source_time_s: float, model_id: str, model_revision: str | None,
              prompt_version: str, algorithm_version: str) -> str:
    """Design-only cache key (P5.2.26/P5.3.17): identity must include model + prompt + algorithm
    version so a future model swap or prompt change can never be silently read back as still
    valid. Not wired to any real cache in this package.
    """
    rev = model_revision or "unknown"
    return f"{source_fingerprint}:{source_time_s:.3f}:{model_id}:{rev}:{prompt_version}:{algorithm_version}"
