from __future__ import annotations

from dataclasses import dataclass, field
import math

Point3 = tuple[float, float, float]


@dataclass(frozen=True)
class MotionFrame:
    time_sec: float
    joints: dict[str, Point3]
    source_time_sec: float | None = None
    source_frame_index: int | None = None
    inference_frame_index: int | None = None
    bone_sides: dict[str, Point3] | None = None
    bone_side_provenance: dict[str, str] | None = None

    def with_joints(self, joints: dict[str, Point3], *, time_sec: float | None = None,
                    rigid_rotation: tuple[tuple[float, float, float], ...] | None = None) -> MotionFrame:
        """Copy a frame while carrying optional model side axes with its bones."""
        sides = transport_bone_sides(self.joints, joints, self.bone_sides,
                                     rigid_rotation=rigid_rotation)
        return MotionFrame(
            time_sec=self.time_sec if time_sec is None else time_sec, joints=joints,
            source_time_sec=self.source_time_sec,
            source_frame_index=self.source_frame_index,
            inference_frame_index=self.inference_frame_index,
            bone_sides=sides,
            bone_side_provenance=self.bone_side_provenance,
        )


def transport_bone_sides(old_joints: dict[str, Point3], new_joints: dict[str, Point3],
                         bone_sides: dict[str, Point3] | None, *,
                         rigid_rotation: tuple[tuple[float, float, float], ...] | None = None
                         ) -> dict[str, Point3] | None:
    """Transport side axes by a known rigid rotation or minimum bone-direction change.

    Non-rigid edits have no observable axial-roll component. The minimal rotation
    aligns the old bone to the edited bone and carries the existing model axis;
    it never invents a new global-up frame.
    """
    if bone_sides is None:
        return None
    result: dict[str, Point3] = {}
    for key, axis_value in bone_sides.items():
        try:
            parent, child = key.split('->', 1)
            axis = tuple(float(value) for value in axis_value)
            old_vector = tuple(old_joints[child][i] - old_joints[parent][i] for i in range(3))
            new_vector = tuple(new_joints[child][i] - new_joints[parent][i] for i in range(3))
            old_length = math.sqrt(sum(value * value for value in old_vector))
            new_length = math.sqrt(sum(value * value for value in new_vector))
            if len(axis) != 3 or old_length <= 1e-12 or new_length <= 1e-12:
                result[key] = axis
                continue
            if rigid_rotation is not None:
                moved = tuple(sum(float(rigid_rotation[row][col]) * axis[col]
                                  for col in range(3)) for row in range(3))
            else:
                old_unit = tuple(value / old_length for value in old_vector)
                new_unit = tuple(value / new_length for value in new_vector)
                cross = (old_unit[1] * new_unit[2] - old_unit[2] * new_unit[1],
                         old_unit[2] * new_unit[0] - old_unit[0] * new_unit[2],
                         old_unit[0] * new_unit[1] - old_unit[1] * new_unit[0])
                sine = math.sqrt(sum(value * value for value in cross))
                cosine = max(-1.0, min(1.0, sum(old_unit[i] * new_unit[i] for i in range(3))))
                if sine <= 1e-12:
                    # At 180 degrees the existing perpendicular side axis is
                    # itself a valid rotation axis, so it remains unchanged.
                    moved = axis
                else:
                    unit_axis = tuple(value / sine for value in cross)
                    dot = sum(unit_axis[i] * axis[i] for i in range(3))
                    cross_axis = (unit_axis[1] * axis[2] - unit_axis[2] * axis[1],
                                  unit_axis[2] * axis[0] - unit_axis[0] * axis[2],
                                  unit_axis[0] * axis[1] - unit_axis[1] * axis[0])
                    moved = tuple(axis[i] * cosine + cross_axis[i] * sine
                                  + unit_axis[i] * dot * (1.0 - cosine) for i in range(3))
            new_unit = tuple(value / new_length for value in new_vector)
            projection = sum(moved[i] * new_unit[i] for i in range(3))
            projected = tuple(moved[i] - projection * new_unit[i] for i in range(3))
            norm = math.sqrt(sum(value * value for value in projected))
            result[key] = (tuple(value / norm for value in projected)
                           if norm > 1e-12 else moved)
        except (AttributeError, KeyError, TypeError, ValueError, ZeroDivisionError):
            result[key] = tuple(axis_value)
    return result


def axis_angle_rotation(axis: Point3, angle_radians: float) -> tuple[tuple[float, float, float], ...]:
    """Return the Rodrigues matrix for an already selected rigid frame rotation."""
    length = math.sqrt(sum(float(value) ** 2 for value in axis))
    if length <= 1e-12 or abs(angle_radians) <= 1e-12:
        return ((1., 0., 0.), (0., 1., 0.), (0., 0., 1.))
    x, y, z = (float(value) / length for value in axis)
    cosine, sine = math.cos(angle_radians), math.sin(angle_radians)
    one_minus = 1. - cosine
    return (
        (cosine + x*x*one_minus, x*y*one_minus - z*sine, x*z*one_minus + y*sine),
        (y*x*one_minus + z*sine, cosine + y*y*one_minus, y*z*one_minus - x*sine),
        (z*x*one_minus - y*sine, z*y*one_minus + x*sine, cosine + z*z*one_minus),
    )


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
