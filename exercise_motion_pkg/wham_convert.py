from __future__ import annotations

from pathlib import Path

from exercise_motion_pkg.legacy_smpl_compat import ensure_legacy_smpl_runtime_compat
from exercise_motion_pkg.models import MotionClip, MotionFrame
from exercise_motion_pkg.smpl_joint_names import SMPL_JOINT_NAMES
from exercise_motion_pkg.wham_results import load_wham_results, resolve_wham_coordinate_keys, select_wham_subject


def convert_wham_results_to_motion_clip(
    *,
    wham_results_pkl: Path,
    body_model_root: Path,
    coordinate_space: str = "world",
    subject_id: int | str | None = None,
) -> MotionClip:
    ensure_legacy_smpl_runtime_compat()
    try:
        import torch  # type: ignore
        import smplx  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "WHAM conversion requires torch and smplx in the active environment. "
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
    if translation.shape[0] != frame_count:
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

    joints = output.joints[:, : len(SMPL_JOINT_NAMES), :].detach().cpu().tolist()
    normalized_frame_ids = _normalize_frame_ids(frame_ids, frame_count=frame_count)
    fps = 30.0
    frames: list[MotionFrame] = []
    for index, joint_row in enumerate(joints):
        frame_joints = {
            SMPL_JOINT_NAMES[joint_index]: (
                float(coords[0]),
                float(coords[1]),
                float(coords[2]),
            )
            for joint_index, coords in enumerate(joint_row)
        }
        frames.append(
            MotionFrame(
                time_sec=float(normalized_frame_ids[index]) / fps,
                joints=frame_joints,
            )
        )

    return MotionClip(
        fps=fps,
        joint_names=list(SMPL_JOINT_NAMES),
        frames=frames,
        source={
            "extractor": "WHAM",
            "whamResultsPkl": str(wham_results_pkl),
            "coordinateSpace": coordinate_space,
            "subjectId": str(resolved_subject_id),
        },
        metadata={
            "upstream": "wham",
            "wham": {
                "coordinateSpace": coordinate_space,
                "subjectId": str(resolved_subject_id),
                "frameIds": normalized_frame_ids,
            },
        },
    )


def normalize_wham_output(
    *,
    wham_results_pkl: Path,
    body_model_root: Path,
    output_json: Path,
    coordinate_space: str = "world",
    subject_id: int | str | None = None,
) -> Path:
    from exercise_motion_pkg.motion_io import save_motion_json

    clip = convert_wham_results_to_motion_clip(
        wham_results_pkl=wham_results_pkl,
        body_model_root=body_model_root,
        coordinate_space=coordinate_space,
        subject_id=subject_id,
    )
    save_motion_json(output_json, clip)
    return output_json


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
    if not hasattr(frame_ids, "__len__"):
        raise ValueError("WHAM frame_ids must be a sequence when provided.")
    normalized = [int(value) for value in frame_ids]  # type: ignore[arg-type]
    if len(normalized) != frame_count:
        raise ValueError(
            f"WHAM frame_ids length {len(normalized)} does not match frame count {frame_count}."
        )
    return normalized
