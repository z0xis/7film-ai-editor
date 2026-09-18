"""P6.22 -- read-only Stage-1 story / sequence planner (shadow only).

Emits an ABSTRACT edit plan (roles/events/pacing/music intent) -- NO source shots, no shot ids. Events
come from the TARGET project's own available material + chronology; pacing / role structure / shot-role
patterns are conditioned on RETRIEVED human reference sequences. This does not touch build_timeline.

Modes (for the ablation):
  retrieval  -- condition on retrieved reference sequences (default)
  off        -- no reference conditioning (fixed canonical arc)
  aggregate  -- condition only on the old style-profile section medians
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from tools.refbrain.retrieval import Retriever
from tools.refbrain.schema import STORY_ROLES

# canonical role -> event it realises, and the music energy it wants
ROLE_EVENT = {
    "INTRO_ESTABLISH": ("OTHER", "low"),
    "PREPARATION": ("PREPARATION", "low"),
    "BUILD": ("PREPARATION", "medium"),
    "RECEPTION_ENTRY": ("CEREMONY", "medium"),
    "FIRST_DANCE": ("FIRST_DANCE", "medium"),
    "PARTY_BUILD": ("PARTY_KINA", "high"),
    "CLIMAX": ("PARTY_KINA", "high"),
    "RESOLUTION_OUTRO": ("OUTRO", "low"),
}


@dataclass
class PlannedSequence:
    index: int
    story_role: str
    event_type: str
    music_energy: str
    duration_target_s: float
    n_shots_target: int
    shot_scale_roles: list[str]
    retrieved: list[dict] = field(default_factory=list)   # provenance: which references informed it

    def to_dict(self):
        return asdict(self)


@dataclass
class TargetContext:
    project: str
    target_duration_s: float
    available_events: list[str]
    music_sections: list[dict]          # [{energy, start_s, end_s}]
    chronology_span: tuple[float, float]


def _default_descriptor(position, energy):
    mean_dur = {"low": 1.4, "medium": 1.0, "high": 0.6}[energy]
    return [round(position, 4), mean_dur, 1.0, 0.0, 0.0, 0.6]


class Stage1Planner:
    def __init__(self, retriever: Retriever | None, mode: str = "retrieval",
                 section_medians: dict | None = None):
        self.retriever = retriever
        self.mode = mode
        self.section_medians = section_medians or {}

    def plan(self, ctx: TargetContext) -> dict:
        roles = [r for r in STORY_ROLES
                 if ROLE_EVENT[r][0] in ctx.available_events or ROLE_EVENT[r][0] == "OTHER"]
        n = len(roles)
        seqs = []
        for i, role in enumerate(roles):
            event, energy = ROLE_EVENT[role]
            position = (i + 0.5) / n
            retrieved = []
            if self.mode == "retrieval" and self.retriever is not None:
                retrieved = self.retriever.retrieve(
                    _default_descriptor(position, energy), story_role=role, event_type=event, k=5)
            dur, nshots, scale_roles = self._pacing(role, energy, position, retrieved)
            seqs.append(PlannedSequence(
                index=i, story_role=role, event_type=event, music_energy=energy,
                duration_target_s=dur, n_shots_target=nshots, shot_scale_roles=scale_roles,
                retrieved=retrieved))
        # normalize durations to the target
        total = sum(s.duration_target_s for s in seqs) or 1.0
        for s in seqs:
            s.duration_target_s = round(s.duration_target_s / total * ctx.target_duration_s, 1)
        transitions = [{"at_index": i + 1, "from": seqs[i].story_role, "to": seqs[i + 1].story_role,
                        "energy_delta": _delta(seqs[i].music_energy, seqs[i + 1].music_energy)}
                       for i in range(len(seqs) - 1)]
        return {
            "mode": self.mode,
            "target": {"project": ctx.project, "target_duration_s": ctx.target_duration_s,
                       "available_events": ctx.available_events},
            "active_references": self.retriever.active_references() if self.retriever else [],
            "sequences": [s.to_dict() for s in seqs],
            "role_order": [s.story_role for s in seqs],
            "event_order": [s.event_type for s in seqs],
            "energy_curve": [s.music_energy for s in seqs],
            "transitions": transitions,
        }

    def _pacing(self, role, energy, position, retrieved):
        scales_default = {"low": ["wide", "medium", "detail"], "medium": ["medium", "wide"],
                          "high": ["medium", "close_up"]}[energy]
        if self.mode == "retrieval" and retrieved:
            durs = [r["duration_s"] for r in retrieved]
            nsh = [r["n_shots"] for r in retrieved]
            dur = sum(durs) / len(durs)
            nshots = round(sum(nsh) / len(nsh))
            # shot-scale roles from the most similar retrieved sequence that has real scales
            scale_roles = scales_default
            for r in retrieved:
                sp = [x for x in r["scale_pattern"] if x != "?"]
                if sp:
                    scale_roles = sp
                    break
            return round(dur, 2), max(2, nshots), scale_roles
        if self.mode == "aggregate":
            band = {"INTRO_ESTABLISH": "intro", "RESOLUTION_OUTRO": "finale"}.get(role, "core")
            med = (self.section_medians or {}).get(band, 1.0)
            return round(med * 3, 2), 3, scales_default
        # off: fixed canonical
        return {"low": 4.0, "medium": 3.0, "high": 2.0}[energy], 3, scales_default


def _delta(a, b):
    order = {"low": 0, "medium": 1, "high": 2}
    d = order[b] - order[a]
    return "up" if d > 0 else "down" if d < 0 else "flat"
