from __future__ import annotations

import joblib
import pytest
import torch
from pathlib import Path

from exercise_motion_pkg.gvhmr_pkl_export import export_gvhmr_results_pkl
from exercise_motion_pkg.gvhmr_runner import build_gvhmr_command

torch = pytest.importorskip("torch")


def test_export_gvhmr_results_pkl_matches_wham_world_schema(tmp_path: Path) -> None:
    frames = 7
    pred = {
        "smpl_params_global": {
            "global_orient": torch.zeros(frames, 3),
            "body_pose": torch.zeros(frames, 63),
            "betas": torch.zeros(frames, 10),
            "transl": torch.ones(frames, 3),
        }
    }
    results_pt = tmp_path / "hmr4d_results.pt"
    torch.save(pred, results_pt)
    output_pkl = tmp_path / "wham_output.pkl"

    export_gvhmr_results_pkl(results_pt, output_pkl)

    raw = joblib.load(output_pkl)
    assert set(raw.keys()) == {0}
    payload = raw[0]
    assert set(["pose_world", "trans_world", "betas", "frame_ids"]) <= set(payload.keys())
    pose = torch.as_tensor(payload["pose_world"])
    trans = torch.as_tensor(payload["trans_world"])
    betas = torch.as_tensor(payload["betas"])
    assert pose.shape == (frames, 72)
    assert trans.shape == (frames, 3)
    assert betas.shape == (10,)
    assert torch.all(betas == 0)  # neutral SMPL betas by default
    assert payload.get("betasSource") == "neutral_smpl"
    assert list(payload["frame_ids"]) == list(range(frames))


def test_export_gvhmr_results_pkl_keep_source_betas(tmp_path: Path) -> None:
    frames = 4
    pred = {
        "smpl_params_global": {
            "global_orient": torch.zeros(frames, 3),
            "body_pose": torch.zeros(frames, 63),
            "betas": torch.ones(frames, 10),
            "transl": torch.zeros(frames, 3),
        }
    }
    results_pt = tmp_path / "hmr4d_results.pt"
    torch.save(pred, results_pt)
    output_pkl = tmp_path / "wham_output.pkl"
    export_gvhmr_results_pkl(results_pt, output_pkl, keep_source_betas=True)
    payload = joblib.load(output_pkl)[0]
    assert torch.all(torch.as_tensor(payload["betas"]) == 1)
    assert payload.get("betasSource") == "gvhmr_smplx_betas"


def test_build_gvhmr_command_static_camera(tmp_path: Path) -> None:
    input_video = tmp_path / "clip.mp4"
    input_video.parent.mkdir(parents=True, exist_ok=True)
    input_video.write_bytes(b"")
    command = build_gvhmr_command(
        input_video=input_video,
        output_root=tmp_path / "out",
        export_script=Path(__file__).parent.parent / "exercise_motion_pkg" / "gvhmr_pkl_export.py",
        docker_image="myworkoutassistant/gvhmr:torch2.3-cu121",
        docker_gpus="all",
        docker_shm_size="8g",
        docker_container_name="mwa-gvhmr-job-test",
        static_camera=True,
    )
    joined = " ".join(command)
    assert "tools/demo/demo.py" in joined
    assert " -s" in joined
    assert "gvhmr_pkl_export.py --results /output/demo/clip/hmr4d_results.pt" in joined
    assert "--output-pkl /output/clip/wham_output.pkl" in joined
    assert "mwa-gvhmr-job-test" in joined
