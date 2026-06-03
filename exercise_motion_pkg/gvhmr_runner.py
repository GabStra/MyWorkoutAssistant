from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GvhmrRunResult:
    output_dir: Path
    results_pt: Path


def run_gvhmr_locally(
    *,
    gvhmr_repo_path: Path,
    input_video: Path,
    output_root: Path,
    logs_dir: Path,
    python_command: str,
    static_camera: bool = False,
) -> GvhmrRunResult:
    validate_gvhmr_repo_layout(gvhmr_repo_path)
    output_root.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    stdout_log = logs_dir / "gvhmr.stdout.log"
    stderr_log = logs_dir / "gvhmr.stderr.log"
    command = build_gvhmr_command(
        gvhmr_repo_path=gvhmr_repo_path,
        input_video=input_video,
        output_root=output_root,
        python_command=python_command,
        static_camera=static_camera,
    )
    with stdout_log.open("w", encoding="utf-8") as stdout_handle, stderr_log.open(
        "w",
        encoding="utf-8",
    ) as stderr_handle:
        process = subprocess.run(
            command,
            cwd=str(gvhmr_repo_path),
            stdout=stdout_handle,
            stderr=stderr_handle,
            text=True,
            check=False,
        )
    if process.returncode != 0:
        raise RuntimeError(
            "GVHMR run failed. Check logs:\n"
            f"- {stdout_log}\n"
            f"- {stderr_log}"
        )

    sequence_dir = output_root / input_video.stem
    results_pt = sequence_dir / "hmr4d_results.pt"
    if not results_pt.exists():
        raise RuntimeError(
            "GVHMR run completed but no hmr4d_results.pt was found.\n"
            f"Expected: {results_pt}\n"
            f"Logs:\n- {stdout_log}\n- {stderr_log}"
        )
    return GvhmrRunResult(output_dir=sequence_dir, results_pt=results_pt)


def build_gvhmr_command(
    *,
    gvhmr_repo_path: Path,
    input_video: Path,
    output_root: Path,
    python_command: str,
    static_camera: bool,
) -> list[str]:
    del gvhmr_repo_path
    command = [
        python_command,
        "tools/demo/demo.py",
        f"--video={input_video.resolve()}",
        "--output_root",
        str(output_root.resolve()),
    ]
    if static_camera:
        command.append("-s")
    return command


def validate_gvhmr_repo_layout(gvhmr_repo_path: Path) -> None:
    required_paths = [
        gvhmr_repo_path / "tools" / "demo" / "demo.py",
        gvhmr_repo_path / "requirements.txt",
        gvhmr_repo_path / "inputs" / "checkpoints" / "gvhmr" / "gvhmr_siga24_release.ckpt",
        gvhmr_repo_path / "inputs" / "checkpoints" / "hmr2" / "epoch=10-step=25000.ckpt",
        gvhmr_repo_path / "inputs" / "checkpoints" / "vitpose" / "vitpose-h-multi-coco.pth",
        gvhmr_repo_path / "inputs" / "checkpoints" / "yolo" / "yolov8x.pt",
        gvhmr_repo_path / "inputs" / "checkpoints" / "body_models" / "smpl" / "SMPL_NEUTRAL.pkl",
        gvhmr_repo_path / "inputs" / "checkpoints" / "body_models" / "smplx" / "SMPLX_NEUTRAL.npz",
    ]
    missing = [path for path in required_paths if not path.exists()]
    if missing:
        formatted = "\n".join(str(path) for path in missing)
        raise RuntimeError(f"GVHMR repo is missing required files:\n{formatted}")
