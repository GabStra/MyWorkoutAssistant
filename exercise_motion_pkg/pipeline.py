from __future__ import annotations

import importlib.util
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import replace
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from exercise_motion_pkg.cleanup import CleanupStats, cleanup_motion_clip
from exercise_motion_pkg.gpu_lock import gpu_stage_lock
from exercise_motion_pkg.ground import GroundMetadata, generate_ground_metadata
from exercise_motion_pkg.motion_io import load_motion_json, save_motion_json
from exercise_motion_pkg.models import MotionClip, MotionFrame
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
WHAM_GLOBAL_CACHE_VERSION = 1
WHAM_LOCAL_CACHE_MANIFEST_NAME = "cache_manifest.json"
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


class IncompleteWhamTrackingError(ValueError):
    """WHAM returned motion, but its selected subject track misses part of the requested cut."""

    def __init__(
        self,
        message: str,
        *,
        requested_start_seconds: float,
        requested_end_seconds: float | None,
        retained_start_seconds: float,
        retained_end_seconds: float,
    ) -> None:
        super().__init__(message)
        self.requested_start_seconds = requested_start_seconds
        self.requested_end_seconds = requested_end_seconds
        self.retained_start_seconds = retained_start_seconds
        self.retained_end_seconds = retained_end_seconds


@dataclass(frozen=True)
class GenerateRequest:
    exercise_slug: str
    workspace: Path
    youtube_url: str | None = None
    video_path: Path | None = None
    wham_repo_path: Path | None = None
    wham_results_pkl: Path | None = None
    reuse_wham_cache: bool = True
    wham_global_cache_dir: Path | None = None
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
    wham_timeout_seconds: float | None = None
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
    ground_contact_mode: str = "unknown"
    export_wham_smpl_preview: bool = False
    source_start_seconds: float | None = None
    source_end_seconds: float | None = None
    output_crop_start_seconds: float | None = None
    output_crop_end_seconds: float | None = None
    allow_incomplete_wham_boundary_crop: bool = False
    wham_output_rotation_degrees: float = 0.0
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


def default_wham_global_cache_dir(workspace: Path) -> Path:
    resolved = workspace.expanduser().resolve()
    for candidate in (resolved, *resolved.parents):
        if candidate.name.lower() == "exercise_motion":
            return candidate / "wham-cache"
    return resolved / "wham-cache"


def wham_content_cache_key(request: GenerateRequest, input_video_path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(f"wham-global-cache-v{WHAM_GLOBAL_CACHE_VERSION}\n".encode("utf-8"))
    digest.update(
        json.dumps(
            {
                "estimateLocalOnly": request.wham_estimate_local_only,
                "runSmplify": request.wham_run_smplify,
                "dockerImage": request.wham_docker_image if request.use_wham_docker else None,
                "outputRotationDegrees": request.wham_output_rotation_degrees,
            },
            sort_keys=True,
        ).encode("utf-8")
    )
    if request.wham_repo_path is not None:
        wham_repo = request.wham_repo_path.expanduser().resolve()
        repository_inputs = (
            wham_repo / "demo.py",
            wham_repo / "configs" / "yamls" / "demo.yaml",
            wham_repo / "lib" / "models" / "preproc" / "detector.py",
            wham_repo / "checkpoints" / "wham_vit_w_3dpw.pth.tar",
            wham_repo / "checkpoints" / "hmr2a.ckpt",
        )
        for path in repository_inputs:
            try:
                stat = path.stat()
            except OSError:
                continue
            digest.update(f"{path.name}:{stat.st_size}:{stat.st_mtime_ns}\n".encode("utf-8"))
    with input_video_path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def global_wham_results_pkl(request: GenerateRequest, input_video_path: Path) -> Path:
    cache_dir = request.wham_global_cache_dir or default_wham_global_cache_dir(request.workspace)
    return cache_dir.expanduser().resolve() / wham_content_cache_key(request, input_video_path) / "wham_output.pkl"


def local_wham_cache_matches_input(
    request: GenerateRequest,
    *,
    input_video_path: Path,
    results_pkl: Path,
) -> bool:
    manifest_path = results_pkl.with_name(WHAM_LOCAL_CACHE_MANIFEST_NAME)
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return False
    return payload.get("cacheKey") == wham_content_cache_key(request, input_video_path)


def write_local_wham_cache_manifest(
    request: GenerateRequest,
    *,
    input_video_path: Path,
    results_pkl: Path,
) -> Path:
    manifest_path = results_pkl.with_name(WHAM_LOCAL_CACHE_MANIFEST_NAME)
    payload = {
        "schemaVersion": 1,
        "cacheKey": wham_content_cache_key(request, input_video_path),
        "sourceInputVideo": str(input_video_path),
        "resultsPkl": str(results_pkl),
    }
    manifest_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return manifest_path


def reusable_wham_results_pkl(request: GenerateRequest, input_video_path: Path) -> Path | None:
    if not request.reuse_wham_cache:
        return None
    local = default_wham_results_pkl(
        PipelinePaths.create(request.workspace, request.exercise_slug).raw_dir / "wham",
        input_video_path,
    )
    if (
        local.is_file()
        and local.stat().st_size > 0
        and local_wham_cache_matches_input(
            request,
            input_video_path=input_video_path,
            results_pkl=local,
        )
    ):
        return local
    shared = global_wham_results_pkl(request, input_video_path)
    if shared.is_file() and shared.stat().st_size > 0:
        return shared
    return None


def publish_global_wham_results(
    request: GenerateRequest,
    *,
    input_video_path: Path,
    results_pkl: Path,
) -> Path:
    destination = global_wham_results_pkl(request, input_video_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(f".tmp-{os.getpid()}-{uuid.uuid4().hex}.pkl")
    shutil.copy2(results_pkl, temporary)
    temporary.replace(destination)
    metadata = {
        "schemaVersion": 1,
        "cacheKey": destination.parent.name,
        "sourceInputVideo": str(input_video_path),
        "sourceResultsPkl": str(results_pkl),
        "estimateLocalOnly": request.wham_estimate_local_only,
        "runSmplify": request.wham_run_smplify,
        "dockerImage": request.wham_docker_image if request.use_wham_docker else None,
    }
    destination.with_name("cache_manifest.json").write_text(
        json.dumps(metadata, indent=2) + "\n",
        encoding="utf-8",
    )
    return destination


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
        reusable_results_pkl = reusable_wham_results_pkl(request, input_video_path)
        wham_source = resolve_wham_results_source(
            explicit_results_pkl=request.wham_results_pkl or reusable_results_pkl,
            wham_output_dir=wham_output_dir,
            input_video_path=input_video_path,
            reuse_wham_cache=request.reuse_wham_cache,
        )
        wham_results_pkl = wham_source.path
        if reusable_results_pkl is not None and request.wham_results_pkl is None:
            local_cached = default_wham_results_pkl(wham_output_dir, input_video_path)
            wham_cache_status = "reused_local" if reusable_results_pkl == local_cached else "reused_global"
        else:
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
                timeout_seconds=request.wham_timeout_seconds,
            )
            record_timing("whamRunSeconds", stage_started)
            timings["wham"] = wham_result.timing_payload()
            wham_results_pkl = wham_result.results_pkl
            local_cache_manifest_path = write_local_wham_cache_manifest(
                request,
                input_video_path=input_video_path,
                results_pkl=wham_results_pkl,
            )
            timings["wham"]["localCacheManifestPath"] = str(local_cache_manifest_path)
            global_cache_path = publish_global_wham_results(
                request,
                input_video_path=input_video_path,
                results_pkl=wham_results_pkl,
            )
            timings["wham"]["globalCachePath"] = str(global_cache_path)
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
            output_rotation_degrees=request.wham_output_rotation_degrees,
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
    if request.output_crop_start_seconds is not None or request.output_crop_end_seconds is not None:
        stage_started = time.perf_counter()
        raw_clip = crop_motion_clip_to_input_window(
            raw_clip,
            start_seconds=request.output_crop_start_seconds,
            end_seconds=request.output_crop_end_seconds,
            allow_boundary_truncation=request.allow_incomplete_wham_boundary_crop,
        )
        save_motion_json(raw_motion_json_path, raw_clip)
        record_timing("cropInferenceContextSeconds", stage_started)
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
        tuning_input_clip = canonicalize_camera_motion_clip(raw_clip)
        record_timing("canonicalizeMotionCoordinatesSeconds", stage_started)
        stage_started = time.perf_counter()
        cleaned_clip, cleanup_stats = cleanup_motion_clip(
            tuning_input_clip,
            one_euro_min_cutoff=request.one_euro_min_cutoff,
            one_euro_beta=request.one_euro_beta,
            one_euro_derivative_cutoff=request.one_euro_derivative_cutoff,
            motion_threshold=request.motion_threshold,
            padding_frames=request.padding_frames,
            ground_contact_mode=request.ground_contact_mode,
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
            "camera_to_canonical_world_coordinates",
            "ground_plane_fitting",
            "support_global_translation_stabilization",
            "root_translation_one_euro_xz",
            "contract_aware_vertical_grounding",
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


def crop_motion_clip_to_input_window(
    clip: MotionClip,
    *,
    start_seconds: float | None,
    end_seconds: float | None,
    allow_boundary_truncation: bool = False,
) -> MotionClip:
    """Remove inference-only video context and rebase retained motion to zero."""
    start = max(0.0, float(start_seconds or 0.0))
    end = float(end_seconds) if end_seconds is not None else float("inf")
    if end <= start:
        raise ValueError("Motion output crop end must be after crop start.")
    retained = [
        frame
        for frame in clip.frames
        if frame.time_sec + 1e-6 >= start and frame.time_sec <= end + 1e-6
    ]
    if not retained:
        raise ValueError(
            f"WHAM produced no motion frames inside the requested output window {start:.3f}-{end:.3f}s."
        )
    frame_duration_seconds = 1.0 / max(float(clip.fps), 1.0)
    requested_duration_seconds = None if end == float("inf") else end - start
    frame_tolerance_seconds = max(
        3.0 * frame_duration_seconds,
        0.05 * requested_duration_seconds if requested_duration_seconds is not None else 0.0,
    )
    boundary_coverage_failures: list[str] = []
    if retained[0].time_sec > start + frame_tolerance_seconds:
        boundary_coverage_failures.append(
            f"starts at {retained[0].time_sec:.3f}s instead of {start:.3f}s"
        )
    if end != float("inf") and retained[-1].time_sec < end - frame_tolerance_seconds:
        boundary_coverage_failures.append(
            f"ends at {retained[-1].time_sec:.3f}s instead of {end:.3f}s"
        )
    largest_internal_gap_seconds = max(
        (
            current.time_sec - previous.time_sec
            for previous, current in zip(retained, retained[1:])
        ),
        default=0.0,
    )
    internal_gap_tolerance_seconds = 2.5 * frame_duration_seconds
    internal_gap_failure = largest_internal_gap_seconds > internal_gap_tolerance_seconds + 1e-6
    coverage_failures = list(boundary_coverage_failures)
    if internal_gap_failure:
        coverage_failures.append(f"contains an internal {largest_internal_gap_seconds:.3f}s tracking gap")
    if internal_gap_failure or (boundary_coverage_failures and not allow_boundary_truncation):
        raise IncompleteWhamTrackingError(
            "WHAM tracking does not cover the complete requested output window: "
            + "; ".join(coverage_failures)
            + ". The subject track was likely fragmented or lost.",
            requested_start_seconds=start,
            requested_end_seconds=None if end == float("inf") else end,
            retained_start_seconds=retained[0].time_sec,
            retained_end_seconds=retained[-1].time_sec,
        )
    first_time = retained[0].time_sec
    return MotionClip(
        fps=clip.fps,
        joint_names=clip.joint_names,
        frames=[
            MotionFrame(time_sec=max(0.0, frame.time_sec - first_time), joints=frame.joints)
            for frame in retained
        ],
        source=clip.source,
        metadata={
            **clip.metadata,
            "inferenceContextCrop": {
                "requestedStartSeconds": start,
                "requestedEndSeconds": None if end == float("inf") else end,
                "retainedInputStartSeconds": retained[0].time_sec,
                "retainedInputEndSeconds": retained[-1].time_sec,
                "inputFrameCount": clip.frame_count,
                "outputFrameCount": len(retained),
                "boundaryToleranceSeconds": frame_tolerance_seconds,
                "missingStartSeconds": max(0.0, retained[0].time_sec - start),
                "missingEndSeconds": (
                    None
                    if end == float("inf")
                    else max(0.0, end - retained[-1].time_sec)
                ),
                "largestInternalGapSeconds": largest_internal_gap_seconds,
                "boundaryTruncationAccepted": bool(boundary_coverage_failures),
                "boundaryCoverageFailures": boundary_coverage_failures,
            },
        },
    )


def canonicalize_camera_motion_clip(clip: MotionClip) -> MotionClip:
    """Convert WHAM/OpenCV camera coordinates into the preview's Y-up world basis.

    WHAM camera coordinates use positive Y down and positive Z forward.  The
    renderer uses positive Y up and the opposite Z direction.  Converting the
    motion once during post-processing keeps world orientation out of preview
    settings and avoids camera-dependent scene inversion heuristics.
    """
    return replace(
        clip,
        frames=[
            MotionFrame(
                time_sec=frame.time_sec,
                joints={
                    joint_name: (point[0], -point[1], -point[2])
                    for joint_name, point in frame.joints.items()
                },
            )
            for frame in clip.frames
        ],
        metadata={
            **clip.metadata,
            "coordinateNormalization": {
                "source": "wham_opencv_camera",
                "target": "canonical_y_up_world",
                "transform": "rotate_x_180_degrees",
            },
        },
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
    gpu_lock_wait_seconds = 0.0
    with log_path.open("w", encoding="utf-8", errors="replace") as log_file:
        with gpu_stage_lock(stage="spinepose", enabled=_spinepose_uses_gpu(device)) as lock_wait_seconds:
            gpu_lock_wait_seconds = lock_wait_seconds
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
        "gpuLockWaitSeconds": round(gpu_lock_wait_seconds, 3),
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


def _spinepose_uses_gpu(device: str) -> bool:
    normalized = device.strip().lower()
    return normalized not in {"cpu", "none", "false", "off"}


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
