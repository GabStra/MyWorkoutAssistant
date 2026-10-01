from __future__ import annotations

import joblib
import pytest
import torch
from pathlib import Path

from exercise_motion_pkg.gvhmr_pkl_export import export_gvhmr_results_pkl
from exercise_motion_pkg.gvhmr_inference import _time_method
from exercise_motion_pkg.gvhmr_runner import (
    _read_phase_timing_markers,
    build_gvhmr_command,
    resolve_gvhmr_warm_worker_session_dir,
    resolve_gvhmr_warm_worker_timeout_seconds,
)

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
    assert "/mwa/gvhmr_inference.py" in joined
    assert "tools/demo/demo.py" not in joined
    assert " -s" in joined
    assert "gvhmr_pkl_export.py --results /output/demo/clip/hmr4d_results.pt" in joined
    assert "--output-pkl /output/clip/wham_output.pkl" in joined
    assert "mwa-gvhmr-job-test" in joined


def test_read_gvhmr_phase_timing_markers(tmp_path: Path) -> None:
    log = tmp_path / "gvhmr.stdout.log"
    log.write_text(
        "noise\n"
        'GVHMR_PHASE_TIMINGS_JSON:{"preprocessSeconds":47.2,"scriptTotalSeconds":51.0}\n'
        'GVHMR_EXPORT_TIMINGS_JSON:{"moduleImportSeconds":2.0,"processTotalSeconds":3.0}\n',
        encoding="utf-8",
    )

    assert _read_phase_timing_markers(log) == {
        "inference": {"preprocessSeconds": 47.2, "scriptTotalSeconds": 51.0},
        "export": {"moduleImportSeconds": 2.0, "processTotalSeconds": 3.0},
    }


def test_time_method_preserves_return_value_and_records_elapsed_time() -> None:
    class Example:
        def calculate(self, value: int) -> int:
            return value * 2

    timings: dict[str, float] = {}
    _time_method(Example, "calculate", "calculateSeconds", timings)

    assert Example().calculate(4) == 8
    assert timings["calculateSeconds"] >= 0.0


def test_resolve_gvhmr_warm_worker_session_dir_prefers_configured(monkeypatch, tmp_path: Path) -> None:
    configured = tmp_path / "configured-session"
    assert resolve_gvhmr_warm_worker_session_dir(configured) == configured.resolve()

    env_dir = tmp_path / "env-session"
    monkeypatch.setenv("EXERCISE_MOTION_GVHMR_WARM_WORKER_SESSION_DIR", str(env_dir))
    assert resolve_gvhmr_warm_worker_session_dir(None) == env_dir.resolve()

    monkeypatch.delenv("EXERCISE_MOTION_GVHMR_WARM_WORKER_SESSION_DIR")
    with pytest.raises(ValueError, match="session directory"):
        resolve_gvhmr_warm_worker_session_dir(None)


def test_resolve_gvhmr_warm_worker_timeout_seconds_defaults_to_run_timeout(monkeypatch) -> None:
    monkeypatch.delenv("EXERCISE_MOTION_GVHMR_WARM_WORKER_TIMEOUT_SECONDS", raising=False)
    assert resolve_gvhmr_warm_worker_timeout_seconds(None) == 20 * 60.0
    assert resolve_gvhmr_warm_worker_timeout_seconds(0.0) is None
    assert resolve_gvhmr_warm_worker_timeout_seconds(90.0) == 90.0
    monkeypatch.setenv("EXERCISE_MOTION_GVHMR_WARM_WORKER_TIMEOUT_SECONDS", "45")
    assert resolve_gvhmr_warm_worker_timeout_seconds(None) == 45.0


def test_run_gvhmr_locally_dispatches_to_warm_worker(monkeypatch, tmp_path: Path) -> None:
    from exercise_motion_pkg import gvhmr_runner

    captured: dict[str, object] = {}

    def fake_warm_run(**kwargs):
        captured.update(kwargs)
        return gvhmr_runner.GvhmrRunResult(
            output_dir=kwargs["output_root"] / "clip",
            results_pkl=kwargs["output_root"] / "clip" / "wham_output.pkl",
            demo_output_dir=kwargs["output_root"] / "demo" / "clip",
            stdout_log=kwargs["stdout_log"],
            stderr_log=kwargs["stderr_log"],
            command=["gvhmr-warm-worker", "job"],
            elapsed_seconds=1.0,
            returncode=0,
            docker_image="myworkoutassistant/gvhmr:torch2.3-cu121",
            gpu_lock_wait_seconds=0.0,
            docker_lock_wait_seconds=0.0,
            phase_timings={},
            unattributed_runner_seconds=0.0,
            timeout_seconds=1200.0,
            warm_worker=True,
        )

    monkeypatch.setattr(gvhmr_runner, "run_gvhmr_with_warm_worker", fake_warm_run)

    result = gvhmr_runner.run_gvhmr_locally(
        input_video=tmp_path / "clip.mp4",
        output_root=tmp_path / "out",
        logs_dir=tmp_path / "logs",
        static_camera=True,
        timeout_seconds=600.0,
        use_warm_worker=True,
        warm_worker_session_dir=tmp_path / "session",
        warm_worker_mount_root=tmp_path / "mount",
        warm_worker_timeout_seconds=1200.0,
    )

    assert result.warm_worker is True
    assert captured["static_camera"] is True
    assert captured["warm_worker_timeout_seconds"] == 1200.0
    assert captured["docker_image"] == "myworkoutassistant/gvhmr:torch2.3-cu121"
