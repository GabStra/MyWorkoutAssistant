"""GVHMR reconstruction runner (Docker).

Mirrors wham_runner.run_wham_locally's contract but executes the GVHMR demo
pipeline inside the myworkoutassistant/gvhmr image and exports a WHAM-schema
pkl so the generation pipeline can consume either backend unchanged.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from exercise_motion_pkg.gpu_lock import gpu_stage_lock
from exercise_motion_pkg.wham_runner import run_wham_process, wham_docker_run_lock


DEFAULT_GVHMR_DOCKER_IMAGE = "myworkoutassistant/gvhmr:torch2.3-cu121"
DEFAULT_GVHMR_DOCKER_SHM_SIZE = "8g"
GVHMR_DOCKER_SOURCE_ROOT = "/opt/gvhmr"
DEFAULT_GVHMR_TIMEOUT_SECONDS = 20 * 60.0


@dataclass(frozen=True)
class GvhmrRunResult:
    output_dir: Path
    results_pkl: Path
    demo_output_dir: Path
    stdout_log: Path
    stderr_log: Path
    command: list[str]
    elapsed_seconds: float
    returncode: int
    docker_image: str
    gpu_lock_wait_seconds: float
    docker_lock_wait_seconds: float
    timeout_seconds: float | None

    def timing_payload(self) -> dict[str, Any]:
        return {
            "elapsedSeconds": round(self.elapsed_seconds, 3),
            "returncode": self.returncode,
            "useDocker": True,
            "backend": "gvhmr",
            "dockerImage": self.docker_image,
            "timeoutSeconds": round(self.timeout_seconds, 3) if self.timeout_seconds is not None else None,
            "stdoutLog": str(self.stdout_log),
            "stderrLog": str(self.stderr_log),
            "command": self.command,
            "outputDir": str(self.output_dir),
            "resultsPkl": str(self.results_pkl),
            "demoOutputDir": str(self.demo_output_dir),
            "dockerLockWaitSeconds": round(self.docker_lock_wait_seconds, 3),
            "gpuLockWaitSeconds": round(self.gpu_lock_wait_seconds, 3),
        }


def build_gvhmr_command(
    *,
    input_video: Path,
    output_root: Path,
    export_script: Path,
    docker_image: str,
    docker_gpus: str,
    docker_shm_size: str,
    docker_container_name: str | None,
    static_camera: bool,
) -> list[str]:
    # demo.py writes to <output_root>/<video-stem>/hmr4d_results.pt; the export
    # step converts it to the WHAM-schema pkl the pipeline expects at
    # <output_root>/<video-stem>/wham_output.pkl.
    container_stem = input_video.stem
    demo_results = f"/output/demo/{container_stem}/hmr4d_results.pt"
    output_pkl = f"/output/{container_stem}/wham_output.pkl"
    demo_command = [
        "python",
        "tools/demo/demo.py",
        "--video",
        f"/input/{input_video.name}",
        "--output_root",
        "/output/demo",
    ]
    if static_camera:
        demo_command.append("-s")
    inner_script = (
        f"{' '.join(demo_command)} && "
        f"python /mwa/gvhmr_pkl_export.py --results {demo_results} --output-pkl {output_pkl}"
    )
    command = ["docker", "run", "--rm"]
    if docker_container_name:
        command.extend(["--name", docker_container_name])
    if docker_gpus:
        command.extend(["--gpus", docker_gpus])
    if docker_shm_size:
        command.extend(["--shm-size", docker_shm_size])
    command.extend(
        [
            "-v",
            f"{input_video.parent.resolve()}:/input",
            "-v",
            f"{output_root.resolve()}:/output",
            "-v",
            f"{export_script.parent.resolve()}:/mwa",
            "-w",
            GVHMR_DOCKER_SOURCE_ROOT,
            docker_image,
            "bash",
            "-lc",
            inner_script,
        ]
    )
    return command


def run_gvhmr_locally(
    *,
    input_video: Path,
    output_root: Path,
    logs_dir: Path,
    docker_image: str = DEFAULT_GVHMR_DOCKER_IMAGE,
    docker_gpus: str = "all",
    docker_shm_size: str = DEFAULT_GVHMR_DOCKER_SHM_SIZE,
    static_camera: bool = True,
    timeout_seconds: float | None = None,
) -> GvhmrRunResult:
    """Run GVHMR in Docker and return a WHAM-schema results pkl path."""
    timeout = (
        DEFAULT_GVHMR_TIMEOUT_SECONDS
        if timeout_seconds is None or float(timeout_seconds) <= 0.0
        else max(1.0, float(timeout_seconds))
    )
    output_root.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)
    stdout_log = logs_dir / "gvhmr.stdout.log"
    stderr_log = logs_dir / "gvhmr.stderr.log"
    docker_container_name = f"mwa-gvhmr-job-{uuid.uuid4().hex}"
    command = build_gvhmr_command(
        input_video=input_video,
        output_root=output_root,
        export_script=Path(__file__).with_name("gvhmr_pkl_export.py"),
        docker_image=docker_image,
        docker_gpus=docker_gpus,
        docker_shm_size=docker_shm_size,
        docker_container_name=docker_container_name,
        static_camera=static_camera,
    )
    started = time.perf_counter()
    lock_wait_seconds = 0.0
    gpu_lock_wait_seconds = 0.0
    with stdout_log.open("w", encoding="utf-8") as stdout_handle, stderr_log.open(
        "w", encoding="utf-8"
    ) as stderr_handle:
        with gpu_stage_lock(stage="gvhmr") as gpu_lock_wait_seconds:
            with wham_docker_run_lock(enabled=True) as lock_wait_seconds:
                returncode = run_wham_process(
                    command,
                    cwd=str(Path(__file__).resolve().parent),
                    stdout=stdout_handle,
                    stderr=stderr_handle,
                    timeout_seconds=timeout,
                    docker_container_name=docker_container_name,
                )
    elapsed = time.perf_counter() - started
    if returncode != 0:
        raise RuntimeError(
            "GVHMR run failed. Check logs:\n"
            f"- {stdout_log}\n- {stderr_log}"
        )
    sequence_dir = output_root / input_video.stem
    results_pkl = sequence_dir / "wham_output.pkl"
    if not results_pkl.exists():
        raise RuntimeError(
            "GVHMR run completed but no wham_output.pkl was found.\n"
            f"Expected: {results_pkl}\nLogs:\n- {stdout_log}\n- {stderr_log}"
        )
    return GvhmrRunResult(
        output_dir=sequence_dir,
        results_pkl=results_pkl,
        demo_output_dir=output_root / "demo" / input_video.stem,
        stdout_log=stdout_log,
        stderr_log=stderr_log,
        command=command,
        elapsed_seconds=elapsed,
        returncode=returncode,
        docker_image=docker_image,
        gpu_lock_wait_seconds=gpu_lock_wait_seconds,
        docker_lock_wait_seconds=lock_wait_seconds,
        timeout_seconds=timeout,
    )
