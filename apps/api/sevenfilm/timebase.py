"""Frame-accurate time primitives used by timeline planning and exports."""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

Number = int | float | str | Fraction


def as_fraction(value: Number) -> Fraction:
    """Convert user-facing seconds to an exact Fraction without float drift."""
    if isinstance(value, Fraction):
        return value
    if isinstance(value, float):
        return Fraction(str(value))
    return Fraction(value)


@dataclass(frozen=True)
class FrameRate:
    numerator: int
    denominator: int = 1

    def __post_init__(self) -> None:
        if self.numerator <= 0 or self.denominator <= 0:
            raise ValueError("Frame rate must be positive")

    @property
    def value(self) -> Fraction:
        return Fraction(self.numerator, self.denominator)

    @classmethod
    def parse(cls, raw: str) -> FrameRate:
        value = Fraction(raw)
        return cls(value.numerator, value.denominator)

    def frames_from_seconds(self, seconds: Number, *, rounding: str = "nearest") -> int:
        frames = as_fraction(seconds) * self.value
        if rounding == "floor":
            return frames.numerator // frames.denominator
        if rounding == "ceil":
            return -(-frames.numerator // frames.denominator)
        return int(frames + Fraction(1, 2))

    def seconds_from_frames(self, frames: int) -> Fraction:
        return Fraction(frames, 1) / self.value


@dataclass(frozen=True)
class TimeRange:
    """A half-open [start, end) range expressed in source frames."""

    start_frame: int
    duration_frames: int
    rate: FrameRate

    def __post_init__(self) -> None:
        if self.start_frame < 0:
            raise ValueError("start_frame cannot be negative")
        if self.duration_frames < 0:
            raise ValueError("duration_frames cannot be negative")

    @property
    def end_frame(self) -> int:
        return self.start_frame + self.duration_frames

    @property
    def start_seconds(self) -> Fraction:
        return self.rate.seconds_from_frames(self.start_frame)

    @property
    def duration_seconds(self) -> Fraction:
        return self.rate.seconds_from_frames(self.duration_frames)

    @property
    def end_seconds(self) -> Fraction:
        return self.rate.seconds_from_frames(self.end_frame)

    def as_rational_dict(self) -> dict[str, object]:
        return {
            "start_frame": self.start_frame,
            "duration_frames": self.duration_frames,
            "rate": f"{self.rate.numerator}/{self.rate.denominator}",
            "start_seconds": str(self.start_seconds),
            "duration_seconds": str(self.duration_seconds),
        }
