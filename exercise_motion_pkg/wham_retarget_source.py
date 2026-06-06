from __future__ import annotations

import json
from pathlib import Path

from exercise_motion_pkg.wham_results import load_wham_results, resolve_wham_coordinate_keys, select_wham_subject


def export_wham_retarget_source(
    *,
    wham_results_pkl: Path,
    output_json: Path,
    coordinate_space: str = "world",
    subject_id: int | str | None = None,
) -> Path:
    payload = build_wham_retarget_source_payload(
        wham_results_pkl=wham_results_pkl,
        coordinate_space=coordinate_space,
        subject_id=subject_id,
    )
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return output_json


def build_wham_retarget_source_payload(
    *,
    wham_results_pkl: Path,
    coordinate_space: str = "world",
    subject_id: int | str | None = None,
) -> dict[str, object]:
    raw_results = load_wham_results(wham_results_pkl)
    resolved_subject_id, payload = select_wham_subject(raw_results, subject_id=subject_id)
    pose_key, translation_key = resolve_wham_coordinate_keys(coordinate_space)

    pose = payload.get(pose_key)
    translation = payload.get(translation_key)
    betas = payload.get("betas")
    frame_ids = payload.get("frame_ids")

    if not hasattr(pose, "shape") or len(pose.shape) != 2 or pose.shape[1] != 72:  # type: ignore[attr-defined]
        raise ValueError(f"WHAM '{pose_key}' must be shaped like [frames, 72].")
    if not hasattr(translation, "shape") or len(translation.shape) != 2 or translation.shape[1] != 3:  # type: ignore[attr-defined]
        raise ValueError(f"WHAM '{translation_key}' must be shaped like [frames, 3].")
    frame_count = int(pose.shape[0])  # type: ignore[index]
    if int(translation.shape[0]) != frame_count:  # type: ignore[index]
        raise ValueError(
            f"WHAM '{translation_key}' frame count {translation.shape[0]} does not match pose frame count {frame_count}."  # type: ignore[index]
        )

    normalized_frame_ids = [int(value) for value in frame_ids] if frame_ids is not None else list(range(frame_count))
    if len(normalized_frame_ids) != frame_count:
        raise ValueError(
            f"WHAM frame_ids length {len(normalized_frame_ids)} does not match frame count {frame_count}."
        )

    return {
        "schemaVersion": 1,
        "source": "WHAM",
        "resultsPath": str(wham_results_pkl),
        "coordinateSpace": coordinate_space,
        "bodyModel": "smpl",
        "fps": 30.0,
        "subjectId": str(resolved_subject_id),
        "frameCount": frame_count,
        "poseKey": pose_key,
        "translationKey": translation_key,
        "frameIds": normalized_frame_ids,
        "poseAxisAngle": pose.tolist(),  # type: ignore[union-attr]
        "translations": translation.tolist(),  # type: ignore[union-attr]
        "betas": betas.tolist() if hasattr(betas, "tolist") else betas,
    }
