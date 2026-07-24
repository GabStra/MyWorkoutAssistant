from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

from exercise_motion_pkg.legacy_smpl_compat import ensure_legacy_smpl_runtime_compat
from exercise_motion_pkg.models import MotionClip, Point3
from exercise_motion_pkg.preview import (
    _apply_rotations_to_point,
    _center_preview_clip_for_render,
    _clip_requests_raw_motion_render,
    _compute_preview_auto_alignment,
    _compute_root_anchor,
    _detect_preview_loops,
    _find_root_joint,
    _fixed_root_translation,
    _prepare_preview_clip,
    _serialize_bounds,
)
from exercise_motion_pkg.wham_results import load_wham_results, resolve_wham_coordinate_keys, select_wham_subject


SPINE_MESH_WARP_CHAIN = ("pelvis", "spine1", "spine2", "spine3", "neck")


@dataclass(frozen=True)
class WhamSmplMeshSequence:
    fps: float
    subject_id: str
    coordinate_space: str
    frame_ids: list[int]
    faces: list[list[int]]
    vertices: list[list[Point3]]

    @property
    def frame_count(self) -> int:
        return len(self.vertices)


def load_wham_smpl_mesh_sequence(
    *,
    wham_results_pkl: Path,
    body_model_root: Path,
    coordinate_space: str = "world",
    subject_id: int | str | None = None,
) -> WhamSmplMeshSequence:
    ensure_legacy_smpl_runtime_compat()
    try:
        import torch  # type: ignore
        import smplx  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "WHAM SMPL mesh preview requires torch and smplx in the active environment. "
            "Run this stage with the WHAM Python environment or install those packages there."
        ) from exc

    raw_results = load_wham_results(wham_results_pkl)
    resolved_subject_id, payload = select_wham_subject(raw_results, subject_id=subject_id)
    pose_key, translation_key = resolve_wham_coordinate_keys(coordinate_space)

    pose = torch.as_tensor(payload.get(pose_key), dtype=torch.float32)
    translation = torch.as_tensor(payload.get(translation_key), dtype=torch.float32)
    betas = torch.as_tensor(payload.get("betas"), dtype=torch.float32)
    frame_ids = payload.get("frame_ids")
    if pose.ndim != 2 or pose.shape[1] != 72:
        raise ValueError(f"WHAM '{pose_key}' must be shaped like [frames, 72].")
    if translation.ndim != 2 or translation.shape[1] != 3:
        raise ValueError(f"WHAM '{translation_key}' must be shaped like [frames, 3].")
    frame_count = int(pose.shape[0])
    if frame_count <= 0:
        raise ValueError(f"WHAM '{pose_key}' must contain at least one frame.")
    if int(translation.shape[0]) != frame_count:
        raise ValueError(
            f"WHAM '{translation_key}' frame count {translation.shape[0]} does not match pose frame count {frame_count}."
        )
    betas = _prepare_betas(torch, betas, frame_count=frame_count)

    model = smplx.create(
        model_path=str(body_model_root),
        model_type="smpl",
        gender="neutral",
        batch_size=frame_count,
    )
    with torch.no_grad():
        output = model(
            global_orient=pose[:, :3],
            body_pose=pose[:, 3:],
            betas=betas,
            transl=translation,
        )

    return WhamSmplMeshSequence(
        fps=30.0,
        subject_id=str(resolved_subject_id),
        coordinate_space=coordinate_space,
        frame_ids=_normalize_frame_ids(frame_ids, frame_count=frame_count),
        faces=[[int(index) for index in face] for face in model.faces.tolist()],
        vertices=[
            [
                (float(vertex[0]), float(vertex[1]), float(vertex[2]))
                for vertex in frame_vertices
            ]
            for frame_vertices in output.vertices.detach().cpu().tolist()
        ],
    )


def write_baked_wham_smpl_preview_json(
    path: Path,
    *,
    sequence: WhamSmplMeshSequence,
    raw_clip: MotionClip,
    cleaned_clip: MotionClip,
    mesh_reference_clip: MotionClip | None = None,
    title: str,
    selected_loop_index: int | None = None,
    lock_y_drift: bool = False,
) -> dict[str, object]:
    payload = build_baked_wham_smpl_preview_payload(
        sequence=sequence,
        raw_clip=raw_clip,
        cleaned_clip=cleaned_clip,
        mesh_reference_clip=mesh_reference_clip,
        title=title,
        selected_loop_index=selected_loop_index,
        lock_y_drift=lock_y_drift,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def build_baked_wham_smpl_preview_payload(
    *,
    sequence: WhamSmplMeshSequence,
    raw_clip: MotionClip,
    cleaned_clip: MotionClip,
    mesh_reference_clip: MotionClip | None = None,
    title: str,
    selected_loop_index: int | None = None,
    lock_y_drift: bool = False,
) -> dict[str, object]:
    raw_motion_review = _clip_requests_raw_motion_render(cleaned_clip)
    preview_clip = _center_preview_clip_for_render(_prepare_preview_clip(cleaned_clip))
    detected_loops = _detect_preview_loops(preview_clip)
    resolved_loop_index = _resolve_loop_index(selected_loop_index, detected_loops)
    selected_loop = detected_loops[resolved_loop_index] if resolved_loop_index >= 0 else None
    active_start_frame = int(selected_loop["startFrame"]) if selected_loop is not None else 0
    active_end_frame = int(selected_loop["endFrame"]) if selected_loop is not None else max(0, preview_clip.frame_count - 1)
    active_frames = preview_clip.frames[active_start_frame:active_end_frame + 1]
    auto_alignment = _compute_preview_auto_alignment(active_frames)
    root_joint = _find_root_joint(preview_clip)
    active_root_anchor = None if raw_motion_review else _compute_root_anchor(active_frames, root_joint)
    trim_start = _cleanup_trim_start(cleaned_clip)
    raw_root_joint = _find_root_joint(raw_clip)
    mesh_reference = mesh_reference_clip or raw_clip
    mesh_warp_stats: list[dict[str, object]] = []

    transformed_frames: list[dict[str, object]] = []
    for local_frame_index, preview_frame in enumerate(active_frames, start=active_start_frame):
        raw_frame_index = trim_start + local_frame_index
        if (
            raw_frame_index < 0
            or raw_frame_index >= sequence.frame_count
            or raw_frame_index >= raw_clip.frame_count
            or raw_frame_index >= mesh_reference.frame_count
        ):
            continue
        frame_translation = (
            _fixed_root_translation(
                preview_frame,
                root_joint,
                active_root_anchor,
                lock_y_drift=lock_y_drift,
            )
            if not raw_motion_review
            else (0.0, 0.0, 0.0)
        )
        cleanup_delta = _root_delta_for_frame(
            raw_clip=raw_clip,
            target_clip=cleaned_clip,
            raw_frame_index=raw_frame_index,
            target_frame_index=local_frame_index,
            raw_root_joint=raw_root_joint,
            target_root_joint=root_joint,
        )
        motion_delta = _root_delta_for_frame(
            raw_clip=raw_clip,
            target_clip=preview_clip,
            raw_frame_index=raw_frame_index,
            target_frame_index=local_frame_index,
            raw_root_joint=raw_root_joint,
            target_root_joint=root_joint,
        )
        vertices, spine_warp = _transform_mesh_vertices_for_preview_frame(
            sequence.vertices[raw_frame_index],
            reference_frame=mesh_reference.frames[raw_frame_index],
            preview_frame=preview_frame,
            motion_delta=motion_delta,
            frame_translation=frame_translation,
            auto_alignment=auto_alignment,
        )
        mesh_warp_stats.append(spine_warp)
        transformed_frames.append(
            {
                "frameIndex": len(transformed_frames),
                "sourceFrameIndex": local_frame_index,
                "rawFrameIndex": raw_frame_index,
                "timeSec": preview_frame.time_sec - active_frames[0].time_sec if active_frames else 0.0,
                "sourceTimeSec": preview_frame.time_sec,
                "rootTranslationApplied": _point_to_list(frame_translation),
                "cleanupDeltaApplied": _point_to_list(cleanup_delta),
                "motionDeltaApplied": _point_to_list(motion_delta),
                "spineMeshWarpApplied": bool(spine_warp["applied"]),
                "spineMeshWarpMaxDelta": spine_warp["maxDelta"],
                "spineMeshWarpVertexCount": spine_warp["vertexCount"],
                "vertices": vertices,
            }
        )

    bounds = _compute_vertex_bounds(transformed_frames)
    scene_origin = _bounds_center(bounds)
    centered_frames = _subtract_scene_origin_from_mesh_frames(transformed_frames, scene_origin)
    centered_bounds = _compute_vertex_bounds(centered_frames)
    active_duration = (
        float(centered_frames[-1]["timeSec"]) - float(centered_frames[0]["timeSec"])
        if len(centered_frames) >= 2
        else 0.0
    )
    spine_warp_applied = any(bool(stats["applied"]) for stats in mesh_warp_stats)
    post_processing = (
        ["preview_scene_centering"]
        if raw_motion_review
        else [
            "cleanup_trim",
            "cleanup_global_translation_delta",
            "preview_refinement_alignment",
            "preview_root_lock",
            "preview_loop_selection",
            "preview_scene_centering",
        ]
    )
    if spine_warp_applied:
        post_processing.insert(-1, "spine_mesh_warp_from_fused_motion")
    return {
        "schemaVersion": 1,
        "kind": "whamBakedSmplMeshPreview",
        "title": title,
        "source": {
            "fps": sequence.fps,
            "frameCount": sequence.frame_count,
            "activeStartFrame": active_start_frame,
            "activeEndFrame": active_end_frame,
            "subjectId": sequence.subject_id,
            "coordinateSpace": sequence.coordinate_space,
            "postProcessedFromCleanedMotion": not raw_motion_review,
            "meshReference": "pre_fusion_wham_motion" if mesh_reference_clip is not None else "raw_motion",
        },
        "fps": sequence.fps,
        "frameCount": len(centered_frames),
        "durationSec": active_duration,
        "bodyModel": "smpl",
        "faces": sequence.faces,
        "bakedPreviewConfiguration": {
            "autoWorldAlignment": True,
            "lockGlobalRootDrift": not raw_motion_review,
            "lockYDrift": lock_y_drift,
            "selectedLoopIndex": resolved_loop_index,
            "postProcessingApplied": post_processing,
            "spineMeshWarp": {
                "applied": spine_warp_applied,
                "reference": "pre_fusion_wham_motion" if mesh_reference_clip is not None else "raw_motion",
                "chain": list(SPINE_MESH_WARP_CHAIN),
                "maxDelta": max((float(stats["maxDelta"]) for stats in mesh_warp_stats), default=0.0),
                "warpedFrameCount": sum(1 for stats in mesh_warp_stats if bool(stats["applied"])),
            },
        },
        "loop": {
            "enabled": selected_loop is not None,
            "startFrame": 0,
            "endFrame": max(0, len(centered_frames) - 1),
            "sourceStartFrame": active_start_frame,
            "sourceEndFrame": active_end_frame,
            "durationSec": active_duration,
            "label": selected_loop.get("label") if selected_loop is not None else "Full clip",
        },
        "transforms": {
            "autoAlignment": _serialize_preview_rotations(auto_alignment),
            "rootAnchor": _point_to_list(active_root_anchor) if active_root_anchor is not None else None,
            "sceneOriginOffset": _point_to_list(scene_origin),
        },
        "bounds": _serialize_bounds(centered_bounds),
        "frames": centered_frames,
    }


def _transform_mesh_vertices_for_preview_frame(
    vertices: list[Point3],
    *,
    reference_frame,
    preview_frame,
    motion_delta: Point3,
    frame_translation: Point3,
    auto_alignment: list[tuple[tuple[float, float, float], float]],
) -> tuple[list[list[float]], dict[str, object]]:
    source_chain = _transformed_spine_chain(
        reference_frame.joints,
        motion_delta=motion_delta,
        frame_translation=frame_translation,
        auto_alignment=auto_alignment,
    )
    target_chain = _transformed_spine_chain(
        preview_frame.joints,
        motion_delta=(0.0, 0.0, 0.0),
        frame_translation=frame_translation,
        auto_alignment=auto_alignment,
    )
    segments = _spine_warp_segments(source_chain, target_chain)
    transformed_vertices: list[list[float]] = []
    warped_vertex_count = 0
    max_delta = 0.0
    for vertex in vertices:
        transformed = _apply_rotations_to_point(
            (
                vertex[0] + motion_delta[0] - frame_translation[0],
                vertex[1] + motion_delta[1] - frame_translation[1],
                vertex[2] + motion_delta[2] - frame_translation[2],
            ),
            auto_alignment,
        )
        warped, delta_length = _apply_spine_mesh_warp(transformed, segments)
        if delta_length > 1e-6:
            warped_vertex_count += 1
            max_delta = max(max_delta, delta_length)
        transformed_vertices.append(_point_to_list(warped))
    return transformed_vertices, {
        "applied": warped_vertex_count > 0,
        "vertexCount": warped_vertex_count,
        "maxDelta": max_delta,
    }


def _transformed_spine_chain(
    joints: dict[str, Point3],
    *,
    motion_delta: Point3,
    frame_translation: Point3,
    auto_alignment: list[tuple[tuple[float, float, float], float]],
) -> dict[str, Point3]:
    transformed: dict[str, Point3] = {}
    for joint_name in SPINE_MESH_WARP_CHAIN:
        point = joints.get(joint_name)
        if point is None:
            continue
        transformed[joint_name] = _apply_rotations_to_point(
            (
                point[0] + motion_delta[0] - frame_translation[0],
                point[1] + motion_delta[1] - frame_translation[1],
                point[2] + motion_delta[2] - frame_translation[2],
            ),
            auto_alignment,
        )
    return transformed


def _spine_warp_segments(
    source_chain: dict[str, Point3],
    target_chain: dict[str, Point3],
) -> list[tuple[Point3, Point3, Point3, Point3]]:
    segments: list[tuple[Point3, Point3, Point3, Point3]] = []
    for start_name, end_name in zip(SPINE_MESH_WARP_CHAIN, SPINE_MESH_WARP_CHAIN[1:], strict=False):
        source_start = source_chain.get(start_name)
        source_end = source_chain.get(end_name)
        target_start = target_chain.get(start_name)
        target_end = target_chain.get(end_name)
        if source_start is None or source_end is None or target_start is None or target_end is None:
            continue
        if _distance(source_start, source_end) <= 1e-6:
            continue
        segments.append((source_start, source_end, target_start, target_end))
    return segments


def _apply_spine_mesh_warp(
    vertex: Point3,
    segments: list[tuple[Point3, Point3, Point3, Point3]],
) -> tuple[Point3, float]:
    if not segments:
        return vertex, 0.0
    weighted_delta = (0.0, 0.0, 0.0)
    total_weight = 0.0
    for source_start, source_end, target_start, target_end in segments:
        closest, progress = _closest_point_on_segment(vertex, source_start, source_end)
        distance = _distance(vertex, closest)
        segment_length = _distance(source_start, source_end)
        radius = max(0.16, min(0.34, segment_length * 0.9))
        normalized = min(1.0, max(0.0, distance / radius))
        smooth = 1.0 - normalized * normalized * (3.0 - 2.0 * normalized)
        weight = smooth * smooth
        if weight <= 1e-6:
            continue
        source_delta = _lerp_point(
            _subtract_point(target_start, source_start),
            _subtract_point(target_end, source_end),
            progress,
        )
        weighted_delta = _add_point(weighted_delta, _scale_point(source_delta, weight))
        total_weight += weight
    if total_weight <= 1e-6:
        return vertex, 0.0
    delta = _scale_point(weighted_delta, 1.0 / total_weight)
    warped = _add_point(vertex, delta)
    return warped, _distance(delta, (0.0, 0.0, 0.0))


def _closest_point_on_segment(point: Point3, start: Point3, end: Point3) -> tuple[Point3, float]:
    segment = _subtract_point(end, start)
    length_sq = _dot(segment, segment)
    if length_sq <= 1e-12:
        return start, 0.0
    progress = max(0.0, min(1.0, _dot(_subtract_point(point, start), segment) / length_sq))
    return _add_point(start, _scale_point(segment, progress)), progress


def _prepare_betas(torch_module: object, betas, *, frame_count: int):
    if betas.ndim == 1:
        return betas.unsqueeze(0).repeat(frame_count, 1)
    if betas.ndim != 2:
        raise ValueError("WHAM betas must be shaped like [10] or [frames, 10].")
    if betas.shape[0] == frame_count:
        return betas
    if betas.shape[0] == 1:
        return betas.repeat(frame_count, 1)
    raise ValueError(
        f"WHAM betas shape {tuple(betas.shape)} is incompatible with frame count {frame_count}."
    )


def _normalize_frame_ids(frame_ids: object, *, frame_count: int) -> list[int]:
    if frame_ids is None:
        return list(range(frame_count))
    normalized = [int(value) for value in frame_ids]  # type: ignore[arg-type]
    if len(normalized) != frame_count:
        raise ValueError(
            f"WHAM frame_ids length {len(normalized)} does not match frame count {frame_count}."
        )
    return normalized


def _resolve_loop_index(selected_loop_index: int | None, detected_loops: list[dict[str, object]]) -> int:
    resolved_loop_index = (
        0
        if selected_loop_index is None and detected_loops
        else -1
        if selected_loop_index is None
        else selected_loop_index
    )
    if resolved_loop_index < -1 or resolved_loop_index >= len(detected_loops):
        raise ValueError(
            f"selected_loop_index must be -1 or between 0 and {len(detected_loops) - 1}; got {resolved_loop_index}"
        )
    return resolved_loop_index


def _cleanup_trim_start(cleaned_clip: MotionClip) -> int:
    cleanup_metadata = cleaned_clip.metadata.get("cleanup") if isinstance(cleaned_clip.metadata, dict) else None
    if not isinstance(cleanup_metadata, dict):
        return 0
    value = cleanup_metadata.get("trimmedStartFrames", 0)
    return int(value) if isinstance(value, (int, float)) else 0


def _root_delta_for_frame(
    *,
    raw_clip: MotionClip,
    target_clip: MotionClip,
    raw_frame_index: int,
    target_frame_index: int,
    raw_root_joint: str | None,
    target_root_joint: str | None,
) -> Point3:
    if raw_root_joint is None or target_root_joint is None:
        return (0.0, 0.0, 0.0)
    if target_frame_index < 0 or target_frame_index >= target_clip.frame_count:
        return (0.0, 0.0, 0.0)
    raw_root = raw_clip.frames[raw_frame_index].joints.get(raw_root_joint)
    target_root = target_clip.frames[target_frame_index].joints.get(target_root_joint)
    if raw_root is None or target_root is None:
        return (0.0, 0.0, 0.0)
    return (
        target_root[0] - raw_root[0],
        target_root[1] - raw_root[1],
        target_root[2] - raw_root[2],
    )


def _compute_vertex_bounds(frames: list[dict[str, object]]) -> dict[str, float]:
    min_x = math.inf
    min_y = math.inf
    min_z = math.inf
    max_x = -math.inf
    max_y = -math.inf
    max_z = -math.inf
    for frame in frames:
        vertices = frame.get("vertices")
        if not isinstance(vertices, list):
            continue
        for vertex in vertices:
            if not _is_point_list(vertex):
                continue
            x, y, z = float(vertex[0]), float(vertex[1]), float(vertex[2])
            min_x = min(min_x, x)
            min_y = min(min_y, y)
            min_z = min(min_z, z)
            max_x = max(max_x, x)
            max_y = max(max_y, y)
            max_z = max(max_z, z)
    if not all(math.isfinite(value) for value in (min_x, min_y, min_z, max_x, max_y, max_z)):
        return {
            "minX": -0.5,
            "maxX": 0.5,
            "minY": -0.5,
            "maxY": 0.5,
            "minZ": -0.5,
            "maxZ": 0.5,
        }
    return {
        "minX": min_x,
        "maxX": max_x,
        "minY": min_y,
        "maxY": max_y,
        "minZ": min_z,
        "maxZ": max_z,
    }


def _bounds_center(bounds: dict[str, float]) -> Point3:
    return (
        (bounds["minX"] + bounds["maxX"]) * 0.5,
        (bounds["minY"] + bounds["maxY"]) * 0.5,
        (bounds["minZ"] + bounds["maxZ"]) * 0.5,
    )


def _subtract_scene_origin_from_mesh_frames(
    frames: list[dict[str, object]],
    scene_origin: Point3,
) -> list[dict[str, object]]:
    centered_frames: list[dict[str, object]] = []
    for frame in frames:
        centered_frame = dict(frame)
        vertices = frame.get("vertices")
        centered_frame["vertices"] = [
            [
                float(vertex[0]) - scene_origin[0],
                float(vertex[1]) - scene_origin[1],
                float(vertex[2]) - scene_origin[2],
            ]
            for vertex in vertices
            if _is_point_list(vertex)
        ] if isinstance(vertices, list) else []
        centered_frames.append(centered_frame)
    return centered_frames


def _serialize_preview_rotations(
    rotations: list[tuple[tuple[float, float, float], float]],
) -> list[dict[str, object]]:
    return [
        {
            "axis": [float(axis[0]), float(axis[1]), float(axis[2])],
            "angle": float(angle),
        }
        for axis, angle in rotations
    ]


def _add_point(a: Point3, b: Point3) -> Point3:
    return (float(a[0] + b[0]), float(a[1] + b[1]), float(a[2] + b[2]))


def _subtract_point(a: Point3, b: Point3) -> Point3:
    return (float(a[0] - b[0]), float(a[1] - b[1]), float(a[2] - b[2]))


def _scale_point(point: Point3, scale: float) -> Point3:
    return (float(point[0] * scale), float(point[1] * scale), float(point[2] * scale))


def _lerp_point(a: Point3, b: Point3, progress: float) -> Point3:
    return (
        float(a[0] + (b[0] - a[0]) * progress),
        float(a[1] + (b[1] - a[1]) * progress),
        float(a[2] + (b[2] - a[2]) * progress),
    )


def _dot(a: Point3, b: Point3) -> float:
    return float(a[0] * b[0] + a[1] * b[1] + a[2] * b[2])


def _distance(a: Point3, b: Point3) -> float:
    return math.sqrt(
        (a[0] - b[0]) * (a[0] - b[0])
        + (a[1] - b[1]) * (a[1] - b[1])
        + (a[2] - b[2]) * (a[2] - b[2])
    )


def _point_to_list(point: Point3) -> list[float]:
    return [float(point[0]), float(point[1]), float(point[2])]


def _is_point_list(value: object) -> bool:
    return isinstance(value, (list, tuple)) and len(value) >= 3
