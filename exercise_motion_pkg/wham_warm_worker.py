from __future__ import annotations

import argparse
import contextlib
import importlib.util
import json
import os
import sys
import time
import traceback
from pathlib import Path
from types import SimpleNamespace
from typing import Any


RESULT_PREFIX = "__WHAM_WARM_WORKER__"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Warm WHAM worker for repeated motion extraction jobs.")
    parser.add_argument("--state-dir", required=True, help="Mounted worker state directory.")
    parser.add_argument("--poll-seconds", type=float, default=0.5)
    return parser.parse_args()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp_path.replace(path)


def load_wham_once() -> dict[str, Any]:
    started = time.perf_counter()
    import torch

    if torch.cuda.is_available():
        torch.set_float32_matmul_precision("high")
        torch.backends.cuda.matmul.allow_tf32 = True
        torch.backends.cudnn.allow_tf32 = True
        torch.backends.cudnn.benchmark = True

    wham_repo_path = Path.cwd()
    if str(wham_repo_path) not in sys.path:
        sys.path.insert(0, str(wham_repo_path))
    demo_path = wham_repo_path / "demo.py"
    spec = importlib.util.spec_from_file_location("wham_demo", demo_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Failed to load WHAM demo module from {demo_path}")
    demo = importlib.util.module_from_spec(spec)
    sys.modules["wham_demo"] = demo
    spec.loader.exec_module(demo)
    from configs.config import get_cfg_defaults
    from lib.models import build_body_model, build_network

    cfg = get_cfg_defaults()
    cfg.merge_from_file("configs/yamls/demo.yaml")
    smpl_batch_size = cfg.TRAIN.BATCH_SIZE * cfg.DATASET.SEQLEN
    smpl = build_body_model(cfg.DEVICE, smpl_batch_size)
    network = build_network(cfg, smpl)
    network.eval()
    demo.smpl = smpl
    original_detection_model = demo.DetectionModel
    original_feature_extractor = demo.FeatureExtractor
    preprocessing_models: dict[str, Any] = {}
    preprocessing_load_seconds = 0.0

    def cached_detection_model(device, *args, **kwargs):
        nonlocal preprocessing_load_seconds
        model = preprocessing_models.get("detector")
        if model is None:
            load_started = time.perf_counter()
            model = original_detection_model(device, *args, **kwargs)
            preprocessing_models["detector"] = model
            preprocessing_load_seconds += time.perf_counter() - load_started
        model.initialize_tracking()
        return model

    def cached_feature_extractor(device, flip_eval=False, *args, **kwargs):
        nonlocal preprocessing_load_seconds
        cache_key = f"extractor:{device}:{bool(flip_eval)}"
        model = preprocessing_models.get(cache_key)
        if model is None:
            load_started = time.perf_counter()
            model = original_feature_extractor(device, flip_eval, *args, **kwargs)
            preprocessing_models[cache_key] = model
            preprocessing_load_seconds += time.perf_counter() - load_started
        return model

    demo.DetectionModel = cached_detection_model
    demo.FeatureExtractor = cached_feature_extractor
    gpu_name = None
    try:
        gpu_name = torch.cuda.get_device_name()
    except Exception:
        gpu_name = None
    return {
        "demo": demo,
        "cfg": cfg,
        "network": network,
        "loadSeconds": round(time.perf_counter() - started, 3),
        "gpuName": gpu_name,
        "preprocessingModels": preprocessing_models,
        "preprocessingLoadSeconds": lambda: preprocessing_load_seconds,
    }


def sequence_output_dir(output_root: Path, video_path: Path) -> Path:
    sequence = ".".join(video_path.name.split(".")[:-1]) or video_path.stem
    return output_root / sequence


def process_job(job_path: Path, result_dir: Path, job_logs_dir: Path, wham_state: dict[str, Any]) -> None:
    job = json.loads(job_path.read_text(encoding="utf-8"))
    job_id = str(job.get("jobId") or job_path.stem)
    result_path = result_dir / f"{job_id}.json"
    stdout_log = job_logs_dir / f"{job_id}.stdout.log"
    stderr_log = job_logs_dir / f"{job_id}.stderr.log"
    started = time.perf_counter()
    payload: dict[str, Any] = {
        "jobId": job_id,
        "status": "failed",
        "stdoutLog": str(stdout_log),
        "stderrLog": str(stderr_log),
    }
    try:
        video_path = Path(str(job["video"]))
        output_root = Path(str(job["outputRoot"]))
        output_path = sequence_output_dir(output_root, video_path)
        output_path.mkdir(parents=True, exist_ok=True)
        preprocessing_cache_hit = (output_path / "tracking_results.pth").is_file() and (
            output_path / "slam_results.pth"
        ).is_file()
        preprocessing_load_before = wham_state["preprocessingLoadSeconds"]()
        wham_state["demo"].args = SimpleNamespace(run_smplify=bool(job.get("runSmplify", True)))
        with stdout_log.open("w", encoding="utf-8") as stdout_handle, stderr_log.open("w", encoding="utf-8") as stderr_handle:
            with contextlib.redirect_stdout(stdout_handle), contextlib.redirect_stderr(stderr_handle):
                wham_state["demo"].run(
                    wham_state["cfg"],
                    str(video_path),
                    str(output_path),
                    wham_state["network"],
                    job.get("calib"),
                    run_global=not bool(job.get("estimateLocalOnly", True)),
                    save_pkl=True,
                    visualize=False,
                )
        results_pkl = output_path / "wham_output.pkl"
        if not results_pkl.exists():
            raise RuntimeError(f"WHAM finished without writing {results_pkl}")
        payload.update(
            {
                "status": "completed",
                "outputDir": str(output_path),
                "resultsPkl": str(results_pkl),
                "elapsedSeconds": round(time.perf_counter() - started, 3),
                "timings": {
                    "workerModelLoadSeconds": wham_state["loadSeconds"],
                    "preprocessingModelLoadSeconds": round(
                        wham_state["preprocessingLoadSeconds"]() - preprocessing_load_before,
                        3,
                    ),
                    "preprocessingCacheHit": preprocessing_cache_hit,
                    "jobElapsedSeconds": round(time.perf_counter() - started, 3),
                },
            }
        )
    except Exception as exc:
        payload.update(
            {
                "status": "failed",
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(),
                "elapsedSeconds": round(time.perf_counter() - started, 3),
            }
        )
    write_json(result_path, payload)
    print(f"{RESULT_PREFIX} {json.dumps({'jobId': job_id, 'status': payload['status']})}", flush=True)


def main() -> int:
    args = parse_args()
    state_dir = Path(args.state_dir)
    jobs_dir = state_dir / "jobs"
    running_dir = state_dir / "running"
    result_dir = state_dir / "results"
    job_logs_dir = state_dir / "job_logs"
    for path in (jobs_dir, running_dir, result_dir, job_logs_dir):
        path.mkdir(parents=True, exist_ok=True)

    try:
        wham_state = load_wham_once()
    except Exception as exc:
        write_json(
            state_dir / "startup_error.json",
            {
                "status": "failed",
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(),
            },
        )
        return 1

    write_json(
        state_dir / "ready.json",
        {
            "status": "ready",
            "pid": os.getpid(),
            "loadSeconds": wham_state["loadSeconds"],
            "gpuName": wham_state["gpuName"],
        },
    )
    print(f"{RESULT_PREFIX} {json.dumps({'status': 'ready', 'loadSeconds': wham_state['loadSeconds']})}", flush=True)

    stop_path = state_dir / "stop"
    poll_seconds = max(0.05, float(args.poll_seconds))
    while not stop_path.exists():
        job_paths = sorted(jobs_dir.glob("*.json"))
        if not job_paths:
            time.sleep(poll_seconds)
            continue
        for job_path in job_paths:
            running_path = running_dir / job_path.name
            try:
                job_path.replace(running_path)
            except FileNotFoundError:
                continue
            process_job(running_path, result_dir, job_logs_dir, wham_state)
            try:
                running_path.unlink()
            except FileNotFoundError:
                pass
    write_json(state_dir / "stopped.json", {"status": "stopped", "pid": os.getpid()})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
