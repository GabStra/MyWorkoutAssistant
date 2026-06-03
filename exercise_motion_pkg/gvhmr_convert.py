from __future__ import annotations

from pathlib import Path

from exercise_motion_pkg.models import MotionClip, MotionFrame
from exercise_motion_pkg.smpl_joint_names import SMPL_JOINT_NAMES


GVHMR_SMPLX_KEYS = (
    "global_orient",
    "body_pose",
    "betas",
    "transl",
    "left_hand_pose",
    "right_hand_pose",
    "jaw_pose",
    "leye_pose",
    "reye_pose",
    "expression",
)


def convert_gvhmr_results_to_motion_clip(
    *,
    gvhmr_results_pt: Path,
    body_model_root: Path,
    coordinate_space: str = "incam",
) -> MotionClip:
    try:
        import torch  # type: ignore
        import smplx  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "GVHMR conversion requires torch and smplx in the active environment. "
            "Run this stage with the GVHMR Python environment or install those packages there."
        ) from exc

    raw = torch.load(gvhmr_results_pt, map_location="cpu", weights_only=False)
    if not isinstance(raw, dict):
        raise ValueError("GVHMR results must be a dict loaded from hmr4d_results.pt.")
    smpl_params_key = _resolve_smpl_params_key(coordinate_space)
    smpl_params = raw.get(smpl_params_key)
    if not isinstance(smpl_params, dict):
        raise ValueError(f"GVHMR results must contain a dict at key '{smpl_params_key}'.")

    normalized_params = {
        key: _as_tensor(torch, value)
        for key, value in smpl_params.items()
        if key in GVHMR_SMPLX_KEYS
    }
    if "global_orient" not in normalized_params or "body_pose" not in normalized_params:
        raise ValueError(
            "GVHMR smpl_params_global must contain at least 'global_orient' and 'body_pose'."
        )

    frame_count = int(normalized_params["global_orient"].shape[0])
    if frame_count <= 0:
        raise ValueError("GVHMR global_orient must contain at least one frame.")
    if "betas" in normalized_params:
        normalized_params["betas"] = _prepare_betas(
            torch,
            normalized_params["betas"],
            frame_count=frame_count,
        )

    model = smplx.create(
        model_path=str(body_model_root),
        model_type="smplx",
        gender="neutral",
        batch_size=frame_count,
        use_pca=False,
    )
    with torch.no_grad():
        output = model(**normalized_params)

    joints = output.joints[:, : len(SMPL_JOINT_NAMES), :].detach().cpu().tolist()
    static_joint_confidence = _extract_static_joint_confidence(torch, raw, frame_count=frame_count)
    frames = []
    fps = 30.0
    for index, joint_row in enumerate(joints):
        frame_joints = {
            SMPL_JOINT_NAMES[joint_index]: (
                float(coords[0]),
                float(coords[1]),
                float(coords[2]),
            )
            for joint_index, coords in enumerate(joint_row)
        }
        frames.append(MotionFrame(time_sec=index / fps, joints=frame_joints))

    return MotionClip(
        fps=fps,
        joint_names=list(SMPL_JOINT_NAMES),
        frames=frames,
        source={
            "extractor": "GVHMR",
            "gvhmrResultsPt": str(gvhmr_results_pt),
            "coordinateSpace": coordinate_space,
        },
        metadata={
            "upstream": "gvhmr",
            "gvhmr": {
                "coordinateSpace": coordinate_space,
                "staticJointConfidence": static_joint_confidence,
            },
        },
    )


def _as_tensor(torch_module: object, value: object):
    tensor = torch_module.as_tensor(value, dtype=torch_module.float32)
    if tensor.ndim == 1:
        return tensor.unsqueeze(0)
    return tensor


def _prepare_betas(torch_module: object, betas, *, frame_count: int):
    if betas.ndim == 1:
        return betas.unsqueeze(0).repeat(frame_count, 1)
    if betas.ndim != 2:
        raise ValueError("GVHMR betas must be shaped like [10] or [frames, 10].")
    if betas.shape[0] == frame_count:
        return betas
    if betas.shape[0] == 1:
        return betas.repeat(frame_count, 1)
    raise ValueError(
        f"GVHMR betas shape {tuple(betas.shape)} is incompatible with frame count {frame_count}."
    )


def _resolve_smpl_params_key(coordinate_space: str) -> str:
    normalized = coordinate_space.strip().lower()
    if normalized == "global":
        return "smpl_params_global"
    if normalized == "incam":
        return "smpl_params_incam"
    raise ValueError("coordinate_space must be either 'incam' or 'global'.")


def _extract_static_joint_confidence(torch_module: object, raw: dict[str, object], *, frame_count: int) -> list[dict[str, float]]:
    net_outputs = raw.get("net_outputs")
    if not isinstance(net_outputs, dict):
        return []
    logits = net_outputs.get("static_conf_logits")
    if logits is None:
        model_output = net_outputs.get("model_output")
        if isinstance(model_output, dict):
            logits = model_output.get("static_conf_logits")
    if logits is None:
        return []

    tensor = torch_module.as_tensor(logits, dtype=torch_module.float32)
    if tensor.ndim == 3 and tensor.shape[0] == 1:
        tensor = tensor.squeeze(0)
    if tensor.ndim != 2 or tensor.shape[1] < 6:
        return []

    confidence = torch_module.sigmoid(tensor[:, :6]).cpu().tolist()
    joint_names = (
        "left_ankle",
        "left_foot",
        "right_ankle",
        "right_foot",
        "left_wrist",
        "right_wrist",
    )
    return [
        {joint_name: float(row[joint_index]) for joint_index, joint_name in enumerate(joint_names)}
        for row in confidence[:frame_count]
    ]
