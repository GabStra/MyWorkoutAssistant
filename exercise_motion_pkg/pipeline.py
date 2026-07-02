from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
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
from exercise_motion_pkg.spinepose_wham_correction import apply_spinepose_to_motion_clip, apply_spinepose_to_wham_pkl
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
from exercise_motion_pkg.video_utils import read_basic_video_metadata, trim_video


WHAM_COORDINATE_SPACE = "camera"
SPINEPOSE_COMMAND_ENV_VAR = "EXERCISE_MOTION_SPINEPOSE_COMMAND"
SPINEPOSE_CONDA_ENV_ENV_VAR = "EXERCISE_MOTION_SPINEPOSE_CONDA_ENV"
DEFAULT_SPINEPOSE_OUTPUT_DIR_NAME = "spinepose_json"
SPINEPOSE_CLI_NAME = "spinepose"
DEFAULT_SPINEPOSE_CONDA_ENV_NAME = "spinepose"
SPINEPOSE_NO_DISPLAY_BOOTSTRAP = (
    "import ctypes, os, pathlib, site; "
    "_dll_dirs=[str(_p) for _root in site.getsitepackages() "
    "for _rel in ('cuda_runtime/bin','cublas/bin','cufft/bin','cudnn/bin','cuda_nvrtc/bin','nvjitlink/bin') "
    "for _p in (pathlib.Path(_root)/'nvidia'/_rel,) if _p.exists()]; "
    "[os.add_dll_directory(_d) for _d in _dll_dirs if hasattr(os, 'add_dll_directory')]; "
    "os.environ['PATH']=os.pathsep.join(_dll_dirs+[os.environ.get('PATH','')]); "
    "[ctypes.WinDLL(str(_dll)) for _d in _dll_dirs for _dll in pathlib.Path(_d).glob('*.dll') if 'cudnn' in _dll.name.lower()]; "
    "import onnxruntime as ort; "
    "getattr(ort, 'preload_dlls', lambda **kwargs: None)(directory=''); "
    "import cv2; "
    "cv2.imshow=lambda *args, **kwargs: None; "
    "cv2.waitKey=lambda *args, **kwargs: -1; "
    "cv2.destroyAllWindows=lambda *args, **kwargs: None; "
    "from spinepose.inference import main; "
    "main()"
)
SPINEPOSE_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp"}


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
    use_warm_wham_worker: bool = False
    wham_worker_session_dir: Path | None = None
    wham_worker_mount_root: Path | None = None
    wham_worker_timeout_seconds: float | None = None
    wham_estimate_local_only: bool = DEFAULT_WHAM_ESTIMATE_LOCAL_ONLY
    wham_run_smplify: bool = True
    spinepose_enabled: bool = False
    spinepose_json_dir: Path | None = None
    spinepose_command: str | None = None
    spinepose_output_dir: Path | None = None
    spinepose_mode: str = "large"
    spinepose_model_version: str = "v2"
    spinepose_device: str = "cuda"
    spinepose_reuse_cache: bool = True
    spinepose_gain: float = 1.0
    spinepose_max_degrees: float = 35.0
    spinepose_axis: int = 0
    spinepose_invert: bool = False
    spinepose_smoothing_window: int = 9
    spinepose_arm_counter_rotation: float = 1.0
    spinepose_merge_mode: str = "motion"
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
    export_wham_smpl_preview: bool = False
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


@dataclass(frozen=True)
class SpinePoseJsonSource:
    json_dir: Path | None
    payload: dict[str, Any]


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
    if request.spinepose_merge_mode not in {"motion", "legacy_pkl"}:
        raise ValueError("spinepose_merge_mode must be 'motion' or 'legacy_pkl'.")
    if request.normalized_motion_json is not None and request.spinepose_merge_mode == "legacy_pkl":
        raise ValueError("legacy_pkl SpinePose merge mode requires WHAM output, not normalized_motion_json.")

    def record_timing(name: str, started: float) -> None:
        timings[name] = round(time.perf_counter() - started, 3)

    paths = PipelinePaths.create(request.workspace, request.exercise_slug)
    stage_started = time.perf_counter()
    input_video_path = prepare_input_video(request, paths)
    record_timing("prepareInputVideoSeconds", stage_started)
    spinepose_source = resolve_spinepose_json_source(
        request=request,
        paths=paths,
        input_video_path=input_video_path,
    )
    active_spinepose_json_dir = spinepose_source.json_dir
    timings["spineposeSource"] = spinepose_source.payload
    raw_motion_json_path = paths.raw_dir / "motion.raw.json"
    retarget_source_path: Path | None = None
    smpl_preview_sequence = None
    smpl_preview_reference_clip = None
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
                use_warm_worker=request.use_warm_wham_worker,
                warm_worker_session_dir=request.wham_worker_session_dir,
                warm_worker_mount_root=request.wham_worker_mount_root,
                warm_worker_timeout_seconds=request.wham_worker_timeout_seconds,
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
        if active_spinepose_json_dir is not None and request.spinepose_merge_mode == "legacy_pkl":
            stage_started = time.perf_counter()
            corrected_wham_results_pkl = paths.raw_dir / "wham_spinepose" / "wham_output.pkl"
            stats = apply_spinepose_to_wham_pkl(
                wham_results_pkl=wham_results_pkl,
                spinepose_json_dir=active_spinepose_json_dir,
                output_pkl=corrected_wham_results_pkl,
                gain=request.spinepose_gain,
                max_degrees=request.spinepose_max_degrees,
                axis=request.spinepose_axis,
                invert=request.spinepose_invert,
                smoothing_window=request.spinepose_smoothing_window,
                arm_counter_rotation=request.spinepose_arm_counter_rotation,
            )
            wham_results_pkl = corrected_wham_results_pkl
            wham_cache_status = f"{wham_cache_status}_spinepose_corrected"
            timings["spineposeWhamCorrection"] = {
                "elapsedSeconds": round(time.perf_counter() - stage_started, 3),
                "sourceJsonDir": str(active_spinepose_json_dir),
                "correctedResultsPkl": str(corrected_wham_results_pkl),
                "frames": stats.frame_count,
                "sourceFrames": stats.source_frame_count,
                "appliedFrames": stats.applied_frame_count,
                "poseKeys": list(stats.pose_keys),
                "maxDeltaDegrees": stats.max_delta_degrees,
                "meanAbsDeltaDegrees": stats.mean_abs_delta_degrees,
                "axis": request.spinepose_axis,
                "gain": request.spinepose_gain,
                "maxDegrees": request.spinepose_max_degrees,
                "invert": request.spinepose_invert,
                "smoothingWindow": request.spinepose_smoothing_window,
                "armCounterRotation": stats.arm_counter_rotation,
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
        if request.export_wham_smpl_preview:
            stage_started = time.perf_counter()
            smpl_preview_sequence = load_wham_smpl_mesh_sequence(
                wham_results_pkl=wham_results_pkl,
                body_model_root=request.body_model_root.expanduser().resolve(),
                coordinate_space=WHAM_COORDINATE_SPACE,
            )
            record_timing("loadWhamSmplMeshSeconds", stage_started)
        else:
            timings["loadWhamSmplMeshSeconds"] = 0.0
            timings["whamSmplPreview"] = {"enabled": False, "status": "disabled"}

    if active_spinepose_json_dir is not None and request.spinepose_merge_mode == "motion":
        stage_started = time.perf_counter()
        source_spinepose_json_dir = active_spinepose_json_dir
        fusion_input_clip = load_motion_json(raw_motion_json_path)
        smpl_preview_reference_clip = fusion_input_clip if smpl_preview_sequence is not None else None
        source_video_fps = _source_video_fps_for_spinepose_alignment(input_video_path, fusion_input_clip)
        fused_clip, stats = apply_spinepose_to_motion_clip(
            fusion_input_clip,
            spinepose_json_dir=source_spinepose_json_dir,
            gain=request.spinepose_gain,
            max_degrees=request.spinepose_max_degrees,
            invert=request.spinepose_invert,
            smoothing_window=request.spinepose_smoothing_window,
            source_fps=source_video_fps,
        )
        save_motion_json(raw_motion_json_path, fused_clip)
        wham_cache_status = f"{wham_cache_status}_spinepose_motion_fused"
        timings["spineposeMotionFusion"] = {
            "elapsedSeconds": round(time.perf_counter() - stage_started, 3),
            "sourceJsonDir": str(source_spinepose_json_dir),
            "frames": stats.frame_count,
            "sourceFrames": stats.source_frame_count,
            "validSourceFrames": stats.valid_source_frame_count,
            "appliedFrames": stats.applied_frame_count,
            "fusedJointNames": list(stats.fused_joint_names),
            "maxDisplacement": stats.max_displacement,
            "meanAbsDisplacement": stats.mean_abs_displacement,
            "gain": stats.gain,
            "maxDegrees": stats.max_degrees,
            "invert": stats.inverted,
            "smoothingWindow": stats.smoothing_window,
            "mergeMode": request.spinepose_merge_mode,
            "alignmentMode": stats.alignment_mode,
            "sourceVideoFps": stats.source_fps,
            "curveSource": stats.curve_source,
            "curveQualityScore": stats.curve_quality_score,
            "curveSelectionReason": stats.curve_selection_reason,
            "propagatedJointNames": list(stats.propagated_joint_names),
            "maxPropagatedDisplacement": stats.max_propagated_displacement,
            "meanAbsPropagatedDisplacement": stats.mean_abs_propagated_displacement,
            "lowerTorsoFollow": stats.lower_torso_follow,
            "upperTorsoFollow": stats.upper_torso_follow,
            "candidateQuality": stats.candidate_quality,
        }

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
            "support_global_translation_stabilization",
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
            mesh_reference_clip=smpl_preview_reference_clip,
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
        "spineposeSource": spinepose_source.payload,
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


def _source_video_fps_for_spinepose_alignment(input_video_path: Path, clip: object) -> float | None:
    metadata = getattr(clip, "metadata", None)
    if not isinstance(metadata, dict) or not isinstance(metadata.get("wham"), dict):
        return None
    try:
        video_metadata = read_basic_video_metadata(input_video_path)
    except RuntimeError:
        return None
    if video_metadata.fps <= 0 or video_metadata.frame_count <= 1:
        return None
    return video_metadata.fps


def resolve_spinepose_json_source(
    *,
    request: GenerateRequest,
    paths: PipelinePaths,
    input_video_path: Path,
) -> SpinePoseJsonSource:
    if not request.spinepose_enabled:
        return SpinePoseJsonSource(
            json_dir=None,
            payload={
                "enabled": False,
                "status": "disabled",
            },
        )

    if request.spinepose_json_dir is not None:
        source_json_dir = request.spinepose_json_dir.expanduser().resolve()
        if not _has_spinepose_json_frames(source_json_dir):
            raise ValueError(f"No SpinePose JSON frames found in {source_json_dir}.")
        return SpinePoseJsonSource(
            json_dir=source_json_dir,
            payload={
                "enabled": True,
                "status": "explicit_json_dir",
                "jsonDir": str(source_json_dir),
                "mergeMode": request.spinepose_merge_mode,
            },
        )

    output_dir = (
        request.spinepose_output_dir.expanduser().resolve()
        if request.spinepose_output_dir is not None
        else paths.root / DEFAULT_SPINEPOSE_OUTPUT_DIR_NAME
    )
    if request.spinepose_reuse_cache and _has_spinepose_json_frames(output_dir):
        return SpinePoseJsonSource(
            json_dir=output_dir,
            payload={
                "enabled": True,
                "status": "reused_cached_json",
                "jsonDir": str(output_dir),
                "mergeMode": request.spinepose_merge_mode,
            },
        )

    command, command_source = resolve_spinepose_command(request.spinepose_command)
    if command is None or not command.strip():
        return SpinePoseJsonSource(
            json_dir=None,
            payload={
                "enabled": True,
                "status": "skipped_no_command",
                "jsonDir": str(output_dir),
                "mergeMode": request.spinepose_merge_mode,
                "commandEnvVar": SPINEPOSE_COMMAND_ENV_VAR,
                "condaEnvVar": SPINEPOSE_CONDA_ENV_ENV_VAR,
                "commandSource": command_source,
            },
        )

    result_payload = run_spinepose_extraction(
        command=command,
        input_video_path=input_video_path,
        output_dir=output_dir,
        logs_dir=paths.logs_dir,
        mode=request.spinepose_mode,
        model_version=request.spinepose_model_version,
        device=request.spinepose_device,
    )
    if not _has_spinepose_json_frames(output_dir):
        raise RuntimeError(f"SpinePose command finished but produced no JSON frames in {output_dir}.")

    return SpinePoseJsonSource(
        json_dir=output_dir,
        payload={
            "enabled": True,
            "status": "generated",
            "jsonDir": str(output_dir),
            "mergeMode": request.spinepose_merge_mode,
            "commandSource": command_source,
            **result_payload,
        },
    )


def resolve_spinepose_command(explicit_command: str | None) -> tuple[str | None, str]:
    if explicit_command is not None and explicit_command.strip():
        return explicit_command.strip(), "request"

    env_command = os.environ.get(SPINEPOSE_COMMAND_ENV_VAR)
    if env_command is not None and env_command.strip():
        return env_command.strip(), "env"

    path_command = shutil.which(SPINEPOSE_CLI_NAME)
    if path_command:
        return _spinepose_command_from_executable(path_command), "path"

    conda_env_command = _spinepose_conda_env_command()
    if conda_env_command is not None:
        return conda_env_command, "conda_env"

    module_command = _spinepose_module_command()
    if module_command is not None:
        return module_command, "python_module"

    return None, "not_found"


def _spinepose_module_command() -> str | None:
    try:
        module_spec = importlib.util.find_spec("spinepose.inference")
    except (ImportError, ModuleNotFoundError, ValueError):
        return None
    if module_spec is None:
        return None
    return _spinepose_python_inference_command(Path(sys.executable))


def _spinepose_conda_env_command() -> str | None:
    env_name = os.environ.get(SPINEPOSE_CONDA_ENV_ENV_VAR, DEFAULT_SPINEPOSE_CONDA_ENV_NAME).strip()
    if not env_name:
        return None
    for conda_root in _candidate_conda_roots():
        env_root = conda_root / "envs" / env_name
        for script_dir_name in ("Scripts", "bin"):
            script_dir = env_root / script_dir_name
            for executable_name in (f"{SPINEPOSE_CLI_NAME}.exe", SPINEPOSE_CLI_NAME):
                candidate = script_dir / executable_name
                if candidate.exists():
                    return _spinepose_command_from_executable(candidate)
    return None


def _spinepose_command_from_executable(executable: str | Path) -> str:
    executable_path = Path(executable).expanduser()
    if executable_path.exists():
        env_root = executable_path.parent.parent
        for python_name in ("python.exe", "python"):
            python_path = env_root / python_name
            if python_path.exists():
                return _spinepose_python_inference_command(python_path)
    return _format_shell_executable(executable)


def _spinepose_python_inference_command(python_executable: str | Path) -> str:
    return subprocess.list2cmdline([str(python_executable), "-c", SPINEPOSE_NO_DISPLAY_BOOTSTRAP])


def _candidate_conda_roots() -> list[Path]:
    roots: list[Path] = []

    conda_prefix = os.environ.get("CONDA_PREFIX")
    if conda_prefix:
        prefix_path = Path(conda_prefix).expanduser()
        roots.append(_conda_root_from_prefix(prefix_path))

    executable_parent = Path(sys.executable).expanduser().resolve().parent
    roots.append(_conda_root_from_prefix(executable_parent))

    home = Path.home()
    roots.extend([home / "miniconda3", home / "anaconda3", home / "mambaforge", home / "miniforge3"])

    unique_roots: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        root_text = str(root)
        if root_text in seen:
            continue
        seen.add(root_text)
        unique_roots.append(root)
    return unique_roots


def _conda_root_from_prefix(prefix_path: Path) -> Path:
    if prefix_path.parent.name.lower() == "envs":
        return prefix_path.parent.parent
    return prefix_path


def run_spinepose_extraction(
    *,
    command: str,
    input_video_path: Path,
    output_dir: Path,
    logs_dir: Path,
    mode: str,
    model_version: str,
    device: str,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)
    for existing_json in output_dir.glob("*.json"):
        existing_json.unlink()

    command_line = _format_spinepose_command(
        command=command,
        input_video_path=input_video_path,
        output_dir=output_dir,
        mode=mode,
        model_version=model_version,
        device=device,
    )
    log_path = logs_dir / "spinepose.log"
    started = time.perf_counter()
    with log_path.open("w", encoding="utf-8", errors="replace") as log_file:
        completed = subprocess.run(
            command_line,
            shell=True,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            text=True,
        )
    elapsed_seconds = round(time.perf_counter() - started, 3)
    if completed.returncode != 0:
        raise RuntimeError(
            f"SpinePose command failed with exit code {completed.returncode}. See log: {log_path}"
        )

    return {
        "elapsedSeconds": elapsed_seconds,
        "command": command_line,
        "logPath": str(log_path),
        "mode": mode,
        "modelVersion": model_version,
        "device": device,
    }


def _format_spinepose_command(
    *,
    command: str,
    input_video_path: Path,
    output_dir: Path,
    mode: str,
    model_version: str,
    device: str,
) -> str:
    values = {
        "video": str(input_video_path),
        "input_video": str(input_video_path),
        "input_path": str(input_video_path),
        "output": str(output_dir),
        "output_dir": str(output_dir),
        "save_path": str(_spinepose_save_path(input_video_path, output_dir)),
        "mode": mode,
        "model_version": model_version,
        "device": device,
        "hardware_acceleration": _spinepose_hardware_acceleration_arg(device),
        "enable_lifting": "--enable-lifting",
    }
    if "{" in command and "}" in command:
        return command.format(**values)
    hardware_acceleration_arg = _spinepose_hardware_acceleration_arg(device)
    save_path = _spinepose_save_path(input_video_path, output_dir)
    visualization_path = _spinepose_visualization_path(input_video_path, output_dir)
    visualization_arg = (
        f" --vis-path {_format_shell_arg(visualization_path)}"
        if visualization_path is not None
        else ""
    )
    return (
        f"{_format_shell_executable(command)} "
        f"--input_path {_format_shell_arg(input_video_path)} "
        f"--save-path {_format_shell_arg(save_path)} "
        f"--mode {mode} --model-version {model_version} "
        f"{hardware_acceleration_arg} --enable-lifting --no-lifting-panel"
        f"{visualization_arg}"
    )


def _spinepose_hardware_acceleration_arg(device: str) -> str:
    normalized = device.strip().lower()
    if normalized in {"cpu", "none", "false", "off"}:
        return "--no-hardware-acceleration"
    return "--hardware-acceleration"


def _format_shell_executable(command: str | Path) -> str:
    command_text = str(command).strip()
    if not command_text:
        return command_text
    if command_text.startswith('"') or command_text.startswith("'"):
        return command_text
    if any(character.isspace() for character in command_text):
        candidate = Path(command_text).expanduser()
        if candidate.exists():
            return _format_shell_arg(candidate)
    return command_text


def _format_shell_arg(value: str | Path) -> str:
    return subprocess.list2cmdline([str(value)])


def _spinepose_save_path(input_path: Path, output_dir: Path) -> Path:
    if input_path.suffix.lower() in SPINEPOSE_IMAGE_EXTENSIONS:
        return output_dir / "frame_00000.json"
    return output_dir


def _spinepose_visualization_path(input_path: Path, output_dir: Path) -> Path | None:
    if input_path.suffix.lower() in SPINEPOSE_IMAGE_EXTENSIONS:
        return output_dir / "spinepose_preview.jpg"
    return None


def _has_spinepose_json_frames(path: Path) -> bool:
    return path.exists() and any(path.glob("*.json"))


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
