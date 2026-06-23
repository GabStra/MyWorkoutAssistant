from __future__ import annotations

import json
import math
from copy import deepcopy
from dataclasses import dataclass
from dataclasses import replace
from pathlib import Path

from exercise_motion_pkg.models import MotionClip, MotionFrame, Point3
from exercise_motion_pkg.wham_results import load_wham_results, select_wham_subject


SPINEPOSE_SPINE_COUNT = 9
SPINEPOSE_NECK_PROFILE_PROGRESS = 6.0 / (SPINEPOSE_SPINE_COUNT - 1)
SMPL_SPINE_JOINTS = (3, 6, 9)
SMPL_ARM_ANCHOR_JOINTS = (13, 14)
DEFAULT_SPINE_WEIGHTS = (0.50, 0.30, 0.20)
DEFAULT_ARM_COUNTER_ROTATION = 1.0
DEFAULT_LOWER_TORSO_FOLLOW = 0.20
DEFAULT_UPPER_TORSO_FOLLOW = 0.45
LOWER_TORSO_FOLLOW_JOINTS = ("pelvis", "left_hip", "right_hip")
UPPER_TORSO_FOLLOW_JOINTS = (
    "neck",
    "head",
    "left_collar",
    "right_collar",
    "left_shoulder",
    "right_shoulder",
)


@dataclass(frozen=True)
class SpinePoseWhamCorrectionStats:
    frame_count: int
    source_frame_count: int
    applied_frame_count: int
    max_delta_degrees: float
    mean_abs_delta_degrees: float
    pose_keys: tuple[str, ...]
    arm_counter_rotation: float


@dataclass(frozen=True)
class SpinePoseMotionFusionStats:
    frame_count: int
    source_frame_count: int
    valid_source_frame_count: int
    applied_frame_count: int
    fused_joint_names: tuple[str, ...]
    max_displacement: float
    mean_abs_displacement: float
    gain: float
    max_degrees: float
    smoothing_window: int
    inverted: bool
    alignment_mode: str
    source_fps: float | None
    curve_source: str
    curve_quality_score: float
    curve_selection_reason: str
    propagated_joint_names: tuple[str, ...]
    max_propagated_displacement: float
    mean_abs_propagated_displacement: float
    lower_torso_follow: float
    upper_torso_follow: float
    candidate_quality: dict[str, object]


@dataclass(frozen=True)
class SpinePoseProfileCandidate:
    source: str
    profiles: list[list[float]]
    valid_frame_count: int
    mean_confidence: float | None
    min_confidence: float | None
    mean_abs_curve: float
    dynamic_range: float
    temporal_roughness: float
    quality_score: float


@dataclass(frozen=True)
class SpinePoseProfileSelection:
    profiles: list[list[float]]
    source_frame_count: int
    valid_source_frame_count: int
    alignment_mode: str
    curve_source: str
    quality_score: float
    selection_reason: str
    candidate_quality: dict[str, object]
    skipped_reason: str | None = None


def apply_spinepose_to_wham_pkl(
    *,
    wham_results_pkl: Path,
    spinepose_json_dir: Path,
    output_pkl: Path,
    subject_id: int | str | None = None,
    gain: float = 1.0,
    max_degrees: float = 35.0,
    axis: int = 0,
    invert: bool = False,
    smoothing_window: int = 9,
    arm_counter_rotation: float = DEFAULT_ARM_COUNTER_ROTATION,
) -> SpinePoseWhamCorrectionStats:
    try:
        import joblib  # type: ignore
        import numpy as np  # type: ignore
    except ImportError as exc:
        raise RuntimeError("SpinePose/WHAM correction requires joblib and numpy.") from exc

    raw_results = load_wham_results(wham_results_pkl)
    selected_subject_id, payload = select_wham_subject(raw_results, subject_id=subject_id)
    corrected_results = deepcopy(raw_results)
    corrected_payload = corrected_results[selected_subject_id]

    pose = payload.get("pose")
    if not hasattr(pose, "shape") or len(pose.shape) != 2 or pose.shape[1] != 72:  # type: ignore[attr-defined]
        raise ValueError("WHAM camera pose must be shaped like [frames, 72].")
    frame_count = int(pose.shape[0])  # type: ignore[index]

    flexion = _load_spinepose_flexion_signal(spinepose_json_dir, frame_count=frame_count)
    flexion = _median_center(flexion)
    flexion = _moving_average(flexion, window=smoothing_window)
    if invert:
        flexion = [-value for value in flexion]
    max_radians = math.radians(max_degrees)
    deltas = [max(-max_radians, min(max_radians, value * gain)) for value in flexion]

    pose_keys = [key for key in ("pose", "pose_world") if key in corrected_payload]
    total_spine_weight = sum(DEFAULT_SPINE_WEIGHTS)
    arm_counter_rotation = max(0.0, min(1.0, arm_counter_rotation))
    for key in pose_keys:
        corrected_pose = np.array(corrected_payload[key], dtype=np.float32, copy=True)
        if corrected_pose.shape[0] != frame_count or corrected_pose.shape[1] != 72:
            continue
        for frame_index, delta in enumerate(deltas):
            for joint_index, weight in zip(SMPL_SPINE_JOINTS, DEFAULT_SPINE_WEIGHTS, strict=True):
                corrected_pose[frame_index, joint_index * 3 + axis] += float(delta * weight)
            arm_counter_delta = float(-delta * total_spine_weight * arm_counter_rotation)
            for joint_index in SMPL_ARM_ANCHOR_JOINTS:
                corrected_pose[frame_index, joint_index * 3 + axis] += arm_counter_delta
        corrected_payload[key] = corrected_pose

    metadata = dict(corrected_payload.get("spinepose_correction", {}))
    metadata.update(
        {
            "source": "spinepose",
            "spineposeJsonDir": str(spinepose_json_dir),
            "gain": gain,
            "maxDegrees": max_degrees,
            "axis": axis,
            "invert": invert,
            "smoothingWindow": smoothing_window,
            "armCounterRotation": arm_counter_rotation,
            "weights": {
                "spine1": DEFAULT_SPINE_WEIGHTS[0],
                "spine2": DEFAULT_SPINE_WEIGHTS[1],
                "spine3": DEFAULT_SPINE_WEIGHTS[2],
            },
        }
    )
    corrected_payload["spinepose_correction"] = metadata

    output_pkl.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(corrected_results, output_pkl)

    abs_deltas = [abs(value) for value in deltas]
    return SpinePoseWhamCorrectionStats(
        frame_count=frame_count,
        source_frame_count=len(list(spinepose_json_dir.glob("*.json"))),
        applied_frame_count=len(deltas),
        max_delta_degrees=math.degrees(max(abs_deltas) if abs_deltas else 0.0),
        mean_abs_delta_degrees=math.degrees(sum(abs_deltas) / len(abs_deltas)) if abs_deltas else 0.0,
        pose_keys=tuple(pose_keys),
        arm_counter_rotation=arm_counter_rotation,
    )


def apply_spinepose_to_motion_clip(
    clip: MotionClip,
    *,
    spinepose_json_dir: Path,
    gain: float = 1.0,
    max_degrees: float = 35.0,
    invert: bool = False,
    smoothing_window: int = 9,
    source_fps: float | None = None,
) -> tuple[MotionClip, SpinePoseMotionFusionStats]:
    if not clip.frames:
        raise ValueError("Cannot fuse SpinePose into an empty motion clip.")

    target_joint_names = _target_spine_joint_names(clip.joint_names)
    if not target_joint_names:
        raise ValueError("Motion clip does not contain spine joints to fuse.")

    frame_times_sec = [frame.time_sec for frame in clip.frames]
    selection = _load_spinepose_curve_profiles(
        spinepose_json_dir,
        frame_count=clip.frame_count,
        frame_times_sec=frame_times_sec,
        source_fps=source_fps,
        smoothing_window=smoothing_window,
    )
    if selection.skipped_reason is not None:
        stats = SpinePoseMotionFusionStats(
            frame_count=clip.frame_count,
            source_frame_count=selection.source_frame_count,
            valid_source_frame_count=selection.valid_source_frame_count,
            applied_frame_count=0,
            fused_joint_names=tuple(target_joint_names),
            max_displacement=0.0,
            mean_abs_displacement=0.0,
            gain=gain,
            max_degrees=max_degrees,
            smoothing_window=smoothing_window,
            inverted=invert,
            alignment_mode=selection.alignment_mode,
            source_fps=source_fps if source_fps is not None and source_fps > 0 else None,
            curve_source=selection.curve_source,
            curve_quality_score=selection.quality_score,
            curve_selection_reason=selection.selection_reason,
            propagated_joint_names=(),
            max_propagated_displacement=0.0,
            mean_abs_propagated_displacement=0.0,
            lower_torso_follow=DEFAULT_LOWER_TORSO_FOLLOW,
            upper_torso_follow=DEFAULT_UPPER_TORSO_FOLLOW,
            candidate_quality=selection.candidate_quality,
        )
        metadata = _spinepose_motion_fusion_metadata(
            spinepose_json_dir=spinepose_json_dir,
            stats=stats,
            skipped_reason=selection.skipped_reason,
        )
        return replace(clip, metadata={**clip.metadata, "spineposeMotionFusion": metadata}), stats

    profiles = selection.profiles
    max_radians = math.radians(max(0.0, max_degrees))
    applied_frames = 0
    displacements: list[float] = []
    propagated_displacements: list[float] = []
    propagated_joint_names: set[str] = set()
    fused_frames: list[MotionFrame] = []
    for frame, profile in zip(clip.frames, profiles, strict=True):
        torso_basis = _build_wham_torso_basis(frame.joints)
        if torso_basis is None:
            fused_frames.append(frame)
            continue
        base, up_axis, lateral_axis, depth_axis, torso_length = torso_basis
        max_displacement = torso_length * math.tan(max_radians) * 0.5
        joints = dict(frame.joints)
        frame_changed = False
        frame_spine_displacements: dict[str, float] = {}
        for joint_name in target_joint_names:
            original = frame.joints.get(joint_name)
            if original is None:
                continue
            progress = _clamp(_dot(_subtract_point(original, base), up_axis) / torso_length, 0.05, 0.95)
            curve_value = _interpolate_profile(profile, progress)
            if invert:
                curve_value = -curve_value
            displacement = _clamp(curve_value * torso_length * gain, -max_displacement, max_displacement)
            straight_point = _add_point(base, _scale_point(up_axis, progress * torso_length))
            preserved_lateral = _dot(_subtract_point(original, straight_point), lateral_axis)
            fused_point = _add_point(
                straight_point,
                _add_point(
                    _scale_point(lateral_axis, preserved_lateral),
                    _scale_point(depth_axis, displacement),
                ),
            )
            joints[joint_name] = fused_point
            frame_spine_displacements[joint_name] = displacement
            displacements.append(abs(displacement))
            if abs(displacement) > 1e-8:
                frame_changed = True
        upper_torso_curve_value = _interpolate_profile(profile, SPINEPOSE_NECK_PROFILE_PROGRESS)
        if invert:
            upper_torso_curve_value = -upper_torso_curve_value
        frame_spine_displacements["upper_torso"] = _clamp(
            upper_torso_curve_value * torso_length * gain,
            -max_displacement,
            max_displacement,
        )
        propagated = _apply_spinepose_torso_follow_through(
            joints,
            depth_axis=depth_axis,
            spine_displacements=frame_spine_displacements,
        )
        for joint_name, distance in propagated:
            propagated_joint_names.add(joint_name)
            propagated_displacements.append(distance)
            if distance > 1e-8:
                frame_changed = True
        if frame_changed:
            applied_frames += 1
        fused_frames.append(MotionFrame(time_sec=frame.time_sec, joints=joints))

    max_applied_displacement = max(displacements) if displacements else 0.0
    mean_abs_displacement = sum(displacements) / len(displacements) if displacements else 0.0
    max_propagated_displacement = max(propagated_displacements) if propagated_displacements else 0.0
    mean_abs_propagated_displacement = (
        sum(propagated_displacements) / len(propagated_displacements) if propagated_displacements else 0.0
    )
    stats = SpinePoseMotionFusionStats(
        frame_count=clip.frame_count,
        source_frame_count=selection.source_frame_count,
        valid_source_frame_count=selection.valid_source_frame_count,
        applied_frame_count=applied_frames,
        fused_joint_names=tuple(target_joint_names),
        max_displacement=max_applied_displacement,
        mean_abs_displacement=mean_abs_displacement,
        gain=gain,
        max_degrees=max_degrees,
        smoothing_window=smoothing_window,
        inverted=invert,
        alignment_mode=selection.alignment_mode,
        source_fps=source_fps if source_fps is not None and source_fps > 0 else None,
        curve_source=selection.curve_source,
        curve_quality_score=selection.quality_score,
        curve_selection_reason=selection.selection_reason,
        propagated_joint_names=tuple(sorted(propagated_joint_names)),
        max_propagated_displacement=max_propagated_displacement,
        mean_abs_propagated_displacement=mean_abs_propagated_displacement,
        lower_torso_follow=DEFAULT_LOWER_TORSO_FOLLOW,
        upper_torso_follow=DEFAULT_UPPER_TORSO_FOLLOW,
        candidate_quality=selection.candidate_quality,
    )
    metadata = dict(clip.metadata)
    metadata["spineposeMotionFusion"] = _spinepose_motion_fusion_metadata(
        spinepose_json_dir=spinepose_json_dir,
        stats=stats,
    )
    return replace(clip, frames=fused_frames, metadata=metadata), stats


def _spinepose_motion_fusion_metadata(
    *,
    spinepose_json_dir: Path,
    stats: SpinePoseMotionFusionStats,
    skipped_reason: str | None = None,
) -> dict[str, object]:
    metadata: dict[str, object] = {
        "source": "spinepose",
        "mode": "motion_clip_spine_curve_fit",
        "spineposeJsonDir": str(spinepose_json_dir),
        "frames": stats.frame_count,
        "sourceFrames": stats.source_frame_count,
        "validSourceFrames": stats.valid_source_frame_count,
        "appliedFrames": stats.applied_frame_count,
        "fusedJointNames": list(stats.fused_joint_names),
        "maxDisplacement": stats.max_displacement,
        "meanAbsDisplacement": stats.mean_abs_displacement,
        "gain": stats.gain,
        "maxDegrees": stats.max_degrees,
        "smoothingWindow": stats.smoothing_window,
        "invert": stats.inverted,
        "alignmentMode": stats.alignment_mode,
        "sourceFps": stats.source_fps,
        "curveSource": stats.curve_source,
        "curveQualityScore": stats.curve_quality_score,
        "curveSelectionReason": stats.curve_selection_reason,
        "propagatedJointNames": list(stats.propagated_joint_names),
        "maxPropagatedDisplacement": stats.max_propagated_displacement,
        "meanAbsPropagatedDisplacement": stats.mean_abs_propagated_displacement,
        "lowerTorsoFollow": stats.lower_torso_follow,
        "upperTorsoFollow": stats.upper_torso_follow,
        "candidateQuality": stats.candidate_quality,
        "basis": {
            "base": "pelvis_or_hips",
            "top": "neck_or_upper_spine",
            "bendAxis": "torso_depth_from_shoulders_or_hips",
        },
    }
    if skipped_reason is not None:
        metadata["skippedReason"] = skipped_reason
    return metadata


def _load_spinepose_flexion_signal(spinepose_json_dir: Path, *, frame_count: int) -> list[float]:
    files = sorted(spinepose_json_dir.glob("*.json"))
    if not files:
        raise ValueError(f"No SpinePose JSON frames found in {spinepose_json_dir}.")

    values: list[float] = []
    previous_value = 0.0
    for file in files[:frame_count]:
        frame = json.loads(file.read_text(encoding="utf-8"))
        people = frame.get("people") or []
        if not people:
            values.append(previous_value)
            continue
        raw_points = people[0].get("pose_keypoints_3d") or people[0].get("pose_keypoints_2d")
        if not raw_points:
            values.append(previous_value)
            continue
        stride = 4 if len(raw_points) >= SPINEPOSE_SPINE_COUNT * 4 else 3
        points = [
            tuple(float(v) for v in raw_points[index : index + stride - 1])
            for index in range(0, min(len(raw_points), SPINEPOSE_SPINE_COUNT * stride), stride)
        ]
        if len(points) < SPINEPOSE_SPINE_COUNT:
            values.append(previous_value)
            continue
        value = _spine_curve_angle(points)
        previous_value = value
        values.append(value)

    if len(values) < frame_count:
        values.extend([previous_value] * (frame_count - len(values)))
    return values[:frame_count]


def _load_spinepose_curve_profiles(
    spinepose_json_dir: Path,
    *,
    frame_count: int,
    frame_times_sec: list[float] | None = None,
    source_fps: float | None = None,
    smoothing_window: int,
) -> SpinePoseProfileSelection:
    files = sorted(spinepose_json_dir.glob("*.json"))
    if not files:
        raise ValueError(f"No SpinePose JSON frames found in {spinepose_json_dir}.")

    source_frames = [json.loads(file.read_text(encoding="utf-8")) for file in files]
    candidates = [
        candidate
        for candidate in (
            _build_spinepose_profile_candidate(source_frames, source="2d", smoothing_window=smoothing_window),
            _build_spinepose_profile_candidate(source_frames, source="3d", smoothing_window=smoothing_window),
        )
        if candidate is not None
    ]
    if not candidates:
        raise ValueError(f"No usable SpinePose spine keypoints found in {spinepose_json_dir}.")

    selected, selection_reason = _select_spinepose_profile_candidate(candidates)
    alignment_mode = "resampled_full_source"
    aligned_profiles = selected.profiles
    if _can_sample_profiles_by_source_time(
        frame_times_sec=frame_times_sec,
        source_fps=source_fps,
        source_frame_count=len(selected.profiles),
        frame_count=frame_count,
    ):
        aligned_profiles = _sample_profiles_by_source_time(
            selected.profiles,
            frame_times_sec=frame_times_sec or [],
            source_fps=float(source_fps),
        )
        alignment_mode = "source_video_time"
    else:
        aligned_profiles = _resample_profiles(selected.profiles, frame_count=frame_count)

    skipped_reason = None
    if selected.quality_score < 0.2:
        aligned_profiles = [[0.0] * SPINEPOSE_SPINE_COUNT for _ in range(frame_count)]
        skipped_reason = "unreliable_spinepose_curve"

    return SpinePoseProfileSelection(
        profiles=aligned_profiles,
        source_frame_count=len(files),
        valid_source_frame_count=selected.valid_frame_count,
        alignment_mode=alignment_mode,
        curve_source=selected.source if skipped_reason is None else "none",
        quality_score=selected.quality_score,
        selection_reason=selection_reason if skipped_reason is None else "skipped_unreliable_curve",
        candidate_quality={candidate.source: _profile_candidate_quality_payload(candidate) for candidate in candidates},
        skipped_reason=skipped_reason,
    )


def _build_spinepose_profile_candidate(
    frames: list[dict[str, object]],
    *,
    source: str,
    smoothing_window: int,
) -> SpinePoseProfileCandidate | None:
    profiles: list[list[float]] = []
    previous_profile = [0.0] * SPINEPOSE_SPINE_COUNT
    valid_frame_count = 0
    confidence_values: list[float] = []
    for frame in frames:
        extraction = _extract_spinepose_points(frame, source=source)
        if extraction is None:
            profiles.append(previous_profile)
            continue
        points, confidences = extraction
        profile = _spine_curve_profile(points)
        previous_profile = profile
        profiles.append(profile)
        valid_frame_count += 1
        confidence_values.extend(confidences)

    if valid_frame_count <= 0:
        return None

    smoothed_profiles = _moving_average_profiles(profiles, window=smoothing_window)
    mean_confidence = sum(confidence_values) / len(confidence_values) if confidence_values else None
    min_confidence = min(confidence_values) if confidence_values else None
    mean_abs_curve = _mean_abs_profile_value(smoothed_profiles)
    dynamic_range = _profile_dynamic_range(smoothed_profiles)
    temporal_roughness = _profile_temporal_roughness(smoothed_profiles)
    quality_score = _score_spinepose_profile_candidate(
        source_frame_count=len(frames),
        valid_frame_count=valid_frame_count,
        mean_confidence=mean_confidence,
        mean_abs_curve=mean_abs_curve,
        dynamic_range=dynamic_range,
        temporal_roughness=temporal_roughness,
    )
    return SpinePoseProfileCandidate(
        source=source,
        profiles=smoothed_profiles,
        valid_frame_count=valid_frame_count,
        mean_confidence=mean_confidence,
        min_confidence=min_confidence,
        mean_abs_curve=mean_abs_curve,
        dynamic_range=dynamic_range,
        temporal_roughness=temporal_roughness,
        quality_score=quality_score,
    )


def _select_spinepose_profile_candidate(
    candidates: list[SpinePoseProfileCandidate],
) -> tuple[SpinePoseProfileCandidate, str]:
    by_source = {candidate.source: candidate for candidate in candidates}
    two_d = by_source.get("2d")
    three_d = by_source.get("3d")
    if two_d is not None and three_d is not None:
        if _visible_2d_curve_has_stronger_motion(two_d, three_d):
            return two_d, "2d_visible_motion_stronger_than_3d_lift"
        if three_d.quality_score >= two_d.quality_score * 0.85:
            return three_d, "3d_lift_quality_comparable"
        return two_d, "2d_quality_higher"
    selected = max(candidates, key=lambda candidate: candidate.quality_score)
    return selected, f"only_{selected.source}_curve_available"


def _visible_2d_curve_has_stronger_motion(
    two_d: SpinePoseProfileCandidate,
    three_d: SpinePoseProfileCandidate,
) -> bool:
    if two_d.dynamic_range < 0.08:
        return False
    if two_d.dynamic_range < three_d.dynamic_range * 1.6:
        return False
    if two_d.quality_score < three_d.quality_score * 0.65:
        return False
    roughness_ratio = two_d.temporal_roughness / max(two_d.dynamic_range, 0.03)
    return roughness_ratio <= 0.08


def _score_spinepose_profile_candidate(
    *,
    source_frame_count: int,
    valid_frame_count: int,
    mean_confidence: float | None,
    mean_abs_curve: float,
    dynamic_range: float,
    temporal_roughness: float,
) -> float:
    valid_ratio = _clamp(valid_frame_count / max(1, source_frame_count), 0.0, 1.0)
    confidence_score = 0.75 if mean_confidence is None else _clamp((mean_confidence - 0.35) / 0.35, 0.0, 1.0)
    signal_strength = max(mean_abs_curve, dynamic_range)
    signal_score = _clamp(signal_strength / 0.08, 0.2, 1.0)
    roughness_ratio = temporal_roughness / max(dynamic_range, 0.03)
    stability_score = _clamp(1.0 - roughness_ratio * 0.5, 0.25, 1.0)
    return valid_ratio * confidence_score * signal_score * stability_score


def _profile_candidate_quality_payload(candidate: SpinePoseProfileCandidate) -> dict[str, object]:
    return {
        "validFrames": candidate.valid_frame_count,
        "meanConfidence": candidate.mean_confidence,
        "minConfidence": candidate.min_confidence,
        "meanAbsCurve": candidate.mean_abs_curve,
        "dynamicRange": candidate.dynamic_range,
        "temporalRoughness": candidate.temporal_roughness,
        "qualityScore": candidate.quality_score,
    }


def _mean_abs_profile_value(profiles: list[list[float]]) -> float:
    values = [abs(value) for profile in profiles for value in profile]
    return sum(values) / len(values) if values else 0.0


def _profile_dynamic_range(profiles: list[list[float]]) -> float:
    if not profiles:
        return 0.0
    sample_ranges: list[float] = []
    for sample_index in range(SPINEPOSE_SPINE_COUNT):
        values = [profile[sample_index] for profile in profiles]
        sample_ranges.append(max(values) - min(values))
    return max(sample_ranges, default=0.0)


def _profile_temporal_roughness(profiles: list[list[float]]) -> float:
    if len(profiles) < 2:
        return 0.0
    deltas: list[float] = []
    for previous, current in zip(profiles, profiles[1:]):
        deltas.extend(abs(current[index] - previous[index]) for index in range(SPINEPOSE_SPINE_COUNT))
    return sum(deltas) / len(deltas) if deltas else 0.0


def _can_sample_profiles_by_source_time(
    *,
    frame_times_sec: list[float] | None,
    source_fps: float | None,
    source_frame_count: int,
    frame_count: int,
) -> bool:
    if source_fps is None or source_fps <= 0 or source_frame_count <= 1:
        return False
    if frame_times_sec is None or len(frame_times_sec) != frame_count or frame_count <= 0:
        return False
    if not all(math.isfinite(value) for value in frame_times_sec):
        return False
    source_duration_sec = source_frame_count / source_fps
    tolerance_sec = max(0.25, 2.0 / source_fps)
    return min(frame_times_sec) >= -tolerance_sec and max(frame_times_sec) <= source_duration_sec + tolerance_sec


def _sample_profiles_by_source_time(
    profiles: list[list[float]],
    *,
    frame_times_sec: list[float],
    source_fps: float,
) -> list[list[float]]:
    if not profiles:
        return []
    sampled_profiles: list[list[float]] = []
    max_source_index = len(profiles) - 1
    for time_sec in frame_times_sec:
        source_position = _clamp(float(time_sec) * source_fps, 0.0, float(max_source_index))
        lower_index = int(math.floor(source_position))
        upper_index = min(max_source_index, lower_index + 1)
        fraction = source_position - lower_index
        lower = profiles[lower_index]
        upper = profiles[upper_index]
        sampled_profiles.append(
            [
                lower[sample_index] + (upper[sample_index] - lower[sample_index]) * fraction
                for sample_index in range(SPINEPOSE_SPINE_COUNT)
            ]
        )
    return sampled_profiles


def _extract_spinepose_points(
    frame: dict[str, object],
    *,
    source: str,
) -> tuple[list[tuple[float, ...]], list[float]] | None:
    people = frame.get("people") if isinstance(frame, dict) else None
    if not isinstance(people, list) or not people:
        return None
    person = people[0]
    if not isinstance(person, dict):
        return None
    if source == "2d":
        raw_points = person.get("pose_keypoints_2d")
        stride = 3
        coordinate_count = 2
    elif source == "3d":
        raw_points = person.get("pose_keypoints_3d")
        stride = 4
        coordinate_count = 3
    else:
        raise ValueError(f"Unsupported SpinePose point source: {source}")
    if not isinstance(raw_points, list) or not raw_points:
        return None
    points: list[tuple[float, ...]] = []
    confidences: list[float] = []
    for index in range(0, min(len(raw_points), SPINEPOSE_SPINE_COUNT * stride), stride):
        row = raw_points[index : index + stride]
        coords = row[:coordinate_count]
        if len(coords) < coordinate_count:
            continue
        points.append(tuple(float(value) for value in coords))
        if len(row) > coordinate_count:
            confidences.append(float(row[coordinate_count]))
    if len(points) < 2:
        return None
    return points, confidences


def _spine_curve_profile(points: list[tuple[float, ...]]) -> list[float]:
    base = points[0]
    top = points[-1]
    if len(base) >= 3 and len(top) >= 3:
        return _spine_curve_profile_3d(points)
    line_x = float(top[0] - base[0])
    line_y = float(top[1] - base[1])
    line_length = math.hypot(line_x, line_y)
    if line_length <= 1e-6:
        return [0.0] * SPINEPOSE_SPINE_COUNT
    normal = (line_y / line_length, -line_x / line_length)
    profile: list[float] = []
    for sample_index in range(SPINEPOSE_SPINE_COUNT):
        progress = sample_index / max(1, SPINEPOSE_SPINE_COUNT - 1)
        source_point = _interpolate_source_points(points, progress)
        straight_x = float(base[0]) + line_x * progress
        straight_y = float(base[1]) + line_y * progress
        offset_x = float(source_point[0]) - straight_x
        offset_y = float(source_point[1]) - straight_y
        profile.append((offset_x * normal[0] + offset_y * normal[1]) / line_length)
    return profile


def _spine_curve_profile_3d(points: list[tuple[float, ...]]) -> list[float]:
    base = _tuple_point3(points[0])
    top = _tuple_point3(points[-1])
    spine_axis = _subtract_point(top, base)
    line_length = _length(spine_axis)
    if line_length <= 1e-6:
        return [0.0] * SPINEPOSE_SPINE_COUNT
    spine_axis = _scale_point(spine_axis, 1.0 / line_length)
    residuals: list[Point3] = []
    for sample_index in range(SPINEPOSE_SPINE_COUNT):
        progress = sample_index / max(1, SPINEPOSE_SPINE_COUNT - 1)
        source_point = _tuple_point3(_interpolate_source_points(points, progress))
        straight_point = _add_point(base, _scale_point(_subtract_point(top, base), progress))
        residual = _subtract_point(source_point, straight_point)
        residual = _subtract_point(residual, _scale_point(spine_axis, _dot(residual, spine_axis)))
        residuals.append(residual)
    bend_axis = _dominant_residual_axis(residuals)
    if bend_axis is None:
        return [0.0] * SPINEPOSE_SPINE_COUNT
    return [_dot(residual, bend_axis) / line_length for residual in residuals]


def _dominant_residual_axis(residuals: list[Point3]) -> Point3 | None:
    dominant = max(residuals, key=_length, default=(0.0, 0.0, 0.0))
    return _normalize(dominant)


def _tuple_point3(point: tuple[float, ...]) -> Point3:
    if len(point) < 3:
        return (float(point[0]), float(point[1]), 0.0)
    return (float(point[0]), float(point[1]), float(point[2]))


def _interpolate_source_points(points: list[tuple[float, ...]], progress: float) -> tuple[float, ...]:
    if len(points) == 1:
        return points[0]
    scaled = _clamp(progress, 0.0, 1.0) * (len(points) - 1)
    lower_index = int(math.floor(scaled))
    upper_index = min(len(points) - 1, lower_index + 1)
    fraction = scaled - lower_index
    lower = points[lower_index]
    upper = points[upper_index]
    dimension_count = min(len(lower), len(upper))
    return tuple(float(lower[index]) + (float(upper[index]) - float(lower[index])) * fraction for index in range(dimension_count))


def _moving_average_profiles(profiles: list[list[float]], *, window: int) -> list[list[float]]:
    if window <= 1 or len(profiles) <= 2:
        return profiles
    radius = max(1, window // 2)
    smoothed: list[list[float]] = []
    for index in range(len(profiles)):
        start = max(0, index - radius)
        end = min(len(profiles), index + radius + 1)
        count = end - start
        smoothed.append(
            [
                sum(profiles[profile_index][sample_index] for profile_index in range(start, end)) / count
                for sample_index in range(SPINEPOSE_SPINE_COUNT)
            ]
        )
    return smoothed


def _resample_profiles(profiles: list[list[float]], *, frame_count: int) -> list[list[float]]:
    if len(profiles) == frame_count:
        return profiles
    if frame_count <= 1:
        return [profiles[0]]
    if len(profiles) <= 1:
        return [profiles[0] for _ in range(frame_count)]
    resampled: list[list[float]] = []
    for frame_index in range(frame_count):
        source_position = frame_index * (len(profiles) - 1) / (frame_count - 1)
        lower_index = int(math.floor(source_position))
        upper_index = min(len(profiles) - 1, lower_index + 1)
        fraction = source_position - lower_index
        lower = profiles[lower_index]
        upper = profiles[upper_index]
        resampled.append(
            [
                lower[sample_index] + (upper[sample_index] - lower[sample_index]) * fraction
                for sample_index in range(SPINEPOSE_SPINE_COUNT)
            ]
        )
    return resampled


def _target_spine_joint_names(joint_names: list[str]) -> list[str]:
    smpl_spine_joints = [joint_name for joint_name in ("spine1", "spine2", "spine3") if joint_name in joint_names]
    if smpl_spine_joints:
        return smpl_spine_joints
    if "spine" in joint_names:
        return ["spine"]
    return []


def _apply_spinepose_torso_follow_through(
    joints: dict[str, Point3],
    *,
    depth_axis: Point3,
    spine_displacements: dict[str, float],
) -> list[tuple[str, float]]:
    lower_displacement = spine_displacements.get("spine1")

    propagated: list[tuple[str, float]] = []
    if lower_displacement is not None:
        for joint_name in LOWER_TORSO_FOLLOW_JOINTS:
            distance = lower_displacement * DEFAULT_LOWER_TORSO_FOLLOW
            if _apply_joint_depth_offset(joints, joint_name, depth_axis, distance):
                propagated.append((joint_name, abs(distance)))

    upper_displacement = spine_displacements.get("upper_torso")
    if upper_displacement is None:
        upper_displacement = spine_displacements.get("spine3")
    if upper_displacement is not None:
        for joint_name in UPPER_TORSO_FOLLOW_JOINTS:
            distance = upper_displacement * DEFAULT_UPPER_TORSO_FOLLOW
            if _apply_joint_depth_offset(joints, joint_name, depth_axis, distance):
                propagated.append((joint_name, abs(distance)))
    return propagated


def _apply_joint_depth_offset(
    joints: dict[str, Point3],
    joint_name: str,
    depth_axis: Point3,
    distance: float,
) -> bool:
    point = joints.get(joint_name)
    if point is None:
        return False
    joints[joint_name] = _add_point(point, _scale_point(depth_axis, distance))
    return True


def _build_wham_torso_basis(joints: dict[str, Point3]) -> tuple[Point3, Point3, Point3, Point3, float] | None:
    base = _joint_or_midpoint(joints, "pelvis", ("left_hip", "right_hip"))
    top = _joint_or_first(joints, ("neck", "spine3", "head", "spine"))
    if base is None or top is None:
        return None
    torso_vector = _subtract_point(top, base)
    torso_length = _length(torso_vector)
    if torso_length <= 1e-6:
        return None
    up_axis = _scale_point(torso_vector, 1.0 / torso_length)
    lateral_axis = _lateral_axis_from_joints(joints, up_axis)
    depth_axis = _normalize(_cross(lateral_axis, up_axis))
    if depth_axis is None:
        return None
    return base, up_axis, lateral_axis, depth_axis, torso_length


def _joint_or_midpoint(
    joints: dict[str, Point3],
    primary: str,
    midpoint_pair: tuple[str, str],
) -> Point3 | None:
    if primary in joints:
        return joints[primary]
    left = joints.get(midpoint_pair[0])
    right = joints.get(midpoint_pair[1])
    if left is None or right is None:
        return None
    return ((left[0] + right[0]) * 0.5, (left[1] + right[1]) * 0.5, (left[2] + right[2]) * 0.5)


def _joint_or_first(joints: dict[str, Point3], names: tuple[str, ...]) -> Point3 | None:
    for name in names:
        point = joints.get(name)
        if point is not None:
            return point
    return None


def _lateral_axis_from_joints(joints: dict[str, Point3], up_axis: Point3) -> Point3:
    for left_name, right_name in (
        ("left_shoulder", "right_shoulder"),
        ("left_collar", "right_collar"),
        ("left_hip", "right_hip"),
    ):
        left = joints.get(left_name)
        right = joints.get(right_name)
        if left is None or right is None:
            continue
        lateral = _subtract_point(right, left)
        lateral = _subtract_point(lateral, _scale_point(up_axis, _dot(lateral, up_axis)))
        normalized = _normalize(lateral)
        if normalized is not None:
            return normalized
    fallback = (1.0, 0.0, 0.0)
    if abs(_dot(fallback, up_axis)) > 0.95:
        fallback = (0.0, 0.0, 1.0)
    lateral = _subtract_point(fallback, _scale_point(up_axis, _dot(fallback, up_axis)))
    normalized = _normalize(lateral)
    if normalized is None:
        return (1.0, 0.0, 0.0)
    return normalized


def _interpolate_profile(profile: list[float], progress: float) -> float:
    if not profile:
        return 0.0
    if len(profile) == 1:
        return profile[0]
    scaled = _clamp(progress, 0.0, 1.0) * (len(profile) - 1)
    lower_index = int(math.floor(scaled))
    upper_index = min(len(profile) - 1, lower_index + 1)
    fraction = scaled - lower_index
    return profile[lower_index] + (profile[upper_index] - profile[lower_index]) * fraction


def _spine_curve_angle(points: list[tuple[float, ...]]) -> float:
    base = points[0]
    mid = points[len(points) // 2]
    top = points[-1]
    lower = _subtract(mid, base)
    upper = _subtract(top, mid)
    horizontal_axis = 2 if len(base) >= 3 and len(mid) >= 3 and len(top) >= 3 else 0
    lower_angle = math.atan2(lower[horizontal_axis], max(abs(lower[1]), 1e-6))
    upper_angle = math.atan2(upper[horizontal_axis], max(abs(upper[1]), 1e-6))
    return upper_angle - lower_angle


def _subtract(a: tuple[float, ...], b: tuple[float, ...]) -> tuple[float, ...]:
    return tuple(float(a[index]) - float(b[index]) for index in range(min(len(a), len(b))))


def _subtract_point(a: Point3, b: Point3) -> Point3:
    return (float(a[0] - b[0]), float(a[1] - b[1]), float(a[2] - b[2]))


def _add_point(a: Point3, b: Point3) -> Point3:
    return (float(a[0] + b[0]), float(a[1] + b[1]), float(a[2] + b[2]))


def _scale_point(point: Point3, scale: float) -> Point3:
    return (float(point[0] * scale), float(point[1] * scale), float(point[2] * scale))


def _dot(a: Point3, b: Point3) -> float:
    return float(a[0] * b[0] + a[1] * b[1] + a[2] * b[2])


def _cross(a: Point3, b: Point3) -> Point3:
    return (
        float(a[1] * b[2] - a[2] * b[1]),
        float(a[2] * b[0] - a[0] * b[2]),
        float(a[0] * b[1] - a[1] * b[0]),
    )


def _length(point: Point3) -> float:
    return math.sqrt(_dot(point, point))


def _normalize(point: Point3) -> Point3 | None:
    length = _length(point)
    if length <= 1e-9:
        return None
    return _scale_point(point, 1.0 / length)


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _median_center(values: list[float]) -> list[float]:
    sorted_values = sorted(values)
    median = sorted_values[len(sorted_values) // 2] if sorted_values else 0.0
    return [value - median for value in values]


def _moving_average(values: list[float], *, window: int) -> list[float]:
    if window <= 1 or len(values) <= 2:
        return values
    radius = max(1, window // 2)
    smoothed: list[float] = []
    for index in range(len(values)):
        start = max(0, index - radius)
        end = min(len(values), index + radius + 1)
        smoothed.append(sum(values[start:end]) / (end - start))
    return smoothed
