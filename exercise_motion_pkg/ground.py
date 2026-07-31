from __future__ import annotations

from dataclasses import replace
import json
import math
from dataclasses import dataclass
from pathlib import Path

from exercise_motion_pkg.models import MotionClip
from exercise_motion_pkg.motion_io import save_motion_json
from exercise_motion_pkg.render_geometry import support_surface_height


@dataclass(frozen=True)
class PlaneEstimate:
    normal: tuple[float, float, float]
    offset: float
    rms_error: float | None = None


@dataclass(frozen=True)
class GroundMetadata:
    render_plane: PlaneEstimate
    render_origin: tuple[float, float, float]
    motion_plane: PlaneEstimate
    motion_origin: tuple[float, float, float]
    camera_plane: PlaneEstimate | None
    sample_frame_seconds: list[float]
    frames_used: int
    model_name: str | None
    alignment_status: str
    render_source: str
    notes: list[str]

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "renderGroundPlane": _plane_to_payload(self.render_plane, space="motion"),
            "renderGroundOrigin": _point_to_payload(self.render_origin, space="motion"),
            "motionGroundPlane": _plane_to_payload(self.motion_plane, space="motion"),
            "motionGroundOrigin": _point_to_payload(self.motion_origin, space="motion"),
            "renderSource": self.render_source,
            "unidepth": {
                "modelName": self.model_name,
                "framesUsed": self.frames_used,
                "sampleFrameSeconds": self.sample_frame_seconds,
                "alignmentStatus": self.alignment_status,
            },
            "notes": self.notes,
        }
        if self.camera_plane is not None:
            payload["unidepth"] = {
                **payload["unidepth"],
                "cameraGroundPlane": _plane_to_payload(self.camera_plane, space="camera"),
            }
        return payload


def generate_ground_metadata(
    *,
    video_path: Path,
    cleaned_clip: MotionClip,
    output_path: Path,
) -> GroundMetadata:
    motion_plane = estimate_motion_ground_plane(cleaned_clip)
    motion_origin = estimate_motion_ground_origin(cleaned_clip, motion_plane)
    render_plane = motion_plane
    render_origin = motion_origin
    alignment_status = "motion_space_only"
    render_source = "motion_contact_authoritative"
    notes = [
        "renderGroundPlane is motion/contact-derived and is the authoritative floor for rendering.",
    ]

    metadata = GroundMetadata(
        render_plane=render_plane,
        render_origin=render_origin,
        motion_plane=motion_plane,
        motion_origin=motion_origin,
        camera_plane=None,
        sample_frame_seconds=[],
        frames_used=0,
        model_name=None,
        alignment_status=alignment_status,
        render_source=render_source,
        notes=notes,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(metadata.to_dict(), indent=2), encoding="utf-8")
    return metadata


def embed_ground_metadata_in_clip(
    *,
    clip: MotionClip,
    ground_metadata: GroundMetadata,
    output_path: Path,
) -> MotionClip:
    enriched_clip = replace(
        clip,
        metadata={
            **clip.metadata,
            "ground": ground_metadata.to_dict(),
        },
    )
    save_motion_json(output_path, enriched_clip)
    return enriched_clip


def estimate_motion_ground_plane(clip: MotionClip) -> PlaneEstimate:
    cleanup_metadata = clip.metadata.get("cleanup") if isinstance(clip.metadata, dict) else None
    support_ground_y = None
    if isinstance(cleanup_metadata, dict):
        raw_support_ground_y = cleanup_metadata.get("supportGroundY")
        if isinstance(raw_support_ground_y, (int, float)) and math.isfinite(raw_support_ground_y):
            support_ground_y = float(raw_support_ground_y)

    if support_ground_y is not None:
        support_heights = _collect_support_heights(clip)
        rms_error = None
        if support_heights:
            rms_error = math.sqrt(
                sum((value - support_ground_y) ** 2 for value in support_heights) / len(support_heights)
            )
        return PlaneEstimate(
            normal=(0.0, 1.0, 0.0),
            offset=-support_ground_y,
            rms_error=rms_error,
        )

    ankle_heights: list[float] = []
    for frame in clip.frames:
        for joint_name in ("left_ankle", "right_ankle", "l_ankle", "r_ankle"):
            joint = frame.joints.get(joint_name)
            if joint is not None and math.isfinite(joint[1]):
                ankle_heights.append(support_surface_height(joint[1]))
    if not ankle_heights:
        return PlaneEstimate(normal=(0.0, 1.0, 0.0), offset=0.0, rms_error=None)

    ground_y = _median(ankle_heights)
    rms_error = math.sqrt(sum((value - ground_y) ** 2 for value in ankle_heights) / len(ankle_heights))
    return PlaneEstimate(
        normal=(0.0, 1.0, 0.0),
        offset=-ground_y,
        rms_error=rms_error,
    )


def estimate_motion_ground_origin(clip: MotionClip, plane: PlaneEstimate) -> tuple[float, float, float]:
    ground_y = -plane.offset / plane.normal[1] if abs(plane.normal[1]) > 1e-8 else 0.0
    contact_threshold = max(0.06, (plane.rms_error or 0.0) * 1.5)
    preferred_joint_names = _support_joint_names(clip)

    contact_points: list[tuple[float, float]] = []
    fallback_points: list[tuple[float, float]] = []
    for frame in clip.frames:
        for joint_name in preferred_joint_names:
            joint = frame.joints.get(joint_name)
            if joint is None:
                continue
            x, y, z = joint
            if not (math.isfinite(x) and math.isfinite(y) and math.isfinite(z)):
                continue
            fallback_points.append((float(x), float(z)))
            if abs(float(y) - ground_y) <= contact_threshold:
                contact_points.append((float(x), float(z)))

    anchor_points = contact_points or fallback_points
    if not anchor_points:
        return (0.0, ground_y, 0.0)

    return (
        _median([point[0] for point in anchor_points]),
        ground_y,
        _median([point[1] for point in anchor_points]),
    )

def adjust_render_ground_height_to_clip(
    *,
    clip: MotionClip,
    proposed_ground_y: float,
    tolerance: float = 0.01,
    validation_quantile: float = 0.1,
) -> float:
    support_heights = _collect_support_heights(clip)
    if not support_heights:
        return proposed_ground_y

    min_clearances = [height - proposed_ground_y for height in support_heights]
    clearance_at_quantile = percentile(min_clearances, validation_quantile)
    if clearance_at_quantile >= -tolerance:
        return proposed_ground_y
    return proposed_ground_y + clearance_at_quantile + tolerance

def _plane_to_payload(plane: PlaneEstimate, *, space: str) -> dict[str, object]:
    payload: dict[str, object] = {
        "space": space,
        "normal": [plane.normal[0], plane.normal[1], plane.normal[2]],
        "offset": plane.offset,
    }
    if plane.rms_error is not None:
        payload["rmsError"] = plane.rms_error
    return payload


def _point_to_payload(point: tuple[float, float, float], *, space: str) -> dict[str, object]:
    return {
        "space": space,
        "point": [point[0], point[1], point[2]],
    }

def _median(values: list[float]) -> float:
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return float(ordered[midpoint])
    return float((ordered[midpoint - 1] + ordered[midpoint]) * 0.5)


def percentile(values: list[float], quantile: float) -> float:
    if not values:
        raise ValueError("percentile requires at least one value")
    ordered = sorted(values)
    clamped = min(max(quantile, 0.0), 1.0)
    if len(ordered) == 1:
        return float(ordered[0])
    position = clamped * (len(ordered) - 1)
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return float(ordered[lower])
    weight = position - lower
    return float(ordered[lower] * (1.0 - weight) + ordered[upper] * weight)


def _collect_support_heights(clip: MotionClip) -> list[float]:
    support_joint_names = _support_joint_names(clip)
    support_heights: list[float] = []
    for frame in clip.frames:
        supports = [
            frame.joints[name]
            for name in support_joint_names
            if name in frame.joints
        ]
        if not supports:
            continue
        support = min(supports, key=lambda point: point[1])
        support_heights.append(support_surface_height(support[1]))
    return support_heights


def _support_joint_names(clip: MotionClip) -> tuple[str, ...]:
    cleanup_metadata = clip.metadata.get("cleanup") if isinstance(clip.metadata, dict) else None
    support_mode = cleanup_metadata.get("supportMode") if isinstance(cleanup_metadata, dict) else None
    if support_mode == "quadruped":
        return ("left_hand", "right_hand", "left_knee", "right_knee")
    return (
        "left_foot",
        "right_foot",
        "left_ankle",
        "right_ankle",
        "l_ankle",
        "r_ankle",
    )
