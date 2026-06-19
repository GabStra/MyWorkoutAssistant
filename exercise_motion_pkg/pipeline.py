from __future__ import annotations

import json
import shutil
import time
from dataclasses import replace
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from exercise_motion_pkg.cleanup import CleanupStats, cleanup_motion_clip
from exercise_motion_pkg.ground import GroundMetadata, generate_ground_metadata
from exercise_motion_pkg.motion_io import load_motion_json, save_motion_json
from exercise_motion_pkg.paths import PipelinePaths
from exercise_motion_pkg.preview import write_preview_html, write_wear_skeleton_json
from exercise_motion_pkg.retarget_contract import build_target_rig_contract
from exercise_motion_pkg.structural_refinement import refine_motion_clip_structurally
from exercise_motion_pkg.wham_convert import normalize_wham_output
from exercise_motion_pkg.wham_retarget_source import export_wham_retarget_source
from exercise_motion_pkg.wham_runner import (
    DEFAULT_WHAM_DOCKER_IMAGE,
    DEFAULT_WHAM_DOCKER_SHM_SIZE,
    DEFAULT_WHAM_ESTIMATE_LOCAL_ONLY,
    run_wham_locally,
)
from exercise_motion_pkg.wham_smpl_preview import (
    load_wham_smpl_mesh_sequence,
    write_baked_wham_smpl_preview_json,
)
from exercise_motion_pkg.youtube import download_youtube, sanitize_video_for_processing
from exercise_motion_pkg.video_utils import trim_video


WHAM_COORDINATE_SPACE = "camera"


@dataclass(frozen=True)
class GenerateRequest:
    exercise_slug: str
    workspace: Path
    youtube_url: str | None = None
    video_path: Path | None = None
    wham_repo_path: Path | None = None
    wham_results_pkl: Path | None = None
    reuse_wham_cache: bool = True
    body_model_root: Path | None = None
    wham_python_command: str = "python"
    use_wham_docker: bool = False
    wham_docker_image: str = DEFAULT_WHAM_DOCKER_IMAGE
    wham_docker_gpus: str = "all"
    wham_docker_shm_size: str = DEFAULT_WHAM_DOCKER_SHM_SIZE
    wham_estimate_local_only: bool = DEFAULT_WHAM_ESTIMATE_LOCAL_ONLY
    wham_run_smplify: bool = True
    normalized_motion_json: Path | None = None
    one_euro_min_cutoff: float = 0.6
    one_euro_beta: float = 0.05
    one_euro_derivative_cutoff: float = 1.0
    motion_threshold: float = 0.015
    padding_frames: int = 3
    dominant_chain_ratio: float = 0.65
    non_dominant_damping: float = 1.0
    non_dominant_radius_scale: float = 1.0
    motion_tuning_enabled: bool = True
    source_start_seconds: float | None = None
    source_end_seconds: float | None = None
    youtube_cookies: Path | None = None


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
    motion_tuning_enabled: bool
    wham_results_pkl: Path | None = None
    wham_cache_status: str = "not_used"
    timings: dict[str, Any] | None = None


@dataclass(frozen=True)
class WhamResultsSource:
    path: Path
    cache_status: str
    should_run_wham: bool


def default_wham_results_pkl(wham_output_dir: Path, input_video_path: Path) -> Path:
    return wham_output_dir / input_video_path.stem / "wham_output.pkl"


def resolve_wham_results_source(
    *,
    explicit_results_pkl: Path | None,
    wham_output_dir: Path,
    input_video_path: Path,
    reuse_wham_cache: bool,
) -> WhamResultsSource:
    if explicit_results_pkl is not None:
        return WhamResultsSource(
            path=explicit_results_pkl.expanduser().resolve(),
            cache_status="explicit",
            should_run_wham=False,
        )

    cached_results_pkl = default_wham_results_pkl(wham_output_dir, input_video_path)
    if reuse_wham_cache and cached_results_pkl.exists():
        return WhamResultsSource(
            path=cached_results_pkl,
            cache_status="reused",
            should_run_wham=False,
        )

    return WhamResultsSource(
        path=cached_results_pkl,
        cache_status="generated",
        should_run_wham=True,
    )


def run_generation_pipeline(request: GenerateRequest) -> GenerateResult:
    pipeline_started = time.perf_counter()
    timings: dict[str, Any] = {}

    def record_timing(name: str, started: float) -> None:
        timings[name] = round(time.perf_counter() - started, 3)

    paths = PipelinePaths.create(request.workspace, request.exercise_slug)
    stage_started = time.perf_counter()
    input_video_path = prepare_input_video(request, paths)
    record_timing("prepareInputVideoSeconds", stage_started)
    raw_motion_json_path = paths.raw_dir / "motion.raw.json"
    retarget_source_path: Path | None = None
    smpl_preview_sequence = None
    smpl_preview_json_path: Path | None = None
    wham_results_pkl: Path | None = None
    wham_cache_status = "not_used_normalized_motion"
    if request.normalized_motion_json is not None:
        stage_started = time.perf_counter()
        shutil.copy2(request.normalized_motion_json, raw_motion_json_path)
        record_timing("copyNormalizedMotionSeconds", stage_started)
    else:
        if request.body_model_root is None:
            raise ValueError("body_model_root is required when using WHAM output.")
        wham_output_dir = paths.raw_dir / "wham"
        wham_output_dir.mkdir(parents=True, exist_ok=True)
        wham_source = resolve_wham_results_source(
            explicit_results_pkl=request.wham_results_pkl,
            wham_output_dir=wham_output_dir,
            input_video_path=input_video_path,
            reuse_wham_cache=request.reuse_wham_cache,
        )
        wham_results_pkl = wham_source.path
        wham_cache_status = wham_source.cache_status
        if wham_source.should_run_wham:
            if request.wham_repo_path is None:
                raise ValueError(
                    "Provide normalized_motion_json, or provide body_model_root with either wham_repo_path or wham_results_pkl."
                )
            stage_started = time.perf_counter()
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
            record_timing("whamRunSeconds", stage_started)
            timings["wham"] = wham_result.timing_payload()
            wham_results_pkl = wham_result.results_pkl
        else:
            timings["wham"] = {
                "elapsedSeconds": 0.0,
                "cacheStatus": wham_cache_status,
                "resultsPkl": str(wham_results_pkl),
            }
        stage_started = time.perf_counter()
        normalize_wham_output(
            wham_results_pkl=wham_results_pkl,
            body_model_root=request.body_model_root.expanduser().resolve(),
            output_json=raw_motion_json_path,
            coordinate_space=WHAM_COORDINATE_SPACE,
        )
        record_timing("normalizeWhamOutputSeconds", stage_started)
        stage_started = time.perf_counter()
        retarget_source_path = export_wham_retarget_source(
            wham_results_pkl=wham_results_pkl,
            output_json=paths.retarget_dir / "wham.retarget_source.json",
            coordinate_space=WHAM_COORDINATE_SPACE,
        )
        record_timing("exportWhamRetargetSourceSeconds", stage_started)
        stage_started = time.perf_counter()
        smpl_preview_sequence = load_wham_smpl_mesh_sequence(
            wham_results_pkl=wham_results_pkl,
            body_model_root=request.body_model_root.expanduser().resolve(),
            coordinate_space=WHAM_COORDINATE_SPACE,
        )
        record_timing("loadWhamSmplMeshSeconds", stage_started)

    stage_started = time.perf_counter()
    raw_clip = load_motion_json(raw_motion_json_path)
    record_timing("loadRawMotionSeconds", stage_started)
    raw_preview_html_path = paths.preview_dir / "motion_preview.raw.html"
    stage_started = time.perf_counter()
    raw_preview_clip = replace(
        raw_clip,
        metadata={
            **raw_clip.metadata,
            "motionTuning": _motion_tuning_metadata(enabled=False),
        },
    )
    write_preview_html(raw_preview_html_path, raw_preview_clip, title=f"{request.exercise_slug}-raw")
    record_timing("writeRawPreviewSeconds", stage_started)

    if request.motion_tuning_enabled:
        stage_started = time.perf_counter()
        cleaned_clip, cleanup_stats = cleanup_motion_clip(
            raw_clip,
            one_euro_min_cutoff=request.one_euro_min_cutoff,
            one_euro_beta=request.one_euro_beta,
            one_euro_derivative_cutoff=request.one_euro_derivative_cutoff,
            motion_threshold=request.motion_threshold,
            padding_frames=request.padding_frames,
        )
        record_timing("cleanupMotionSeconds", stage_started)
        stage_started = time.perf_counter()
        cleaned_clip = refine_motion_clip_structurally(
            cleaned_clip,
            dominant_chain_ratio=request.dominant_chain_ratio,
            non_dominant_damping=request.non_dominant_damping,
            non_dominant_radius_scale=request.non_dominant_radius_scale,
        )
        record_timing("structuralRefinementSeconds", stage_started)
        ground_metadata_path = paths.cleaned_dir / "ground.metadata.json"
        stage_started = time.perf_counter()
        ground_metadata: GroundMetadata | None = generate_ground_metadata(
            video_path=input_video_path,
            cleaned_clip=cleaned_clip,
            output_path=ground_metadata_path,
        )
        record_timing("groundMetadataSeconds", stage_started)
        cleaned_clip = replace(
            cleaned_clip,
            metadata={
                **cleaned_clip.metadata,
                "ground": ground_metadata.to_dict(),
                "motionTuning": _motion_tuning_metadata(enabled=True),
            },
        )
        post_processing_steps = [
            "ground_plane_fitting",
            "root_translation_one_euro_xz",
            "structural_ik_refinement",
        ]
    else:
        cleaned_clip = replace(
            raw_clip,
            metadata={
                **raw_clip.metadata,
                "motionTuning": _motion_tuning_metadata(enabled=False),
            },
        )
        cleanup_stats = _identity_cleanup_stats(raw_clip)
        ground_metadata_path = None
        ground_metadata = None
        post_processing_steps = []

    cleaned_motion_json_path = paths.cleaned_dir / "motion.cleaned.json"
    stage_started = time.perf_counter()
    save_motion_json(cleaned_motion_json_path, cleaned_clip)
    record_timing("saveCleanedMotionSeconds", stage_started)

    preview_html_path = paths.preview_dir / "motion_preview.html"
    if smpl_preview_sequence is not None:
        smpl_preview_json_path = paths.retarget_dir / "wham.smpl_preview.baked.json"
        stage_started = time.perf_counter()
        write_baked_wham_smpl_preview_json(
            smpl_preview_json_path,
            sequence=smpl_preview_sequence,
            raw_clip=raw_clip,
            cleaned_clip=cleaned_clip,
            title=request.exercise_slug,
        )
        record_timing("writeSmplPreviewJsonSeconds", stage_started)
    stage_started = time.perf_counter()
    write_preview_html(
        preview_html_path,
        cleaned_clip,
        title=request.exercise_slug,
    )
    record_timing("writeCleanedPreviewSeconds", stage_started)
    wear_skeleton_json_path = paths.wear_dir / "skeleton.preview.json"
    stage_started = time.perf_counter()
    write_wear_skeleton_json(wear_skeleton_json_path, cleaned_clip, title=request.exercise_slug)
    record_timing("writeWearSkeletonSeconds", stage_started)
    target_rig_contract_path = paths.retarget_dir / "target_rig.contract.json"
    stage_started = time.perf_counter()
    target_rig_contract_path.write_text(
        json.dumps(build_target_rig_contract(), indent=2),
        encoding="utf-8",
    )
    record_timing("writeTargetRigContractSeconds", stage_started)

    manifest_path = paths.root / "manifest.json"
    timings["totalSeconds"] = round(time.perf_counter() - pipeline_started, 3)
    manifest_payload = {
        "exerciseSlug": request.exercise_slug,
        "inputVideoPath": str(input_video_path),
        "rawMotionJsonPath": str(raw_motion_json_path),
        "cleanedMotionJsonPath": str(cleaned_motion_json_path),
        "rawPreviewHtmlPath": str(raw_preview_html_path),
        "previewHtmlPath": str(preview_html_path),
        "wearSkeletonJsonPath": str(wear_skeleton_json_path),
        "groundMetadataPath": str(ground_metadata_path) if ground_metadata_path is not None else None,
        "targetRigContractPath": str(target_rig_contract_path),
        "retargetSourcePath": str(retarget_source_path) if retarget_source_path is not None else None,
        "whamRetargetSourcePath": str(retarget_source_path) if retarget_source_path is not None else None,
        "whamSmplPreviewJsonPath": str(smpl_preview_json_path) if smpl_preview_json_path is not None else None,
        "whamResultsPkl": str(wham_results_pkl) if wham_results_pkl is not None else None,
        "whamCacheStatus": wham_cache_status,
        "motionTuningEnabled": request.motion_tuning_enabled,
        "cleanupStats": {
            "inputFrames": cleanup_stats.input_frames,
            "outputFrames": cleanup_stats.output_frames,
            "trimmedStartFrames": cleanup_stats.trimmed_start_frames,
            "trimmedEndFrames": cleanup_stats.trimmed_end_frames,
            "averageRootHeightBefore": cleanup_stats.average_root_height_before,
            "averageRootHeightAfter": cleanup_stats.average_root_height_after,
        },
        "groundMetadata": ground_metadata.to_dict() if ground_metadata is not None else None,
        "postProcessing": {
            "applied": request.motion_tuning_enabled,
            "steps": post_processing_steps,
        },
        "timings": timings,
        "nextStage": {
            "status": "wear_preview_skeleton_ready",
            "description": (
                "Render the baked preview skeleton directly on Wear. It already includes preview alignment, root-drift lock, active loop selection, and centering."
                if request.motion_tuning_enabled
                else "Raw camera-space WHAM motion was passed through without cleanup, ground fitting, or structural tuning."
            ),
            "cleanedMotionJsonPath": str(cleaned_motion_json_path),
            "wearSkeletonJsonPath": str(wear_skeleton_json_path),
            "retargetSourcePath": str(retarget_source_path) if retarget_source_path is not None else None,
            "whamRetargetSourcePath": str(retarget_source_path) if retarget_source_path is not None else None,
            "targetRigContractPath": str(target_rig_contract_path),
            "whamSmplPreviewJsonPath": str(smpl_preview_json_path) if smpl_preview_json_path is not None else None,
            "whamResultsPkl": str(wham_results_pkl) if wham_results_pkl is not None else None,
            "whamCacheStatus": wham_cache_status,
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
        motion_tuning_enabled=request.motion_tuning_enabled,
            wham_results_pkl=wham_results_pkl,
            wham_cache_status=wham_cache_status,
            timings=timings,
    )


def _motion_tuning_metadata(*, enabled: bool) -> dict[str, object]:
    if enabled:
        return {
            "enabled": True,
            "mode": "cleanup_structural_refinement_grounding",
        }
    return {
        "enabled": False,
        "mode": "raw_wham_camera_space_passthrough",
        "skippedSteps": [
            "cleanup_static_trim",
            "ground_plane_fitting",
            "root_translation_one_euro_xz",
            "support_contact_detection",
            "structural_ik_refinement",
        ],
        "reviewIntent": "Compare the generated preview directly against raw WHAM camera-space motion.",
    }


def _identity_cleanup_stats(clip) -> CleanupStats:
    average_root_height = _average_root_height(clip)
    return CleanupStats(
        input_frames=clip.frame_count,
        output_frames=clip.frame_count,
        trimmed_start_frames=0,
        trimmed_end_frames=0,
        average_root_height_before=average_root_height,
        average_root_height_after=average_root_height,
    )


def _average_root_height(clip) -> float:
    root_joint = next((joint for joint in ("pelvis", "hips", "root") if joint in clip.joint_names), None)
    if root_joint is None or not clip.frames:
        return 0.0
    values = [frame.joints[root_joint][1] for frame in clip.frames if root_joint in frame.joints]
    if not values:
        return 0.0
    return sum(values) / len(values)


def prepare_input_video(request: GenerateRequest, paths: PipelinePaths) -> Path:
    def maybe_trim_segment(path: Path) -> Path:
        if request.source_start_seconds is None and request.source_end_seconds is None:
            return path
        if request.source_start_seconds is None or request.source_end_seconds is None:
            raise ValueError("Both source_start_seconds and source_end_seconds are required for source segment trimming.")
        if request.source_start_seconds < 0:
            raise ValueError("source_start_seconds must be >= 0.")
        if request.source_end_seconds <= request.source_start_seconds:
            raise ValueError("source_end_seconds must be greater than source_start_seconds.")
        trimmed = paths.input_dir / "selected_segment.mp4"
        return trim_video(
            source_path=path,
            output_path=trimmed,
            start_seconds=request.source_start_seconds,
            end_seconds=request.source_end_seconds,
        )

    if request.youtube_url:
        source_video = download_youtube(
            request.youtube_url,
            paths.input_dir,
            request.youtube_cookies,
        )
        return maybe_trim_segment(source_video)
    if request.video_path:
        source = request.video_path.expanduser().resolve()
        if not source.exists():
            raise FileNotFoundError(f"Input video not found: {source}")
        destination = paths.input_dir / source.name
        if source == destination.resolve():
            sanitized = sanitize_video_for_processing(destination)
        else:
            shutil.copy2(source, destination)
            sanitized = sanitize_video_for_processing(destination)
        return maybe_trim_segment(sanitized)
    raise ValueError("Either youtube_url or video_path must be provided.")
