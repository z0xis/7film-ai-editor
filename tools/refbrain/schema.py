"""P6.22 -- reference corpus schema (structured, provenance-preserving, versioned).

Deliberately NOT collapsed into a single style profile. Every derived object keeps a back-pointer to
the human edit that produced it, so we can always answer "which edit taught this?".
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

SCHEMA_VERSION = "p6.22.1"

# event taxonomy -- weddings need not contain every event
EVENTS = (
    "PREPARATION", "ENTRANCE", "CEREMONY", "RING", "KISS", "CAKE",
    "FIRST_DANCE", "PARTY_KINA", "BOUQUET", "OUTRO", "OTHER",
)

# map the shot categories used across the projects to a coarse event.
CATEGORY_EVENT = {
    "bride_prep": "PREPARATION", "groom_prep": "PREPARATION",
    "bride": "PREPARATION", "groom": "PREPARATION", "detail": "PREPARATION",
    "couple": "OTHER", "family": "OTHER", "venue": "OTHER",
    "ceremony": "CEREMONY", "party": "PARTY_KINA",
}

# coarse story role, indexed by normalized story position (0..1)
STORY_ROLES = ("INTRO_ESTABLISH", "PREPARATION", "BUILD", "RECEPTION_ENTRY",
               "FIRST_DANCE", "PARTY_BUILD", "CLIMAX", "RESOLUTION_OUTRO")


@dataclass
class ReferenceShot:
    reference_id: str
    shot_index: int
    timeline_in: int
    timeline_out: int
    duration_s: float
    source_asset: str | None = None
    source_in: int | None = None
    source_out: int | None = None
    category: str | None = None
    shot_scale: str | None = None
    event: str | None = None
    day_position: float | None = None
    music_track: str | None = None
    music_energy: str | None = None

    def to_dict(self):
        return asdict(self)


@dataclass
class ReferenceMusicSection:
    reference_id: str
    track: str
    role: str            # intro / calm / build / peak / outro (best available)
    energy: str          # low / medium / high
    timeline_start_s: float
    timeline_end_s: float

    def to_dict(self):
        return asdict(self)


@dataclass
class ReferenceSequence:
    sequence_id: str
    reference_id: str
    tier: int
    story_role: str
    event_type: str
    story_position: float          # midpoint, normalized 0..1
    timeline_start_s: float
    duration_s: float
    n_shots: int
    shot_indices: list[int]        # provenance: which reference shots
    scale_pattern: list[str] = field(default_factory=list)
    category_pattern: list[str] = field(default_factory=list)
    shot_durations_s: list[float] = field(default_factory=list)
    source_reuse: bool = False     # a source repeated within the window
    forward_progression: bool = False  # same-source uses advance in source
    music_energy: str | None = None
    descriptor: list[float] = field(default_factory=list)  # numeric embedding

    def to_dict(self):
        return asdict(self)


@dataclass
class ReferenceTransition:
    reference_id: str
    at_s: float
    before_event: str
    after_event: str
    before_energy: str | None
    after_energy: str | None
    song_seam: bool
    energy_delta: str            # up / down / flat

    def to_dict(self):
        return asdict(self)


@dataclass
class ReferenceEventEpisode:
    reference_id: str
    event_type: str
    timeline_start_s: float
    timeline_end_s: float
    n_shots: int
    phases: list[str]            # observed ordered phase labels, if any

    def to_dict(self):
        return asdict(self)


@dataclass
class ReferenceEdit:
    reference_id: str
    source: str                  # provenance: where it came from
    tier: int                    # 1 rich edit trace, 2 final-edit trace
    kind: str                    # narrative / selects / render_only
    project: str
    duration_s: float
    fps: float
    n_shots: int
    music_tracks: list[str]
    available_evidence: list[str]

    def to_dict(self):
        return asdict(self)
