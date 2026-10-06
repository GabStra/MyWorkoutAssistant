"""Compare GVHMR worker startup and output against a retained reference run."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PKG_DIR = REPO_ROOT / "exercise_motion_pkg"
PARITY_ROOT = REPO_ROOT / "build/exercise_motion/speed-harness/prewarm/parity"
WORKSPACE = REPO_ROOT / "build/exercise_motion/speed-harness/prewarm/workspace"
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
PARITY_FIELDS = ("pose_world", "trans_world", "betas", "frame_ids")


def validate_run_id(value: str) -> str:
    if not RUN_ID_PATTERN.fullmatch(value):
        raise ValueError("run id must be 1-64 letters, digits, underscores, or hyphens")
    return value


def compare_motion_outputs(reference_path: Path, candidate_path: Path) -> dict:
    """Compare the motion payload fields consumed by the pipeline."""
    import joblib
    import numpy as np

    def load_payload(path: Path) -> dict:
        value = joblib.load(path)
        if isinstance(value, dict) and 0 in value and isinstance(value[0], dict):
            value = value[0]
        if not isinstance(value, dict):
            raise ValueError(f"{path} does not contain a motion payload object")
        missing = [field for field in PARITY_FIELDS if field not in value]
        if missing:
            raise ValueError(f"{path} is missing required motion fields: {missing}")
        return value

    reference = load_payload(reference_path)
    candidate = load_payload(candidate_path)
    fields = {}
    for field in PARITY_FIELDS:
        expected = np.asarray(reference[field])
        actual = np.asarray(candidate[field])
        fields[field] = {
            "equal": bool(
                expected.shape == actual.shape
                and expected.dtype == actual.dtype
                and np.array_equal(expected, actual)
            ),
            "shape": list(actual.shape),
            "dtype": str(actual.dtype),
        }
    metadata_equal = reference.get("betasSource") == candidate.get("betasSource")
    identical = all(result["equal"] for result in fields.values()) and metadata_equal
    return {
        "identical": identical,
        "betasSourceEqual": metadata_equal,
        "fields": fields,
    }


def _docker_status(container: str) -> str:
    result = subprocess.run(
        ["docker", "inspect", "--format", "{{.State.Status}}", container],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    if result.returncode != 0:
        combined = f"{result.stdout or ''} {result.stderr or ''}".casefold()
        if "no such object" in combined or "no such container" in combined:
            return "not_found"
        return "inspect_error"
    return result.stdout.strip() or "unknown"


def _remove_container(container: str) -> None:
    try:
        subprocess.run(
            ["docker", "rm", "-f", container],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        pass


def _positive_seconds(value: str) -> float:
    seconds = float(value)
    if seconds <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return seconds


def _write_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value), encoding="utf-8")
    temporary.replace(path)


def run(args: argparse.Namespace) -> dict:
    run_id = validate_run_id(args.run)
    video = args.video.resolve()
    reference_pkl = args.reference_pkl.resolve()
    if not video.is_file():
        raise FileNotFoundError(f"input video does not exist: {video}")
    if not reference_pkl.is_file():
        raise FileNotFoundError(f"reference pkl does not exist: {reference_pkl}")

    run_dir = PARITY_ROOT / run_id
    if run_dir.exists():
        raise FileExistsError(f"parity run already exists; choose a new --run id: {run_dir}")
    run_dir.mkdir(parents=True)
    state_dir = run_dir / "worker-state"
    out_dir = WORKSPACE / f"out-{run_id}"
    for child in ("jobs", "running", "results", "job_logs"):
        (state_dir / child).mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=False)

    container = f"mwa-gvhmr-parity-{uuid.uuid4().hex[:10]}"
    worker_started = time.perf_counter()
    try:
        launch = subprocess.run(
            [
                "docker", "run", "-d", "--rm", "--name", container,
                "--gpus", "all", "--shm-size", "8g",
                "-v", f"{PKG_DIR / 'gvhmr_inference.py'}:/worker/gvhmr_inference.py:ro",
                "-v", f"{PKG_DIR / 'gvhmr_pkl_export.py'}:/worker/gvhmr_pkl_export.py:ro",
                "-v", f"{WORKSPACE}:/workspace",
                "-v", f"{video.parent}:/input:ro",
                "-v", f"{state_dir}:/worker_state",
                "-v", f"{PKG_DIR / 'gvhmr_warm_worker.py'}:/worker/gvhmr_warm_worker.py:ro",
                "-v", f"{PKG_DIR / 'warm_worker_retention.py'}:/worker/warm_worker_retention.py:ro",
                "-w", "/opt/gvhmr", args.image,
                "python", "-u", "/worker/gvhmr_warm_worker.py",
                "--state-dir", "/worker_state",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=90,
        )
    except subprocess.TimeoutExpired as exc:
        _remove_container(container)
        raise RuntimeError("docker run did not return within 90 seconds") from exc
    if launch.returncode != 0:
        _remove_container(container)
        raise RuntimeError(f"docker run failed ({launch.returncode}): {launch.stderr.strip()}")

    ready_path = state_dir / "ready.json"
    startup_error_path = state_dir / "startup_error.json"
    result_path = state_dir / "results" / f"parity-{run_id}.json"
    job_submitted = False
    try:
        wait_started = time.perf_counter()
        ready = None
        while time.perf_counter() - wait_started < args.ready_timeout:
            if ready_path.is_file():
                ready = json.loads(ready_path.read_text(encoding="utf-8"))
                break
            if startup_error_path.is_file():
                raise RuntimeError(
                    "GVHMR worker startup failed: "
                    + startup_error_path.read_text(encoding="utf-8")
                )
            if _docker_status(container) in {"exited", "dead", "not_found"}:
                raise RuntimeError("GVHMR worker container exited before becoming ready")
            time.sleep(2.0)
        if ready is None:
            raise TimeoutError(f"GVHMR worker did not become ready in {args.ready_timeout:.0f}s")
        worker_startup_wall_seconds = round(time.perf_counter() - worker_started, 1)

        job_id = f"parity-{run_id}"
        job = {
            "jobId": job_id,
            "video": f"/input/{video.name}",
            "outputRoot": f"/workspace/out-{run_id}",
            "staticCam": True,
            "keepSourceBetas": False,
        }
        _write_json(state_dir / "jobs" / f"{job_id}.json", job)
        job_submitted = True
        job_started = time.perf_counter()
        while time.perf_counter() - job_started < args.job_timeout:
            if result_path.is_file():
                break
            if _docker_status(container) in {"exited", "dead", "not_found"}:
                raise RuntimeError("GVHMR worker exited before returning a job result")
            time.sleep(1.0)
        if not result_path.is_file():
            raise TimeoutError(f"GVHMR job did not finish in {args.job_timeout:.0f}s")
        job_wall_seconds = round(time.perf_counter() - job_started, 1)

        result = json.loads(result_path.read_text(encoding="utf-8"))
        if result.get("status") != "completed":
            raise RuntimeError(f"GVHMR job failed: {result.get('error') or result}")
        candidate_pkl = out_dir / video.stem / "wham_output.pkl"
        if not candidate_pkl.is_file():
            raise FileNotFoundError(f"GVHMR job result omitted output pkl: {candidate_pkl}")
        parity = compare_motion_outputs(reference_pkl, candidate_pkl)
        report = {
            "runId": run_id,
            "image": args.image,
            "video": str(video),
            "referencePkl": str(reference_pkl),
            "candidatePkl": str(candidate_pkl),
            "workerLoadSeconds": ready.get("loadSeconds"),
            "workerStartupWallSeconds": worker_startup_wall_seconds,
            "jobWallSeconds": job_wall_seconds,
            "jobElapsedSeconds": result.get("elapsedSeconds"),
            "status": result.get("status"),
            "parity": parity,
        }
        (run_dir / "parity-result.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )
        return report
    finally:
        if state_dir.is_dir():
            (state_dir / "stop").write_text("{}", encoding="utf-8")
        try:
            subprocess.run(
                ["docker", "wait", container],
                capture_output=True,
                text=True,
                check=False,
                timeout=120,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass
        try:
            status = _docker_status(container)
        except (OSError, subprocess.SubprocessError):
            status = "inspect_error"
        if status not in {"not_found", "exited", "dead"}:
            _remove_container(container)
        if not job_submitted and state_dir.exists():
            (state_dir / "aborted-before-job.json").write_text("{}", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--run", required=True)
    parser.add_argument("--video", type=Path, required=True, help="input clip to reconstruct")
    parser.add_argument("--reference-pkl", type=Path, required=True)
    parser.add_argument("--ready-timeout", type=_positive_seconds, default=600.0)
    parser.add_argument("--job-timeout", type=_positive_seconds, default=420.0)
    args = parser.parse_args()
    try:
        report = run(args)
    except (OSError, ValueError, RuntimeError, TimeoutError, subprocess.SubprocessError) as exc:
        parser.exit(1, f"GVHMR parity run failed: {exc}\n")
    print(json.dumps(report, indent=2))
    return 0 if report["parity"]["identical"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
