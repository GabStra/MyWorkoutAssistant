from __future__ import annotations

import subprocess
import time
from typing import Any
from dataclasses import dataclass
from pathlib import Path


DEFAULT_WHAM_DOCKER_IMAGE = "myworkoutassistant/wham-ada:torch2.9-cu128-mmpose1"
DEFAULT_WHAM_DOCKER_SHM_SIZE = "16g"
DEFAULT_WHAM_ESTIMATE_LOCAL_ONLY = True


@dataclass(frozen=True)
class WhamRunResult:
    output_dir: Path
    results_pkl: Path
    stdout_log: Path
    stderr_log: Path
    command: list[str]
    elapsed_seconds: float
    returncode: int
    use_docker: bool
    estimate_local_only: bool
    run_smplify: bool
    docker_image: str | None = None

    def timing_payload(self) -> dict[str, Any]:
        return {
            "elapsedSeconds": round(self.elapsed_seconds, 3),
            "returncode": self.returncode,
            "useDocker": self.use_docker,
            "estimateLocalOnly": self.estimate_local_only,
            "runSmplify": self.run_smplify,
            "dockerImage": self.docker_image if self.use_docker else None,
            "stdoutLog": str(self.stdout_log),
            "stderrLog": str(self.stderr_log),
            "command": self.command,
            "outputDir": str(self.output_dir),
            "resultsPkl": str(self.results_pkl),
        }


def run_wham_locally(
    *,
    wham_repo_path: Path,
    input_video: Path,
    output_root: Path,
    logs_dir: Path,
    python_command: str,
    estimate_local_only: bool = DEFAULT_WHAM_ESTIMATE_LOCAL_ONLY,
    run_smplify: bool = True,
    use_docker: bool = False,
    docker_image: str = DEFAULT_WHAM_DOCKER_IMAGE,
    docker_gpus: str = "all",
    docker_shm_size: str = DEFAULT_WHAM_DOCKER_SHM_SIZE,
) -> WhamRunResult:
    validate_wham_repo_layout(wham_repo_path, estimate_local_only=estimate_local_only)
    output_root.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    stdout_log = logs_dir / "wham.stdout.log"
    stderr_log = logs_dir / "wham.stderr.log"
    command = build_wham_command(
        wham_repo_path=wham_repo_path,
        input_video=input_video,
        output_root=output_root,
        python_command=python_command,
        estimate_local_only=estimate_local_only,
        run_smplify=run_smplify,
        use_docker=use_docker,
        docker_image=docker_image,
        docker_gpus=docker_gpus,
        docker_shm_size=docker_shm_size,
    )
    started = time.perf_counter()
    with stdout_log.open("w", encoding="utf-8") as stdout_handle, stderr_log.open(
        "w",
        encoding="utf-8",
    ) as stderr_handle:
        process = subprocess.run(
            command,
            cwd=str(wham_repo_path),
            stdout=stdout_handle,
            stderr=stderr_handle,
            text=True,
            check=False,
        )
    elapsed = time.perf_counter() - started
    if process.returncode != 0:
        raise RuntimeError(
            "WHAM run failed. Check logs:\n"
            f"- {stdout_log}\n"
            f"- {stderr_log}"
        )

    sequence_dir = output_root / input_video.stem
    results_pkl = sequence_dir / "wham_output.pkl"
    if not results_pkl.exists():
        raise RuntimeError(
            "WHAM run completed but no wham_output.pkl was found.\n"
            f"Expected: {results_pkl}\n"
            f"Logs:\n- {stdout_log}\n- {stderr_log}"
        )
    return WhamRunResult(
        output_dir=sequence_dir,
        results_pkl=results_pkl,
        stdout_log=stdout_log,
        stderr_log=stderr_log,
        command=command,
        elapsed_seconds=elapsed,
        returncode=process.returncode,
        use_docker=use_docker,
        estimate_local_only=estimate_local_only,
        run_smplify=run_smplify,
        docker_image=docker_image if use_docker else None,
    )


def build_wham_command(
    *,
    wham_repo_path: Path,
    input_video: Path,
    output_root: Path,
    python_command: str,
    estimate_local_only: bool,
    run_smplify: bool,
    use_docker: bool = False,
    docker_image: str = DEFAULT_WHAM_DOCKER_IMAGE,
    docker_gpus: str = "all",
    docker_shm_size: str = DEFAULT_WHAM_DOCKER_SHM_SIZE,
) -> list[str]:
    if use_docker:
        command = ["docker", "run", "--rm"]
        if docker_gpus:
            command.extend(["--gpus", docker_gpus])
        if docker_shm_size:
            command.extend(["--shm-size", docker_shm_size])
        command.extend(
            [
                "-v",
                f"{wham_repo_path.resolve()}:/code",
                "-v",
                f"{input_video.parent.resolve()}:/input",
                "-v",
                f"{output_root.resolve()}:/output",
                "-w",
                "/code",
                docker_image,
                "python",
                "-u",
                "demo.py",
                "--video",
                f"/input/{input_video.name}",
                "--output_pth",
                "/output",
                "--save_pkl",
            ]
        )
        if estimate_local_only:
            command.append("--estimate_local_only")
        if run_smplify:
            command.append("--run_smplify")
        return command

    del wham_repo_path, docker_image, docker_gpus, docker_shm_size
    command = [
        python_command,
        "demo.py",
        "--video",
        str(input_video.resolve()),
        "--output_pth",
        str(output_root.resolve()),
        "--save_pkl",
    ]
    if estimate_local_only:
        command.append("--estimate_local_only")
    if run_smplify:
        command.append("--run_smplify")
    return command


def validate_wham_repo_layout(wham_repo_path: Path, *, estimate_local_only: bool) -> None:
    required_paths = [
        wham_repo_path / "demo.py",
        wham_repo_path / "requirements.txt",
        wham_repo_path / "checkpoints" / "wham_vit_w_3dpw.pth.tar",
        wham_repo_path / "checkpoints" / "hmr2a.ckpt",
        wham_repo_path / "checkpoints" / "vitpose-h-multi-coco.pth",
        wham_repo_path / "checkpoints" / "yolo26x.pt",
        wham_repo_path / "dataset" / "body_models" / "smpl" / "SMPL_NEUTRAL.pkl",
    ]
    if not estimate_local_only:
        required_paths.append(wham_repo_path / "checkpoints" / "dpvo.pth")
    missing = [path for path in required_paths if not path.exists()]
    if missing:
        formatted = "\n".join(str(path) for path in missing)
        raise RuntimeError(f"WHAM repo is missing required files:\n{formatted}")
