from __future__ import annotations

import argparse
import contextlib
import gc
import importlib.util
import json
import os
import sys
import threading
import time
import traceback
from pathlib import Path
from types import SimpleNamespace
from typing import Any


RESULT_PREFIX = "__WHAM_WARM_WORKER__"
HEARTBEAT_INTERVAL_SECONDS = 2.0
INTERRUPTED_AMBIGUOUS_STATUS = "interrupted_ambiguous"
TERMINAL_JOB_STATUSES = {
    "completed",
    "failed",
    "rejected_tracking_preflight",
    INTERRUPTED_AMBIGUOUS_STATUS,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Warm WHAM worker for repeated motion extraction jobs.")
    parser.add_argument("--state-dir", required=True, help="Mounted worker state directory.")
    parser.add_argument("--poll-seconds", type=float, default=0.5)
    return parser.parse_args()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp_path.replace(path)


def recover_interrupted_running_jobs(state_dir: Path) -> list[dict[str, Any]]:
    """Publish terminal ambiguity for claimed jobs left by a dead worker.

    A request in ``running`` may have written partial inference output, so it
    must never be put back in ``jobs``. Unclaimed requests are intentionally
    left untouched for the replacement worker to process.
    """
    state_dir = Path(state_dir)
    running_dir = state_dir / "running"
    results_dir = state_dir / "results"
    ambiguous_dir = state_dir / "ambiguous"
    for directory in (running_dir, results_dir, ambiguous_dir):
        directory.mkdir(parents=True, exist_ok=True)

    recovered: list[dict[str, Any]] = []
    for claimed_path in sorted(running_dir.glob("*.json")):
        job_id = claimed_path.stem
        result_path = results_dir / f"{job_id}.json"
        try:
            request_payload = json.loads(claimed_path.read_text(encoding="utf-8"))
            if not isinstance(request_payload, dict):
                request_payload = {}
                request_error = "Claimed request was not a JSON object."
            else:
                request_error = None
        except (OSError, json.JSONDecodeError) as exc:
            request_payload = {}
            request_error = f"Claimed request could not be read: {type(exc).__name__}: {exc}"

        stage_identity = request_payload.get("stageIdentity")
        if not isinstance(stage_identity, dict):
            stage_identity = None
        recorded_job_id = str(request_payload.get("jobId") or "")
        archive_path = ambiguous_dir / claimed_path.name
        if archive_path.exists():
            archive_path = ambiguous_dir / f"{job_id}-{time.time_ns()}.json"

        # A completed result may have been atomically published just before
        # the prior worker died while removing its claimed request. Preserve
        # it only when it still belongs to this exact job and identity.
        existing_result: dict[str, Any] | None = None
        try:
            decoded_result = json.loads(result_path.read_text(encoding="utf-8"))
            if isinstance(decoded_result, dict):
                existing_result = decoded_result
        except (OSError, json.JSONDecodeError):
            pass
        existing_result_matches = (
            existing_result is not None
            and str(existing_result.get("jobId") or "") == job_id
            and existing_result.get("stageIdentity") == stage_identity
            and existing_result.get("status") in TERMINAL_JOB_STATUSES
        )

        if not existing_result_matches:
            recovery_error = (
                "The WHAM worker stopped after claiming this request. Output completeness is "
                "unknown, so the request was archived and will not be replayed."
            )
            if request_error:
                recovery_error += f" {request_error}"
            elif recorded_job_id and recorded_job_id != job_id:
                recovery_error += (
                    f" The request payload jobId {recorded_job_id!r} did not match its queue filename."
                )
            write_json(
                result_path,
                {
                    "jobId": job_id,
                    "stageIdentity": stage_identity,
                    "status": INTERRUPTED_AMBIGUOUS_STATUS,
                    "terminal": True,
                    "retryable": False,
                    "error": recovery_error,
                    "recovery": {
                        "classification": INTERRUPTED_AMBIGUOUS_STATUS,
                        "partialOutputPossible": True,
                        "automaticReplay": False,
                        "claimedRequestPath": f"running/{claimed_path.name}",
                        "archivedRequestPath": f"ambiguous/{archive_path.name}",
                        "requestPayloadJobId": recorded_job_id or None,
                    },
                },
            )

        claimed_path.replace(archive_path)
        recovered.append(
            {
                "jobId": job_id,
                "status": (
                    existing_result.get("status")
                    if existing_result_matches and existing_result is not None
                    else INTERRUPTED_AMBIGUOUS_STATUS
                ),
                "resultPath": str(result_path),
                "archivePath": str(archive_path),
            }
        )
    return recovered


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

    def reset_preprocessing_models() -> None:
        preprocessing_models.clear()
        gc.collect()
        try:
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.synchronize()
        except Exception:
            pass

    demo.DetectionModel = cached_detection_model
    demo.FeatureExtractor = cached_feature_extractor
    preflight_path = Path(__file__).with_name("wham_tracking_preflight.py")
    preflight_spec = importlib.util.spec_from_file_location(
        "wham_tracking_preflight",
        preflight_path,
    )
    if preflight_spec is None or preflight_spec.loader is None:
        raise RuntimeError(f"Failed to load WHAM tracking preflight from {preflight_path}")
    tracking_preflight = importlib.util.module_from_spec(preflight_spec)
    sys.modules["wham_tracking_preflight"] = tracking_preflight
    preflight_spec.loader.exec_module(tracking_preflight)
    gpu_name = None
    try:
        gpu_name = torch.cuda.get_device_name()
    except Exception:
        gpu_name = None
    return {
        "demo": demo,
        "cfg": cfg,
        "network": network,
        "trackingPreflight": tracking_preflight,
        "loadSeconds": round(time.perf_counter() - started, 3),
        "gpuName": gpu_name,
        "preprocessingModels": preprocessing_models,
        "preprocessingLoadSeconds": lambda: preprocessing_load_seconds,
        "resetPreprocessingModels": reset_preprocessing_models,
    }


def release_wham_state(wham_state: dict[str, Any]) -> None:
    """Release CUDA allocations before advertising that the worker stopped."""
    wham_state.clear()
    sys.modules.pop("wham_demo", None)
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
        "stageIdentity": job.get("stageIdentity"),
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
                preflight_report: dict[str, Any] | None = None
                preflight_seconds = 0.0
                if bool(job.get("trackingPreflight", False)):
                    preflight_started = time.perf_counter()
                    preflight_report = wham_state["trackingPreflight"].run_tracking_preflight(
                        video_path=video_path,
                        output_root=output_root,
                        report_path=output_path / "tracking_preflight.json",
                        required_start_seconds=job.get("requiredStartSeconds"),
                        required_end_seconds=job.get("requiredEndSeconds"),
                        cfg=wham_state["cfg"],
                        detection_model_factory=wham_state["demo"].DetectionModel,
                        feature_extractor_factory=wham_state["demo"].FeatureExtractor,
                    )
                    preflight_seconds = time.perf_counter() - preflight_started
                    payload["trackingPreflight"] = preflight_report
                    if not bool(preflight_report.get("passed")):
                        payload.update(
                            {
                                "status": "rejected_tracking_preflight",
                                "elapsedSeconds": round(time.perf_counter() - started, 3),
                                "timings": {
                                    "workerModelLoadSeconds": wham_state["loadSeconds"],
                                    "trackingPreflightSeconds": round(preflight_seconds, 3),
                                    "trackingPreflightCacheHit": preflight_report.get("cacheStatus") == "reused",
                                    "jobElapsedSeconds": round(time.perf_counter() - started, 3),
                                },
                            }
                        )
                        write_json(result_path, payload)
                        print(
                            f"{RESULT_PREFIX} {json.dumps({'jobId': job_id, 'status': payload['status']})}",
                            flush=True,
                        )
                        wham_state["resetPreprocessingModels"]()
                        return
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
                    "trackingPreflightSeconds": round(preflight_seconds, 3),
                    "trackingPreflightCacheHit": bool(
                        preflight_report
                        and preflight_report.get("cacheStatus") == "reused"
                    ),
                    "jobElapsedSeconds": round(time.perf_counter() - started, 3),
                },
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
    wham_state["resetPreprocessingModels"]()


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

    thread = threading.Thread(target=heartbeat_loop, name="wham-worker-heartbeat", daemon=True)
    thread.start()
    return stop_event, thread


def main() -> int:
    args = parse_args()
    state_dir = Path(args.state_dir)
    jobs_dir = state_dir / "jobs"
    running_dir = state_dir / "running"
    result_dir = state_dir / "results"
    job_logs_dir = state_dir / "job_logs"
    ambiguous_dir = state_dir / "ambiguous"
    for path in (jobs_dir, running_dir, result_dir, job_logs_dir, ambiguous_dir):
        path.mkdir(parents=True, exist_ok=True)

    recovered_jobs = recover_interrupted_running_jobs(state_dir)
    if recovered_jobs:
        print(
            f"Recovered {len(recovered_jobs)} interrupted WHAM job(s) as terminal ambiguous results.",
            flush=True,
        )

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

    heartbeat_stop, heartbeat_thread = start_heartbeat(state_dir)
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
                process_job(running_path, result_dir, job_logs_dir, wham_state)
                try:
                    running_path.unlink()
                except FileNotFoundError:
                    pass
    finally:
        heartbeat_stop.set()
        heartbeat_thread.join(timeout=HEARTBEAT_INTERVAL_SECONDS * 2.0)
        release_wham_state(wham_state)
        write_json(state_dir / "stopped.json", {"status": "stopped", "pid": os.getpid()})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
