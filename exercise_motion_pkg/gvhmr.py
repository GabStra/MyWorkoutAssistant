from __future__ import annotations

from pathlib import Path

from exercise_motion_pkg.gvhmr_convert import convert_gvhmr_results_to_motion_clip
from exercise_motion_pkg.motion_io import save_motion_json


def normalize_gvhmr_output(
    *,
    gvhmr_results_pt: Path,
    body_model_root: Path,
    output_json: Path,
    coordinate_space: str = "incam",
) -> None:
    clip = convert_gvhmr_results_to_motion_clip(
        gvhmr_results_pt=gvhmr_results_pt,
        body_model_root=body_model_root,
        coordinate_space=coordinate_space,
    )
    save_motion_json(output_json, clip)
