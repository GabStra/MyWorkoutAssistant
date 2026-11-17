from __future__ import annotations

from dataclasses import replace
import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from exercise_motion_pkg.models import MotionClip
from exercise_motion_pkg.motion_io import save_motion_json
from exercise_motion_pkg.render_geometry import support_surface_height


def estimate_native_ground_plane_from_source_support(
    clip: MotionClip,
    source_support_evidence: dict[str, object] | None,
    *,
    selected_video_path: Path | None,
) -> dict[str, object] | None:
    """Estimate one fixed floor plane from verified source contacts and native shoes."""
    if not isinstance(source_support_evidence, dict) or selected_video_path is None:
        return None
    try:
        selected_video_path = Path(selected_video_path).expanduser().resolve()
        selected_digest = hashlib.sha256(selected_video_path.read_bytes()).hexdigest()
    except OSError:
        return None
    if str(source_support_evidence.get("sourceVideoSha256") or "").casefold() != selected_digest:
        return None

    reconstruction = clip.metadata.get("reconstruction") if isinstance(clip.metadata, dict) else None
    prior = reconstruction.get("footMarkerPrior") if isinstance(reconstruction, dict) else None
    from .native_foot_geometry import native_foot_geometry_from_prior
    from .foot_geometry import foot_scale_from_pose, shoe_vertices

    native_geometry = native_foot_geometry_from_prior(prior)
    if native_geometry is None or not clip.frames:
        return None
    mapping = clip.metadata.get("sourceTimelineMapping")
    if (not isinstance(mapping, dict) or mapping.get("verified") is not True
            or str(mapping.get("selectedSegmentSha256") or "").casefold() != selected_digest):
        return None
    lineage = mapping.get("selectedFrameLineage")
    if not isinstance(lineage, list) or not lineage:
        return None
    try:
        selected_clock_path = Path(str(mapping["selectedFrameClockReceiptPath"])).expanduser().resolve()
        selected_clock_sha = hashlib.sha256(selected_clock_path.read_bytes()).hexdigest()
        if selected_clock_sha != str(mapping.get("selectedFrameClockReceiptSha256") or "").casefold():
            return None
        from .source_frame_clock import load_verified_source_frame_clock
        selected_clock = load_verified_source_frame_clock(selected_clock_path)
        # The verified receipt may name an earlier exact copy of the selected
        # clip. Bind by output bytes and recorded selected-segment lineage, not
        # by comparing its parent/source hash or output path to this copy path.
        if (str(selected_clock.get("outputVideoSha256") or "").casefold() != selected_digest
                or selected_clock.get("outputFrameCount") != len(lineage)):
            return None
        clock_frames = selected_clock.get("frames")
        output_fps = float(selected_clock.get("outputFps", 0.0))
        if (not isinstance(clock_frames, list) or len(clock_frames) != len(lineage)
                or not math.isfinite(output_fps) or output_fps <= 0.0):
            return None
    except (KeyError, OSError, ValueError, TypeError):
        return None

    from .body_support_observation import validated_body_support_contact_timeline
    rows = validated_body_support_contact_timeline(
        source_support_evidence.get("bodySupportObservation"),
        expected_video_sha256=selected_digest)
    if rows is None:
        return None
    lineage_by_index: dict[int, tuple[float, float]] = {}
    try:
        for item in lineage:
            selected_index = item["selectedFrameIndex"]
            local_time, parent_time = float(item["selectedFrameTimeSec"]), float(item["parentSourceTimeSec"])
            if (type(selected_index) is not int or selected_index < 0
                    or not math.isfinite(local_time) or not math.isfinite(parent_time)):
                return None
            clock_frame = clock_frames[selected_index]
            if (not isinstance(clock_frame, dict)
                    or item.get("parentSourceFrameIndex") != clock_frame.get("sourceFrameIndex")
                    or abs(parent_time - float(clock_frame.get("sourceTimeSec"))) > 1e-6
                    or abs(local_time - selected_index / output_fps) > 1e-6):
                return None
            lineage_by_index[selected_index] = (local_time, parent_time)
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
    if not lineage_by_index:
        return None

    timed_frames = []
    for frame in clip.frames:
        if frame.source_time_sec is None or not math.isfinite(float(frame.source_time_sec)):
            return None
        timed_frames.append((float(frame.source_time_sec), frame))
    timed_frames.sort(key=lambda item: item[0])
    if any(timed_frames[i][0] >= timed_frames[i + 1][0] for i in range(len(timed_frames) - 1)):
        return None
    names = clip.joint_names
    try:
        scale = float(foot_scale_from_pose(
            np.asarray([clip.frames[0].joints[name] for name in names], dtype=float), names))
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(scale) or scale <= 0.0:
        return None

    times = [item[0] for item in timed_frames]

    def frame_at(source_time: float):
        index = int(np.searchsorted(times, source_time, side="left"))
        if index < len(times) and abs(times[index] - source_time) <= 1e-5:
            return timed_frames[index][1]
        if index <= 0 or index >= len(times):
            return None
        left_time, left = timed_frames[index - 1]
        right_time, right = timed_frames[index]
        fraction = (source_time - left_time) / (right_time - left_time)
        joints = {
            name: tuple(float(a) + (float(b) - float(a)) * fraction
                        for a, b in zip(left.joints[name], right.joints[name]))
            for name in names
        }
        if not isinstance(left.bone_sides, dict) or not isinstance(right.bone_sides, dict):
            return None
        sides = {}
        for key in set(left.bone_sides) & set(right.bone_sides):
            axis = np.asarray(left.bone_sides[key], dtype=float) * (1.0 - fraction) + np.asarray(
                right.bone_sides[key], dtype=float) * fraction
            norm = float(np.linalg.norm(axis))
            if norm <= 1e-9 or not np.isfinite(axis).all():
                return None
            sides[key] = tuple((axis / norm).tolist())
        from .models import MotionFrame
        return MotionFrame(time_sec=source_time, source_time_sec=source_time,
                           joints=joints, bone_sides=sides)

    patches = {
        "full_sole": tuple(range(26)),
        "forefoot": (*range(16, 24), 25),
        "heel_only": (*range(0, 8), 24),
        "inferred_outsole_patch": tuple(range(26)),
    }
    samples: list[tuple[float, str, str, str]] = []
    for row in rows:
        side = row.get("side")
        landmark, state, surface = row.get("landmark", "foot"), row.get("contactState"), row.get("surface")
        if side not in {"left", "right"} or row.get("visible") is not True or surface not in {"ground", "floor"}:
            continue
        if landmark == "foot" and state in {"full_sole", "forefoot", "heel_only"}:
            patch = state
        elif landmark == "region" and row.get("contactRegion") == "foot" and state == "direct_contact":
            patch = "inferred_outsole_patch"
        else:
            continue
        source_index = row.get("sourceFrameIndex")
        if source_index not in lineage_by_index:
            return None
        local_time, parent_time = lineage_by_index[source_index]
        if abs(local_time - float(row["sourceTimeSec"])) > 1e-4:
            return None
        pose_frame = frame_at(parent_time)
        if pose_frame is None:
            return None
        ankle_name, foot_name = f"{side}_ankle", f"{side}_foot"
        side_axis = (pose_frame.bone_sides or {}).get(f"{ankle_name}->{foot_name}")
        geometry_side = native_geometry["sides"].get(side)
        if ankle_name not in pose_frame.joints or foot_name not in pose_frame.joints or side_axis is None or geometry_side is None:
            return None
        try:
            vertices = shoe_vertices(
                np.asarray(pose_frame.joints[ankle_name]), np.asarray(pose_frame.joints[foot_name]),
                np.asarray(side_axis), None, scale, native_geometry=geometry_side)
            contact_y = float(np.min(np.asarray(vertices)[list(patches[patch]), 1]))
        except (ValueError, TypeError, IndexError, FloatingPointError):
            return None
        if not math.isfinite(contact_y):
            return None
        samples.append((contact_y, side, patch, str(row.get("sampleId"))))
    if not samples:
        return None
    floor_y = float(np.median([sample[0] for sample in samples]))
    rms = float(np.sqrt(np.mean([(sample[0] - floor_y) ** 2 for sample in samples])))
    return {
        "schemaVersion": 1,
        "kind": "source_native_foot_contact_plane_estimate",
        "authority": "verified_source_contact_plus_native_mesh_geometry",
        "planeNormal": [0.0, 1.0, 0.0],
        "planeOffsetMeters": floor_y,
        "planeRmsErrorMeters": rms,
        "surfaceHeightSource": "native_shoe_contact_patch_at_verified_source_times",
        "sourceVideoSha256": selected_digest,
        "selectedFrameClockReceiptPath": str(selected_clock_path),
        "selectedFrameClockReceiptSha256": selected_clock_sha,
        "sourceTimelineMappingKind": mapping.get("mappingKind"),
        "sampleCount": len(samples),
        "samples": [
            {"heightMeters": height, "side": side, "patchRole": role, "sampleId": sample_id}
            for height, side, role, sample_id in samples
        ],
    }


@dataclass(frozen=True)
class PlaneEstimate:
    normal: tuple[float, float, float]
    offset: float
    rms_error: float | None = None


@dataclass(frozen=True)
class GroundMetadata:
    render_plane: PlaneEstimate | None
    render_origin: tuple[float, float, float] | None
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
        if self.render_plane is not None and self.render_origin is not None:
            payload["renderGroundPlane"] = _plane_to_payload(self.render_plane, space="motion")
            payload["renderGroundOrigin"] = _point_to_payload(self.render_origin, space="motion")
        if self.camera_plane is not None:
            payload["unidepth"] = {
                **payload["unidepth"],
                "cameraGroundPlane": _plane_to_payload(self.camera_plane, space="camera"),
            }
        return payload


def _has_ground_contact_observations(clip: MotionClip) -> bool:
    cleanup = clip.metadata.get("cleanup") or {}
    reconstruction = clip.metadata.get("reconstruction") or {}
    native_geometry_present = (isinstance(reconstruction, dict)
                               and ("footMarkerPrior" in reconstruction
                                    or "nativeFootGeometry" in reconstruction))
    if native_geometry_present:
        native_contact = cleanup.get("nativeGroundContact") if isinstance(cleanup, dict) else None
        return bool(isinstance(native_contact, dict)
                    and native_contact.get("applied") is True
                    and native_contact.get("authority")
                    == "verified_source_contact_plus_native_mesh_geometry")
    grounding = cleanup.get("verticalGrounding") or {}
    if grounding.get("groundContactMode") == "none":
        return False
    return any(isinstance(state, dict) and bool(state.get("contactJoints"))
               for state in cleanup.get("footContacts") or [])


def clip_has_render_floor_authority(clip: MotionClip) -> bool:
    """Contact observations or applied camera-floor registration own the plane.

    Numeric all-frame foot bounds alone remain diagnostic, including retained
    metadata that formerly labelled that fallback as contact-authoritative.
    """
    ground = clip.metadata.get("ground") or {}
    if _has_ground_contact_observations(clip):
        return True
    video = clip.metadata.get("videoWorldAlignment") or {}
    if video.get("applied") and _camera_plane_from_alignment_metadata(video) is not None:
        return True
    depth = ground.get("unidepth") or {}
    return bool(depth.get("alignmentStatus") == "video_depth_yolo_aligned"
                and isinstance(depth.get("framesUsed"), int) and depth["framesUsed"] > 0
                and _camera_plane_from_alignment_metadata(depth) is not None)


def generate_ground_metadata(
    *,
    video_path: Path,
    cleaned_clip: MotionClip,
    output_path: Path,
    video_alignment_metadata: dict[str, object] | None = None,
) -> GroundMetadata:
    motion_plane = estimate_motion_ground_plane(cleaned_clip)
    motion_origin = estimate_motion_ground_origin(cleaned_clip, motion_plane)
    observed_contacts = _has_ground_contact_observations(cleaned_clip)
    cleanup = cleaned_clip.metadata.get("cleanup") if isinstance(cleaned_clip.metadata, dict) else None
    native_contact = cleanup.get("nativeGroundContact") if isinstance(cleanup, dict) else None
    native_contact_applied = (observed_contacts and isinstance(native_contact, dict)
                              and native_contact.get("applied") is True
                              and native_contact.get("authority")
                              == "verified_source_contact_plus_native_mesh_geometry")
    if native_contact_applied:
        plane_rms = native_contact.get("planeRmsErrorMeters")
        render_plane = PlaneEstimate((0.0, 1.0, 0.0), 0.0,
                                     float(plane_rms) if isinstance(plane_rms, (int, float)) else None)
        render_origin = (0.0, 0.0, 0.0)
    else:
        render_plane = motion_plane if observed_contacts else None
        render_origin = motion_origin if observed_contacts else None
    alignment_status = "motion_space_only"
    render_source = ("source_native_contact_mesh_inferred_plane" if native_contact_applied else
                     "motion_contact_authoritative" if observed_contacts else "motion_bounds_only")
    notes = ([
        "A single clip-level floor translation was estimated from verified ground-contact rows and the native shoe mesh; contact states and sole roles remain those in source evidence."
    ] if native_contact_applied else [
        "Motion-space foot bounds do not establish an observed render floor."
        if not observed_contacts else
        "Render floor is supported by recorded ground-contact episodes."
    ])
    camera_plane = _camera_plane_from_alignment_metadata(video_alignment_metadata)
    sample_frame_seconds: list[float] = []
    frames_used = 0
    model_name = None
    if (not native_contact_applied
            and isinstance(video_alignment_metadata, dict)
            and bool(video_alignment_metadata.get("applied"))
            and camera_plane is not None):
        render_plane, render_origin = motion_plane, motion_origin
        alignment_status = "video_depth_yolo_aligned"
        render_source = "video_depth_yolo_aligned_motion_contact"
        notes.append(
            "Video-grounded UniDepth floor + YOLO rigid alignment was applied before cleanup.",
        )
        sample_value = video_alignment_metadata.get("sampleFrameSeconds")
        if isinstance(sample_value, list):
            sample_frame_seconds = [
                float(value) for value in sample_value if isinstance(value, (int, float))
            ]
        frames_value = video_alignment_metadata.get("framesUsed")
        if isinstance(frames_value, int):
            frames_used = frames_value
        model_value = video_alignment_metadata.get("modelName")
        if isinstance(model_value, str) and model_value.strip():
            model_name = model_value.strip()

    metadata = GroundMetadata(
        render_plane=render_plane,
        render_origin=render_origin,
        motion_plane=motion_plane,
        motion_origin=motion_origin,
        camera_plane=camera_plane,
        sample_frame_seconds=sample_frame_seconds,
        frames_used=frames_used,
        model_name=model_name,
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


def _floor_anchored_ground_y(support_heights: list[float], measured_ground_y: float) -> float:
    """Anchor the ground to the floor when contacts span multiple surfaces.

    Movements onto a box/step produce contacts at the floor and at the raised
    surface. A plain median parks the render plane between the two, so floor
    contacts penetrate and raised landings float. When the contact-height
    spread clearly exceeds single-surface noise, use the lowest cluster.
    """
    if len(support_heights) < 6:
        return measured_ground_y
    sorted_heights = sorted(support_heights)
    low_percentile = percentile(sorted_heights, 0.10)
    high_percentile = percentile(sorted_heights, 0.90)
    if high_percentile - low_percentile <= 0.15:
        return measured_ground_y
    floor_ceiling = percentile(sorted_heights, 0.10) + 0.08
    floor_cluster = [value for value in sorted_heights if value <= floor_ceiling]
    if len(floor_cluster) < 3:
        return measured_ground_y
    return _median(floor_cluster)


def estimate_motion_ground_plane(clip: MotionClip) -> PlaneEstimate:
    cleanup_metadata = clip.metadata.get("cleanup") if isinstance(clip.metadata, dict) else None
    support_ground_y = None
    if isinstance(cleanup_metadata, dict):
        raw_support_ground_y = cleanup_metadata.get("supportGroundY")
        if isinstance(raw_support_ground_y, (int, float)) and math.isfinite(raw_support_ground_y):
            support_ground_y = float(raw_support_ground_y)

    # Sanity-check against measured support joint heights.
    support_heights = _collect_support_heights(clip)
    if support_heights:
        measured_ground_y = _median(support_heights)
        vertical_grounding = (
            cleanup_metadata.get("verticalGrounding")
            if isinstance(cleanup_metadata, dict)
            else None
        )
        intermittent_support = (
            isinstance(vertical_grounding, dict)
            and str(vertical_grounding.get("groundContactMode") or "").casefold()
            == "intermittent"
        )
        if intermittent_support:
            contact_episode_heights = _contact_episode_support_heights(clip)
            # Contact phases can belong to a floor and an elevated box/step.
            # Use the planted episode at the lower endpoint: the initial one
            # for an ascent and the final one for a descent. A numerically low
            # outlier episode can otherwise make a valid landing hover.
            if contact_episode_heights:
                root_name = next(
                    (name for name in ("pelvis", "hips", "root") if name in clip.joint_names),
                    None,
                )
                ends_higher = (
                    root_name is not None
                    and clip.frames[-1].joints[root_name][1]
                    > clip.frames[0].joints[root_name][1]
                )
                ground_y = (
                    contact_episode_heights[0]
                    if ends_higher
                    else contact_episode_heights[-1]
                )
            else:
                ground_y = percentile(support_heights, 0.10)
        elif support_ground_y is not None and abs(support_ground_y - measured_ground_y) <= 0.05:
            ground_y = support_ground_y
        else:
            ground_y = _floor_anchored_ground_y(support_heights, measured_ground_y)

        rms_error = math.sqrt(
            sum((value - ground_y) ** 2 for value in support_heights) / len(support_heights)
        )
        return PlaneEstimate(normal=(0.0, 1.0, 0.0), offset=-ground_y, rms_error=rms_error)

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
    support_heights = _collect_support_joint_center_heights(clip)
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


def _contact_episode_support_heights(clip: MotionClip) -> list[float]:
    cleanup = clip.metadata.get("cleanup") if isinstance(clip.metadata, dict) else None
    contacts = cleanup.get("footContacts") if isinstance(cleanup, dict) else None
    if not isinstance(contacts, list):
        return []
    episodes: list[list[float]] = []
    active: list[float] = []
    for frame_index, state in enumerate(contacts):
        if frame_index >= clip.frame_count or not isinstance(state, dict):
            break
        joint_names = state.get("contactJoints")
        if not isinstance(joint_names, list) or not joint_names:
            if active:
                episodes.append(active)
                active = []
            continue
        frame = clip.frames[frame_index]
        frame_heights = [
            support_surface_height(frame.joints[name][1])
            for name in joint_names
            if isinstance(name, str) and name in frame.joints
        ]
        if frame_heights:
            active.append(min(frame_heights))
    if active:
        episodes.append(active)
    return [_median(episode) for episode in episodes if episode]


def _collect_support_joint_center_heights(clip: MotionClip) -> list[float]:
    """Collect support joint CENTER heights (no capsule-surface subtraction)."""
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
        support_heights.append(float(support[1]))
    return support_heights


def _camera_plane_from_alignment_metadata(
    video_alignment_metadata: dict[str, object] | None,
) -> PlaneEstimate | None:
    if not isinstance(video_alignment_metadata, dict):
        return None
    payload = video_alignment_metadata.get("cameraGroundPlane")
    if not isinstance(payload, dict):
        return None
    normal_value = payload.get("normal")
    offset_value = payload.get("offset")
    if not isinstance(normal_value, list) or len(normal_value) != 3:
        return None
    if not isinstance(offset_value, (int, float)) or not math.isfinite(offset_value):
        return None
    rms_value = payload.get("rmsError")
    rms_error = float(rms_value) if isinstance(rms_value, (int, float)) else None
    return PlaneEstimate(
        normal=(float(normal_value[0]), float(normal_value[1]), float(normal_value[2])),
        offset=float(offset_value),
        rms_error=rms_error,
    )


def _support_joint_names(clip: MotionClip) -> tuple[str, ...]:
    cleanup_metadata = clip.metadata.get("cleanup") if isinstance(clip.metadata, dict) else None
    support_mode = cleanup_metadata.get("supportMode") if isinstance(cleanup_metadata, dict) else None
    if support_mode == "quadruped":
        return ("left_hand", "right_hand", "left_knee", "right_knee")
    if support_mode == "kneeling":
        return ("left_knee", "right_knee")
    return (
        "left_foot",
        "right_foot",
        "left_ankle",
        "right_ankle",
        "l_ankle",
        "r_ankle",
    )
