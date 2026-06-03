from __future__ import annotations

import json
import shutil
from dataclasses import replace
from dataclasses import dataclass
from pathlib import Path

from exercise_motion_pkg.cleanup import CleanupStats, cleanup_motion_clip
from exercise_motion_pkg.gvhmr import normalize_gvhmr_output
from exercise_motion_pkg.gvhmr_retarget_source import export_gvhmr_retarget_source
from exercise_motion_pkg.gvhmr_runner import run_gvhmr_locally
from exercise_motion_pkg.ground import GroundMetadata, generate_ground_metadata
from exercise_motion_pkg.motion_io import load_motion_json, save_motion_json
from exercise_motion_pkg.paths import PipelinePaths
from exercise_motion_pkg.preview import write_preview_html
from exercise_motion_pkg.retarget_contract import build_target_rig_contract
from exercise_motion_pkg.youtube import download_youtube


@dataclass(frozen=True)
class GenerateRequest:
    exercise_slug: str
    workspace: Path
    youtube_url: str | None = None
    video_path: Path | None = None
    gvhmr_repo_path: Path | None = None
    gvhmr_results_pt: Path | None = None
    body_model_root: Path | None = None
    gvhmr_python_command: str = "python"
    gvhmr_static_camera: bool = False
    gvhmr_coordinate_space: str = "incam"
    normalized_motion_json: Path | None = None
    smoothing_window: int = 5
    motion_threshold: float = 0.015
    padding_frames: int = 3


@dataclass(frozen=True)
class GenerateResult:
    manifest_path: Path
    preview_html_path: Path
    raw_preview_html_path: Path
    cleaned_motion_json_path: Path
    raw_motion_json_path: Path
    target_rig_contract_path: Path
    gvhmr_retarget_source_path: Path | None
    copied_input_video_path: Path
    cleanup_stats: CleanupStats
    ground_metadata_path: Path | None


def run_generation_pipeline(request: GenerateRequest) -> GenerateResult:
    paths = PipelinePaths.create(request.workspace, request.exercise_slug)
    input_video_path = prepare_input_video(request, paths)
    raw_motion_json_path = paths.raw_dir / "motion.raw.json"
    gvhmr_retarget_source_path: Path | None = None
    if request.normalized_motion_json is not None:
        shutil.copy2(request.normalized_motion_json, raw_motion_json_path)
    else:
        if request.body_model_root is None:
            raise ValueError("body_model_root is required when using GVHMR output.")
        gvhmr_output_dir = paths.raw_dir / "gvhmr"
        gvhmr_output_dir.mkdir(parents=True, exist_ok=True)
        gvhmr_results_pt = request.gvhmr_results_pt or (gvhmr_output_dir / "hmr4d_results.pt")
        if request.gvhmr_results_pt is not None:
            gvhmr_results_pt = request.gvhmr_results_pt.expanduser().resolve()
        elif request.gvhmr_repo_path is not None:
            gvhmr_result = run_gvhmr_locally(
                gvhmr_repo_path=request.gvhmr_repo_path.expanduser().resolve(),
                input_video=input_video_path,
                output_root=gvhmr_output_dir,
                logs_dir=paths.logs_dir,
                python_command=request.gvhmr_python_command,
                static_camera=request.gvhmr_static_camera,
            )
            gvhmr_results_pt = gvhmr_result.results_pt
        else:
            raise ValueError(
                "Provide normalized_motion_json, or provide body_model_root with either gvhmr_repo_path or gvhmr_results_pt."
            )
        normalize_gvhmr_output(
            gvhmr_results_pt=gvhmr_results_pt,
            body_model_root=request.body_model_root.expanduser().resolve(),
            output_json=raw_motion_json_path,
            coordinate_space=request.gvhmr_coordinate_space,
        )
        gvhmr_retarget_source_path = export_gvhmr_retarget_source(
            gvhmr_results_pt=gvhmr_results_pt,
            output_json=paths.retarget_dir / "gvhmr.retarget_source.json",
            coordinate_space=request.gvhmr_coordinate_space,
        )

    raw_clip = load_motion_json(raw_motion_json_path)
    raw_preview_html_path = paths.preview_dir / "motion_preview.raw.html"
    write_preview_html(raw_preview_html_path, raw_clip, title=f"{request.exercise_slug}-raw")
    cleaned_clip, cleanup_stats = cleanup_motion_clip(
        raw_clip,
        smoothing_window=request.smoothing_window,
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
    write_preview_html(preview_html_path, cleaned_clip, title=request.exercise_slug)
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
        "groundMetadataPath": str(ground_metadata_path),
        "targetRigContractPath": str(target_rig_contract_path),
        "gvhmrRetargetSourcePath": str(gvhmr_retarget_source_path) if gvhmr_retarget_source_path is not None else None,
        "cleanupStats": {
            "inputFrames": cleanup_stats.input_frames,
            "outputFrames": cleanup_stats.output_frames,
            "trimmedStartFrames": cleanup_stats.trimmed_start_frames,
            "trimmedEndFrames": cleanup_stats.trimmed_end_frames,
            "averageRootHeightBefore": cleanup_stats.average_root_height_before,
            "averageRootHeightAfter": cleanup_stats.average_root_height_after,
        },
        "groundMetadata": ground_metadata.to_dict(),
        "nextStage": {
            "status": "pending_offline_retarget",
            "description": "Retarget offline from the GVHMR SMPL source and cleaned motion review clip to the fixed humanoid rig, then export glb/glTF for Wear.",
            "cleanedMotionJsonPath": str(cleaned_motion_json_path),
            "gvhmrRetargetSourcePath": str(gvhmr_retarget_source_path) if gvhmr_retarget_source_path is not None else None,
            "targetRigContractPath": str(target_rig_contract_path),
        },
    }
    manifest_path.write_text(json.dumps(manifest_payload, indent=2), encoding="utf-8")
    return GenerateResult(
        manifest_path=manifest_path,
        preview_html_path=preview_html_path,
        raw_preview_html_path=raw_preview_html_path,
        cleaned_motion_json_path=cleaned_motion_json_path,
        raw_motion_json_path=raw_motion_json_path,
        target_rig_contract_path=target_rig_contract_path,
        gvhmr_retarget_source_path=gvhmr_retarget_source_path,
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
            return destination
        shutil.copy2(source, destination)
        return destination
    raise ValueError("Either youtube_url or video_path must be provided.")
