"""Warm GVHMR worker for repeated motion extraction jobs.

Runs inside the GVHMR Docker image and mirrors the WHAM warm-worker file
protocol (jobs/running/results/job_logs + ready/heartbeat/stop markers). The
one-shot runner pays the full container lifecycle per job: Python imports,
ViTPose/HMR2 checkpoint loads, and CUDA context setup dominate the attempt
wall time while the GPU itself computes only a small fraction of it. This
worker loads Tracker/VitPoseExtractor/Extractor/DemoPL once and keeps them
resident across jobs, so each job costs only its preprocessing execution,
prediction, and in-process pkl export.
"""

from __future__ import annotations

import argparse
import contextlib
import gc
import json
import os
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Any


RESULT_PREFIX = "__GVHMR_WARM_WORKER__"
HEARTBEAT_INTERVAL_SECONDS = 2.0
GVHMR_ROOT = Path("/opt/gvhmr")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Warm GVHMR worker for repeated motion extraction jobs.")
    parser.add_argument("--state-dir", required=True, help="Mounted worker state directory.")
    parser.add_argument("--poll-seconds", type=float, default=0.5)
    return parser.parse_args()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp_path.replace(path)


def load_gvhmr_once() -> dict[str, Any]:
    started = time.perf_counter()
    for path in (str(GVHMR_ROOT), str(Path(__file__).resolve().parent)):
        if path not in sys.path:
            sys.path.insert(0, path)

    timings: dict[str, float] = {}
    from tools.demo import demo as demo_module
    from gvhmr_inference import _instrument_preprocessing

    _instrument_preprocessing(demo_module, timings)
    timings["demoImportsSeconds"] = time.perf_counter() - started

    import torch
    import hydra
    from hydra import initialize_config_module, compose

    from hmr4d.configs import register_store_gvhmr

    # Deliberately no TF32/cudnn-benchmark toggles here (unlike the WHAM
    # worker): the one-shot gvhmr_inference.py path sets none of them, and any
    # deviation could change numerics between warm and one-shot outputs.

    # Eagerly construct every preprocessing model plus the prediction model so
    # ready.json reflects true readiness and the first job pays only execution.
    preprocessing_models: dict[str, Any] = {}
    preprocessing_load_seconds = 0.0

    def cached_constructor(name: str, original: Any):
        def constructor(*args: Any, **kwargs: Any):
            model = preprocessing_models.get(name)
            if model is None:
                load_started = time.perf_counter()
                model = original(*args, **kwargs)
                preprocessing_models[name] = model
                nonlocal preprocessing_load_seconds
                preprocessing_load_seconds += time.perf_counter() - load_started
            return model

        return constructor

    for class_name in ("Tracker", "VitPoseExtractor", "Extractor"):
        original = getattr(demo_module, class_name)
        setattr(demo_module, class_name, cached_constructor(class_name, original))
        getattr(demo_module, class_name)()

    model_cfg_started = time.perf_counter()
    with initialize_config_module(version_base="1.3", config_module="hmr4d.configs"):
        register_store_gvhmr()
        startup_cfg = compose(config_name="demo", overrides=["video_name=warm_worker_startup"])
    model: Any = hydra.utils.instantiate(startup_cfg.model, _recursive_=False)
    model.load_pretrained_model(startup_cfg.ckpt_path)
    model = model.eval().cuda()
    timings["modelSetupSeconds"] = time.perf_counter() - model_cfg_started

    gpu_name = None
    try:
        gpu_name = torch.cuda.get_device_name()
    except Exception:
        gpu_name = None
    return {
        "demo": demo_module,
        "model": model,
        "ckptPath": str(startup_cfg.ckpt_path),
        "timings": timings,
        "composeCfg": compose,
        "initializeConfigModule": initialize_config_module,
        "registerStoreGvhmr": register_store_gvhmr,
        "loadSeconds": round(time.perf_counter() - started, 3),
        "gpuName": gpu_name,
        "preprocessingLoadSeconds": lambda: preprocessing_load_seconds,
    }


def release_gvhmr_state(state: dict[str, Any]) -> None:
    """Release CUDA allocations before advertising that the worker stopped."""
    state.clear()
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.synchronize()
    except Exception:
        # Process exit remains the final release boundary even if CUDA cleanup
        # itself cannot run during shutdown.
        pass


def compose_job_cfg(state: dict[str, Any], video_path: Path, output_root: Path, static_cam: bool) -> Any:
    """Replicate tools.demo.parse_args_to_cfg without argv: same overrides and
    raw-input-video copy, so cached preprocessing results stay path-compatible
    with the one-shot runner."""
    from hmr4d.utils.pylogger import Log
    from hmr4d.utils.video_io_utils import get_video_lwh, get_video_reader, get_writer
    from tqdm import tqdm

    video_path = video_path.resolve()
    if not video_path.exists():
        raise FileNotFoundError(f"Video not found at {video_path}")
    length, width, height = get_video_lwh(video_path)
    Log.info(f"[Input]: {video_path}")
    Log.info(f"(L, W, H) = ({length}, {width}, {height})")

    with state["initializeConfigModule"](version_base="1.3", config_module="hmr4d.configs"):
        overrides = [
            f"video_name={video_path.stem}",
            f"static_cam={bool(static_cam)}",
            "verbose=False",
            "use_dpvo=False",
            f"output_root={output_root.resolve() / 'demo'}",
        ]
        state["registerStoreGvhmr"]()
        cfg = state["composeCfg"](config_name="demo", overrides=overrides)

    if str(cfg.ckpt_path) != state["ckptPath"]:
        # The prediction model is instantiated once at startup and reused, and
        # this function never overrides the model group — only video_name,
        # static_cam, verbose, use_dpvo, and output_root, none of which feed
        # cfg.model. Comparing the resolved model node instead proved unstable:
        # its "${pipeline}" interpolation resolves differently depending on
        # import/compose history within one process, so it cannot serve as a
        # reuse guard. The checkpoint path is the stable identity here.
        raise RuntimeError("Warm GVHMR worker received a job with a different checkpoint than startup")

    Log.info(f"[Output Dir]: {cfg.output_dir}")
    Path(cfg.output_dir).mkdir(parents=True, exist_ok=True)
    Path(cfg.preprocess_dir).mkdir(parents=True, exist_ok=True)

    Log.info(f"[Copy Video] {video_path} -> {cfg.video_path}")
    if not Path(cfg.video_path).exists() or get_video_lwh(video_path)[0] != get_video_lwh(cfg.video_path)[0]:
        reader = get_video_reader(video_path)
        writer = get_writer(cfg.video_path, fps=30, crf=state["demo"].CRF)
        for img in tqdm(reader, total=get_video_lwh(video_path)[0], desc="Copy"):
            writer.write_frame(img)
        writer.close()
        reader.close()
    return cfg


def process_job(job_path: Path, result_dir: Path, job_logs_dir: Path, state: dict[str, Any]) -> None:
    from gvhmr_pkl_export import export_gvhmr_results_pkl

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
        static_cam = bool(job.get("staticCam", True))
        keep_source_betas = bool(job.get("keepSourceBetas", False))
        timings: dict[str, float] = dict(state["timings"])
        with stdout_log.open("w", encoding="utf-8") as stdout_handle, stderr_log.open(
            "w", encoding="utf-8"
        ) as stderr_handle:
            with contextlib.redirect_stdout(stdout_handle), contextlib.redirect_stderr(stderr_handle):
                phase_started = time.perf_counter()
                cfg = compose_job_cfg(state, video_path, output_root, static_cam)
                timings["configSeconds"] = time.perf_counter() - phase_started

                phase_started = time.perf_counter()
                state["demo"].run_preprocess(cfg)
                timings["preprocessSeconds"] = time.perf_counter() - phase_started

                phase_started = time.perf_counter()
                data = state["demo"].load_data_dict(cfg)
                timings["loadDataSeconds"] = time.perf_counter() - phase_started

                results_path = Path(cfg.paths.hmr4d_results)
                if results_path.exists():
                    from hmr4d.utils.pylogger import Log

                    Log.info(f"[HMR4D] Results already exist at {results_path}")
                    timings["predictionSeconds"] = 0.0
                    timings["savePredictionSeconds"] = 0.0
                else:
                    import torch

                    from hmr4d.utils.net_utils import detach_to_cpu
                    from hmr4d.utils.pylogger import Log

                    Log.info("[HMR4D] Predicting")
                    phase_started = time.perf_counter()
                    prediction = detach_to_cpu(state["model"].predict(data, static_cam=cfg.static_cam))
                    timings["predictionSeconds"] = time.perf_counter() - phase_started
                    phase_started = time.perf_counter()
                    results_path.parent.mkdir(parents=True, exist_ok=True)
                    torch.save(prediction, results_path)
                    timings["savePredictionSeconds"] = time.perf_counter() - phase_started

                phase_started = time.perf_counter()
                output_pkl = output_root.resolve() / video_path.stem / "wham_output.pkl"
                export_summary = export_gvhmr_results_pkl(
                    results_path, output_pkl, keep_source_betas=keep_source_betas
                )
                timings["exportSeconds"] = time.perf_counter() - phase_started
        if not output_pkl.exists():
            raise RuntimeError(f"GVHMR worker finished without writing {output_pkl}")
        payload.update(
            {
                "status": "completed",
                "outputDir": str(output_root / video_path.stem),
                "resultsPkl": str(output_pkl),
                "exportSummary": export_summary,
                "elapsedSeconds": round(time.perf_counter() - started, 3),
                "timings": {key: round(value, 3) for key, value in timings.items()},
            }
        )
    except BaseException as exc:
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
    # Keep the loaded models resident; only release per-job activation caches.
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.synchronize()
    except Exception:
        pass


def start_heartbeat(state_dir: Path) -> tuple[threading.Event, threading.Thread]:
    stop_event = threading.Event()
    heartbeat_path = state_dir / "heartbeat.json"

    def heartbeat_loop() -> None:
        while not stop_event.is_set():
            try:
                write_json(
                    heartbeat_path,
                    {
                        "status": "alive",
                        "pid": os.getpid(),
                        "updatedAtUnixSeconds": time.time(),
                    },
                )
            except OSError:
                pass
            stop_event.wait(HEARTBEAT_INTERVAL_SECONDS)

    thread = threading.Thread(target=heartbeat_loop, name="gvhmr-worker-heartbeat", daemon=True)
    thread.start()
    return stop_event, thread


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
        state = load_gvhmr_once()
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

    heartbeat_stop, heartbeat_thread = start_heartbeat(state_dir)
    write_json(
        state_dir / "ready.json",
        {
            "status": "ready",
            "pid": os.getpid(),
            "loadSeconds": state["loadSeconds"],
            "gpuName": state["gpuName"],
        },
    )
    print(f"{RESULT_PREFIX} {json.dumps({'status': 'ready', 'loadSeconds': state['loadSeconds']})}", flush=True)

    stop_path = state_dir / "stop"
    poll_seconds = max(0.05, float(args.poll_seconds))
    try:
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
                process_job(running_path, result_dir, job_logs_dir, state)
                try:
                    running_path.unlink()
                except FileNotFoundError:
                    pass
    finally:
        heartbeat_stop.set()
        heartbeat_thread.join(timeout=HEARTBEAT_INTERVAL_SECONDS * 2.0)
        release_gvhmr_state(state)
        write_json(state_dir / "stopped.json", {"status": "stopped", "pid": os.getpid()})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
