from __future__ import annotations

from dataclasses import dataclass, field

Point3 = tuple[float, float, float]


@dataclass(frozen=True)
class MotionFrame:
    time_sec: float
    joints: dict[str, Point3]


@dataclass(frozen=True)
class MotionClip:
    fps: float
    joint_names: list[str]
    frames: list[MotionFrame]
    source: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, object] = field(default_factory=dict)

    def require_joint(self, joint_name: str) -> None:
        if joint_name not in self.joint_names:
            raise ValueError(f"Required joint '{joint_name}' not found in clip.")

    @property
    def frame_count(self) -> int:
        return len(self.frames)

    @property
    def duration_sec(self) -> float:
        if not self.frames:
            return 0.0
        return self.frames[-1].time_sec - self.frames[0].time_sec
