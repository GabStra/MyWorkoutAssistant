from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class WhamRunResult:
    output_dir: Path
    results_pkl: Path


def run_wham_locally(
    *,
    wham_repo_path: Path,
    input_video: Path,
    output_root: Path,
    logs_dir: Path,
    python_command: str,
    estimate_local_only: bool = False,
    run_smplify: bool = False,
    use_docker: bool = False,
    docker_image: str = "yusun9/wham-vitpose-dpvo-cuda11.3-python3.9:latest",
    docker_gpus: str = "all",
    docker_shm_size: str = "8g",
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
    return WhamRunResult(output_dir=sequence_dir, results_pkl=results_pkl)


def build_wham_command(
    *,
    wham_repo_path: Path,
    input_video: Path,
    output_root: Path,
    python_command: str,
    estimate_local_only: bool,
    run_smplify: bool,
    use_docker: bool = False,
    docker_image: str = "yusun9/wham-vitpose-dpvo-cuda11.3-python3.9:latest",
    docker_gpus: str = "all",
    docker_shm_size: str = "8g",
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
        wham_repo_path / "checkpoints" / "yolov8x.pt",
        wham_repo_path / "dataset" / "body_models" / "smpl" / "SMPL_NEUTRAL.pkl",
    ]
    if not estimate_local_only:
        required_paths.append(wham_repo_path / "checkpoints" / "dpvo.pth")
    missing = [path for path in required_paths if not path.exists()]
    if missing:
        formatted = "\n".join(str(path) for path in missing)
        raise RuntimeError(f"WHAM repo is missing required files:\n{formatted}")
