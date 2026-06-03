from __future__ import annotations

import json
from pathlib import Path

from exercise_motion_pkg.gvhmr_convert import GVHMR_SMPLX_KEYS


def export_gvhmr_retarget_source(
    *,
    gvhmr_results_pt: Path,
    output_json: Path,
    coordinate_space: str = "incam",
) -> Path:
    payload = build_gvhmr_retarget_source_payload(
        gvhmr_results_pt=gvhmr_results_pt,
        coordinate_space=coordinate_space,
    )
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return output_json


def build_gvhmr_retarget_source_payload(
    *,
    gvhmr_results_pt: Path,
    coordinate_space: str = "incam",
) -> dict[str, object]:
    try:
        import torch  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "GVHMR retarget source export requires torch in the active environment."
        ) from exc

    raw = torch.load(gvhmr_results_pt, map_location="cpu", weights_only=False)
    if not isinstance(raw, dict):
        raise ValueError("GVHMR results must load to a dict.")

    smpl_params_key = _resolve_smpl_params_key(coordinate_space)
    smpl_params = raw.get(smpl_params_key)
    if not isinstance(smpl_params, dict):
        raise ValueError(f"GVHMR results must contain a dict at key '{smpl_params_key}'.")

    serialized_params: dict[str, object] = {}
    frame_count: int | None = None
    for key in GVHMR_SMPLX_KEYS:
        value = smpl_params.get(key)
        if value is None:
            continue
        tensor = torch.as_tensor(value, dtype=torch.float32)
        if tensor.ndim == 1:
            tensor = tensor.unsqueeze(0)
        if key != "betas":
            current_count = int(tensor.shape[0])
            if frame_count is None:
                frame_count = current_count
            elif current_count != frame_count:
                raise ValueError(
                    f"GVHMR parameter '{key}' has frame count {current_count}, expected {frame_count}."
                )
        serialized_params[key] = tensor.cpu().tolist()

    if frame_count is None:
        raise ValueError("GVHMR results did not contain any frame-based SMPL parameters.")

    net_outputs = raw.get("net_outputs")
    has_static_confidence = False
    if isinstance(net_outputs, dict):
        has_static_confidence = (
            net_outputs.get("static_conf_logits") is not None
            or (
                isinstance(net_outputs.get("model_output"), dict)
                and net_outputs["model_output"].get("static_conf_logits") is not None
            )
        )

    return {
        "schemaVersion": 1,
        "source": "GVHMR",
        "resultsPath": str(gvhmr_results_pt),
        "coordinateSpace": coordinate_space,
        "bodyModel": "smplx",
        "fps": 30.0,
        "frameCount": frame_count,
        "smplParamsKey": smpl_params_key,
        "hasStaticJointConfidence": has_static_confidence,
        "smplParams": serialized_params,
    }


def _resolve_smpl_params_key(coordinate_space: str) -> str:
    normalized = coordinate_space.strip().lower()
    if normalized == "global":
        return "smpl_params_global"
    if normalized == "incam":
        return "smpl_params_incam"
    raise ValueError("coordinate_space must be either 'incam' or 'global'.")
