from __future__ import annotations

import json
import shutil
from dataclasses import replace
from dataclasses import dataclass
from pathlib import Path

from exercise_motion_pkg.cleanup import CleanupStats, cleanup_motion_clip
from exercise_motion_pkg.ground import GroundMetadata, generate_ground_metadata
from exercise_motion_pkg.motion_io import load_motion_json, save_motion_json
from exercise_motion_pkg.paths import PipelinePaths
from exercise_motion_pkg.preview import write_preview_html, write_wear_skeleton_json
from exercise_motion_pkg.retarget_contract import build_target_rig_contract
from exercise_motion_pkg.wham_convert import normalize_wham_output
from exercise_motion_pkg.wham_retarget_source import export_wham_retarget_source
from exercise_motion_pkg.wham_runner import run_wham_locally
from exercise_motion_pkg.wham_smpl_preview import (
    build_wham_smpl_runtime_mesh_payload,
    load_wham_smpl_mesh_sequence,
    write_baked_wham_smpl_preview_json,
)
from exercise_motion_pkg.youtube import download_youtube, sanitize_video_for_processing


@dataclass(frozen=True)
class GenerateRequest:
    exercise_slug: str
    workspace: Path
    youtube_url: str | None = None
    video_path: Path | None = None
    wham_repo_path: Path | None = None
    wham_results_pkl: Path | None = None
    body_model_root: Path | None = None
    wham_python_command: str = "python"
    use_wham_docker: bool = False
    wham_docker_image: str = "yusun9/wham-vitpose-dpvo-cuda11.3-python3.9:latest"
    wham_docker_gpus: str = "all"
    wham_docker_shm_size: str = "8g"
    wham_estimate_local_only: bool = False
    wham_run_smplify: bool = False
    wham_coordinate_space: str = "camera"
    normalized_motion_json: Path | None = None
    one_euro_min_cutoff: float = 0.6
    one_euro_beta: float = 0.05
    one_euro_derivative_cutoff: float = 1.0
    motion_threshold: float = 0.015
    padding_frames: int = 3


@dataclass(frozen=True)
class GenerateResult:
    manifest_path: Path
    preview_html_path: Path
    raw_preview_html_path: Path
    wear_skeleton_json_path: Path
    cleaned_motion_json_path: Path
    raw_motion_json_path: Path
    target_rig_contract_path: Path
    retarget_source_path: Path | None
    smpl_preview_json_path: Path | None
    copied_input_video_path: Path
    cleanup_stats: CleanupStats
    ground_metadata_path: Path | None


def run_generation_pipeline(request: GenerateRequest) -> GenerateResult:
    paths = PipelinePaths.create(request.workspace, request.exercise_slug)
    input_video_path = prepare_input_video(request, paths)
    raw_motion_json_path = paths.raw_dir / "motion.raw.json"
    retarget_source_path: Path | None = None
    smpl_preview_sequence = None
    smpl_preview_json_path: Path | None = None
    if request.normalized_motion_json is not None:
        shutil.copy2(request.normalized_motion_json, raw_motion_json_path)
    else:
        if request.body_model_root is None:
            raise ValueError("body_model_root is required when using WHAM output.")
        wham_output_dir = paths.raw_dir / "wham"
        wham_output_dir.mkdir(parents=True, exist_ok=True)
        wham_results_pkl = request.wham_results_pkl or (wham_output_dir / "wham_output.pkl")
        if request.wham_results_pkl is not None:
            wham_results_pkl = request.wham_results_pkl.expanduser().resolve()
        elif request.wham_repo_path is not None:
            wham_result = run_wham_locally(
                wham_repo_path=request.wham_repo_path.expanduser().resolve(),
                input_video=input_video_path,
                output_root=wham_output_dir,
                logs_dir=paths.logs_dir,
                python_command=request.wham_python_command,
                estimate_local_only=request.wham_estimate_local_only,
                run_smplify=request.wham_run_smplify,
                use_docker=request.use_wham_docker,
                docker_image=request.wham_docker_image,
                docker_gpus=request.wham_docker_gpus,
                docker_shm_size=request.wham_docker_shm_size,
            )
            wham_results_pkl = wham_result.results_pkl
        else:
            raise ValueError(
                "Provide normalized_motion_json, or provide body_model_root with either wham_repo_path or wham_results_pkl."
            )
        normalize_wham_output(
            wham_results_pkl=wham_results_pkl,
            body_model_root=request.body_model_root.expanduser().resolve(),
            output_json=raw_motion_json_path,
            coordinate_space=request.wham_coordinate_space,
        )
        retarget_source_path = export_wham_retarget_source(
            wham_results_pkl=wham_results_pkl,
            output_json=paths.retarget_dir / "wham.retarget_source.json",
            coordinate_space=request.wham_coordinate_space,
        )
        smpl_preview_sequence = load_wham_smpl_mesh_sequence(
            wham_results_pkl=wham_results_pkl,
            body_model_root=request.body_model_root.expanduser().resolve(),
            coordinate_space=request.wham_coordinate_space,
        )

    raw_clip = load_motion_json(raw_motion_json_path)
    raw_preview_html_path = paths.preview_dir / "motion_preview.raw.html"
    write_preview_html(raw_preview_html_path, raw_clip, title=f"{request.exercise_slug}-raw")
    cleaned_clip, cleanup_stats = cleanup_motion_clip(
        raw_clip,
        one_euro_min_cutoff=request.one_euro_min_cutoff,
        one_euro_beta=request.one_euro_beta,
        one_euro_derivative_cutoff=request.one_euro_derivative_cutoff,
        motion_threshold=request.motion_threshold,
        padding_frames=request.padding_frames,
    )
    ground_metadata_path = paths.cleaned_dir / "ground.metadata.json"
    ground_metadata = generate_ground_metadata(
        video_path=input_video_path,
        cleaned_clip=cleaned_clip,
        output_path=ground_metadata_path,
    )
    cleaned_clip = replace(
        cleaned_clip,
        metadata={
            **cleaned_clip.metadata,
            "ground": ground_metadata.to_dict(),
        },
    )
    cleaned_motion_json_path = paths.cleaned_dir / "motion.cleaned.json"
    save_motion_json(cleaned_motion_json_path, cleaned_clip)

    preview_html_path = paths.preview_dir / "motion_preview.html"
    smpl_mesh_payload = None
    if smpl_preview_sequence is not None:
        smpl_preview_json_path = paths.retarget_dir / "wham.smpl_preview.baked.json"
        smpl_preview_payload = write_baked_wham_smpl_preview_json(
            smpl_preview_json_path,
            sequence=smpl_preview_sequence,
            raw_clip=raw_clip,
            cleaned_clip=cleaned_clip,
            title=request.exercise_slug,
        )
        smpl_mesh_payload = build_wham_smpl_runtime_mesh_payload(
            sequence=smpl_preview_sequence,
            raw_clip=raw_clip,
            cleaned_clip=cleaned_clip,
        )
    write_preview_html(
        preview_html_path,
        cleaned_clip,
        title=request.exercise_slug,
        smpl_mesh_payload=smpl_mesh_payload,
    )
    wear_skeleton_json_path = paths.wear_dir / "skeleton.preview.json"
    write_wear_skeleton_json(wear_skeleton_json_path, cleaned_clip, title=request.exercise_slug)
    target_rig_contract_path = paths.retarget_dir / "target_rig.contract.json"
    target_rig_contract_path.write_text(
        json.dumps(build_target_rig_contract(), indent=2),
        encoding="utf-8",
    )

    manifest_path = paths.root / "manifest.json"
    manifest_payload = {
        "exerciseSlug": request.exercise_slug,
        "inputVideoPath": str(input_video_path),
        "rawMotionJsonPath": str(raw_motion_json_path),
        "cleanedMotionJsonPath": str(cleaned_motion_json_path),
        "rawPreviewHtmlPath": str(raw_preview_html_path),
        "previewHtmlPath": str(preview_html_path),
        "wearSkeletonJsonPath": str(wear_skeleton_json_path),
        "groundMetadataPath": str(ground_metadata_path),
        "targetRigContractPath": str(target_rig_contract_path),
        "retargetSourcePath": str(retarget_source_path) if retarget_source_path is not None else None,
        "whamRetargetSourcePath": str(retarget_source_path) if retarget_source_path is not None else None,
        "whamSmplPreviewJsonPath": str(smpl_preview_json_path) if smpl_preview_json_path is not None else None,
        "cleanupStats": {
            "inputFrames": cleanup_stats.input_frames,
            "outputFrames": cleanup_stats.output_frames,
            "trimmedStartFrames": cleanup_stats.trimmed_start_frames,
            "trimmedEndFrames": cleanup_stats.trimmed_end_frames,
            "averageRootHeightBefore": cleanup_stats.average_root_height_before,
            "averageRootHeightAfter": cleanup_stats.average_root_height_after,
        },
        "groundMetadata": ground_metadata.to_dict(),
        "postProcessing": {
            "applied": True,
            "steps": [
                "ground_plane_fitting",
                "root_translation_one_euro_xz",
            ],
        },
        "nextStage": {
            "status": "wear_preview_skeleton_ready",
            "description": "Render the baked preview skeleton directly on Wear. It already includes preview alignment, root-drift lock, active loop selection, and centering.",
            "cleanedMotionJsonPath": str(cleaned_motion_json_path),
            "wearSkeletonJsonPath": str(wear_skeleton_json_path),
            "retargetSourcePath": str(retarget_source_path) if retarget_source_path is not None else None,
            "whamRetargetSourcePath": str(retarget_source_path) if retarget_source_path is not None else None,
            "targetRigContractPath": str(target_rig_contract_path),
            "whamSmplPreviewJsonPath": str(smpl_preview_json_path) if smpl_preview_json_path is not None else None,
        },
    }
    manifest_path.write_text(json.dumps(manifest_payload, indent=2), encoding="utf-8")
    return GenerateResult(
        manifest_path=manifest_path,
        preview_html_path=preview_html_path,
        raw_preview_html_path=raw_preview_html_path,
        wear_skeleton_json_path=wear_skeleton_json_path,
        cleaned_motion_json_path=cleaned_motion_json_path,
        raw_motion_json_path=raw_motion_json_path,
        target_rig_contract_path=target_rig_contract_path,
        retarget_source_path=retarget_source_path,
        smpl_preview_json_path=smpl_preview_json_path,
        copied_input_video_path=input_video_path,
        cleanup_stats=cleanup_stats,
        ground_metadata_path=ground_metadata_path,
    )


def prepare_input_video(request: GenerateRequest, paths: PipelinePaths) -> Path:
    if request.youtube_url:
        return download_youtube(request.youtube_url, paths.input_dir)
    if request.video_path:
        source = request.video_path.expanduser().resolve()
        if not source.exists():
            raise FileNotFoundError(f"Input video not found: {source}")
        destination = paths.input_dir / source.name
        if source == destination.resolve():
            return sanitize_video_for_processing(destination)
        shutil.copy2(source, destination)
        return sanitize_video_for_processing(destination)
    raise ValueError("Either youtube_url or video_path must be provided.")
