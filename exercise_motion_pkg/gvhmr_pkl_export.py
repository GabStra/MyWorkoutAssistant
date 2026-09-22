"""Convert GVHMR hmr4d_results.pt into the WHAM output-pkl schema.

Runs inside the GVHMR container so the pipeline's WHAM cache, normalization,
and retarget stages can consume a GVHMR reconstruction unchanged. The global
(gravity-aligned, Y-up, world) SMPL parameters are exposed through the WHAM
"world" coordinate keys.

GVHMR betas are trained for the SMPL-X topology; feeding them into the SMPL
model produces a body ~20% wider at the shoulders than the SMPL-native bodies
the pipeline's fits and gates are tuned for. Neutral SMPL betas are therefore
the default export (poses are unchanged, only the shape basis).
"""
from __future__ import annotations

import argparse
from pathlib import Path

import joblib
import torch


def export_gvhmr_results_pkl(results_pt: Path, output_pkl: Path, *, keep_source_betas: bool = False) -> dict[str, object]:
    pred = torch.load(results_pt, map_location="cpu")
    params = pred["smpl_params_global"]
    global_orient = params["global_orient"].reshape(-1, 3)
    frame_count = global_orient.shape[0]
    body_pose = params["body_pose"].reshape(frame_count, -1)
    if body_pose.shape[1] not in (63, 69):
        raise ValueError(f"GVHMR body_pose must have 63 or 69 columns, got {body_pose.shape}")
    if body_pose.shape[1] == 63:
        # GVHMR poses the SMPL body like SMPL-X (root + 21 joints). SMPL expects
        # root + 23; the two trailing hand-root joints stay at neutral rotation.
        body_pose = torch.cat(
            [body_pose, torch.zeros(frame_count, 6, dtype=body_pose.dtype)],
            dim=-1,
        )
    pose_world = torch.cat([global_orient, body_pose], dim=-1)  # (T, 72) axis-angle
    trans_world = params["transl"].reshape(frame_count, 3)
    if keep_source_betas:
        betas = params["betas"].reshape(params["betas"].shape[0], -1)[0]  # (10,)
        betas_source = "gvhmr_smplx_betas"
    else:
        betas = torch.zeros(10)
        betas_source = "neutral_smpl"
    frame_ids = list(range(int(pose_world.shape[0])))
    payload = {
        "pose_world": pose_world.numpy(),
        "trans_world": trans_world.numpy(),
        "betas": betas.numpy(),
        "frame_ids": frame_ids,
        "betasSource": betas_source,
    }
    output_pkl.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({0: payload}, output_pkl)
    return {"frames": len(frame_ids), "betasSource": betas_source}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, required=True, help="hmr4d_results.pt path")
    parser.add_argument("--output-pkl", type=Path, required=True, help="wham_output.pkl destination")
    parser.add_argument(
        "--keep-source-betas",
        action="store_true",
        help="Export GVHMR's SMPL-X betas instead of neutral SMPL betas.",
    )
    args = parser.parse_args()
    summary = export_gvhmr_results_pkl(args.results, args.output_pkl, keep_source_betas=args.keep_source_betas)
    print(f"GVHMR pkl export complete: {summary}")


if __name__ == "__main__":
    main()
